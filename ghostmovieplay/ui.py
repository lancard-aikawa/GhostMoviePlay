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


@dataclass(frozen=True)
class Field:
    """行の中の 1 項目."""

    path: str
    prefix: str = ""            # 項目の直前に置く小さな見出し / 区切り ("×" など)
    width: int | None = None    # 数字は狭くする


@dataclass(frozen=True)
class Row:
    """1 行。近い項目は横に並べる (幅と高さを 2 行に分けても得がない).

    **同じ行に置けるのは書ける層が同じ設定だけ。** 書込先は行に 1 つなので、
    層の違うものを並べると選べる先が嘘になる (tests/test_ui.py が見ている)。
    """

    label: str
    fields: tuple[Field, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.fields)


@dataclass(frozen=True)
class Group:
    """タブの中の区切り. collapsed=True は既定で畳む (めったに変えないもの)."""

    title: str
    rows: tuple[Row, ...]
    collapsed: bool = False


@dataclass(frozen=True)
class Tab:
    title: str
    note: str
    groups: tuple[Group, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(p for g in self.groups for r in g.rows for p in r.paths)


def _one(path: str, label: str | None = None) -> Row:
    return Row(label or LABELS.get(path, path), (Field(path),))


RARELY = "めったに変えないもの"

TABS: tuple[Tab, ...] = (
    Tab(
        "声と口調", "話者と口調。plan.json に焼かれ、say の文面と音声になる",
        (
            Group("話者と声", (
                Row("話者", (Field("voice.speaker"),
                             Field("voice.style", prefix="スタイル"))),
                Row("声の調整", (
                    Field("voice.speed", prefix="話速", width=6),
                    Field("voice.pitch", prefix="音高", width=6),
                    Field("voice.intonation", prefix="抑揚", width=6),
                    Field("voice.volume", prefix="音量", width=6),
                )),
            )),
            Group("原稿", (
                _one("persona.style", "口調"),
                _one("voice.dict", "読み辞書"),
            )),
            Group(RARELY, (
                Row("発話の前後の無音", (
                    Field("voice.pre", prefix="前", width=6),
                    Field("voice.post", prefix="後", width=6),
                )),
                _one("voice.engine", "TTS エンジン"),
            ), collapsed=True),
        ),
    ),
    Tab(
        "何を撮るか", "Pass1 への指示。plan.json には残らない",
        (
            Group("何を作るか", (
                _one("series.audience", "狙う視聴者"),
                _one("series.topics", "題材の候補"),
                _one("series.count", "作る本数"),
                _one("series.avoid", "触れないこと"),
            )),
            Group("1本の長さ", (
                Row("目標尺", (
                    Field("series.target_seconds", prefix="秒", width=8),
                    Field("series.tolerance", prefix="許容超過", width=6),
                )),
            )),
            Group("字幕の作り方", (
                Row("字幕の大きさ", (
                    Field("subtitle.max_chars", prefix="1行の文字数", width=6),
                    Field("subtitle.max_lines", prefix="行数", width=6),
                )),
                Row("読み切る時間", (
                    Field("subtitle.reading_cps", prefix="文字/秒", width=6),
                    Field("subtitle.pad", prefix="余白(秒)", width=6),
                )),
            ), collapsed=True),
        ),
    ),
    Tab(
        "対象と動画", "収録対象と絵の形。プロジェクト固有の事実はここ",
        (
            Group("収録対象", (
                _one("app.url", "URL"),
                _one("app.ready", "準備完了のセレクタ"),
                _one("app.start", "起動コマンド"),
                _one("app.cwd", "ソースのフォルダ"),
            )),
            Group("素性", (
                _one("project", "プロジェクト名"),
                _one("title", "動画タイトル"),
            )),
            Group("再現性", (
                _one("determinism.time", "固定する開始時刻"),
                _one("determinism.seed", "乱数の seed"),
            )),
            Group(RARELY, (
                Row("解像度", (
                    Field("video.width", width=8),
                    Field("video.height", prefix="×", width=8),
                )),
                Row("fps と前後の余白", (
                    Field("video.fps", prefix="fps", width=6),
                    Field("video.leader", prefix="冒頭(秒)", width=6),
                    Field("video.trailer", prefix="末尾(秒)", width=6),
                )),
                _one("app.start_timeout", "起動待ち上限(秒)"),
                _one("lang", "言語"),
            ), collapsed=True),
        ),
    ),
    Tab(
        "この機械", "この機械でだけ効く。plan.json には入らない",
        (
            Group("置き場所", (
                _one("home", "生成物の置き場所"),
            )),
            Group("VOICEVOX", (
                _one("engine.voicevox.url", "接続先"),
                _one("engine.voicevox.exe", "実行ファイル"),
            )),
            Group("書き出し", (
                _one("render.font", "字幕フォント"),
                Row("画質", (
                    Field("render.crf", prefix="CRF", width=6),
                    Field("render.preset", prefix="preset", width=10),
                )),
            )),
            Group("Pass1 の claude", (
                _one("agent.model", "モデル"),
                _one("agent.permission_mode", "権限モード"),
            ), collapsed=True),
        ),
    ),
)


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


def visible(row: Row, has_project: bool, explicit: set[str]) -> bool:
    """その行を画面に出すか.

    **書ける先が無い行は、いま効いている値があるときだけ読み取り専用で出す。**
    `gmp.toml` を作る前に「入力できない入力欄」を並べても、埋められないものを
    埋めようとして詰まるだけ。一方、video.md が上書きしている値は、直せなくても
    「いまこうなっている」を見せる価値がある。
    """
    if write_targets(row.paths[0], has_project):
        return True
    return any(path in explicit for path in row.paths)


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
        # 畳んだ状態は読み直しても保つ (開くたびに畳まれると邪魔になる)
        self.folded: dict[tuple[str, str], bool] = {}

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

        # gmp.toml の有無はフォルダの性質なので、フォルダを選ぶ場所に出す
        note = tk.Frame(head)
        note.grid(row=1, column=1, sticky="ew", padx=6)
        self.project_note = tk.Label(note, text="", anchor="w", fg="#666")
        self.project_note.pack(side=tk.LEFT)
        self.project_action = tk.Button(note, text="", command=self.create_project_file)
        self.project_action.pack(side=tk.LEFT, padx=8)

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
            # 下の帯は本体より**先に** pack する。本体は side=LEFT で cavity を
            # 取るので、後から pack した帯は右側の残りから幅を持っていき、
            # 本体が半分の幅になる (フッターのボタン行と同じ罠)
            if tab.title == "声と口調":
                self._build_preview_row(outer)
            body = self._scrollable(outer)
            self.frames[tab.title] = body

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

        # ホイールはポインタが乗っている間だけ受ける。bind_all を出しっぱなしに
        # すると、タブごとの canvas が同じ束縛を上書きし合って、**最後に作った
        # タブしかスクロールしなくなる**
        def wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
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
        if project_file:
            self.project_note.config(text=f"{settings.PROJECT_FILE} あり")
            self.project_action.config(text="削除", command=self.delete_project_file)
        else:
            self.project_note.config(
                text=f"{settings.PROJECT_FILE} が無いので、共通の既定を保存できません"
            )
            self.project_action.config(text="作る", command=self.create_project_file)

        for frame in self.frames.values():
            for child in frame.winfo_children():
                child.destroy()
        self.rows.clear()
        for tab in TABS:
            self._fill(tab)
        self._fill_speaker_boxes()   # 作り直したコンボボックスは中身が空

        warnings = len(self.resolved.warnings)
        self.status.set(
            f"読み込みました ({'警告 %d 件' % warnings if warnings else '警告なし'})"
        )

    def _explicit_paths(self) -> set[str]:
        return {p for p in settings.SETTINGS if self.resolved.is_explicit(p)}

    def _fill(self, tab: Tab) -> None:
        body = self.frames[tab.title]
        has_project = self.project_file is not None
        explicit = self._explicit_paths()

        hidden = sum(
            not visible(row, has_project, explicit)
            for group in tab.groups for row in group.rows
        )
        if hidden and not has_project:
            # 「入力できない入力欄」を並べる代わりに、何をすれば出るかを言う
            box = tk.Frame(body, bg="#fff8e1")
            box.pack(fill=tk.X, padx=8, pady=(8, 0))
            tk.Label(
                box, bg="#fff8e1", fg="#8a6d00", justify=tk.LEFT, anchor="w",
                wraplength=860,
                text=f"{settings.PROJECT_FILE} を作ると、ここに {hidden} 行出ます"
                     "（対象URL・起動コマンド・seed などはプロジェクトにしか置けません）。",
            ).pack(side=tk.LEFT, padx=8, pady=6)
            tk.Button(box, text="作る", command=self.create_project_file).pack(
                side=tk.LEFT, padx=8
            )

        for group in tab.groups:
            self._fill_group(body, tab, group, has_project, explicit)

    def _fill_group(self, body: tk.Frame, tab: Tab, group: Group,
                    has_project: bool, explicit: set[str]) -> None:
        """区切りごとに見出しを付け、めったに変えないものは畳んでおく."""
        rows = [row for row in group.rows if visible(row, has_project, explicit)]
        if not rows:
            return      # 全部出ない区切りは見出しごと出さない

        key = (tab.title, group.title)
        folded = self.folded.setdefault(key, group.collapsed)

        head = tk.Frame(body)
        head.pack(fill=tk.X, padx=8, pady=(10, 0))
        inner = tk.Frame(body)
        inner.columnconfigure(1, weight=1)

        mark = tk.Label(head, text="▶" if folded else "▼", fg="#888", cursor="hand2")
        title = tk.Label(head, text=group.title, font=("", 9, "bold"),
                         fg="#333", cursor="hand2")
        mark.pack(side=tk.LEFT)
        title.pack(side=tk.LEFT, padx=4)
        tk.Frame(head, height=1, bg="#ddd").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=8
        )

        def toggle(_event=None) -> None:
            self.folded[key] = not self.folded[key]
            if self.folded[key]:
                inner.pack_forget()
            else:
                inner.pack(fill=tk.X, after=head)
            mark.config(text="▶" if self.folded[key] else "▼")

        for widget in (mark, title):
            widget.bind("<Button-1>", toggle)
        if not folded:
            inner.pack(fill=tk.X)

        for index, row in enumerate(rows):
            self._fill_row(inner, index * 2, row)

    def _fill_row(self, frame: tk.Frame, grid_row: int, row: Row) -> None:
        has_project = self.project_file is not None
        origins = [self.resolved.origin(p) for p in row.paths]

        tk.Label(frame, text=row.label, anchor="w", font=("", 9, "bold")).grid(
            row=grid_row, column=0, sticky="w", padx=(14, 6), pady=(6, 0)
        )

        # 1 行に複数項目を置くので、入力は横並びの入れ物にまとめる
        holder = tk.Frame(frame)
        holder.grid(row=grid_row, column=1, sticky="ew", padx=6, pady=(6, 0))
        writable = write_targets(row.paths[0], has_project)

        for field in row.fields:
            if field.prefix:
                tk.Label(holder, text=field.prefix, fg="#555").pack(
                    side=tk.LEFT, padx=(0 if field is row.fields[0] else 8, 4)
                )
            widget, getter = self._widget(holder, field)
            if not writable:
                # 書ける先が無い行を編集させると、保存で必ず行き止まりになる
                kind = settings.SETTINGS[field.path].kind
                widget.configure(state="disabled" if kind == "table" else "readonly")
            widget.pack(side=tk.LEFT, fill=tk.X, expand=field.width is None)
            self.rows[field.path] = {"getter": getter, "targets": writable,
                                     "original": format_value(
                                         field.path, self.resolved.values.get(field.path))}

        target = tk.StringVar(value=default_target(
            row.paths[0], origins[0].layer, has_project
        ))
        box = ttk.Combobox(
            frame, textvariable=target, state="readonly", width=12,
            values=[settings.LAYER_LABEL[t] for t in writable] or [NOWHERE],
        )
        box.set(settings.LAYER_LABEL.get(target.get(), NOWHERE))
        box.grid(row=grid_row, column=2, padx=(0, 10), pady=(6, 0))
        for path in row.paths:
            self.rows[path]["target"] = target      # 書込先は行に 1 つ

        tk.Label(frame, text=self._note(row, origins), anchor="w",
                 justify=tk.LEFT, wraplength=860,
                 fg=self._note_color(origins), font=("", 8)).grid(
            row=grid_row + 1, column=0, columnspan=3, sticky="w", padx=(16, 10)
        )

    def _widget(self, parent: tk.Frame, field: Field):
        path = field.path
        value = format_value(path, self.resolved.values.get(path))

        if settings.SETTINGS[path].kind == "table":
            widget = tk.Text(parent, height=5, width=40)
            widget.insert("1.0", value)
            return widget, lambda w=widget: w.get("1.0", "end-1c")
        if path in ("voice.speaker", "voice.style"):
            widget = ttk.Combobox(parent, width=field.width or 20)
            widget.set(value)
            if path == "voice.speaker":
                self.speaker_box = widget
                widget.bind("<<ComboboxSelected>>", lambda _e: self._refresh_styles())
            else:
                self.style_box = widget
            return widget, lambda w=widget: w.get()

        var = tk.StringVar(value=value)
        widget = tk.Entry(parent, textvariable=var, width=field.width or 20)
        return widget, lambda v=var: v.get()

    def _note(self, row: Row, origins) -> str:
        """行の下に出す 1 行. 由来が項目ごとに違うなら項目ごとに書く."""
        layers = {o.short() for o in origins}
        if len(layers) == 1:
            parts = [f"由来: {origins[0].short()}"]
        else:
            parts = ["由来: " + " / ".join(
                f"{label_of(p)}={o.short()}" for p, o in zip(row.paths, origins)
            )]
        if any(o.layer == settings.VIDEO for o in origins):
            parts.append("! この1本が上書き中 (ここで直しても効きません)")
        if any(affects_audio(p) for p in row.paths):
            parts.append("! 再合成")
        helps = [settings.SETTINGS[p].help for p in row.paths]
        if len(row.fields) == 1 and helps[0]:
            parts.append(helps[0])
        return "   ".join(parts)

    def _note_color(self, origins) -> str:
        if any(o.layer == settings.VIDEO for o in origins):
            return "#b26b00"
        if all(o.layer == settings.DEFAULT for o in origins):
            return "#666"
        return "#0a6"

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
        """ENGINE から話者一覧が返ってきたとき."""
        self.speakers = found
        if not found:
            self.status.set(
                "VOICEVOX ENGINE に繋がりません (話者名は手で入力できます)"
            )
        self._fill_speaker_boxes()

    def _fill_speaker_boxes(self) -> None:
        """話者一覧をコンボボックスへ入れる.

        **行を作り直すたびに呼ぶ。** 取得は起動時に 1 回だけなので、
        プロジェクトを選び直した後にここを通さないと一覧が空のままになる
        (実際に空になった)。
        """
        box = getattr(self, "speaker_box", None)
        if box is not None:
            box["values"] = [s.get("name", "") for s in self.speakers]
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

    def delete_project_file(self) -> None:
        """gmp.toml を消す. 消えると困るものが入っているので必ず訊く."""
        target = self.project_file
        if not target:
            return
        if not messagebox.askyesno(
            "削除しますか",
            f"{target}\n\nを削除します。ここに書いた共通の既定"
            "（対象URL・起動コマンド・声・口調・題材・読み辞書・seed）は失われ、\n"
            "以降の動画はコードの既定に戻ります。\n\n"
            "git に入れてあれば戻せます。",
            default=messagebox.NO,
        ):
            return
        try:
            target.unlink()
        except OSError as exc:
            messagebox.showerror("削除できません", str(exc))
            return
        self.status.set(f"削除: {target}")
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
