"""Android の画面を読んで操作する (adb 経由).

**`record_android` の駆動担当。** 撮るのは [capture_android.py](capture_android.py)、
ここは「どこを押すか」を決めて押すほうだけを持つ。

実測 (moto g05 / Android 15。[docs/ideas/android.md](../docs/ideas/android.md)):

- **`uiautomator dump` は 1 回 2.6 秒。** 要素を引くたびに走らせると使い物に
  ならないので、**1 回読んだら使い回す** (`Driver.refresh()` を呼ぶまで)
- **Flutter はラベルを `text` ではなく `content-desc` に載せる。** a-lamo で
  実測したところ 35 ノード中 `text` を持つものは **0**、`content-desc` は 16。
  Web の癖で `text=` を書くと 1 つも当たらない
- **ダンプはウィンドウが idle になるまで待つ。** アニメーションが止まらない
  画面では `ERROR: could not get idle state` で落ちる。落ちたら握り潰さず、
  待って撮り直す側に判断させる
- **`input text` は日本語を黙って落とす。** 非 ASCII は端末側の KeyCharacterMap
  に無いので、コマンドは成功して入力欄が空のまま残る (a-lamo で実測。**失敗が
  画面にもログにも出ない**)。ローマ字は IME が変換してしまい
  (`zentai renraku` → 「全体れんらく」)、**学習状態で結果が変わる**ので
  決定論にならない。日本語は `ADBKeyboard` に broadcast で渡す

**セレクタは接頭辞を必ず書かせる。** 省略時に「たぶん content-desc」と推測すると、
当たらなかったのか間違ったものに当たったのかが区別できない。

    desc=送信          content-desc が完全一致
    desc*=送信         content-desc に含む
    text=送信          text が完全一致 (Flutter では当たらない)
    id=btn_send        resource-id の末尾一致 (`:id/` の後ろ)
    at=0.5,0.75        画面の割合で直接指す。**ツリーに出ない相手の最後の手**
"""

from __future__ import annotations

import base64
import html
import re
import subprocess
import time
from dataclasses import dataclass

from .capture import CaptureError
from .capture_android import REMOTE_TMP, _argv, _run, _text

# ダンプが idle を待てずに落ちたときの、諦めるまでの回数
DUMP_TRIES = 3
# 端末側の作業場所は capture_android が 1 か所で持っている (`/sdcard` に置かない
# 理由もあちら)。**録画とダンプで別の場所にしない**
REMOTE_DUMP = f"{REMOTE_TMP}/gmp-ui.xml"

# 日本語を打つための IME (senzhk/ADBKeyBoard)。**端末に入れるのは撮る人の仕事**で、
# ここは入れない —— 人の端末にアプリを勝手に足す道を作らない。既定に据えるのも
# `app.setup` の役目 (仕込みと後片付けはそこに書く、という決まりのまま)
ADB_KEYBOARD = "com.android.adbkeyboard"
# **base64 で渡す** (`ADB_INPUT_TEXT` ではなく)。日本語をそのまま並べると、
# ホストの shell と端末の shell の 2 回の引用を抜けられない
ADB_KEYBOARD_ACTION = "ADB_INPUT_B64"

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_NODE = re.compile(r"<node\s([^>]*?)/?>")
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"')


class DriveError(CaptureError):
    """操作できなかった. **CaptureError の仲間**なので撮る側と同じ扱いになる."""


@dataclass
class Node:
    cls: str
    desc: str
    text: str
    rid: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def label(self) -> str:
        """人が読める名前. **無ければ空** —— class 名を出すと、見つからないときの
        案内が `android.view.View` の羅列になって役に立たない (実際になった)."""
        return self.desc or self.text or self.rid.rpartition("/")[2]


