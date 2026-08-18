"""設定画面 (tkinter). `gmp ui` から開く.

**用途でタブを切り、行ごとに「値・由来・書込先」を並べる。**
設定は 3 層 (config.toml / gmp.toml / video.md) あるので、値だけ見せても
「なぜこの値なのか」「直したのにどこが効いているのか」が分からなくなる。
`gmp config` が由来を出しているのと同じ理由で、画面でも由来を必ず出す。

書き込むのは **機械 (config.toml) とプロジェクト (gmp.toml) だけ**。
video.md は本文 (補足の散文) とコメントを持つので、GUI から書き戻すと
人の書いた文章を壊す。こちらは「効いている値」の表示に留める。

画面に出す判断のうち、Tk が要らないものは全部モジュール関数にしてある
(TABS / write_targets / plan_writes など)。ウィンドウを作らずにテストできる。
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import paths, settings
from .plan import Voice
from .tts import NON_AUDIO_KEYS

PREVIEW_TEXT = "こんにちは。この声と話速で読み上げます。"


# --- どのタブに何を出すか ---------------------------------------------
@dataclass(frozen=True)
class Tab:
    title: str
    note: str
    keys: tuple[str, ...]


TABS: tuple[Tab, ...] = (
    Tab(
        "声と口調", "話者と口調。plan.json に焼かれ、say の文面と音声になる",
        (
            "voice.speaker", "voice.style", "voice.speed", "voice.pitch",
            "voice.intonation", "voice.volume", "voice.pre", "voice.post",
            "voice.engine", "persona.style", "voice.dict",
        ),
    ),
    Tab(
        "何を撮るか", "Pass1 への指示。plan.json には残らない",
        (
            "series.audience", "series.topics", "series.count",
            "series.target_seconds", "series.tolerance", "series.avoid",
            "subtitle.max_chars", "subtitle.max_lines",
            "subtitle.reading_cps", "subtitle.pad",
        ),
    ),
    Tab(
        "対象と動画", "収録対象と絵の形。プロジェクト固有の事実はここ",
        (
            "project", "title", "lang",
            "app.url", "app.ready", "app.start", "app.cwd", "app.start_timeout",
            "video.width", "video.height", "video.fps", "video.leader", "video.trailer",
            "determinism.seed", "determinism.time",
        ),
    ),
    Tab(
        "この機械", "この機械でだけ効く。plan.json には入らない",
        (
            "home", "engine.voicevox.url", "engine.voicevox.exe",
            "render.font", "render.crf", "render.preset",
            "agent.model", "agent.permission_mode",
        ),
    ),
)


# 行の見出し。キーの末尾をそのまま出すと voice.style と persona.style が
# どちらも "style" になって見分けられない
LABELS: dict[str, str] = {
    "voice.speaker": "話者",
    "voice.style": "話者のスタイル",
    "voice.speed": "話速",
    "voice.pitch": "音高",
    "voice.intonation": "抑揚",
    "voice.volume": "音量",
    "voice.pre": "発話前の無音",
    "voice.post": "発話後の無音",
    "voice.engine": "TTS エンジン",
    "voice.dict": "読み辞書",
    "persona.style": "口調",
    "series.audience": "狙う視聴者",
    "series.topics": "題材の候補",
    "series.count": "作る本数",
    "series.target_seconds": "1本の目標尺(秒)",
    "series.tolerance": "目標尺の許容超過",
    "series.avoid": "触れないこと",
    "subtitle.max_chars": "字幕 1行の文字数",
    "subtitle.max_lines": "字幕の行数",
    "subtitle.reading_cps": "読み速度(文字/秒)",
    "subtitle.pad": "読み切る余白(秒)",
    "project": "プロジェクト名",
    "title": "動画タイトル",
    "lang": "言語",
    "app.url": "収録する URL",
    "app.ready": "準備完了のセレクタ",
    "app.start": "起動コマンド",
    "app.cwd": "ソースのフォルダ",
    "app.start_timeout": "起動待ち上限(秒)",
    "video.width": "幅",
    "video.height": "高さ",
    "video.fps": "fps",
    "video.leader": "冒頭の待ち(秒)",
    "video.trailer": "末尾の余白(秒)",
    "determinism.seed": "乱数の seed",
    "determinism.time": "固定する開始時刻",
    "home": "生成物の置き場所",
    "engine.voicevox.url": "VOICEVOX の接続先",
    "engine.voicevox.exe": "VOICEVOX の実行ファイル",
    "render.font": "字幕フォント",
    "render.crf": "画質 (CRF)",
    "render.preset": "x264 preset",
    "agent.model": "claude のモデル",
    "agent.permission_mode": "claude の権限モード",
}


def label_of(path: str) -> str:
    return LABELS.get(path, path.rpartition(".")[2])


def tab_of(path: str) -> str | None:
    for tab in TABS:
        if path in tab.keys:
            return tab.title
    return None


def affects_audio(path: str) -> bool:
    """変えると音声が作り直しになる項目か (画面で先に言う)."""
    head, _, leaf = path.rpartition(".")
    return head == "voice" and leaf not in NON_AUDIO_KEYS


# --- 書込先 -----------------------------------------------------------
NOWHERE = "(保存先なし)"


def write_targets(path: str, has_project: bool) -> list[str]:
    """この項目を書ける層. video.md は UI からは書かない."""
    setting = settings.SETTINGS[path]
    out = []
    if settings.MACHINE in setting.layers:
        out.append(settings.MACHINE)
    if has_project and settings.PROJECT in setting.layers:
        out.append(settings.PROJECT)
    return out


def default_target(path: str, origin_layer: str, has_project: bool) -> str:
    """既定の書込先. いま効いている層に上書きするのが素直."""
    choices = write_targets(path, has_project)
    if not choices:
        return NOWHERE
    if origin_layer in choices:
        return origin_layer
    # プロジェクト固有の事実は機械に置けないので、プロジェクトを優先する
    return choices[-1] if settings.PROJECT in choices else choices[0]


# --- 値と文字列の変換 -------------------------------------------------
def format_value(path: str, value: Any) -> str:
    if value is None:
        return ""
    setting = settings.SETTINGS[path]
    if setting.kind == "list":
        return ", ".join(str(v) for v in value)
    if setting.kind == "table":
        return format_dict_text(value)
    return str(value)


def format_dict_text(entries: dict[str, Any] | None) -> str:
    """読み辞書を 1 行 1 件のテキストにする. `表記 = 読み` か `表記 = 読み, アクセント`."""
    lines = []
    for surface, spec in (entries or {}).items():
        if isinstance(spec, dict):
            reading = spec.get("pronunciation", "")
            accent = spec.get("accent")
            # accent = 0 は「頭高」という意味のある値。falsy だからと落とすと、
            # 画面に出した時点で消えて、次の保存で本当に失われる
            lines.append(f"{surface} = {reading}" + (f", {accent}" if accent is not None else ""))
        else:
            lines.append(f"{surface} = {spec}")
    return "\n".join(lines)


def parse_dict_text(text: str) -> dict[str, Any]:
    """読み辞書のテキストを dict に戻す. 壊れた行は SettingsError."""
    entries: dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        if "=" not in row:
            raise settings.SettingsError(f"読み {number} 行目: `表記 = 読み` の形で書きます")
        surface, _, rest = row.partition("=")
        surface = surface.strip()
        reading, _, accent = rest.partition(",")
        reading, accent = reading.strip(), accent.strip()
        if not surface or not reading:
            raise settings.SettingsError(f"読み {number} 行目: 表記と読みの両方が要ります")
        if accent:
            try:
                entries[surface] = {"pronunciation": reading, "accent": int(accent)}
            except ValueError:
                raise settings.SettingsError(
                    f"読み {number} 行目: アクセントは数字で書きます"
                ) from None
        else:
            entries[surface] = reading
    return entries


# --- 保存するものを決める ---------------------------------------------
@dataclass
class Edit:
    path: str
    text: str        # いま画面に入っている文字列
    original: str    # 開いたときの文字列
    target: str      # 書込先の層

    @property
    def changed(self) -> bool:
        return self.text.strip() != self.original.strip()


def plan_writes(edits: list[Edit]) -> dict[str, dict[str, Any]]:
    """変更された行だけを、層ごとの変更 dict にまとめる.

    空にした行は None (= その層から消す)。書けない行が変更されていたら
    そこで止める (黙って捨てると「保存したのに戻る」になる)。
    """
    writes: dict[str, dict[str, Any]] = {}
    for edit in edits:
        if not edit.changed:
            continue
        if edit.target == NOWHERE:
            raise settings.SettingsError(
                f"{edit.path} の保存先がありません"
                " (プロジェクトを選ぶか、gmp.toml を作ってください)"
            )
        text = edit.text.strip()
        setting = settings.SETTINGS[edit.path]
        if not text:
            value = {} if setting.kind == "table" else None
        elif setting.kind == "table":
            value = parse_dict_text(edit.text)
        else:
            try:
                value = settings.parse_value(edit.path, text)
            except (settings.SettingsError, ValueError) as exc:
                raise settings.SettingsError(f"{edit.path}: {exc}") from None
        writes.setdefault(edit.target, {})[edit.path] = value
    return writes


def save(writes: dict[str, dict[str, Any]], project_file: Path | None) -> list[Path]:
    """層ごとの変更をファイルに当てる. 戻り値は書いたファイル."""
    written: list[Path] = []
    for layer, changes in writes.items():
        if layer == settings.MACHINE:
            written.append(settings.write_layer(paths.config_path(), changes))
        elif layer == settings.PROJECT:
            if not project_file:
                raise settings.SettingsError("プロジェクトが選ばれていません")
            written.append(settings.write_layer(project_file, changes))
    return written


# --- 見た目 -----------------------------------------------------------
def ensure_notebook_style(name: str = "Gmp.TNotebook") -> str:
    """選択中のタブが分かるようにする.

    Windows 既定の vista テーマは選択タブと非選択タブのコントラストが
    ほとんど無く、どのタブを開いているのか分からなくなる。
    """
    style = ttk.Style()
    try:
        style.configure(f"{name}.Tab", padding=[14, 6])
        style.map(
            f"{name}.Tab",
            background=[("selected", "#ffffff"), ("!selected", "#e8e8e8")],
            foreground=[("selected", "#000000"), ("!selected", "#757575")],
            font=[("selected", ("", 10, "bold")), ("!selected", ("", 9))],
        )
    except tk.TclError:
        pass   # style を受け付けないテーマでは既定のまま
    return name


def play_wav(path: Path) -> None:
    """試聴. 鳴らせない環境では黙って諦める (合成できたことは status に出る)."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    import shutil
    import subprocess

    for player in ("afplay", "aplay", "paplay"):
        if shutil.which(player):
            subprocess.Popen([player, str(path)])
            return


