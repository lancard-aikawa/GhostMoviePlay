"""Pass3: raw.webm + timing.json -> 字幕焼き込み済み mp4.

やっていること:
  1. webm(可変フレーム間隔) を CFR 化する  ← ここを飛ばすと字幕がズレる
  2. ASS 字幕を焼き込む
  3. ビートに音声があれば adelay で並べて mix する

ffmpeg は outdir を作業ディレクトリにして起動する。字幕フィルタに
Windows の絶対パス (C:\\... のコロン) を渡すと壊れるため、相対名で渡す。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .subtitles import DEFAULT_FONT, write_ass


@dataclass
class Rendered:
    video: Path
    subtitles: Path
    audio_tracks: int


def _audio_inputs(timing: dict, base: Path) -> list[tuple[Path, float]]:
    tracks: list[tuple[Path, float]] = []
    for beat in timing.get("beats", []):
        rel = beat.get("audio")
        if not rel:
            continue
        path = (base / rel).resolve()
        if path.exists():
            tracks.append((path, float(beat.get("start", 0.0))))
    return tracks


def render(
    timing_path: str | Path,
    out: str | Path | None = None,
    font: str = DEFAULT_FONT,
    crf: int = 20,
    preset: str = "medium",
    burn_subtitles: bool = True,
    with_audio: bool = True,
) -> Rendered:
    timing_path = Path(timing_path)
    outdir = timing_path.parent
    timing = json.loads(timing_path.read_text(encoding="utf-8"))

    source = outdir / timing.get("source_video", "raw.webm")
    if not source.exists():
        raise FileNotFoundError(f"収録動画が見つかりません: {source}")

    out = Path(out) if out else outdir / "output.mp4"
    fps = int(timing.get("video", {}).get("fps", 30))

    ass_path = write_ass(timing, outdir / "subs.ass", font=font)

    vf = [f"fps={fps}"]
    if burn_subtitles:
        vf.append(f"subtitles={ass_path.name}")

    args = ["-i", source.name]
    tracks = _audio_inputs(timing, outdir) if with_audio else []
    for path, _ in tracks:
        args += ["-i", str(path)]

    if tracks:
        parts = []
        labels = []
        for i, (_, start) in enumerate(tracks, start=1):
            ms = int(round(start * 1000))
            parts.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
            labels.append(f"[a{i}]")
        mix = f"{''.join(labels)}amix=inputs={len(tracks)}:normalize=0:dropout_transition=0[mix]"
        parts.append(mix)
        parts.append("[mix]apad[aout]")
        parts.append(f"[0:v]{','.join(vf)}[vout]")
        args += [
            "-filter_complex", ";".join(parts),
            "-map", "[vout]", "-map", "[aout]",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
        ]
    else:
        args += ["-vf", ",".join(vf), "-an"]

    args += [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out.name if out.parent == outdir else str(out),
    ]

    ffmpeg.run(args, cwd=outdir)
    return Rendered(video=out, subtitles=ass_path, audio_tracks=len(tracks))
