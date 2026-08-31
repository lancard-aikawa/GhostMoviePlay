"""ウィンドウ単位の画面キャプチャ (Windows).

**支援収録 (`gmp shoot`) の撮影担当。** 自動操作が届かない相手 —— ログインの要る
業務アプリ、canvas、OAuth —— を人が操作し、そのウィンドウだけを撮る。

**必ずウィンドウ単位で撮る。デスクトップ全体は撮らない。**
ウィンドウを 1 つ起こすだけで、撮る対象と関係のないものが画面に載る (検証中、メモ帳が
前のセッションのタブを復元して機密ファイル名を表示した)。範囲をウィンドウに閉じておけば、
撮る本人が見ていないものは入らない。

静止画は `PrintWindow` で**ウィンドウ自身に描かせる**ので、手前に別のウィンドウがあっても画面外に
はみ出していても綺麗に撮れる。代わりにマウスカーソルは写らない。
動画は `ffmpeg -f gdigrab` で画面の矩形を舐めるので**カーソルは写るが重なりに弱い**。
この違いは埋められないので、録画中はウィンドウを隠さないこと。

実測して分かったこと (Windows 11):

- `PrintWindow` の第 3 引数は **`2` (`PW_RENDERFULLCONTENT`) が要る**。`0` だと
  DirectComposition で描くアプリ (WinUI・Chromium・Electron) が真っ黒になる
- ストア配信のアプリは launcher が別 PID に受け渡して終了するので、
  **起動したときの PID を覚えてもウィンドウに辿り着けない**。ウィンドウの側から掴み直す
- `GetWindowRect` は不可視のリサイズ枠を含む。録画の範囲にそのまま使うと
  ウィンドウの外が写り込むので、`DWMWA_EXTENDED_FRAME_BOUNDS` のほうを使う
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg


class CaptureError(RuntimeError):
    """撮れなかった."""


# --- 撮る画面が backend ごとに出し分けるもの --------------------------
# 撮る相手の呼び名 (画面の文言に使う)
NOUN = "ウィンドウ"
# 使えないときに理由として出す文
UNSUPPORTED = "画面キャプチャは Windows でだけ使えます"
# **選んだ相手の名前を plan.json に書き戻してよいか。** ウィンドウのタイトルは
# 機械に依らないのでそのまま `app.window` になる (Android のシリアルは違う)
NAMES_THE_TARGET = True
# 撮る前に人へ言っておくこと。**録画だけ重なりに弱い** (静止画は PrintWindow で
# ウィンドウ自身に描かせるが、録画は gdigrab で画面の矩形を舐める)
CAUTION = "録画中はウィンドウを隠さないこと（静止画は隠れていても撮れます）"


def supported() -> bool:
    return sys.platform == "win32"


# --- Win32 ------------------------------------------------------------
PW_RENDERFULLCONTENT = 2
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
BI_RGB = 0
DIB_RGB_COLORS = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _api():
    """user32 / gdi32 / dwmapi。Windows 以外では使わせない."""
    if not supported():
        raise CaptureError("画面キャプチャは Windows でだけ使えます")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    user32.SetProcessDPIAware()
    return user32, gdi32, dwmapi


@dataclass(frozen=True)
class Window:
    """撮れるウィンドウ 1 つ."""

    handle: int
    title: str
    process: str
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.title}  —  {self.process}  ({self.width}x{self.height})"


def _process_name(user32, handle: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    try:
        # psutil は入れない。tasklist も遅い。実行ファイル名だけ取れれば足りる
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        proc = kernel32.OpenProcess(0x1000, False, pid.value)   # LIMITED_INFORMATION
        if not proc:
            return str(pid.value)
        try:
            size = wintypes.DWORD(260)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(proc)
    except OSError:
        pass
    return str(pid.value)


def windows(min_size: int = 120) -> list[Window]:
    """いま開いているウィンドウの一覧. **画素は返さない** ので安く安全に呼べる.

    撮る前にこれで当たりを付ける手順にしておけば、何が写るか分かったうえで撮れる。
    """
    user32, _gdi32, dwmapi = _api()
    found: list[Window] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _param):
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        # UWP の隠しウィンドウは EnumWindows に出てくるが描画されていない
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(handle), DWMWA_CLOAKED,
            ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < min_size or height < min_size:
            return True
        found.append(Window(int(handle), title, _process_name(user32, handle),
                            width, height))
        return True

    user32.EnumWindows(visit, 0)
    return found


def foreground() -> int:
    """いま前面にあるウィンドウ. **自分のプロセスのものは 0** を返す.

    撮る画面に戻ってきたとき「直前に触っていたのはどれか」を知るために使う。
    ダイアログは操作している最中に出てくるので、これが無いと人が毎回
    一覧から選び直すことになる。
    """
    if not supported():
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle = user32.GetForegroundWindow()
    if not handle:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return 0 if pid.value == os.getpid() else int(handle)


def find(title: str) -> Window | None:
    """タイトルの部分一致で 1 つ選ぶ. 複数当たったら先頭.

    **起動したときの PID では掴まない。** ストア配信のアプリは launcher が
    別 PID に受け渡して終了するので、PID を覚えても永遠にウィンドウが見つからない。
    """
    if not title:
        return None
    needle = title.casefold()
    for window in windows():
        if needle in window.title.casefold():
            return window
    return None


def _rect(user32, dwmapi, handle: int, visible: bool) -> tuple[int, int, int, int]:
    """(left, top, width, height). visible なら不可視のリサイズ枠を除く."""
    rect = wintypes.RECT()
    if visible:
        status = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(handle), DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect), ctypes.sizeof(rect))
        if status != 0:
            user32.GetWindowRect(handle, ctypes.byref(rect))
    else:
        user32.GetWindowRect(handle, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def even(value: int) -> int:
    """h264 は偶数の幅と高さしか受け付けない."""
    return max(2, value - (value % 2))


def shot(handle: int, out: str | Path) -> Path:
    """ウィンドウ 1 つを PNG で撮る. **重なっていても画面外でも撮れる**.

    最小化中のウィンドウは中身を持たないので撮れない (呼ぶ前に確かめること)。
    """
    user32, gdi32, dwmapi = _api()
    if not user32.IsWindow(handle):
        raise CaptureError("そのウィンドウはもうありません")
    if user32.IsIconic(handle):
        raise CaptureError("最小化されているウィンドウは撮れません (元に戻してください)")

    _left, _top, width, height = _rect(user32, dwmapi, handle, visible=False)
    width, height = even(width), even(height)
    if width < 2 or height < 2:
        raise CaptureError("ウィンドウの大きさが取れません")

    window_dc = user32.GetWindowDC(handle)
    if not window_dc:
        raise CaptureError("デバイスコンテキストを取れません")
    mem_dc = bitmap = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        gdi32.SelectObject(mem_dc, bitmap)
        # **フラグは 2 (PW_RENDERFULLCONTENT)。** 0 だと WinUI や Chromium が真っ黒
        if not user32.PrintWindow(handle, mem_dc, PW_RENDERFULLCONTENT):
            raise CaptureError("PrintWindow が失敗しました")

        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height          # 負なら上から下 (top-down)
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer,
                               ctypes.byref(info), DIB_RGB_COLORS):
            raise CaptureError("画素を取り出せません")
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(handle, window_dc)

    return _encode_png(buffer.raw, width, height, Path(out))


def _encode_png(raw: bytes, width: int, height: int, out: Path) -> Path:
    """生の BGRA を ffmpeg に食わせて PNG にする.

    **Pillow を足さない。** ffmpeg はこの道具の必須依存なので、静止画 1 枚の
    ために画像ライブラリを増やす理由が無い。`bgr0` にしているのは、
    `PrintWindow` が返すアルファが 0 のことがあり、`bgra` だと**全面透明の
    PNG** になるため。
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr0", "-s", f"{width}x{height}",
         "-i", "-", "-frames:v", "1", str(out)],
        input=raw, capture_output=True,
    )
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise CaptureError("PNG にできません: " + ("\n".join(tail[-5:]) or "ffmpeg 失敗"))
    return out