# --- ウィンドウ -------------------------------------------------------
class SettingsWindow:
    def __init__(self, root: tk.Tk, spec: Path | None = None):
        self.root = root
        self.rows: dict[str, dict[str, Any]] = {}
        self.speakers: list[dict[str, Any]] = []

        start = Path(spec).parent if spec else Path.cwd()
        found = settings.find_project_file(start)
        directory = found.parent if found else start
        self.project_dir = tk.StringVar(value=str(directory))
        # 一覧は相対で並べるので、渡された 1 本も相対に揃える
        shown = ""
        if spec:
            resolved_spec = Path(spec).resolve()
            try:
                shown = str(resolved_spec.relative_to(directory.resolve()))
            except ValueError:
                shown = str(resolved_spec)
        self.spec_path = tk.StringVar(value=shown)
        self.status = tk.StringVar(value="")

        root.title("GhostMoviePlay 設定")
        root.geometry("960x720")

        # フッターを先に (side=BOTTOM)。本体を先に pack すると cavity を
        # 食い尽くしてボタン行が画面外に出る
        self._build_footer()
        self._build_status()
        self._build_header()
        self._build_tabs()

        self.reload()
        self._load_speakers_async()

    # --- 組み立て ----------------------------------------------------
    def _build_footer(self) -> None:
        bar = tk.Frame(self.root)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        tk.Button(bar, text="閉じる", width=10, command=self.root.destroy).pack(side=tk.RIGHT)
        tk.Button(bar, text="保存", width=10, command=self.on_save).pack(side=tk.RIGHT, padx=6)
        tk.Button(bar, text="読み直す", width=10, command=self.reload).pack(side=tk.RIGHT)

    def _build_status(self) -> None:
        bar = tk.Frame(self.root)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Label(bar, textvariable=self.status, anchor="w", fg="#444").pack(
            side=tk.LEFT, fill=tk.X, padx=10, pady=2
        )

    def _build_header(self) -> None:
        head = tk.Frame(self.root)
        head.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 4))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="プロジェクト").grid(row=0, column=0, sticky="w")
        tk.Entry(head, textvariable=self.project_dir).grid(row=0, column=1, sticky="ew", padx=6)
        tk.Button(head, text="選択", command=self.choose_project).grid(row=0, column=2)
        self.project_note = tk.Label(head, text="", anchor="w", fg="#666")
        self.project_note.grid(row=1, column=1, sticky="ew", padx=6)

        tk.Label(head, text="この1本").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.spec_box = ttk.Combobox(head, textvariable=self.spec_path, state="readonly")
        self.spec_box.grid(row=2, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.spec_box.bind("<<ComboboxSelected>>", lambda _event: self.reload())
        tk.Label(head, text="(表示のみ)", fg="#666").grid(row=2, column=2, pady=(6, 0))

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.root, style=ensure_notebook_style())
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=6)
        self.frames: dict[str, tk.Frame] = {}

        for tab in TABS:
            outer = tk.Frame(self.notebook)
            self.notebook.add(outer, text=tab.title)
            tk.Label(outer, text=tab.note, fg="#666", anchor="w").pack(
                fill=tk.X, padx=10, pady=(8, 4)
            )
            body = self._scrollable(outer)
            self.frames[tab.title] = body
            if tab.title == "声と口調":
                self._build_preview_row(outer)

    def _scrollable(self, parent: tk.Frame) -> tk.Frame:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas)
        body.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)

        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind_all(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
        )
        return body

    def _build_preview_row(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(bar, text="試聴", width=10, command=self.on_preview).pack(side=tk.LEFT)
        tk.Label(
            bar, text=f"いまの設定で「{PREVIEW_TEXT}」を鳴らします", fg="#666"
        ).pack(side=tk.LEFT, padx=8)

    # --- 中身の入れ替え ----------------------------------------------
    @property
    def project_file(self) -> Path | None:
        candidate = Path(self.project_dir.get()) / settings.PROJECT_FILE
        return candidate if candidate.is_file() else None

    def reload(self) -> None:
        """3 層を読み直して行を作り直す."""
        directory = Path(self.project_dir.get())
        self.spec_box["values"] = [""] + [
            str(p.relative_to(directory)) for p in sorted(directory.glob("**/video.md"))[:50]
        ]

        spec = Path(self.spec_path.get()) if self.spec_path.get() else None
        if spec and not spec.is_absolute():
            spec = directory / spec

        video_meta: dict = {}
        if spec and spec.is_file():
            from .spec import parse

            video_meta = parse(spec).raw

        project_file = self.project_file
        self.resolved = settings.resolve(
            machine=paths.load_config(),
            project=settings.read_toml(project_file) if project_file else {},
            video=video_meta,
            machine_path=paths.config_path(),
            project_path=project_file,
            video_path=spec,
        )
        self.project_note.config(
            text=f"{settings.PROJECT_FILE} あり" if project_file
            else f"{settings.PROJECT_FILE} が無いので、共通の既定を保存できません (作成 で作れます)"
        )

        for frame in self.frames.values():
            for child in frame.winfo_children():
                child.destroy()
        self.rows.clear()
        for tab in TABS:
            self._fill(tab)

        warnings = len(self.resolved.warnings)
        self.status.set(
            f"読み込みました ({'警告 %d 件' % warnings if warnings else '警告なし'})"
        )
        if not project_file:
            self._offer_project_file()

    def _offer_project_file(self) -> None:
        frame = self.frames["対象と動画"]
        tk.Button(
            frame, text=f"{settings.PROJECT_FILE} を作る",
            command=self.create_project_file,
        ).grid(row=999, column=0, sticky="w", padx=10, pady=10)

    def _fill(self, tab: Tab) -> None:
        frame = self.frames[tab.title]
        frame.columnconfigure(1, weight=1)
        has_project = self.project_file is not None

        for index, path in enumerate(tab.keys):
            setting = settings.SETTINGS[path]
            origin = self.resolved.origin(path)
            value = format_value(path, self.resolved.values.get(path))

            row = index * 2
            tk.Label(frame, text=label_of(path), anchor="w", font=("", 9, "bold")).grid(
                row=row, column=0, sticky="w", padx=(10, 6), pady=(6, 0)
            )

            if setting.kind == "table":
                widget = tk.Text(frame, height=5, width=40)
                widget.insert("1.0", value)
                getter = lambda w=widget: w.get("1.0", "end-1c")   # noqa: E731
            elif path == "voice.speaker":
                widget = ttk.Combobox(frame)
                widget.set(value)
                getter = lambda w=widget: w.get()                  # noqa: E731
                self.speaker_box = widget
                widget.bind("<<ComboboxSelected>>", lambda _e: self._refresh_styles())
            elif path == "voice.style":
                widget = ttk.Combobox(frame)
                widget.set(value)
                getter = lambda w=widget: w.get()                  # noqa: E731
                self.style_box = widget
            else:
                var = tk.StringVar(value=value)
                widget = tk.Entry(frame, textvariable=var)
                getter = lambda v=var: v.get()                     # noqa: E731
            widget.grid(row=row, column=1, sticky="ew", padx=6, pady=(6, 0))

            targets = write_targets(path, has_project)
            if not targets:
                # 書ける先が無い行を編集させると、保存で必ず行き止まりになる
                widget.configure(state="disabled" if setting.kind == "table" else "readonly")
            target = tk.StringVar(
                value=default_target(path, origin.layer, has_project)
            )
            box = ttk.Combobox(
                frame, textvariable=target, state="readonly", width=12,
                values=[settings.LAYER_LABEL[t] for t in targets] or [NOWHERE],
            )
            box.set(settings.LAYER_LABEL.get(target.get(), NOWHERE))
            box.grid(row=row, column=2, padx=(0, 10), pady=(6, 0))

            # 説明は横に長い。全列を使って折り返さないと途中で切れる
            tk.Label(frame, text=self._note(path, origin, setting), anchor="w",
                     justify=tk.LEFT, wraplength=860,
                     fg=self._note_color(origin), font=("", 8)).grid(
                row=row + 1, column=0, columnspan=3, sticky="w", padx=(12, 10)
            )

            self.rows[path] = {
                "getter": getter, "original": value,
                "target": target, "targets": targets,
            }

    def _note(self, path: str, origin, setting) -> str:
        parts = [f"由来: {origin.short()}"]
        if origin.layer == settings.VIDEO:
            parts.append("! この1本が上書き中 (ここで直しても効きません)")
        if affects_audio(path):
            parts.append("! 再合成")
        if setting.help:
            parts.append(setting.help)
        return "   ".join(parts)

    def _note_color(self, origin) -> str:
        if origin.layer == settings.VIDEO:
            return "#b26b00"
        return "#666" if origin.layer == settings.DEFAULT else "#0a6"

    # --- 話者 --------------------------------------------------------
    def _load_speakers_async(self) -> None:
        import threading

        def work():
            try:
                from .tts.voicevox import VoiceVox

                found = VoiceVox(Voice()).speakers()
            except Exception:
                found = []
            self.root.after(0, lambda: self._apply_speakers(found))

        threading.Thread(target=work, daemon=True).start()

    def _apply_speakers(self, found: list[dict[str, Any]]) -> None:
        self.speakers = found
        if not found:
            self.status.set(
                "VOICEVOX ENGINE に繋がりません (話者名は手で入力できます)"
            )
            return
        box = getattr(self, "speaker_box", None)
        if box is not None:
            box["values"] = [s.get("name", "") for s in found]
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        box = getattr(self, "style_box", None)
        speaker = getattr(self, "speaker_box", None)
        if box is None or speaker is None:
            return
        for entry in self.speakers:
            if entry.get("name") == speaker.get():
                box["values"] = [s.get("name", "") for s in entry.get("styles", [])]
                return

    # --- 操作 --------------------------------------------------------
    def choose_project(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.project_dir.get())
        if chosen:
            self.project_dir.set(chosen)
            self.spec_path.set("")
            self.reload()

    def create_project_file(self) -> None:
        try:
            written = settings.init_project(self.project_dir.get())
        except settings.SettingsError as exc:
            messagebox.showerror("作れません", str(exc))
            return
        self.status.set(f"作成: {written}")
        self.reload()

    def edits(self) -> list[Edit]:
        out = []
        for path, row in self.rows.items():
            label = row["target"].get()
            layer = next(
                (t for t in row["targets"] if settings.LAYER_LABEL[t] == label), NOWHERE
            )
            out.append(
                Edit(path=path, text=row["getter"](), original=row["original"], target=layer)
            )
        return out

    def on_save(self) -> None:
        try:
            writes = plan_writes(self.edits())
        except settings.SettingsError as exc:
            messagebox.showerror("保存できません", str(exc))
            return
        if not writes:
            self.status.set("変更はありません")
            return
        try:
            written = save(writes, self.project_file)
        except (settings.SettingsError, OSError) as exc:
            messagebox.showerror("保存できません", str(exc))
            return

        overridden = [
            path for layer in writes for path in writes[layer]
            if self.resolved.origin(path).layer == settings.VIDEO
        ]
        self.status.set("保存: " + " / ".join(str(p) for p in written))
        if overridden:
            messagebox.showwarning(
                "保存しましたが効きません",
                "この1本 (video.md) が上書きしているので、次の項目は効きません:\n\n"
                + "\n".join(overridden)
                + "\n\nvideo.md 側の記述を消してください。",
            )
        self.reload()

    def on_preview(self) -> None:
        import tempfile
        import threading

        voice = Voice()
        for path, row in self.rows.items():
            head, _, leaf = path.rpartition(".")
            if head != "voice" or leaf == "dict" or not hasattr(voice, leaf):
                continue
            text = row["getter"]().strip()
            if not text:
                continue
            try:
                setattr(voice, leaf, settings.parse_value(path, text))
            except settings.SettingsError:
                pass
        if not voice.speaker:
            self.status.set("話者を選んでから試聴してください")
            return

        self.status.set("合成中…")

        def work():
            try:
                from .tts.voicevox import VoiceVox

                engine = VoiceVox(voice)
                data = engine.synthesize(PREVIEW_TEXT, engine.resolve_speaker())
                wav = Path(tempfile.gettempdir()) / "gmp-preview.wav"
                wav.write_bytes(data)
                play_wav(wav)
                message = f"試聴: {voice.speaker} ({voice.style or '既定'})"
            except Exception as exc:                      # noqa: BLE001
                message = f"試聴できません: {exc}"
            self.root.after(0, lambda: self.status.set(message))

        threading.Thread(target=work, daemon=True).start()


def open_window(spec: str | Path | None = None) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"gmp: 画面を開けません ({exc})", file=sys.stderr)
        return 1
    SettingsWindow(root, Path(spec) if spec else None)
    root.mainloop()
    return 0
