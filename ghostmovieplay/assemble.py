"""支援収録の Pass2: 人が撮ったショット + 音声 -> raw.mp4 + timing.json.

**`record` の代わりに立つ段。** 出すものが同じ (`raw.*` と `timing.json`) なので、
`render` は 1 行も変わらずに字幕とクレジットを乗せられる。撮る面の段も
「収録する」のままでよい。

**順番の不変条件がここだけ裏返る。**

    自動収録  voice -> record   音声の尺がビートの尺を決める
    支援収録  撮る -> voice -> assemble   画が先にあるので、足りない分を静止で埋める

先に撮ってしまっている以上、音声の尺で画を伸縮するしかない。伸ばすほうは
最後のフレームで埋める (`tpad`)。**縮めはしない** —— 人が 8 秒かけて操作した
ものを 3 秒の原稿に合わせて切ると、操作の途中で切れる。ビートの尺は
「音声 + 余白」と「ショットの尺」と `hold` の**いちばん長いもの**になる。

**ショットが欠けていても止めない。** 黒画で埋めて `timing.json` の warnings に残す
(`record` の止めない失敗と同じ枠)。撮り忘れた 1 ビートのために、撮れている
20 ビートを捨てさせない。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg
from .plan import AUDIO_TAIL, Plan, wav_seconds

WORK_DIR = "assemble"
SOURCE_NAME = "raw.mp4"

# ショットも音声も hold も無いビートの尺 (秒)。**0 にはしない** ——
# 尺 0 のセグメントは concat が受け付けない
MIN_SECONDS = 1.0
READING_CPS = 8.0       # plan.estimate と同じ読み速度
READING_PAD = 0.6


@dataclass
class Assembled:
    """`record.Recorded` と同じ形 (撮る面と CLI が区別せずに扱えるように)."""

    video: Path
    timing: Path
    duration: float
    skew: float = 0.0            # 組み立てに録画開始の遅れは無い
    warnings: list[dict] = field(default_factory=list)


def _warn(warnings: list[dict], kind: str, where: str | None, message: str) -> None:
    warnings.append({"kind": kind, "where": where, "message": message})


def _vf(width: int, height: int, fps: int) -> str:
    """どのショットも同じ大きさに揃える.

    **ウィンドウの大きさが途中で変わっても組み立てられる**ようにしておく (letterbox)。
    ただし黙って変えると気づけないので、呼び側が警告を残す。
    """
    return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps},setsar=1")


ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
          "-pix_fmt", "yuv420p", "-an"]


def _still_segment(image: Path, out: Path, seconds: float,
                   width: int, height: int, fps: int) -> None:
    ffmpeg.run(["-loop", "1", "-framerate", str(fps), "-i", str(image),
                "-t", f"{seconds:.3f}", "-vf", _vf(width, height, fps),
                *ENCODE, str(out)])


def _clip_segment(clip: Path, out: Path, seconds: float, clip_seconds: float,
                  width: int, height: int, fps: int) -> None:
    chain = _vf(width, height, fps)
    extra = seconds - clip_seconds
    if extra > 0.02:
        # 足りない分は最後のフレームで埋める (原稿のほうが長いとき)
        chain += f",tpad=stop_mode=clone:stop_duration={extra:.3f}"
    ffmpeg.run(["-i", str(clip), "-t", f"{seconds:.3f}", "-vf", chain,
                *ENCODE, str(out)])


def _black_segment(out: Path, seconds: float,
                   width: int, height: int, fps: int) -> None:
    ffmpeg.run(["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}",
                "-t", f"{seconds:.3f}", *ENCODE, str(out)])


def _frame(source: Path, out: Path, last: bool) -> Path | None:
    """動画の先頭か末尾のフレームを 1 枚。静止画ならそれ自身."""
    if source.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
        return source
    args = ["-sseof", "-0.2"] if last else []
    try:
        ffmpeg.run([*args, "-i", str(source), "-frames:v", "1", str(out)])
    except ffmpeg.FFmpegError:
        return None
    return out if out.exists() else None


def _beat_seconds(outdir: Path, beat, shot_seconds: float | None) -> float:
    """そのビートの尺. **音声・ショット・hold のいちばん長いもの**."""
    seconds = float(beat.hold or 0.0)
    if beat.audio:
        measured = wav_seconds(outdir / beat.audio)
        if measured is not None:
            seconds = max(seconds, measured + AUDIO_TAIL)
    if shot_seconds:
        seconds = max(seconds, shot_seconds)
    if seconds <= 0.0:
        caption = beat.caption
        read = len(caption) / READING_CPS + READING_PAD if caption else 0.0
        seconds = max(MIN_SECONDS, read)
    return round(seconds, 3)


def assemble(plan: Plan, outdir: str | Path, verbose: bool = True) -> Assembled:
    """ショットを並べて 1 本にする."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / WORK_DIR
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    v = plan.video
    width, height, fps = v.width, v.height, v.fps
    warnings: list[dict] = []
    pieces: list[str] = []
    entries: list[dict] = []
    odd_sizes: dict[str, int] = {}

    # **plan.beats は使わない。** (scene, beat) の組しか返さないので、ビートの
    # 添字を beats.index(beat) で取ることになり、**同じ内容のビートが 2 つある
    # と先に出てくるほうの添字を返す** (say が空のビートは実際に並ぶ)
    numbered = [(scene, index, beat)
                for scene in plan.scenes
                for index, beat in enumerate(scene.beats)]
    if not numbered:
        raise ValueError("ビートがありません")

    # --- 冒頭の余白 (最初のショットで止めておく) ---------------------------
    first_shot = _resolve_shot(outdir, numbered[0][2])
    if v.leader > 0.01:
        still = _frame(first_shot, work / "leader.png", last=False) if first_shot else None
        piece = work / "seg-lead.mp4"
        if still:
            _still_segment(still, piece, v.leader, width, height, fps)
        else:
            _black_segment(piece, v.leader, width, height, fps)
        pieces.append(piece.name)

    # --- ビート -------------------------------------------------------
    at = v.leader if v.leader > 0.01 else 0.0
    last_shot: Path | None = None
    for order, (scene, index, beat) in enumerate(numbered):
        where = f"{scene.id}#{index}"
        shot = _resolve_shot(outdir, beat)
        shot_seconds = None

        if shot is None:
            if beat.shot:
                _warn(warnings, "shot_missing", where,
                      f"ショットが見つかりません: {beat.shot} (黒画で埋めます)")
            else:
                _warn(warnings, "shot_missing", where,
                      "ショットがまだありません (黒画で埋めます)")
        else:
            last_shot = shot
            if shot.suffix.lower() == ".mp4":
                shot_seconds = ffmpeg.probe_duration(shot)
            size = _size_of(shot)
            if size and size != (width, height):
                odd_sizes[f"{size[0]}x{size[1]}"] = odd_sizes.get(
                    f"{size[0]}x{size[1]}", 0) + 1

        seconds = _beat_seconds(outdir, beat, shot_seconds)
        piece = work / f"seg-{order:04d}.mp4"
        if shot is None:
            _black_segment(piece, seconds, width, height, fps)
        elif shot_seconds:
            _clip_segment(shot, piece, seconds, shot_seconds, width, height, fps)
        else:
            _still_segment(shot, piece, seconds, width, height, fps)
        pieces.append(piece.name)

        if verbose:
            print(f"    [{at:6.2f}s] {where}: {seconds:5.2f}s  "
                  f"{beat.shot or '(ショットなし)'}")

        audio_path = outdir / beat.audio if beat.audio else None
        entries.append({
            "scene": scene.id,
            "index": index,
            "say": beat.say,
            "caption": beat.caption,
            # timing.json は out/ に置かれ plan.json とは階層が違うので絶対パス
            "audio": str(audio_path.resolve())
                     if audio_path and audio_path.exists() else None,
            "wall_start": round(at, 3),
            "wall_end": round(at + seconds, 3),
            "start": round(at, 3),
            "end": round(at + seconds, 3),
        })
        at += seconds

    # --- 末尾の余白 ---------------------------------------------------
    if v.trailer > 0.01:
        still = _frame(last_shot, work / "trailer.png", last=True) if last_shot else None
        piece = work / "seg-tail.mp4"
        if still:
            _still_segment(still, piece, v.trailer, width, height, fps)
        else:
            _black_segment(piece, v.trailer, width, height, fps)
        pieces.append(piece.name)
        at += v.trailer

    if odd_sizes:
        detail = ", ".join(f"{size} ({count} ビート)" for size, count in odd_sizes.items())
        _warn(warnings, "shot_size", None,
              f"ショットの大きさが video ({width}x{height}) と違います: {detail}。"
              f"上下左右を黒で埋めています。ウィンドウの大きさを変えずに撮り直すと綺麗になります")

    # --- つなぐ -------------------------------------------------------
    listing = work / "concat.txt"
    # **リストの中の相対パスは「リストのある場所」が基準** (cwd ではない)。
    # ここに WORK_DIR を足すと assemble/assemble/… を探しに行く
    listing.write_text("".join(f"file '{name}'\n" for name in pieces),
                       encoding="utf-8")
    dest = outdir / SOURCE_NAME
    if dest.exists():
        dest.unlink()
    # **cwd を出力ディレクトリにして相対名で渡す。** Windows の絶対パスの
    # コロンは concat のリストでも壊れる (render が字幕でやっているのと同じ)
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", f"{WORK_DIR}/{listing.name}",
                "-c", "copy", dest.name], cwd=outdir)

    total = ffmpeg.probe_duration(dest) or at
    timing = {
        "title": plan.title,
        "lang": plan.lang,
        # 音声を使ったときだけクレジットを持ち回す (render が焼く)
        "credit": plan.voice.credit if any(e["audio"] for e in entries) else None,
        "video": {"width": width, "height": height, "fps": fps},
        "source_video": dest.name,
        "duration": round(total, 3),
        "wall_duration": round(at, 3),
        "sync_skew": 0.0,
        # **組み立てが通ったことは中身が合っている証明にはならない。**
        # ショットの欠けと大きさのズレはここに残す
        "warnings": warnings,
        "beats": entries,
    }
    timing_path = outdir / "timing.json"
    timing_path.write_text(json.dumps(timing, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    # 中間ファイルは残さない (ショットと同じ場所に同じ画が二重に貯まる)
    shutil.rmtree(work, ignore_errors=True)
    return Assembled(video=dest, timing=timing_path, duration=total,
                     warnings=warnings)


def _resolve_shot(outdir: Path, beat) -> Path | None:
    if not beat.shot:
        return None
    path = outdir / beat.shot
    return path if path.is_file() else None


def _size_of(path: Path) -> tuple[int, int] | None:
    import subprocess

    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        width, height = out.split("x")[:2]
        return int(width), int(height)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None
