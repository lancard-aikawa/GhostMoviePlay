"""ffmpeg / ffprobe の薄いラッパ."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def available() -> tuple[bool, bool]:
    return shutil.which("ffmpeg") is not None, shutil.which("ffprobe") is not None


def probe_duration(path: str | Path) -> float | None:
    """メディアの尺(秒)。取れなければ None."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError):
        return None


def frame_at(video: str | Path, seconds: float, out: str | Path,
             width: int = 320) -> Path | None:
    """動画の指定時刻から静止画を 1 枚抜く. 取れなければ None.

    台本を直すときに「どのビートの話か」を目で確かめるためのもの。
    **失敗しても呼び側を止めない** —— 画が出ないだけで編集はできる。
    PNG にするのは tkinter がそのまま読めるため。
    """
    out = Path(out)
    if not shutil.which("ffmpeg"):
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # -ss を -i より前に置くと、そこまでデコードせずに飛べる (速い)
        run([
            "-ss", f"{max(0.0, seconds):.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={width}:-1", str(out),
        ])
    except FFmpegError:
        return None
    return out if out.exists() else None


def run(args: list[str], cwd: str | Path | None = None, quiet: bool = True) -> None:
    """ffmpeg を実行。失敗したら stderr 込みで送出する."""
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if quiet:
        cmd += ["-loglevel", "error"]
    cmd += args
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        raise FFmpegError(f"ffmpeg 失敗 (exit {proc.returncode}):\n{tail}")