def parse(dump: str) -> list[Node]:
    """ダンプを読む. **矩形の無いノードは落とす** (押せないので).

    **XML パーサを使わない。** ダンプは `<node .../>` が並ぶだけの平坦な形なので
    属性を直接拾えば足りる。パーサを持ち込むと XXE や billion laughs のために
    `defusedxml` を足すことになり、**静止画 1 枚のために Pillow を足さない**のと
    同じ理由で割に合わない (端末の中のアプリが content-desc に何を書いていても、
    ここは文字として扱うだけになる)。
    """
    found: list[Node] = []
    for raw in _NODE.finditer(dump):
        attrs = {k: html.unescape(v) for k, v in _ATTR.findall(raw.group(1))}
        hit = _BOUNDS.fullmatch(attrs.get("bounds", ""))
        if not hit:
            continue
        left, top, right, bottom = (int(x) for x in hit.groups())
        if right <= left or bottom <= top:
            continue
        found.append(Node(
            cls=attrs.get("class", ""), desc=attrs.get("content-desc", ""),
            text=attrs.get("text", ""), rid=attrs.get("resource-id", ""),
            left=left, top=top, right=right, bottom=bottom,
        ))
    return found


def matches(node: Node, selector: str) -> bool:
    """セレクタ 1 つに当たるか. **接頭辞が要る** (推測しない)."""
    kind, sep, want = selector.partition("=")
    if not sep:
        raise DriveError(
            f"セレクタに接頭辞がありません: {selector!r} "
            "(desc= / desc*= / text= / id= / at= のどれか)")
    if kind == "desc":
        return node.desc == want
    if kind == "desc*":
        return want in node.desc
    if kind == "text":
        return node.text == want
    if kind == "id":
        return node.rid.rpartition("/")[2] == want
    if kind == "at":
        return False        # 座標は探さずに直接使う (find の外で扱う)
    raise DriveError(f"知らないセレクタです: {selector!r}")


def inside(outer: Node, inner: Node) -> bool:
    """`inner` の矩形が `outer` に収まっているか."""
    return (inner.left >= outer.left and inner.top >= outer.top
            and inner.right <= outer.right and inner.bottom <= outer.bottom)


def text_within(nodes: list[Node], target: Node) -> str:
    """その矩形の中にある文字を集める. **web の `inner_text` に当たるもの**.

    **ダンプは平坦で親子が無い**ので、矩形の内側かどうかで代用する。Flutter は
    文字を子ノードの content-desc に載せるので、**指した相手そのものには文字が
    無いのが普通** —— `id=set_enquete` (枠) の中に `desc=未設定` が別ノードで
    いる。自分の文字だけを見ると、達成条件がいつまでも当たらない。
    """
    parts = [n.desc or n.text for n in nodes if inside(target, n) and (n.desc or n.text)]
    return " ".join(" ".join(parts).split())


def point_at(selector: str, width: int, height: int) -> tuple[int, int] | None:
    """`at=0.5,0.75` を画素にする. それ以外なら None.

    **割合で持つ。** 画素で焼くと、同じ台本が別の端末で違うところを押す。
    """
    kind, sep, want = selector.partition("=")
    if kind != "at" or not sep:
        return None
    try:
        x, y = (float(v) for v in want.split(","))
    except ValueError as exc:
        raise DriveError(f"at= は 0〜1 の 2 つの数で書きます: {selector!r}") from exc
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise DriveError(f"at= は画面の割合なので 0〜1 です: {selector!r}")
    return round(width * x), round(height * y)


