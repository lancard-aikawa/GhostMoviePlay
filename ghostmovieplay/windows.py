r"""Windows アプリの画面を読んで操作する (Pass2 の Windows 版のドライバ).

[android.py](android.py) の Windows 版。あちらが `uiautomator dump` を読むのに対し、
こちらは **Win32 のウィンドウツリー**を読む。

## UIA ではなく Win32 を見る

[docs/ideas/desktop.md](../docs/ideas/desktop.md) は UIA ドライバとして書かれていたが、
**当ての外れている前提が 1 つある** —— 7-Zip は UIA に Pane しか出さない (だから
1 本目は人が撮った)。同じウィンドウを Win32 から見ると、こう出る:

    [ToolbarWindow32]  id=0
    [7-Zip::Panel]     id=1000
    [SysListView32]    id=1001     ← ファイル一覧
    [ComboBoxEx32]     id=1003     ← アドレスバー
    [msctls_statusbar32] id=1004

**UIA で何も出ない相手が、Win32 では構造ごと出る。** COM の依存も要らない
(`capture.py` が user32 を ctypes で叩いているのと同じ形で済む)。逆に、Win32 に
子ウィンドウを持たない相手 (WPF / WinUI / Electron) はここでは掴めない —— そちらは
UIA が要るので、**そのときにこの隣へ足す** (`find` の実装を差し替える形になる)。

## 繰り返し撮れるようにするための決めごと

**hwnd を焼かない。** ウィンドウハンドルも control id の並びも起動のたびに変わる
(id そのものはアプリのビルドで決まるので変わらないが、**同じ id が複数出る**)。
掴み直す口は毎回タイトルから始める (`capture.find`)。

**中身で指せるようにする** (`row=`)。一覧の行は「上から 3 番目」で指すと、並び順や
スクロール位置が変わった瞬間に別のものを押す。`SysListView32` は別プロセスからでも
**行の文字と矩形を読める**ので、`row=給与明細_2026-07.pdf` と書けるようにしてある。
これが「id の変わる相手でも繰り返し撮れる」の芯。

**大きさを固定してから始める** (`Driver.fit`)。座標に落ちる操作 (`at=`) と、撮る
矩形の両方がウィンドウの大きさに依存するので、`video.width/height` に合わせてから
操作する。合わせないと、前回の撮影でリサイズした状態が残って絵が変わる。

**触る前に前面へ出す。** 入力は実際のマウスとキーボードとして送るので、裏に居ると
別のアプリに入る。`click` も `type` も自分で前面に出してから送る。

## 入力は実際の入力として送る

`InvokePattern.Invoke()` のような「押したことにする」道は採らない。**実演動画なので、
観る人にはカーソルが動いて見えないと何を押したのか分からない**。`SetCursorPos` +
`mouse_event` で本物のカーソルを動かす。

文字は `SendInput` の `KEYEVENTF_UNICODE`。**IME を経由しない**ので、撮る人の IME が
日本語入力の状態でもそのまま入る (実測: `KEYEVENTF_UNICODE` は IME ON でも素通し。
普通の打鍵は未確定のまま残って**空の入力欄が撮れる**)。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

from .capture import CaptureError, find, supported

# --- Win32 の定数 -----------------------------------------------------
LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMRECT = LVM_FIRST + 14
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVM_ENSUREVISIBLE = LVM_FIRST + 19
LVIF_TEXT = 0x0001
# **行全体 (LVIR_BOUNDS) ではなく、アイコンとラベルの矩形 (LVIR_SELECTBOUNDS)。**
# 一覧に「行全体を選択」が入っていないと、**ラベルの外は当たり判定ではない** ——
# 行全体の中心を押すと、focus の点線は動くのに開かない (7-Zip で実測。
# ダブルクリックが 1 度も効かず、押す場所のせいだと分かるまで時間を使った)
LVIR_SELECTBOUNDS = 3

PROCESS_VM = 0x0008 | 0x0010 | 0x0020 | 0x0400
MEM_COMMIT, MEM_RELEASE, PAGE_RW = 0x1000, 0x8000, 0x04

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004

SETTLE = 0.35           # 押したあと画面が落ち着くまで
POLL = 0.25             # wait_for の間隔
CLICK_GAP = 0.06        # 押してから離すまで
DOUBLE_GAP = 0.08       # ダブルクリックの間隔 (既定の 500ms より十分短く)

# 打てるキーの名前 -> 仮想キーコード。**web と同じ綴りで書けるようにする**
# (`plan.json` の `press` は Playwright の名前で書かれている)
KEYS = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "arrowup": 0x26, "arrowdown": 0x28, "arrowleft": 0x25, "arrowright": 0x27,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}
MODIFIERS = {"control": 0x11, "ctrl": 0x11, "shift": 0x10, "alt": 0x12}


class DriveError(CaptureError):
    """操作できなかった. **CaptureError の仲間**なので撮る側と同じ扱いになる."""


# --- ctypes の型 ------------------------------------------------------
class _LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT), ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int), ("lParam", ctypes.c_void_p),
        ("iIndent", ctypes.c_int), ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT), ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p), ("iGroup", ctypes.c_int),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    # **union に `MOUSEINPUT` を残したまま組む。** `KEYBDINPUT` だけで作ると
    # x64 で 32 バイトになり、SendInput が `cbSize` 不一致で
    # ERROR_INVALID_PARAMETER (87) を返して **1 文字も入らない** (実測)。
    # 権限の問題に見えるが違う
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _api():
    """user32 / kernel32. **Windows 以外では使わせない.**"""
    if not supported():
        raise DriveError("Windows アプリの自動操作は Windows でだけ使えます")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # **DPI を先に宣言する。** 呼ばないプロセスから見た座標は OS に仮想化されるので、
    # ウィンドウが返す物理座標とかみ合わず、押す場所がずれる
    user32.SetProcessDPIAware()
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    return user32, kernel32


# --- 読む -------------------------------------------------------------
@dataclass
class Node:
    """ウィンドウツリーの 1 つ. 画面の座標で持つ."""

    hwnd: int
    cls: str
    text: str
    cid: int
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def label(self) -> str:
        """人が読める名前. **無ければ class** —— 見つからないときの案内に使う."""
        return self.text or f"[{self.cls}]"


def _text_of(user32, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _class_of(user32, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def tree(hwnd: int) -> list[Node]:
    """ウィンドウの中の子ウィンドウを全部読む.

    **見えないものと潰れているものは落とす** (押せないので)。順番は Z オーダー
    ではなく列挙の順 —— 同じ相手なら毎回同じ並びになる。
    """
    user32, _ = _api()
    found: list[Node] = []
    seen: set[int] = set()

    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(child, _lparam):
        child = int(child)
        if child in seen:
            return True
        seen.add(child)
        if not user32.IsWindowVisible(child):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(child, ctypes.byref(rect))
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return True
        found.append(Node(
            hwnd=child, cls=_class_of(user32, child), text=_text_of(user32, child),
            cid=int(user32.GetDlgCtrlID(child)),
            left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom,
        ))
        return True

    user32.EnumChildWindows(hwnd, proc_type(visit), 0)
    return found


def matches(node: Node, selector: str) -> bool:
    """セレクタ 1 つに当たるか. **接頭辞が要る** (推測しない)."""
    kind, sep, want = selector.partition("=")
    if not sep:
        raise DriveError(
            f"セレクタに接頭辞がありません: {selector!r} "
            "(name= / name*= / class= / cid= / row= / row*= / at= のどれか)")
    if kind == "name":
        return node.text == want
    if kind == "name*":
        return want in node.text
    if kind == "class":
        return node.cls == want
    if kind == "cid":
        return str(node.cid) == want.strip()
    if kind in ("row", "row*", "at"):
        return False        # 一覧の中と座標は find の外で扱う
    raise DriveError(f"知らないセレクタです: {selector!r}")


# --- 一覧 (SysListView32) の中を読む ----------------------------------
def _list_views(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.cls == "SysListView32"]


def rows(hwnd: int, limit: int = 400) -> list[tuple[int, str, tuple[int, int, int, int]]]:
    """一覧の行を (番号, 文字, 画面座標の矩形) で読む.

    番号を返すのは `scroll_to` (`LVM_ENSUREVISIBLE`) が要るため。**呼び側が
    数え直さない** —— 読めなかった行を飛ばすので、並びの位置と番号はずれる。

    **別プロセスのメモリを借りて読む。** `LVM_GETITEMTEXTW` は「相手のプロセスから
    見えるポインタ」を要求するので、`VirtualAllocEx` した先に構造体を書いてから
    送り、返ってきた文字を読み戻す。UIA が何も出さない相手でも、これで**行を
    中身で指せる**ようになる (7-Zip がまさにそれ)。
    """
    user32, kernel32 = _api()
    count = int(user32.SendMessageW(hwnd, LVM_GETITEMCOUNT, 0, 0))
    if count <= 0:
        return []

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_VM, False, pid)
    if not handle:
        raise DriveError("一覧を読めません (プロセスを開けません)")

    remote = kernel32.VirtualAllocEx(handle, None, 4096, MEM_COMMIT, PAGE_RW)
    if not remote:
        kernel32.CloseHandle(handle)
        raise DriveError("一覧を読めません (メモリを確保できません)")

    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    text_at = remote + ctypes.sizeof(_LVITEMW)
    out: list[tuple[int, str, tuple[int, int, int, int]]] = []
    try:
        for index in range(min(count, limit)):
            item = _LVITEMW(mask=LVIF_TEXT, iItem=index, iSubItem=0,
                            pszText=text_at, cchTextMax=512)
            kernel32.WriteProcessMemory(handle, ctypes.c_void_p(remote),
                                        ctypes.byref(item), ctypes.sizeof(item), None)
            user32.SendMessageW(hwnd, LVM_GETITEMTEXTW, index, ctypes.c_void_p(remote))
            buf = ctypes.create_unicode_buffer(512)
            kernel32.ReadProcessMemory(handle, ctypes.c_void_p(text_at), buf, 1024, None)

            rect = wintypes.RECT(left=LVIR_SELECTBOUNDS)
            kernel32.WriteProcessMemory(handle, ctypes.c_void_p(remote),
                                        ctypes.byref(rect), ctypes.sizeof(rect), None)
            ok = user32.SendMessageW(hwnd, LVM_GETITEMRECT, index,
                                     ctypes.c_void_p(remote))
            got = wintypes.RECT()
            kernel32.ReadProcessMemory(handle, ctypes.c_void_p(remote),
                                       ctypes.byref(got), ctypes.sizeof(got), None)
            if not ok:
                continue
            out.append((index, buf.value,
                        (origin.x + got.left, origin.y + got.top,
                         origin.x + got.right, origin.y + got.bottom)))
    finally:
        kernel32.VirtualFreeEx(handle, ctypes.c_void_p(remote), 0, MEM_RELEASE)
        kernel32.CloseHandle(handle)
    return out


def point_at(selector: str, rect: tuple[int, int, int, int]) -> tuple[int, int] | None:
    """`at=0.5,0.75` を画面の座標にする. それ以外なら None.

    **ウィンドウの中の割合で持つ** (画面の割合ではない)。画素で焼くと、同じ台本が
    別の解像度で違うところを押す。
    """
    kind, sep, want = selector.partition("=")
    if kind != "at" or not sep:
        return None
    try:
        x, y = (float(v) for v in want.split(","))
    except ValueError as exc:
        raise DriveError(f"at= は 0〜1 の 2 つの数で書きます: {selector!r}") from exc
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise DriveError(f"at= はウィンドウの中の割合なので 0〜1 です: {selector!r}")
    left, top, right, bottom = rect
    return round(left + (right - left) * x), round(top + (bottom - top) * y)


# --- 操作する ---------------------------------------------------------
class Driver:
    """1 つのウィンドウを操作する.

    **ウィンドウは掴み直す。** タイトルで探し直すので、アプリが別ウィンドウ
    (ダイアログ) を出しても `focus()` で乗り換えられる。hwnd を覚えたままにすると、
    閉じたダイアログを押し続ける。
    """

    def __init__(self, title: str, timeout: float = 15.0) -> None:
        self.title = title
        self.timeout = timeout
        self._nodes: list[Node] | None = None

    # --- ウィンドウ ---------------------------------------------------
    @property
    def window(self):
        """いま撮っている / 操作しているウィンドウ. 無ければ落とす."""
        found = find(self.title)
        if found is None:
            raise DriveError(f"ウィンドウが見つかりません: {self.title!r}")
        return found

    @property
    def rect(self) -> tuple[int, int, int, int]:
        user32, _ = _api()
        rect = wintypes.RECT()
        user32.GetWindowRect(self.window.handle, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    def focus(self) -> None:
        """前面に出す. **入力の前に必ず通る** (裏に居ると別のアプリに入る)."""
        user32, _ = _api()
        hwnd = self.window.handle
        user32.ShowWindow(hwnd, 9)              # SW_RESTORE (最小化を戻す)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.12)

    def fit(self, width: int, height: int) -> None:
        """撮る大きさに合わせる. **座標に落ちる操作を繰り返し可能にする芯.**

        前回の撮影でリサイズされたままだと、同じ台本が違うレイアウトを撮る。
        合わせられない相手 (固定サイズのダイアログ) は黙って諦める —— そこは
        中身で指すセレクタの担当。
        """
        user32, _ = _api()
        hwnd = self.window.handle
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.MoveWindow(hwnd, rect.left, rect.top, int(width), int(height), True)
        time.sleep(0.2)
        self._nodes = None

    # --- 読む ---------------------------------------------------------
    def refresh(self) -> list[Node]:
        self._nodes = tree(self.window.handle)
        return self._nodes

    @property
    def nodes(self) -> list[Node]:
        return self._nodes if self._nodes is not None else self.refresh()

    def find(self, selector: str) -> tuple[int, int, int, int] | None:
        """セレクタの矩形 (画面座標). 見つからなければ None.

        `row=` は一覧の中を読む。**見えている一覧が複数あるときは全部見る** ——
        どれが「その一覧」かは台本に書けないので、当たったものを使う。
        """
        kind, _, want = selector.partition("=")
        if kind == "at":
            point = point_at(selector, self.rect)
            if point is None:
                return None
            x, y = point
            return (x, y, x, y)
        if kind in ("row", "row*"):
            hit = self._row(selector)
            return hit[2] if hit else None
        for node in self.nodes:
            if matches(node, selector):
                return (node.left, node.top, node.right, node.bottom)
        return None

    def _row(self, selector: str):
        """`row=` に当たる (一覧, 番号, 矩形, 文字). 見つからなければ None.

        **見えている一覧が複数あるときは全部見る** —— どれが「その一覧」かは
        台本に書けないので、当たったものを使う。
        """
        kind, _, want = selector.partition("=")
        for view in _list_views(self.nodes):
            for index, text, rect in rows(view.hwnd):
                if (text == want) if kind == "row" else (want in text):
                    return view, index, rect, text
        return None

    def wait_for(self, selector: str, seconds: float | None = None) -> tuple[int, int, int, int]:
        """出てくるまで待つ. **触る前は必ずこれを通る.**

        画面が変わるのを待たずに押すと、前の画面の同じ場所を押す (ダイアログが
        出る前に「OK」を押したことにされる)。
        """
        limit = self.timeout if seconds is None else float(seconds)
        deadline = time.monotonic() + limit
        while True:
            self.refresh()
            rect = self.find(selector)
            if rect is not None:
                return rect
            if time.monotonic() >= deadline:
                break
            time.sleep(POLL)
        raise DriveError(
            f"{limit:.0f} 秒待っても見つかりません: {selector!r}\n"
            f"  見えているもの: {self._summary()}")

    def _summary(self, limit: int = 8) -> str:
        """見つからないときに、何が見えているかを出す (直す手がかり)."""
        parts = [f"{n.cls}#{n.cid}" + (f":{n.text}" if n.text else "")
                 for n in self.nodes[:limit]]
        return " / ".join(parts) or "(子ウィンドウ無し)"

    def text(self, selector: str) -> str | None:
        """その矩形が持っている文字. **無ければ None** (空文字と区別する).

        一覧なら行の文字を全部つなぐ (`goal` の `contains` / `absent` が
        「一覧に何が並んでいるか」を見られるように)。
        """
        self.refresh()
        kind, _, _want = selector.partition("=")
        if kind in ("row", "row*"):
            hit = self._row(selector)
            return hit[3] if hit else None
        for node in self.nodes:
            if matches(node, selector):
                if node.cls == "SysListView32":
                    return " ".join(text for _index, text, _rect in rows(node.hwnd))
                return node.text
        return None

    # --- 押す・打つ ---------------------------------------------------
    def click(self, selector: str, double: bool = False) -> None:
        rect = self.wait_for(selector)
        self.focus()
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        self._click_at(x, y, double)
        self._nodes = None

    def _click_at(self, x: int, y: int, double: bool = False) -> None:
        """**本物のカーソルを動かして押す。** 観る人に何を押したか見せるため."""
        user32, _ = _api()
        user32.SetCursorPos(int(x), int(y))
        time.sleep(CLICK_GAP)
        for index in range(2 if double else 1):
            if index:
                time.sleep(DOUBLE_GAP)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(CLICK_GAP)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def hover(self, selector: str) -> None:
        """押さずにカーソルを乗せる. **ツールチップや hover の見た目を撮る用.**"""
        rect = self.wait_for(selector)
        self.focus()
        user32, _ = _api()
        user32.SetCursorPos((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        time.sleep(SETTLE)

    def scroll_to(self, selector: str) -> None:
        """一覧の行を見えるところまで送る (`LVM_ENSUREVISIBLE`).

        **画面の外の行も矩形は返ってくる。** そのまま押すと一覧の外を押すので、
        送ってから押す。行以外のセレクタは、見つかれば何もしない (スクロールの
        いらない相手をわざわざ動かさない)。
        """
        self.refresh()
        kind, _, _want = selector.partition("=")
        if kind in ("row", "row*"):
            hit = self._row(selector)
            if hit is None:
                raise DriveError(f"一覧にありません: {selector!r}")
            view, index, _rect, _text = hit
            user32, _ = _api()
            user32.SendMessageW(view.hwnd, LVM_ENSUREVISIBLE, index, 0)
            time.sleep(SETTLE)
            self._nodes = None
            return
        if self.find(selector) is None:
            raise DriveError(f"見つかりません: {selector!r}")

    def type_text(self, selector: str, text: str) -> None:
        """入力欄を押して、**中身を置き換えて**打つ.

        **web の `type` は追記だが、こちらは置き換え。** デスクトップで打つ相手は
        アドレス欄や検索欄のように**最初から中身がある**のが普通で、追記にすると
        `C:\\gmp\\sampleC:\\gmp` のような値が出来て動かない (実際に踏んだ)。
        押す前に `press Control+a` を書いても効かない —— **入力欄を押した時点で
        選択が外れる**ので、消す手が台本の側に無くなる。

        文字は `_send_unicode` で送るので **IME を経由しない** (撮る人の IME が
        日本語入力の状態でもそのまま入る)。
        """
        self.click(selector)
        time.sleep(SETTLE)
        self.key("Control+a")
        self._send_unicode(text)

    def _send_unicode(self, text: str) -> None:
        user32, _ = _api()
        events = []
        for ch in text:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                item = _INPUT(type=INPUT_KEYBOARD)
                item.ki = _KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flags,
                                      time=0, dwExtraInfo=None)
                events.append(item)
        if not events:
            return
        array = (_INPUT * len(events))(*events)
        sent = user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
        if sent != len(events):
            raise DriveError(
                f"文字を送れません (SendInput={sent}/{len(events)}, "
                f"error={ctypes.get_last_error()})")

    def key(self, name: str) -> None:
        """`Enter` / `Control+A` のような打鍵. **web と同じ綴りで書ける.**"""
        self.focus()
        parts = [p.strip() for p in str(name).split("+") if p.strip()]
        if not parts:
            raise DriveError("押すキーが空です")
        *mods, last = parts
        codes = []
        for mod in mods:
            code = MODIFIERS.get(mod.casefold())
            if code is None:
                raise DriveError(f"知らない修飾キーです: {mod!r}")
            codes.append(code)
        target = KEYS.get(last.casefold())
        if target is None:
            if len(last) == 1:
                target = ord(last.upper())
            else:
                raise DriveError(
                    f"知らないキーです: {last!r} (使えるのは: "
                    f"{' / '.join(sorted(KEYS))})")
        user32, _ = _api()
        for code in codes:
            user32.keybd_event(code, 0, 0, 0)
        user32.keybd_event(target, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(target, 0, KEYEVENTF_KEYUP, 0)
        for code in reversed(codes):
            user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
        self._nodes = None
