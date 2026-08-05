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