class Driver:
    """1 台の端末を操作する.

    **ダンプは高い (2.6 秒) ので、明示的に読み直すまで使い回す。**
    操作したあとは画面が変わるので、`tap` などは自分で読み直す。
    """

    def __init__(self, serial: str, size: tuple[int, int]):
        self.serial = serial
        self.width, self.height = size
        self._nodes: list[Node] | None = None
        self._ime: str | None = None

    # --- 読む ---------------------------------------------------------
    def refresh(self) -> list[Node]:
        last = ""
        for _ in range(DUMP_TRIES):
            out = _text("shell", "uiautomator", "dump", REMOTE_DUMP, serial=self.serial)
            if "ERROR" not in out.upper():
                xml = _text("shell", "cat", REMOTE_DUMP, serial=self.serial)
                _run("shell", "rm", "-f", REMOTE_DUMP, serial=self.serial)
                self._nodes = parse(xml)
                return self._nodes
            last = out
            # **idle を待てなかっただけのことが多い。** 少し待って読み直す
            time.sleep(1.0)
        raise DriveError(f"画面を読めません: {last or '理由なし'}")

    @property
    def nodes(self) -> list[Node]:
        return self._nodes if self._nodes is not None else self.refresh()

    def find(self, selector: str) -> Node | None:
        return next((n for n in self.nodes if matches(n, selector)), None)

    def text(self, selector: str) -> str | None:
        """その相手の中にある文字. 見つからなければ None (空文字と区別する)."""
        hit = self.find(selector)
        return None if hit is None else text_within(self.nodes, hit)

    def wait_for(self, selector: str, timeout: float = 10.0) -> Node:
        """出るまで待つ. **出なければ落とす** (見えていない画面を撮らない)."""
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            hit = self.find(selector)
            if hit is not None:
                return hit
            if time.monotonic() >= deadline:
                raise DriveError(f"{selector} が {timeout:g} 秒待っても出ません")

    # --- 押す ---------------------------------------------------------
    def point(self, selector: str) -> tuple[int, int]:
        fixed = point_at(selector, self.width, self.height)
        if fixed is not None:
            return fixed
        hit = self.find(selector)
        if hit is None:
            self.refresh()
            hit = self.find(selector)
        if hit is None:
            near = ", ".join(sorted({n.label for n in self.nodes if n.label})[:8])
            raise DriveError(f"{selector} が見つかりません (画面にあるもの: {near})")
        return hit.center

    def tap(self, selector: str) -> None:
        x, y = self.point(selector)
        _run("shell", "input", "tap", str(x), str(y), serial=self.serial)
        self._nodes = None          # 押したら画面が変わる

    def ime(self) -> str:
        """いま既定になっている IME. **1 回読んだら覚える** (adb 1 往復ぶん)."""
        if self._ime is None:
            self._ime = _text("shell", "settings", "get", "secure",
                              "default_input_method", serial=self.serial)
        return self._ime

    def type_text(self, selector: str, text: str) -> None:
        """入力欄を押してから打つ. **`input text` は空白を打てない**ので %s に置く.

        **ADBKeyboard が既定なら、いつでも broadcast で渡す。** ASCII だけ
        `input text` に戻すと、同じ台本が端末の状態で 2 通りの打ち方になる。
        """
        self.tap(selector)
        time.sleep(0.4)
        if self.ime().startswith(ADB_KEYBOARD):
            msg = base64.b64encode(text.encode("utf-8")).decode("ascii")
            _run("shell", "am", "broadcast", "-a", ADB_KEYBOARD_ACTION,
                 "--es", "msg", msg, serial=self.serial)
        elif text.isascii():
            _run("shell", "input", "text", text.replace(" ", "%s"), serial=self.serial)
        else:
            # **黙って空のまま撮らない。** `input text` は非 ASCII を落として
            # 成功するので、ここで止めないと打てていない画が撮れる (実際に撮れた)
            raise DriveError(
                f"日本語は `input text` では打てません: {text!r}\n"
                f"  ADBKeyboard を入れて既定の IME にしてください "
                f"(いまの既定: {self.ime() or '読めません'})\n"
                f"  adb install ADBKeyboard.apk && "
                f"adb shell ime enable {ADB_KEYBOARD}/.AdbIME && "
                f"adb shell ime set {ADB_KEYBOARD}/.AdbIME")
        self._nodes = None

    def key(self, name: str) -> None:
        _run("shell", "input", "keyevent", name, serial=self.serial)
        self._nodes = None

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        _run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms),
             serial=self.serial)
        self._nodes = None

    def argv(self, *args: str) -> list[str]:
        """テストから組み立てを覗くため."""
        return _argv(*args, serial=self.serial)


def available(serial: str) -> bool:
    proc = subprocess.run(_argv("shell", "true", serial=serial), capture_output=True)
    return proc.returncode == 0
