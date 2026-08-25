"""支援収録の窓 (tkinter). 人が操作して、撮れたものをビートに貯める.

**自動操作が届かない相手のための道。** ログインの要る業務アプリ、canvas、OAuth
は `gmp record` が原理的に届かない。そこは人が手を動かすしかないので、画面は
**ショットを貯めて、どのビートのものかを覚えておくこと**だけをやる。

**ここも「決める」画面ではない。** コメント (`say`) は打てるが、**画面から
Claude を呼ぶボタンは置かない** —— 言葉は Claude の領分で、頼み方は
`撮る面` の「claude に書かせる」に 1 か所だけある (「画面は Claude の代わりを
しない」)。Claude が plan.json の say を書いたら、この窓は開き直せば読める。

**呼び名は台本に揃える。** 人が「セクション / ステップ」と呼ぶものは、
plan.json では **シーン / ビート**。同じものに 2 つ名前を付けると、
`voice` も `render` も `check` もどちらで喋るのか決められなくなる
(README の「呼び名」)。

ショットの置き場所は **出力ディレクトリの `shots/`**。plan.json の隣ではない ——
ショットは生成物なのでユーザフォルダ側に出る (`beat.audio` と同じ規則)。
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import capture, paths
from .shoot import Doc, Row, ShootError, next_shot_path, progress, skeleton

SHOT_WIDTH = 360        # プレビューの幅 (px)
SHOT_LINES = 12         # 画が無いときに空けておく高さ (行)
# プレビューは台本エディタと同じ捨て場に置く (ショットの shots/ と混ぜない)
PREVIEW = ("_shots", "preview-shoot.png")

FOOTER_NOTE = ("撮れるのは選んでいるビート。コメント (say) は claude にも書かせられます"
               "（撮る面の「claude に書かせる」）")


def preview_source(row: Row | None, outdir: Path | None) -> Path | None:
    """その行のショットの実体. 無ければ None."""
    if row is None or not row.shot or outdir is None:
        return None
    path = Path(outdir) / row.shot
    return path if path.is_file() else None


def summary(rows: list[Row]) -> str:
    """いまどこまで撮れたか. **数えるのはショットのあるビート**."""
    have, total = progress(rows)
    if not total:
        return "ビートがありません"
    if have == total:
        return f"ショット {have} / {total} ビート (揃いました)"
    return f"ショット {have} / {total} ビート"


def default_title(plan_path: Path) -> str:
    """plan.json をこれから作るときの題名. フォルダ名を使う."""
    return plan_path.parent.name or "untitled"


class ShootWindow:
    """支援収録の窓."""

    TICK = 200          # 録画中の時計の更新間隔 (ms)

    def __init__(self, parent: tk.Misc, plan_path: Path, on_saved=None):
        self.path = Path(plan_path)
        self.on_saved = on_saved
        self.current: Row | None = None
        self.rows: list[Row] = []
        self.found: list[capture.Window] = []
        self.recording: capture.Recording | None = None
        self.pending_clip: tuple[Row, str] | None = None
        self.app_proc: subprocess.Popen | None = None
        self._photo = None                  # PhotoImage は参照を持たないと消える

        if self.path.is_file():
            self.doc = Doc.load(self.path)
        else:
            # **まだ台本が無いときは骨から作る。** 窓を選ぶまで window は空で、
            # 空のままでは保存しない (「設定済みに見える嘘」を焼かない)
            self.doc = Doc.create(self.path, skeleton(
                default_title(self.path), "", 1280, 720))

        self.outdir = self._outdir()

        self.window = tk.Toplevel(parent)
        self.window.title(f"支援収録 — {self.path}")
        self.window.geometry("1080x680")

        # **下の帯を先に pack する。** 本体を先に置くと cavity を食い尽くして
        # ボタンが画面外に出る (CLAUDE.md)
        self._build_footer()
        self._build_status()
        self._build_edit()
        self._build_head()
        self._build_capture()
        self._build_body()

        self.reload_windows()
        self.refresh()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- 置き場所 ----------------------------------------------------
    def _outdir(self) -> Path:
        meta = self.doc.raw.get("meta") or {}
        app = self.doc.raw.get("app") or {}
        return paths.resolve_outdir(self.path, project=meta.get("project"),
                                    app_cwd=app.get("cwd"))

    # --- 組み立て ----------------------------------------------------
    def _build_footer(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        tk.Button(bar, text="閉じる", width=10, command=self.on_close).pack(side=tk.RIGHT)
        tk.Button(bar, text="保存", width=10, command=self.on_save).pack(
            side=tk.RIGHT, padx=6)
        tk.Label(bar, fg="#666", justify=tk.LEFT, wraplength=760,
                 text=FOOTER_NOTE).pack(side=tk.LEFT)

    def _build_status(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value=str(self.path))
        tk.Label(bar, textvariable=self.status, anchor="w", fg="#444",
                 wraplength=1040, justify=tk.LEFT).pack(
            side=tk.LEFT, fill=tk.X, padx=10, pady=2)

    def _build_head(self) -> None:
        head = tk.Frame(self.window)
        head.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 2))
        tk.Label(head, text="撮る窓").pack(side=tk.LEFT)
        self.picker = ttk.Combobox(head, state="readonly", width=64)
        self.picker.pack(side=tk.LEFT, padx=6)
        self.picker.bind("<<ComboboxSelected>>", self._on_pick_window)
        tk.Button(head, text="調べ直す", command=self.reload_windows).pack(side=tk.LEFT)
        self.launch_button = tk.Button(head, text="起動", width=8, command=self.on_launch)
        if (self.doc.raw.get("app") or {}).get("start"):
            self.launch_button.pack(side=tk.LEFT, padx=(12, 0))

    def _build_capture(self) -> None:
        bar = tk.Frame(self.window)
        bar.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(6, 2))
        self.shot_button = tk.Button(bar, text="画像を撮る", width=14,
                                     command=self.on_shot)
        self.shot_button.pack(side=tk.LEFT)
        self.clip_button = tk.Button(bar, text="録画を始める", width=14,
                                     command=self.on_clip)
        self.clip_button.pack(side=tk.LEFT, padx=6)
        self.advance = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="撮ったら次のビートを作る",
                       variable=self.advance).pack(side=tk.LEFT, padx=12)
        # **録画だけ重なりに弱い。** 静止画は窓自身に描かせるので隠れていても
        # 撮れるが、録画は画面の矩形を舐めるので手前の窓が写る
        tk.Label(bar, fg="#666",
                 text="録画中は窓を隠さないこと（静止画は隠れていても撮れます）").pack(
            side=tk.LEFT)

    def _build_edit(self) -> None:
        """一覧の下の帯.

        **本体より先に pack する。** 本体は expand=True で cavity を取るので、
        あとから pack すると帯が押し出されて見えなくなる (CLAUDE.md に同じ罠が
        2 か所ある)。
        """
        edit = tk.Frame(self.window)
        edit.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 2))
        for text, command in (("シーンを足す", self.on_add_scene),
                              ("ビートを足す", self.on_add_beat),
                              ("ビートを消す", self.on_drop_beat),
                              ("ショットを外す", self.on_drop_shot)):
            tk.Button(edit, text=text, command=command).pack(side=tk.LEFT, padx=(0, 6))
        # **参照を外すだけでファイルは消さない。** 撮り直しの効かないショットなので、
        # 現物を消すのは画面の操作にしない
        tk.Label(edit, fg="#666",
                 text="「ショットを外す」は参照を外すだけ（ファイルは shots/ に残ります）").pack(
            side=tk.LEFT, padx=6)

    def _build_body(self) -> None:
        body = tk.Frame(self.window)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(6, 4))

        left = tk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(left, columns=("kind", "say"),
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="シーン / ビート")
        self.tree.heading("kind", text="ショット")
        self.tree.heading("say", text="コメント")
        self.tree.column("#0", width=180, anchor="w")
        self.tree.column("kind", width=64, anchor="w")
        self.tree.column("say", width=300, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_pick_row)

        right = tk.Frame(body, width=400)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        self.preview = tk.Label(right, text="", anchor="center", fg="#999",
                                bg="#1e1e1e", height=SHOT_LINES)
        self.preview.pack(side=tk.TOP, fill=tk.X)
        self.shot_label = tk.Label(right, text="", anchor="w", fg="#666",
                                   wraplength=380, justify=tk.LEFT)
        self.shot_label.pack(side=tk.TOP, fill=tk.X, pady=(4, 8))

        tk.Label(right, text="コメント (say)", anchor="w").pack(side=tk.TOP, fill=tk.X)
        self.say = tk.Text(right, height=5, wrap="char")
        self.say.pack(side=tk.TOP, fill=tk.X)

        tk.Label(right, text="字幕 (空なら原稿をそのまま使う)", anchor="w").pack(
            side=tk.TOP, fill=tk.X, pady=(8, 0))
        self.subtitle = tk.Text(right, height=3, wrap="char")
        self.subtitle.pack(side=tk.TOP, fill=tk.X)

    # --- 窓えらび ----------------------------------------------------
    def reload_windows(self) -> None:
        if not capture.supported():
            self.picker.configure(values=["(Windows でだけ使えます)"])
            self.shot_button.configure(state=tk.DISABLED)
            self.clip_button.configure(state=tk.DISABLED)
            return
        try:
            self.found = capture.windows()
        except capture.CaptureError as exc:
            self.found = []
            self.status.set(str(exc))
            return
        labels = [w.label for w in self.found]
        self.picker.configure(values=labels)
        # 台本が覚えている窓があれば選び直す (開くたびに選ばせない)
        wanted = self.doc.window
        if wanted:
            for i, window in enumerate(self.found):
                if wanted.casefold() in window.title.casefold():
                    self.picker.current(i)
                    return
        if labels and not self.picker.get():
            self.picker.set("")

    @property
    def target(self) -> capture.Window | None:
        index = self.picker.current()
        if index is None or index < 0 or index >= len(self.found):
            return None
        return self.found[index]

    def _on_pick_window(self, _event=None) -> None:
        window = self.target
        if window is None:
            return
        self.doc.set_window(window.title)
        # **まだ 1 枚も撮っていないなら、動画の大きさを窓に合わせる。**
        # 撮り始めてから変えると、それまでのショットが黒帯つきで並ぶ
        if not any(r.shot for r in self.rows):
            self.doc.set_size(capture.even(window.width), capture.even(window.height))
        self.refresh()

    # --- 一覧 ---------------------------------------------------------
    def refresh(self) -> None:
        keep = self.current.address if self.current else None
        self.rows = self.doc.rows()
        self.tree.delete(*self.tree.get_children())
        seen: set[int] = set()
        for row in self.rows:
            node = f"s{row.scene_index}"
            if row.scene_index not in seen:
                seen.add(row.scene_index)
                title = row.scene_title or row.scene_id
                self.tree.insert("", "end", iid=node, text=title, open=True,
                                 values=("", ""))
            self.tree.insert(node, "end", iid=self._iid(row),
                             text=f"  {row.beat_index}",
                             values=(row.kind, row.say[:40]))
        pick = next((r for r in self.rows if r.address == keep), None) or (
            self.rows[0] if self.rows else None)
        if pick is not None:
            self.tree.selection_set(self._iid(pick))
            self.show(pick)
        width, height = self.doc.size
        self.status.set(f"{self.path}   {summary(self.rows)}   "
                        f"{width}x{height}   → {self.outdir}")

    @staticmethod
    def _iid(row: Row) -> str:
        return f"b{row.scene_index}:{row.beat_index}"

    def _on_pick_row(self, _event=None) -> None:
        picked = self.tree.selection()
        if not picked:
            return
        row = next((r for r in self.rows if self._iid(r) == picked[0]), None)
        if row is None or (self.current and row.address == self.current.address):
            return
        self.show(row)

    def show(self, row: Row) -> None:
        """その行を右側に出す.

        **出ている行の入力を先に覚える** (`ui_plan` と同じ理由) —— どの道から
        行を移っても、打った文字が消えないように取り込みはここに置く。
        """
        self.capture_text()
        self.current = row
        self._set(self.say, row.say)
        self._set(self.subtitle, row.subtitle)
        self._show_preview(row)

    def _show_preview(self, row: Row) -> None:
        source = preview_source(row, self.outdir)
        self._photo = None
        if source is None:
            # **画が無いときは高さを行数で空けておく** (画のときは 0 に戻す)
            self.preview.configure(image="", text="(ショットなし)", height=SHOT_LINES)
            self.shot_label.configure(text=row.shot or "まだ撮っていません")
            return
        small = self._thumbnail(source)
        if small is None:
            self.preview.configure(image="", text="(表示できません)", height=SHOT_LINES)
        else:
            try:
                # **master を渡す。** 省くと「既定の root」に乗るので、窓を
                # 作り直す場面でたまに読めなくなる
                self._photo = tk.PhotoImage(master=self.window, file=str(small))
            except tk.TclError:
                self._photo = None
            if self._photo is None:
                self.preview.configure(image="", text="(表示できません)",
                                       height=SHOT_LINES)
            else:
                # **画のときは height=0。** 行数のまま画像を入れると 11px に潰れる
                self.preview.configure(image=self._photo, text="", height=0)
        seconds = ""
        if source.suffix.lower() == ".mp4":
            length = capture.duration(source)
            seconds = f"   {length:.1f} 秒" if length else ""
        self.shot_label.configure(text=f"{row.shot}{seconds}")

    def _thumbnail(self, source: Path) -> Path | None:
        """プレビュー用の小さい PNG. 失敗しても呼び側を止めない."""
        from . import ffmpeg

        out = self.outdir.joinpath(*PREVIEW)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.suffix.lower() == ".mp4":
                length = capture.duration(source) or 0.0
                return ffmpeg.frame_at(source, length / 2, out, width=SHOT_WIDTH)
            ffmpeg.run(["-i", str(source), "-vf", f"scale={SHOT_WIDTH}:-2", str(out)])
        except ffmpeg.FFmpegError:
            return None
        return out if out.exists() else None

    @staticmethod
    def _set(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)

    def capture_text(self) -> None:
        """出ている行の入力を doc に取り込む."""
        if self.current is None:
            return
        self.doc.set_text(
            self.current.scene_index, self.current.beat_index,
            say=self.say.get("1.0", tk.END).rstrip("\n"),
            subtitle=self.subtitle.get("1.0", tk.END).rstrip("\n"),
        )

    # --- 撮る ---------------------------------------------------------
    def _ready(self) -> capture.Window | None:
        if self.current is None:
            messagebox.showinfo("撮れません", "先にビートを選んでください",
                                parent=self.window)
            return None
        window = self.target
        if window is None:
            messagebox.showinfo("撮れません", "上で撮る窓を選んでください",
                                parent=self.window)
            return None
        return window

    def on_shot(self) -> None:
        window = self._ready()
        if window is None:
            return
        self.capture_text()
        row = self.current
        dest, relative = next_shot_path(self.outdir, row.scene_id, clip=False)
        try:
            capture.shot(window.handle, dest)
        except capture.CaptureError as exc:
            messagebox.showerror("撮れません", str(exc), parent=self.window)
            return
        self._attach(row, relative)

    def on_clip(self) -> None:
        if self.recording is not None:
            self._stop_clip()
            return
        window = self._ready()
        if window is None:
            return
        self.capture_text()
        row = self.current
        dest, relative = next_shot_path(self.outdir, row.scene_id, clip=True)
        try:
            self.recording = capture.Recording(window.handle, dest)
        except capture.CaptureError as exc:
            messagebox.showerror("録画できません", str(exc), parent=self.window)
            return
        self.pending_clip = (row, relative)
        self.shot_button.configure(state=tk.DISABLED)
        self._tick()

    def _tick(self) -> None:
        if self.recording is None:
            return
        self.clip_button.configure(text=f"止める ({self.recording.seconds:.1f}s)")
        self.window.after(self.TICK, self._tick)

    def _stop_clip(self) -> None:
        recording, self.recording = self.recording, None
        pending, self.pending_clip = self.pending_clip, None
        self.clip_button.configure(text="録画を始める")
        self.shot_button.configure(state=tk.NORMAL)
        if recording is None or pending is None:
            return
        row, relative = pending
        try:
            recording.stop()
        except capture.CaptureError as exc:
            messagebox.showerror("録画できません", str(exc), parent=self.window)
            return
        self._attach(row, relative)

    def _attach(self, row: Row, relative: str) -> None:
        """撮れたものを選んでいるビートに結びつける."""
        self.doc.set_shot(row.scene_index, row.beat_index, relative)
        if self.advance.get():
            # **撮るたびにビートが増える。** 「1 ステップに何枚も」は階層では
            # なくビートの数で表す (1 画像 1 コメントがそのまま守れる)
            at = self.doc.add_beat(row.scene_index, row.beat_index)
            self.current = None
            self.refresh()
            nxt = next((r for r in self.rows
                        if r.scene_index == row.scene_index and r.beat_index == at), None)
            if nxt is not None:
                self.tree.selection_set(self._iid(nxt))
                self.show(nxt)
        else:
            self.current = None
            self.refresh()

    # --- 構造 ---------------------------------------------------------
    def on_add_scene(self) -> None:
        self.capture_text()
        self.doc.add_scene()
        self.current = None
        self.refresh()

    def on_add_beat(self) -> None:
        if self.current is None:
            return
        self.capture_text()
        self.doc.add_beat(self.current.scene_index, self.current.beat_index)
        self.current = None
        self.refresh()

    def on_drop_beat(self) -> None:
        if self.current is None:
            return
        if not self.doc.remove_beat(self.current.scene_index, self.current.beat_index):
            messagebox.showinfo(
                "消せません",
                "シーンの最後の 1 ビートは消せません（台本が読めなくなります）。"
                "シーンごと消すか、別のビートを消してください", parent=self.window)
            return
        self.current = None
        self.refresh()

    def on_drop_shot(self) -> None:
        if self.current is None:
            return
        self.capture_text()
        self.doc.set_shot(self.current.scene_index, self.current.beat_index, None)
        self.current = None
        self.refresh()

    # --- 起動 ---------------------------------------------------------
    def on_launch(self) -> None:
        """`app.start` を起こす / 畳む. **収録の仕込みは走らせない** ——
        `app.setup` は `gmp record` (組み立て) の担当で、ここで走らせると
        人が撮っている最中にデータを作り直すことになる。
        """
        if self.app_proc is not None and self.app_proc.poll() is None:
            from .server import _kill_tree

            _kill_tree(self.app_proc)
            self.app_proc = None
            self.launch_button.configure(text="起動")
            self.status.set("終了しました")
            return
        app = self.doc.raw.get("app") or {}
        start = app.get("start")
        if not start:
            return
        cwd = self.path.parent
        if app.get("cwd"):
            cwd = (self.path.parent / app["cwd"]).resolve()
        try:
            flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} \
                if sys.platform == "win32" else {"start_new_session": True}
            self.app_proc = subprocess.Popen(
                start, shell=True, cwd=str(cwd),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        except OSError as exc:
            messagebox.showerror("起動できません", f"{start}\n\n{exc}",
                                 parent=self.window)
            return
        self.launch_button.configure(text="終了")
        self.status.set(f"起動: {start}   (窓が出たら「調べ直す」)")

    # --- 保存 ---------------------------------------------------------
    def on_save(self) -> bool:
        self.capture_text()
        if not self.doc.window:
            messagebox.showinfo("保存しません",
                                "先に撮る窓を選んでください（app.window に書きます）",
                                parent=self.window)
            return False
        # **他所で書き換わっていたら訊く。** この窓は構造ごと書き戻すので、
        # Claude が同じ plan.json の say を書いている最中に上書きすると、
        # 書かれた文が黙って消える
        if self.doc.stale() and not messagebox.askyesno(
                "上書きしますか",
                "この plan.json は開いたあとに別のところで変わっています。\n"
                "このまま保存すると、その変更は失われます。",
                default=messagebox.NO, parent=self.window):
            return False
        try:
            self.doc.save()
        except OSError as exc:
            messagebox.showerror("保存できません", str(exc), parent=self.window)
            return False
        self.status.set(f"保存しました: {self.path}")
        if self.on_saved:
            self.on_saved()
        return True

    def on_close(self) -> None:
        if self.recording is not None:
            messagebox.showinfo("閉じられません", "先に録画を止めてください",
                                parent=self.window)
            return
        self.capture_text()
        if self.doc.dirty and not messagebox.askyesno(
                "保存しますか", "保存していない変更があります。破棄して閉じますか。",
                default=messagebox.NO, parent=self.window):
            return
        if self.app_proc is not None and self.app_proc.poll() is None:
            from .server import _kill_tree

            _kill_tree(self.app_proc)
        self.window.destroy()


def open_window(parent: tk.Misc, plan_path: Path, on_saved=None) -> ShootWindow | None:
    """撮る面から開く. 開けない理由があれば教えて None."""
    try:
        return ShootWindow(parent, plan_path, on_saved=on_saved)
    except ShootError as exc:
        messagebox.showerror("開けません", str(exc), parent=parent)
        return None
