"""台本 (plan.json) の文と間を画面の中で直す.

**動画を観てから「ここだけ」を直す道。** 出来上がりを観ると、言い回しを
変えたい・もう少し説明が欲しい、が必ず出る。それを Claude に回すと、1 行の
ために台本全体を書き直させることになる —— 録画も書き出しも決定論にしてある
道具で、唯一決定論の外にいるのが Pass1 なので、そこを呼ばずに済ませたい。

**ここは「決める」画面ではない。** 直せるのは `say` / `subtitle` / `hold` の
3 つだけで、`actions` と selector は入れない。何をどう操作するかは
そのプロジェクトを読まないと決まらないので、Claude の領分のまま
(「画面は Claude の代わりをしない」)。

画面にしかできない仕事は**どこからやり直せば反映されるかを言うこと**:

    字幕だけ  → 仕上げ直すだけ (数十秒)
    間        → 撮り直し
    原稿      → 声を作り直して撮り直し

`timing.json` がビートごとの実測時刻を持っているので、`raw.webm` からその
ビートの画を 1 枚抜いて出せる。「動画のここ」と画面の行がそれで結び付く。
"""

from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from .plan import EDITABLE, Plan, beat_address

SHOT_WIDTH = 320          # 静止画の幅 (px)
SHOT_LINES = 11           # 画が無いときに空けておく高さ (行)。おおよそ同じ高さ

# 直した項目 → どこからやり直すか。深いほうが勝つ
DEPTH = {"subtitle": 0, "hold": 1, "say": 2}
REDO = {
    0: ("render", "仕上げ直すだけで反映されます (絵も音も変わりません)"),
    1: ("record", "撮り直しが要ります (間が変わるので)"),
    2: ("voice", "声を作り直してから撮り直します (直したビートの wav だけ)"),
}


def redo_for(changed) -> tuple[str, str] | None:
    """直した項目から、やり直しの深さを決める. 何も直していなければ None."""
    depths = [DEPTH[name] for name in changed if name in DEPTH]
    return REDO[max(depths)] if depths else None


@dataclass(frozen=True)
class BeatRow:
    """一覧に出す 1 ビート."""

    address: str            # "why#1" (収録の警告の where と同じ書き方)
    scene: str
    index: int
    say: str
    subtitle: str
    hold: float
    start: float | None = None   # timing.json があれば実測時刻
    end: float | None = None

    @property
    def caption(self) -> str:
        return self.subtitle or self.say

    @property
    def when(self) -> str:
        if self.start is None:
            return "-"
        return f"{int(self.start // 60)}:{self.start % 60:04.1f}"

    @property
    def seconds(self) -> float | None:
        if self.start is None or self.end is None:
            return None
        return max(0.0, self.end - self.start)

    @property
    def middle(self) -> float | None:
        """そのビートを代表する時刻 (静止画を抜く位置)."""
        if self.start is None:
            return None
        return self.start + (self.seconds or 0.0) / 2


def rows(plan: Plan, timing: dict | None = None) -> list[BeatRow]:
    """台本を一覧の行にする. timing.json があれば実測時刻も添える."""
    measured: dict[str, tuple[float, float]] = {}
    for entry in (timing or {}).get("beats", []) or []:
        try:
            key = f"{entry['scene']}#{entry['index']}"
            measured[key] = (float(entry["start"]), float(entry["end"]))
        except (KeyError, TypeError, ValueError):
            continue

    out: list[BeatRow] = []
    for index, scene in enumerate(plan.scenes):
        for beat_index, beat in enumerate(scene.beats):
            address = beat_address({"id": scene.id}, index, beat_index)
            start, end = measured.get(address, (None, None))
            out.append(BeatRow(
                address=address, scene=scene.id, index=beat_index,
                say=beat.say or "", subtitle=beat.subtitle or "",
                hold=float(beat.hold or 0.0), start=start, end=end,
            ))
    return out


