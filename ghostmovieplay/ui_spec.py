"""構成 (video.md) を画面の中で書く.

**ここが無いと画面は自己完結しない。** 構成にしか置けないものがある ——
シーンと狙い、本文の散文、タイトル、そしてこの動画だけの上書き。設定画面は
video.md を書かない (人の書いた散文とコメントを壊すため) ので、外のエディタを
開くしか道が無かった。「どこかの道筋で直せなければ、直接編集できるエディタを
積むしかない」——積むほうを選んだ。

設定画面と違って**構造を触らない**。人が打った文字をそのまま保存するだけで、
GUI が勝手に書き直すことはしない。だから散文もコメントも壊れない。

`雛形から作り直す` だけは中身を組み直すが、**保存はしない** —— エディタの中身と
して出すので、人が見てから保存する (`gmp init --force` は問答無用で上書きする)。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


class SpecEditor:
    """video.md を編集する小さなウィンドウ."""

    def __init__(self, parent: tk.Misc, path: Path, on_saved=None):
        self.path = Path(path)
        self.on_saved = on_saved
        self.window = tk.Toplevel(parent)
        self.window.title(f"構成 — {self.path}")
        self.window.geometry("880x680")

        # **ボタン行を先に (side=BOTTOM)。** 本体を先に pack すると cavity を
        # 食い尽くしてボタンが画面外に出る (CLAUDE.md)
        self._build_footer()
        self._build_status()
        self._build_body()

        self.original = self._read()
        self.text.insert("1.0", self.original)
        self.text.edit_modified(False)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.text.focus_set()

    # --- 組み立て ----------------------------------------------------
    def _build_footer(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        tk.Button(bar, text="閉じる", width=10, command=self.on_close).pack(side=tk.RIGHT)
        tk.Button(bar, text="保存", width=10, command=self.on_save).pack(
            side=tk.RIGHT, padx=6)
        tk.Button(bar, text="雛形から作り直す", command=self.on_rebuild).pack(side=tk.LEFT)
        tk.Label(bar, fg="#666",
                 text="シーンと本文は残したまま、上の枠組みを今の雛形に揃えます").pack(
            side=tk.LEFT, padx=8)

    def _build_status(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value=str(self.path))
        tk.Label(bar, textvariable=self.status, anchor="w", fg="#444").pack(
            side=tk.LEFT, fill=tk.X, padx=10, pady=2)

    def _build_body(self) -> None:
        frame = tk.Frame(self.window)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text = tk.Text(frame, wrap="none", undo=True, font=("Consolas", 11))
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.configure(command=self.text.yview)

    # --- 中身 --------------------------------------------------------
    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"# 読めません: {exc}\n"

    @property
    def content(self) -> str:
        return self.text.get("1.0", "end-1c")

    @property
    def changed(self) -> bool:
        return self.content != self.original

    # --- 操作 --------------------------------------------------------
    def on_save(self) -> bool:
        """保存する. フロントマターが壊れていたら訊いてから."""
        broken = self.front_matter_error()
        if broken and not messagebox.askyesno(
            "このまま保存しますか",
            f"フロントマターが読めません:\n\n{broken}\n\n"
            "このまま保存すると、台本づくりも収録もこのファイルを読めません。",
            parent=self.window, default=messagebox.NO,
        ):
            return False
        try:
            self.path.write_text(self.content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存できません", str(exc), parent=self.window)
            return False
        self.original = self.content
        self.status.set(f"保存: {self.path}")
        if self.on_saved:
            self.on_saved()
        return True

    def front_matter_error(self) -> str:
        """フロントマターが読めなければその理由. 読めれば空文字."""
        import yaml

        from .spec import split_front

        front, _ = split_front(self.content)
        if not front.strip():
            return "フロントマター (--- で挟んだ部分) がありません"
        try:
            loaded = yaml.safe_load(front)
        except yaml.YAMLError as exc:
            return str(exc).splitlines()[0]
        return "" if isinstance(loaded, dict) else "フロントマターが表になっていません"

    def on_rebuild(self) -> None:
        """雛形から組み直す. **保存はしない** —— 中身として見せる."""
        from . import settings
        from .spec import parse, rebuild_text

        try:
            resolved = settings.load(spec=self.path, video=parse(self.path).raw)
            without = settings.load(spec=self.path, video={})
        except Exception as exc:                            # noqa: BLE001
            messagebox.showerror("作り直せません", str(exc), parent=self.window)
            return
        project_file = resolved.sources.get(settings.PROJECT)

        made, dropped = rebuild_text(
            self.content, resolved=resolved, project_file=project_file,
            without_video=without,
        )
        note = ("\n\n下の上書きは、プロジェクトと同じ値なので落とします"
                " (書き写された共通の値が残っていると、この動画が常に"
                "プロジェクトを上書きし続けます):\n  " + "\n  ".join(dropped)
                if dropped else "")
        if not messagebox.askyesno(
            "雛形から作り直しますか",
            "タイトル・シーン・本文は残したまま、上の枠組みを今の雛形に"
            "揃えます。" + note + "\n\n保存はしません。中身を見てから保存できます。",
            parent=self.window,
        ):
            return
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", made)
        self.status.set(
            "作り直しました (未保存)。"
            + (f"落とした上書き: {' / '.join(dropped)}" if dropped else "落とした上書きなし")
        )

    def on_close(self) -> None:
        if self.changed and not messagebox.askyesno(
            "閉じますか", "保存していない変更があります。",
            parent=self.window, default=messagebox.NO,
        ):
            return
        self.window.destroy()
