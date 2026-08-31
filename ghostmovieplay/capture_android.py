"""Android 端末の画面キャプチャ (adb 経由).

**支援収録 (`gmp shoot`) の撮影担当の Android 版。** [capture.py](capture.py) と
同じ面 (`supported` / `windows` / `foreground` / `find` / `shot` / `Recording` /
`duration` / `even`) を持つので、撮る画面はどちらでも同じように使える。

Windows 版との決定的な違いが 3 つある。

- **範囲を狭められない。** Windows は `PrintWindow` でウィンドウ 1 つを撮るので
  「撮る本人が見ていないものは入らない」が保てる。Android は**画面全体しか撮れない**
  ので、SSID・キャリア名・通知・電池・時計が必ず入る (実測で全部入った)。
  demo mode と DND で減らせても**ゼロにはできない** —— 撮る面がそう書くしかない
- **矩形は一致する。** 静止画も録画も画面全体なので、Windows で踏んだ
  「`PrintWindow` と `gdigrab` で 14x8 px ずれる」は起きない
- **フォーカスを奪わない。** ホスト側から叩くので、ポップアップメニューや通知
  シェードを**開いたまま**撮れる (Krita でメニューが閉じたのとは逆)

実測 (moto g05 / Android 15 / 720x1604 / USB。[docs/ideas/android.md](../docs/ideas/android.md)):

- **静止画は生で取ってホストで PNG にするほうが速い** (1015 ms 対 1241 ms)。
  `screencap -p` は端末側で PNG に圧縮するぶん遅い。`capture.py` が Windows で
  やっているのと同じ形なので **Pillow も要らない**
- **`screencap` は RGBA_8888 を返す** (`PrintWindow` の `bgr0` ではない)。
  アルファは 255 で埋まっていたので、全面透明の PNG になる罠は無い
- **録画は端末側の `screenrecord`。** 開始の遅れが 0.2〜0.3 秒で、scrcpy
  (0.93 秒と 1.89 秒。**同じコマンドの連続 2 回で 1 秒ばらついた**) より小さく
  安定している。既定 180 秒の上限は `--time-limit 0` で外す
- **画面が変わらないとフレームを出さない** (静止した画面を 10 秒撮って 2 フレーム)。
  VFR は `render.py` が先頭で CFR 化するので吸収されるが、
  **尺から録画開始の遅れを逆算する手が使えない** —— 遅れは定数で持たず、
  収録ごとに同期マーカーで測る
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .capture import CaptureError, even

__all__ = ["CaptureError", "Recording", "Device", "duration", "even",
           "find", "foreground", "shot", "supported", "windows"]

ADB = "adb"

# 録画を置く端末側の場所。**撮り終わったら必ず消す** (人の端末に溜めない)
REMOTE_CLIP = "/sdcard/gmp-shoot.mp4"

# screencap のヘッダ。Android 9 以降は 16 バイト (幅・高さ・format・colorspace)、
# それ以前は 12 バイト。**どちらも受ける** —— 長さで見分ける
_HEADERS = (16, 12)

# Android の PixelFormat -> ffmpeg の -pix_fmt。4 バイト/画素のものだけ扱う
_PIX_FMT = {1: "rgba", 2: "rgb0"}


def supported() -> bool:
    """adb があるか. **端末が繋がっているかは見ない** (それは `windows()` の話)."""
    return shutil.which(ADB) is not None


def _argv(*args: str, serial: str = "") -> list[str]:
    """adb のコマンドライン. serial があれば `-s` で 1 台に絞る."""
    head = [ADB, "-s", serial] if serial else [ADB]
    return head + list(args)


def _run(*args: str, serial: str = "", timeout: float = 20.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(_argv(*args, serial=serial), capture_output=True,
                              timeout=timeout)
    except FileNotFoundError as exc:
        raise CaptureError("adb が見つかりません (platform-tools を PATH に)") from exc
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"adb が応答しません: {' '.join(args)}") from exc


def _text(*args: str, serial: str = "") -> str:
    proc = _run(*args, serial=serial)
    return (proc.stdout or b"").decode("utf-8", "replace").replace("\r", "").strip()


@dataclass
class Device:
    """撮れる端末 1 台. **`capture.Window` と同じ属性名**にしてある.

    撮る画面は `handle` を撮影の相手として持ち回るだけなので、それが
    ウィンドウハンドル (int) でもシリアル (str) でも同じように動く。
    """

    handle: str          # シリアル。`adb -s` に渡す
    title: str           # 機種名
    process: str         # Android の版
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.title}  —  {self.process}  ({self.width}x{self.height})"


def _screen_size(serial: str) -> tuple[int, int]:
    """画面の大きさ. **`Override size` があればそちらが実際に映る大きさ**."""
    out = _text("shell", "wm", "size", serial=serial)
    found = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", out)
    if not found:
        raise CaptureError(f"画面の大きさが取れません: {out or '(応答なし)'}")
    width, height = found[-1]          # Override は Physical の後に出る
    return int(width), int(height)


def windows() -> list[Device]:
    """繋がっている端末. **名前は `capture.windows()` に合わせてある**.

    `unauthorized` (端末側で許可していない) と `offline` は落とす ——
    一覧に出しても撮れないので、選ばせると必ず失敗する。
    """
    if not supported():
        return []
    found: list[Device] = []
    for line in _text("devices").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]
        try:
            width, height = _screen_size(serial)
        except CaptureError:
            continue
        model = _text("shell", "getprop", "ro.product.model", serial=serial) or serial
        release = _text("shell", "getprop", "ro.build.version.release", serial=serial)
        found.append(Device(serial, model, f"Android {release}" if release else "Android",
                            width, height))
    return found


def foreground() -> str:
    """**Android には「直前に触っていたウィンドウ」が無い**ので常に空.

    Windows 版はダイアログが別ウィンドウで出るのでこれが要るが、Android は
    画面が 1 つしかない。撮る画面は「空なら選び直さない」ので、これで素通りする。
    """
    return ""


def find(needle: str) -> Device | None:
    """シリアルか機種名の部分一致で 1 台選ぶ. 複数当たったら先頭."""
    if not needle:
        return None
    want = needle.casefold()
    for device in windows():
        if want in device.handle.casefold() or want in device.title.casefold():
            return device
    return None


def _decode(raw: bytes) -> tuple[int, int, str, bytes]:
    """screencap の生データを (幅, 高さ, pix_fmt, 画素) に割る.

    ヘッダの長さは版で違う (Android 9 以降 16 / それ以前 12) ので、
    **宣言された幅・高さと実際の長さが合うほうを採る**。
    """
    if len(raw) < min(_HEADERS):
        raise CaptureError("screencap が何も返しませんでした")
    width, height, fmt = struct.unpack_from("<III", raw, 0)
    if width <= 0 or height <= 0:
        raise CaptureError("screencap のヘッダを読めません")
    for header in _HEADERS:
        if len(raw) == header + width * height * 4:
            if fmt not in _PIX_FMT:
                raise CaptureError(f"知らない画素形式です (PixelFormat {fmt})")
            return width, height, _PIX_FMT[fmt], raw[header:]
    raise CaptureError(
        f"screencap の長さが合いません ({len(raw)} バイト / {width}x{height})")


def shot(handle: str, out: str | Path) -> Path:
    """画面 1 枚を PNG で撮る. **画面全体しか撮れない** (上の注意を読むこと).

    生のまま取ってホストで PNG にする —— 端末側で圧縮させるより速い (実測)。
    """
    proc = _run("exec-out", "screencap", serial=handle, timeout=30.0)
    if proc.returncode != 0:
        why = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise CaptureError(f"screencap が失敗しました: {why or '理由なし'}")
    width, height, pix_fmt, pixels = _decode(proc.stdout or b"")
    return _encode_png(pixels, width, height, pix_fmt, Path(out))


def _encode_png(raw: bytes, width: int, height: int, pix_fmt: str, out: Path) -> Path:
    """生の画素を ffmpeg に食わせて PNG にする. **Pillow を足さない**."""
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{width}x{height}",
         "-i", "-", "-frames:v", "1", str(out)],
        input=raw, capture_output=True,
    )
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise CaptureError("PNG にできません: " + ("\n".join(tail[-5:]) or "ffmpeg 失敗"))
    return out


class Recording:
    """端末の画面を録り続ける. `stop()` まで走る.

    **`screenrecord` は VFR** —— 画面が変わらないとフレームを出さない
    (静止した画面を 10 秒撮って 2 フレームだった)。`fps` は面を合わせるために
    受け取るだけで**使わない**。CFR 化は `render.py` が先頭でやる。

    **`--time-limit 0` で上限を外す。** 既定は 180 秒で、支援収録の 1 ショットが
    それを超えることはまず無いが、黙って切れるほうが危ない。
    """

    # SIGINT を送ってから諦めるまで。**kill してはいけない** (mp4 が壊れる)
    QUIT_TIMEOUT = 15.0
    # ログにこれが出たら実際に録れている (画面のボタンを有効にする合図)
    READY_MARK = "Configuring recorder"

    def __init__(self, handle: str, out: str | Path, fps: int = 15):
        self.serial = handle
        self.out = Path(out)
        self.fps = fps
        width, height = _screen_size(handle)
        self.width, self.height = even(width), even(height)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        _run("shell", "rm", "-f", REMOTE_CLIP, serial=handle)
        self.started = time.monotonic()
        # **stderr をファイルに逃がす。** パイプにして誰も読まないと、埋まった
        # 時点で止まる (capture.py と同じ理由)。`--verbose` の行はここに出る
        self.log = self.out.with_suffix(".log")
        self._log_handle = self.log.open("wb")
        try:
            self.proc = subprocess.Popen(
                _argv("shell", "screenrecord", "--verbose", "--time-limit", "0",
                      REMOTE_CLIP, serial=handle),
                stdin=subprocess.DEVNULL, stdout=self._log_handle,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            self._log_handle.close()
            raise CaptureError(f"screenrecord を起動できません: {exc}") from exc

    @property
    def busy(self) -> bool:
        return self.proc.poll() is None

    @property
    def seconds(self) -> float:
        return time.monotonic() - self.started

    @property
    def ready(self) -> bool:
        """実際に録り始めたか.

        **開始には遅れがある** (実測 0.2〜0.3 秒)。人は `撮影開始` を押してすぐ
        操作を始めるので、これを見ずに始めさせると**頭が録れていない**。
        """
        try:
            return self.READY_MARK in self.log.read_text("utf-8", "replace")
        except OSError:
            return False

    def _wait_gone(self) -> bool:
        """端末から screenrecord が消えるまで待つ.

        **消える前に pull すると、まだ閉じていない mp4 が取れる** —— 尺が読めず
        フレームが 1 つしか入っていない箱になる (実際にそうなった)。
        `adb shell` のほうが先に戻ることがあるので、**ホスト側のプロセスの終了を
        finalize の合図にしてはいけない**。
        """
        deadline = time.monotonic() + self.QUIT_TIMEOUT
        while time.monotonic() < deadline:
            if not _text("shell", "pidof", "screenrecord", serial=self.serial):
                return True
            time.sleep(0.2)
        return False

    def stop(self) -> Path:
        """録画を閉じて手元に持ってくる. **SIGINT で終わらせる** (kill は壊す)."""
        # 実際に録っていた時間。**止めに行く前に読む** (pull と再エンコードを含めない)。
        # 起動の遅れ (実測 0.2〜0.3 秒) のぶん多めに出るが、埋めるほうへ多めなので
        # 「縮めはしない」を破らない
        wall = self.seconds
        if self.proc.poll() is None:
            _run("shell", "pkill", "-INT", "screenrecord", serial=self.serial)
            self._wait_gone()
            try:
                self.proc.wait(timeout=self.QUIT_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        try:
            self._log_handle.close()
        except OSError:
            pass
        pulled = _run("pull", REMOTE_CLIP, str(self.out), serial=self.serial, timeout=120.0)
        # **端末に残さない。** 人の端末なので、失敗しても消しに行く
        _run("shell", "rm", "-f", REMOTE_CLIP, serial=self.serial)
        if pulled.returncode != 0 or not self.out.exists() or self.out.stat().st_size == 0:
            raise CaptureError("録画できませんでした\n" + self._why())
        self._match_wall_clock(wall)
        self.log.unlink(missing_ok=True)
        return self.out

    # 実時間とのずれがこれを超えたら埋める (下の丸めと録画停止の分だけ必ずずれる)
    SLACK = 0.25

    def _match_wall_clock(self, wall: float) -> None:
        """mp4 の尺を、実際に録っていた時間に合わせる.

        **VFR なので、画面が変わらないと尺が実時間より短くなる** —— 静止した
        画面を 6.00 秒撮ったら 0.83 秒だった (最後に変化した時刻で終わる)。
        そのままだと**人が置いた「間」が丸ごと消える**。支援収録は
        「人が 8 秒かけて操作したものを縮めはしない」が決まりなので、ここで直す。

        **足りないぶんを最後のフレームで埋めるだけ** (`assemble` が音声に合わせて
        伸ばすのと同じ手)。**縮めることはしない。** ずれが小さいときは触らない ——
        動きのある画では実測 0.04 秒しかずれず、**その 1 本のために再エンコードを
        かけると撮る人を待たせる**だけになる。
        """
        got = ffmpeg.probe_duration(self.out)
        if got is None or wall - got <= self.SLACK:
            return
        padded = self.out.with_name(self.out.stem + ".pad.mp4")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.out),
             "-vf", f"tpad=stop_mode=clone:stop_duration={wall - got:.3f}",
             "-an", "-r", str(self.fps), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", str(padded)],
            capture_output=True,
        )
        if proc.returncode != 0 or not padded.exists() or padded.stat().st_size == 0:
            padded.unlink(missing_ok=True)
            return          # **埋められなくても撮れたものは返す** (短いだけ)
        padded.replace(self.out)

    def _why(self) -> str:
        try:
            tail = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(tail.strip().splitlines()[-5:])


def duration(path: str | Path) -> float | None:
    return ffmpeg.probe_duration(path)