def read_timing(outdir: Path | None) -> dict | None:
    if not outdir:
        return None
    try:
        return json.loads((Path(outdir) / "timing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class PlanEditor:
    """台本の文と間を直す小さなウィンドウ."""

    def __init__(self, parent: tk.Misc, path: Path, outdir: Path | None = None,
                 on_saved=None):
        self.path = Path(path)
        self.outdir = Path(outdir) if outdir else None
        self.on_saved = on_saved
        self.pending: dict[str, dict] = {}   # 直したがまだ保存していないもの
        self.current: BeatRow | None = None
        self._photo = None                   # PhotoImage は参照を持たないと消える

        from .plan import PlanError, load

        try:
            self.plan = load(self.path)
        except (PlanError, OSError, ValueError) as exc:
            raise ValueError(str(exc).removeprefix(f"{self.path}: ")) from exc
        self.rows = rows(self.plan, read_timing(self.outdir))

        self.window = tk.Toplevel(parent)
        self.window.title(f"台本 — {self.path}")
        self.window.geometry("1000x620")

        # **下の帯を先に pack する。** 本体を先に置くと cavity を食い尽くして
        # ボタンが画面外に出る (CLAUDE.md)
        self._build_footer()
        self._build_status()
        self._build_body()

        if self.rows:
            self.table.selection_set(self.rows[0].address)
            self.show(self.rows[0])
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- 組み立て ----------------------------------------------------
    def _build_footer(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        tk.Button(bar, text="閉じる", width=10, command=self.on_close).pack(side=tk.RIGHT)
        tk.Button(bar, text="保存", width=10, command=self.on_save).pack(
            side=tk.RIGHT, padx=6)
        tk.Label(bar, fg="#666", justify=tk.LEFT,
                 text="直せるのは文と間だけ。操作 (actions) と selector は"
                      "claude に書かせる").pack(side=tk.LEFT)

    def _build_status(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value=str(self.path))
        tk.Label(bar, textvariable=self.status, anchor="w", fg="#444",
                 wraplength=960, justify=tk.LEFT).pack(
            side=tk.LEFT, fill=tk.X, padx=10, pady=2)

    def _build_body(self) -> None:
        body = tk.Frame(self.window)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

        left = tk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.table = ttk.Treeview(left, columns=("when", "len", "caption"),
                                  show="headings", selectmode="browse")
        for key, title, width in (("when", "時刻", 60), ("len", "尺", 50),
                                  ("caption", "字幕", 320)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.table.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.table.bind("<<TreeviewSelect>>", self._on_pick)
        self._fill_table()

        right = tk.Frame(body, width=380)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        self.shot = tk.Label(right, text="", anchor="center", fg="#999",
                             bg="#1e1e1e", height=SHOT_LINES)
        self.shot.pack(side=tk.TOP, fill=tk.X)
        self.when = tk.Label(right, text="", anchor="w", fg="#666")
        self.when.pack(side=tk.TOP, fill=tk.X, pady=(4, 8))

        tk.Label(right, text="原稿 (say)", anchor="w").pack(side=tk.TOP, fill=tk.X)
        self.say = tk.Text(right, height=4, wrap="char")
        self.say.pack(side=tk.TOP, fill=tk.X)

        tk.Label(right, text="字幕 (空なら原稿をそのまま使う)", anchor="w").pack(
            side=tk.TOP, fill=tk.X, pady=(8, 0))
        self.subtitle = tk.Text(right, height=3, wrap="char")
        self.subtitle.pack(side=tk.TOP, fill=tk.X)

        line = tk.Frame(right)
        line.pack(side=tk.TOP, fill=tk.X, pady=(8, 0))
        tk.Label(line, text="間 (hold) 秒").pack(side=tk.LEFT)
        self.hold = tk.Entry(line, width=8)
        self.hold.pack(side=tk.LEFT, padx=6)
        tk.Label(line, fg="#666", text="音声があればそちらの尺が優先").pack(side=tk.LEFT)

    def _fill_table(self) -> None:
        for row in self.rows:
            length = f"{row.seconds:.1f}s" if row.seconds is not None else "-"
            self.table.insert("", "end", iid=row.address,
                              values=(row.when, length, row.caption[:40]))

    # --- 行の出し入れ -------------------------------------------------
    def _on_pick(self, _event=None) -> None:
        picked = self.table.selection()
        if not picked:
            return
        row = next((r for r in self.rows if r.address == picked[0]), None)
        if row is None or (self.current and row.address == self.current.address):
            return
        self.show(row)

    def show(self, row: BeatRow) -> None:
        """その行の中身を右側に出す (直しかけがあればそちらを出す).

        **出ている行の入力を先に覚える。** どの道から行を移っても消えないよう、
        取り込みは表の選択ではなくここに置く (観ながら直す道具なので、行を
        行き来しているうちに打った文字が消えるのは致命的)。
        """
        self.capture()
        self.current = row
        held = self.pending.get(row.address, {})
        self._set(self.say, held.get("say", row.say))
        self._set(self.subtitle, held.get("subtitle", row.subtitle))
        self.hold.delete(0, tk.END)
        self.hold.insert(0, self._hold_text(held.get("hold", row.hold)))
        self.when.config(text=(
            f"{row.address}   {row.when} から {row.seconds:.1f} 秒"
            if row.seconds is not None else f"{row.address}   (まだ撮っていません)"
        ))
        self._show_shot(row)

    def capture(self) -> None:
        """いま出ている行の入力を覚える (行を移っても消えないように)."""
        row = self.current
        if row is None:
            return
        values = {
            "say": self.say.get("1.0", "end-1c"),
            "subtitle": self.subtitle.get("1.0", "end-1c"),
            "hold": self.hold.get().strip(),
        }
        if (values["say"] == row.say and values["subtitle"] == row.subtitle
                and values["hold"] == self._hold_text(row.hold)):
            self.pending.pop(row.address, None)
        else:
            self.pending[row.address] = values

    @staticmethod
    def _set(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)

    @staticmethod
    def _hold_text(value) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return str(int(number)) if number == int(number) else f"{number:g}"

    # --- 静止画 -------------------------------------------------------
    def _show_shot(self, row: BeatRow) -> None:
        """静止画を出す (無ければ場所だけ空けておく).

        **`Label` の `height` は、テキストなら行数・画像ならピクセル。**
        画を入れる前の値 (11 行のつもり) を残したまま画像を入れると 11px に
        潰れて、画の上端だけが見える (実際にそうなった)。画のときは 0 =
        中身の大きさに任せる、に必ず戻す。
        """
        image = self.shot_for(row)
        if image is None:
            self._photo = None
            self.shot.config(image="", text="収録するとここに画が出ます", height=SHOT_LINES)
            return
        try:
            self._photo = tk.PhotoImage(file=str(image))
        except tk.TclError:
            self._photo = None
            self.shot.config(image="", text="画を読めません", height=SHOT_LINES)
            return
        self.shot.config(image=self._photo, text="", height=0)

    def shot_for(self, row: BeatRow) -> Path | None:
        """そのビートの静止画. 無ければ抜く. 抜けなければ None."""
        if self.outdir is None or row.middle is None:
            return None
        video = self.outdir / "raw.webm"
        if not video.is_file():
            return None
        target = self.outdir / "_shots" / f"{row.scene}-{row.index}.png"
        try:
            fresh = target.stat().st_mtime >= video.stat().st_mtime
        except OSError:
            fresh = False
        if fresh:
            return target

        from . import ffmpeg

        return ffmpeg.frame_at(video, row.middle, target, width=SHOT_WIDTH)

    # --- 保存 ---------------------------------------------------------
    def edits(self) -> dict[str, dict]:
        """保存する内容. 入力のまま (数字の検査は on_save がする)."""
        self.capture()
        return dict(self.pending)

    def on_save(self) -> bool:
        from .plan import patch

        edits = self.edits()
        if not edits:
            self.status.set("直したところがありません")
            return False

        for address, fields in edits.items():
            try:
                fields["hold"] = float(fields["hold"] or 0.0)
            except ValueError:
                messagebox.showerror(
                    "間が数字ではありません",
                    f"{address} の間 (hold) が {fields['hold']!r} になっています。",
                    parent=self.window)
                return False

        try:
            changed = patch(self.path, edits)
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存できません", str(exc), parent=self.window)
            return False

        self.pending.clear()
        self._reload()
        step = redo_for(changed)
        note = f"   → {step[1]}" if step else ""
        self.status.set(f"保存: {len(edits)} ビート ({'/'.join(sorted(set(changed)))}){note}")
        if self.on_saved:
            self.on_saved()
        return True

    def _reload(self) -> None:
        from .plan import load

        self.plan = load(self.path)
        self.rows = rows(self.plan, read_timing(self.outdir))
        keep = self.current.address if self.current else None
        self.table.delete(*self.table.get_children())
        self._fill_table()
        self.current = None
        row = next((r for r in self.rows if r.address == keep), None)
        if row:
            self.table.selection_set(row.address)
            self.show(row)

    def on_close(self) -> None:
        if self.edits() and not messagebox.askyesno(
            "閉じますか", "保存していない変更があります。",
            parent=self.window, default=messagebox.NO,
        ):
            return
        self.window.destroy()


__all__ = ["PlanEditor", "BeatRow", "rows", "redo_for", "read_timing", "EDITABLE"]