class Recording:
    """ウィンドウの矩形を録画し続ける. `stop()` まで走る.

    **`gdigrab` は画面の矩形を舐める方式**なので、録画中に別のウィンドウを手前に出すと
    それが写る。`PrintWindow` のような重なり耐性は無い —— 埋められない差なので、
    呼び側が「ウィンドウを隠さないでください」と言うこと。
    """

    # ffmpeg に 'q' を送ってから諦めるまで
    QUIT_TIMEOUT = 10.0

    def __init__(self, handle: int, out: str | Path, fps: int = 15):
        self.out = Path(out)
        self.fps = fps
        user32, _gdi32, dwmapi = _api()
        if not user32.IsWindow(handle):
            raise CaptureError("そのウィンドウはもうありません")
        if user32.IsIconic(handle):
            raise CaptureError("最小化されているウィンドウは撮れません")
        left, top, width, height = _rect(user32, dwmapi, handle, visible=True)
        self.width, self.height = even(width), even(height)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        # **stderr をパイプにしない。** 誰も読まないまま録り続けると、パイプが
        # 埋まった時点で ffmpeg が書き込みで止まる —— 画面上は録画中のまま
        # 何分でも固まる。ファイルなら埋まらないし、失敗の理由も後から読める
        self.log = self.out.with_suffix(".log")
        self._log_handle = self.log.open("wb")
        try:
            self.proc = subprocess.Popen(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "gdigrab", "-framerate", str(fps),
                 "-offset_x", str(left), "-offset_y", str(top),
                 "-video_size", f"{self.width}x{self.height}", "-i", "desktop",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(self.out)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._log_handle,
            )
        except OSError as exc:
            self._log_handle.close()
            raise CaptureError(f"ffmpeg を起動できません: {exc}") from exc

    @property
    def busy(self) -> bool:
        return self.proc.poll() is None

    @property
    def seconds(self) -> float:
        return time.monotonic() - self.started

    def stop(self) -> Path:
        """録画を閉じる. **`q` で終わらせる** —— kill するとファイルが壊れる."""
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=self.QUIT_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for handle in (self.proc.stdin, self._log_handle):
            try:
                handle.close()
            except OSError:
                pass
        if not self.out.exists() or self.out.stat().st_size == 0:
            raise CaptureError("録画できませんでした\n" + self._why())
        # 通ったログは残さない (出力先に読まれない .log が貯まる)
        self.log.unlink(missing_ok=True)
        return self.out

    def _why(self) -> str:
        try:
            tail = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(tail.strip().splitlines()[-5:])


def duration(path: str | Path) -> float | None:
    return ffmpeg.probe_duration(path)
