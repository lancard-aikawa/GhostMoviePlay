"""設定のスキーマと、層をまたいだ解決.

設定は 3 層ある (弱い順)。それぞれ「何を置いてよいか」が違う:

  1. config.toml        グローバル設定 (この機械の既定)。git に入らない
  2. <project>/gmp.toml  プロジェクトの既定。**git に入る**
  3. video.md           動画 1 本ぶん。フロントマターで上書きする

`config.toml` に置けるのは **機械が変われば変わる値** (出力ルート、ENGINE の
接続先、入っているフォント) と **好みの既定** (声、口調、目標尺) だけ。
アプリの URL や起動コマンド、seed のような「プロジェクト固有の事実」は
機械の設定に置けない (`layers` で弾いて警告する)。同じ機械で 2 つ目の
プロジェクトを撮った瞬間に嘘になるため。

## 解決した値をどこへ渡すか (`Setting.bake`)

| bake | 行き先 | 意味 |
| --- | --- | --- |
| `plan` | plan.json | Pass2/3 が読む。**必ず plan.json に焼き切る** |
| `brief` | PLAN_REQUEST.md | Pass1 への指示。plan.json には残らない |
| `runtime` | 実行時に解決 | 機械依存で、絵と音に影響しない値だけ |

**`bake="plan"` の値を record / render が設定ファイルから読んではいけない。**
読むと、同じ plan.json が機械ごとに違う動画を出すようになり、3 段に分けた
意味が消える (CLAUDE.md「Pass2 と Pass3 に AI を入れない」と同じ理由)。
`runtime` が例外として成り立つのは、そこに並ぶ値が絵と音を変えないから。

将来ここに「役割ごとの声」を足すときは `voices.<名前>.*` を使う。
`voice.*` は単一話者のまま残す (既存の plan.json を壊さないため)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .subtitles import DEFAULT_FONT

# --- 層 ---------------------------------------------------------------
DEFAULT = "default"   # コードの既定値
MACHINE = "machine"   # config.toml
ENV = "env"           # 環境変数 (機械の設定の一時上書き)
PROJECT = "project"   # <project>/gmp.toml
VIDEO = "video"       # video.md のフロントマター
CLI = "cli"           # コマンドライン引数

# 設定ファイルとして書ける層 (DEFAULT/ENV/CLI はファイルではない)
WRITABLE = (MACHINE, PROJECT, VIDEO)

PROJECT_FILE = "gmp.toml"
ENV_PREFIX = "GHOSTMOVIEPLAY_"

LAYER_LABEL = {
    DEFAULT: "コード既定",
    MACHINE: "グローバル",
    ENV: "環境変数",
    PROJECT: "プロジェクト",
    VIDEO: "この動画",
    CLI: "コマンド引数",
}


# --- スキーマ ---------------------------------------------------------
@dataclass(frozen=True)
class Setting:
    path: str                       # ドット区切りのキー
    kind: str                       # str/int/float/bool/list/table/path
    default: Any = None             # 0引数の callable も可 (機械依存の既定)
    layers: tuple[str, ...] = WRITABLE
    bake: str = "plan"              # plan / brief / runtime
    help: str = ""

    def fallback(self) -> Any:
        return self.default() if callable(self.default) else self.default


def _default_home() -> str:
    from . import paths

    return str(paths.user_videos_dir() / paths.APP_DIR_NAME)


_ALL = WRITABLE
_PV = (PROJECT, VIDEO)      # プロジェクト固有の事実。機械には置けない
_M = (MACHINE,)             # 機械依存。plan.json に入れてはいけない

SCHEMA: tuple[Setting, ...] = (
    # --- 機械だけが決められるもの (bake=runtime) ---------------------
    Setting("home", "path", _default_home, _M, "runtime",
            "生成物の出力ルート"),
    Setting("engine.voicevox.url", "str", "http://127.0.0.1:50021", _M, "runtime",
            "VOICEVOX ENGINE の接続先"),
    Setting("render.font", "str", DEFAULT_FONT, _M, "runtime",
            "字幕フォント。この機械に入っているものを指す"),
    Setting("render.crf", "int", 20, _M, "runtime",
            "x264 CRF (小さいほど高画質)"),
    Setting("render.preset", "str", "medium", _M, "runtime",
            "x264 preset"),
    Setting("agent.model", "str", None, _M, "runtime",
            "gmp plan --run が claude に渡すモデル"),
    Setting("agent.permission_mode", "str", "acceptEdits", _M, "runtime",
            "gmp plan --run が claude に渡す権限モード"),

    # --- 素性 --------------------------------------------------------
    Setting("project", "str", None, _PV, "plan",
            "生成物の置き場所 <home>/<project>/ に使う名前"),
    Setting("title", "str", None, (VIDEO,), "plan",
            "動画タイトル"),
    Setting("lang", "str", "ja", _ALL, "plan",
            "字幕・原稿の言語"),

    # --- 収録対象 (プロジェクト固有の事実) ---------------------------
    Setting("app.url", "str", None, _PV, "plan",
            "収録対象の URL。file:///C:/... でもよい"),
    # **ここが埋まっていると「人が操作して撮る」1 本になる** (支援収録)。
    # ブラウザを開かないので url は要らない。自動操作の届かない相手
    # (ログインの要る業務アプリ・canvas・OAuth) のための道
    Setting("app.window", "str", None, _PV, "plan",
            "支援収録で撮るウィンドウのタイトル (部分一致)。埋めると URL は要らない"),
    # Android の 1 本。window と同じ役目で、撮るのが端末の画面になる。
    # **シリアルは書かない** —— 機械ごとに違うので、焼くと別の端末で繋がらない
    Setting("app.package", "str", None, _PV, "plan",
            "支援収録で撮る Android アプリ (com.example.app)。埋めると URL は要らない"),
    # 支援収録で撮る人に出す前提。**手順ではない** (手順は beat.do)。
    # ログイン済み・撮ってはいけない画面など、始める前に知る必要があるもの
    Setting("app.precondition", "str", None, _PV, "plan",
            "撮る前に人が満たしておくこと (支援収録の画面のいちばん上に出る)"),
    Setting("app.ready", "str", None, _PV, "plan",
            "これが見えたら準備完了とみなすセレクタ"),
    Setting("app.start", "str", None, _PV, "plan",
            "開発サーバの起動コマンド。既に応答していれば起動しない"),
    Setting("app.cwd", "path", None, _PV, "plan",
            "ソースを読ませるプロジェクトフォルダ (書いたファイルからの相対)"),
    Setting("app.start_timeout", "float", 60.0, _PV, "plan",
            "start の応答待ち上限(秒)"),
    # 仕込みは **start より前**に走る (仕込んだデータをサーバが読むので、
    # 逆順だと空のまま起動する)。荒れたデータを見せる題材はこれが主役になる
    Setting("app.setup", "str", None, _PV, "plan",
            "収録前に走らせるコマンド。落ちたら収録しない"),
    Setting("app.teardown", "str", None, _PV, "plan",
            "収録後に走らせるコマンド。落ちても収録は失敗にしない"),

    # --- 声 ----------------------------------------------------------
    Setting("voice.engine", "str", "voicevox", _ALL, "plan",
            "TTS エンジン"),
    Setting("voice.speaker", "str", None, _ALL, "plan",
            "話者名 (ずんだもん / zundamon) か話者ID"),
    Setting("voice.style", "str", None, _ALL, "plan",
            "話者のスタイル (ノーマル / あまあま など)"),
    Setting("voice.speed", "float", 1.0, _ALL, "plan", "話速"),
    Setting("voice.pitch", "float", 0.0, _ALL, "plan", "音高"),
    Setting("voice.intonation", "float", 1.0, _ALL, "plan", "抑揚"),
    Setting("voice.volume", "float", 1.0, _ALL, "plan", "音量"),
    Setting("voice.pre", "float", 0.1, _ALL, "plan", "発話前の無音(秒)"),
    Setting("voice.post", "float", 0.1, _ALL, "plan", "発話後の無音(秒)"),
    # 用語の読みは動画をまたいで共通なので、プロジェクトで持つのが正しい。
    # 1本ずつ持つと「1本目で直した読みが2本目で戻る」を必ず踏む。
    # 層をまたいで **マージ** される (下の MERGED を見よ)
    Setting("voice.dict", "table", None, _PV, "plan",
            "読みの指定。層をまたいでマージされる"),

    # --- 口調 (plan.json には残らない。say の文面に焼かれる) ---------
    Setting("persona.style", "str", None, _ALL, "brief",
            "口調。ずんだもんとして振る舞うのか、一般的な言葉遣いなのか"),

    # --- 動画の形 ----------------------------------------------------
    Setting("video.width", "int", 1280, _ALL, "plan"),
    Setting("video.height", "int", 720, _ALL, "plan"),
    Setting("video.fps", "int", 30, _ALL, "plan"),
    Setting("video.leader", "float", 2.5, _ALL, "plan",
            "ページ生成から最初のビートまでの最小待ち。短いと冒頭が動画に入らない"),
    Setting("video.trailer", "float", 1.2, _ALL, "plan", "末尾の余白(秒)"),

    # --- 字幕の作り方 (Pass1 への制約) ------------------------------
    Setting("subtitle.max_chars", "int", 26, _ALL, "brief", "1行の上限文字数"),
    Setting("subtitle.max_lines", "int", 2, _ALL, "brief", "字幕の行数上限"),
    Setting("subtitle.reading_cps", "float", 8.0, _ALL, "brief",
            "読み速度(文字/秒)。hold の見積りに使う"),
    Setting("subtitle.pad", "float", 0.6, _ALL, "brief",
            "読み切るための余白(秒)。hold = 文字数/reading_cps + pad"),

    # --- 何を動画にするか -------------------------------------------
    Setting("series.audience", "str", None, _ALL, "brief",
            "狙う視聴者。初心者 / 特定機能を使う人 / 特定用途 など"),
    Setting("series.topics", "list", None, (PROJECT,), "brief",
            "動画にしたい題材の一覧"),
    Setting("series.count", "int", None, (PROJECT,), "brief",
            "作る本数"),
    Setting("series.target_seconds", "float", 90.0, _ALL, "brief",
            "1本の目標尺。見積りと突き合わせて超過を警告する"),
    Setting("series.tolerance", "float", 0.25, _ALL, "brief",
            "目標尺の許容超過 (0.25 = +25% まで黙る)"),
    Setting("series.avoid", "list", None, _ALL, "brief",
            "触れてほしくない画面・機能 (未実装、課金、実データが映るもの)"),

    # --- 決定論 ------------------------------------------------------
    Setting("determinism.seed", "int", None, _PV, "plan",
            "Math.random の固定"),
    Setting("determinism.time", "str", None, _PV, "plan",
            "開始時刻の固定。プロジェクトで決めると全動画の日付表示が揃う"),
)

SETTINGS: dict[str, Setting] = {s.path: s for s in SCHEMA}

# 層をまたいで上書きせずマージするもの。読みは足していきたい
MERGED = frozenset({"voice.dict"})

# 人が書きやすい別名 -> 正規のキー
ALIASES = {
    "video.lang": "lang",
    "meta.lang": "lang",
    "meta.title": "title",
    "meta.project": "project",
    "persona.voice": "voice.speaker",   # video.md の雛形が使っている書き方
}


class SettingsError(ValueError):
    """設定ファイルが読めない."""


# --- 正規化 -----------------------------------------------------------
def _flatten(raw: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """ネストした dict をドット区切りに潰す.

    kind="table" の設定 (voice.dict など) は中身まで潰さずそのまま持つ。
    """
    out: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        path = f"{prefix}{key}"
        setting = SETTINGS.get(ALIASES.get(path, path))
        if isinstance(value, dict) and (setting is None or setting.kind != "table"):
            out.update(_flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """1層ぶんの生 dict を、ドット区切りの正規キーに直す."""
    flat = _flatten(raw)

    # video.size: [w, h] は人が書きやすい形。幅と高さに割る
    size = flat.pop("video.size", None)
    if isinstance(size, (list, tuple)) and len(size) == 2:
        flat.setdefault("video.width", size[0])
        flat.setdefault("video.height", size[1])

    return {ALIASES.get(k, k): v for k, v in flat.items()}


def _coerce(setting: Setting, value: Any) -> Any:
    kind = setting.kind
    if kind in ("str", "path"):
        if isinstance(value, (dict, list)):
            raise SettingsError(f"{setting.path}: 文字列が必要です")
        return str(value)
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "list":
        return list(value) if isinstance(value, (list, tuple)) else [value]
    if kind == "table":
        if not isinstance(value, dict):
            raise SettingsError(f"{setting.path}: テーブルが必要です")
        return dict(value)
    return value


# --- 置き場所 ---------------------------------------------------------
def find_project_file(start: str | Path, limit: int = 8) -> Path | None:
    """start から上へ辿って gmp.toml を探す.

    video.md は <project>/docs/video/<name>/ のように深いところに置かれるので、
    プロジェクトルートまで数階層ある。最初に見つかった 1 枚だけを使う
    (複数見つけて合成すると、どこの値が効いているのか誰も追えなくなる)。
    """
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for directory in [here, *here.parents][:limit]:
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def read_toml(path: Path) -> dict[str, Any]:
    import tomllib

    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise SettingsError(f"{path}: TOML として読めません: {exc}") from exc


def env_var_name(path: str) -> str:
    """設定キーに対応する環境変数名. home -> GHOSTMOVIEPLAY_HOME."""
    return ENV_PREFIX + path.upper().replace(".", "_")


def env_layer() -> dict[str, Any]:
    """環境変数からの上書き.

    GHOSTMOVIEPLAY_HOME / GHOSTMOVIEPLAY_ENGINE_VOICEVOX_URL のように
    キーを大文字にして `.` を `_` にした名前。機械の層に置ける設定だけを見る
    (環境変数は「この機械・この起動だけ」を差し替える口なので、口調や
    シーン構成のようにプロジェクトが決めるべきものは対象にしない)。
    """
    found: dict[str, Any] = {}
    for setting in SCHEMA:
        if MACHINE not in setting.layers:
            continue
        value = os.environ.get(env_var_name(setting.path))
        if value:
            found[setting.path] = value
    return found


# --- 解決結果 ---------------------------------------------------------
@dataclass
class Origin:
    layer: str
    source: Path | None = None
    detail: str | None = None   # 環境変数名など

    def short(self) -> str:
        """一覧に並べる用. どのファイルかはヘッダに出るので層の名前だけ."""
        return self.detail or LAYER_LABEL.get(self.layer, self.layer)

    def label(self) -> str:
        """1 個だけ出す用. ファイルまで含める."""
        base = LAYER_LABEL.get(self.layer, self.layer)
        if self.detail:
            return f"{base} {self.detail}"
        return f"{base} ({self.source})" if self.source else base


@dataclass
class Resolved:
    values: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, Origin] = field(default_factory=dict)
    sources: dict[str, Path] = field(default_factory=dict)   # 層 -> ファイル
    warnings: list[str] = field(default_factory=list)

    def get(self, path: str, default: Any = None) -> Any:
        value = self.values.get(path)
        return default if value is None else value

    def origin(self, path: str) -> Origin:
        return self.origins.get(path, Origin(DEFAULT))

    def is_explicit(self, path: str) -> bool:
        """コードの既定ではなく、どこかで明示されているか."""
        return self.origin(path).layer != DEFAULT

    def section(self, prefix: str, explicit_only: bool = False) -> dict[str, Any]:
        """`voice` のような区画を、prefix を落とした dict で返す."""
        head = f"{prefix}."
        out: dict[str, Any] = {}
        for path, value in self.values.items():
            # 空の辞書・配列・文字列は「書いていない」と同じ扱い。0 や False は残す。
            # **空文字は下の層を打ち消す唯一の手** —— 支援収録の 1 本は
            # プロジェクトが持っている app.url を要らないが、これが無いと
            # video.md からは消せず、使いもしない URL が plan.json に焼かれる
            if (not path.startswith(head) or value is None
                    or value == {} or value == [] or value == ""):
                continue
            if explicit_only and not self.is_explicit(path):
                continue
            out[path[len(head):]] = value
        return out

    def baked(self, bake: str) -> list[Setting]:
        return [s for s in SCHEMA if s.bake == bake]

    def rebase_path(self, path: str, base: str | Path) -> str | None:
        """相対パスの設定を、base からの相対に書き直す.

        **相対パスは「それを書いたファイル」からの相対として解釈する。**
        gmp.toml の `cwd = '.'` はプロジェクトルート、video.md の `cwd = '.'`
        は動画のフォルダで、別の場所を指す。層をまたぐと基準が変わるので、
        使う側の基準 (plan.json の置き場所など) に直してから渡す。

        絶対のまま返すのは別ドライブのときだけ。plan.json に絶対パスを
        焼くとマシンをまたいだときに壊れるため、できるだけ相対で返す。
        """
        value = self.values.get(path)
        if not value:
            return None
        target = Path(str(value)).expanduser()
        if not target.is_absolute():
            declared = self.origin(path).source
            root = declared.parent if declared else Path.cwd()
            target = root / target
        try:
            return os.path.relpath(target.resolve(), Path(base).resolve()).replace("\\", "/")
        except ValueError:
            return str(target.resolve())   # ドライブが違うと相対にできない


def resolve(
    machine: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    video: dict[str, Any] | None = None,
    cli: dict[str, Any] | None = None,
    machine_path: Path | None = None,
    project_path: Path | None = None,
    video_path: Path | None = None,
    use_env: bool = True,
) -> Resolved:
    """層を重ねて 1 つの設定にする.

    渡された dict は生のまま (ネストしていてよい)。値の由来を全部覚えるので、
    UI や `gmp config` が「この値はどこから来たか」を出せる。
    """
    result = Resolved()
    result.sources = {
        layer: path
        for layer, path in ((MACHINE, machine_path), (PROJECT, project_path), (VIDEO, video_path))
        if path is not None
    }

    for setting in SCHEMA:
        result.values[setting.path] = setting.fallback()
        result.origins[setting.path] = Origin(DEFAULT)

    layers: list[tuple[str, dict[str, Any]]] = [(MACHINE, machine or {})]
    if use_env:
        layers.append((ENV, env_layer()))
    layers += [(PROJECT, project or {}), (VIDEO, video or {}), (CLI, cli or {})]

    for layer, raw in layers:
        flat = raw if layer == ENV else normalize(raw)
        source = result.sources.get(layer)
        for path, value in flat.items():
            if value is None:
                continue
            setting = SETTINGS.get(path)
            if setting is None:
                result.warnings.append(
                    f"{_where(layer, source)}: 未知の設定 {path!r} (無視しました)"
                )
                continue
            # 「機械の設定に app.url を書いたのに効かない」を黙って起こさない
            if layer in WRITABLE and layer not in setting.layers:
                allowed = " / ".join(LAYER_LABEL[x] for x in setting.layers)
                result.warnings.append(
                    f"{_where(layer, source)}: {path!r} はここに書けません"
                    f" (書ける層: {allowed})"
                )
                continue
            # **空文字は「打ち消す」。** 下の層が持っている値を上の層から
            # 消せる唯一の手で、型に関わらず同じ意味にしておく (数の項目だけ
            # `int('')` で落ちて「書いたのに効かない」になるのを避ける)
            if isinstance(value, str) and not value.strip():
                result.values[path] = None
                result.origins[path] = Origin(
                    layer, source, env_var_name(path) if layer == ENV else None
                )
                continue
            try:
                coerced = _coerce(setting, value)
            except (SettingsError, TypeError, ValueError) as exc:
                result.warnings.append(f"{_where(layer, source)}: {exc}")
                continue
            if path in MERGED and isinstance(result.values.get(path), dict):
                merged = dict(result.values[path])
                merged.update(coerced)
                coerced = merged
            result.values[path] = coerced
            result.origins[path] = Origin(
                layer, source, env_var_name(path) if layer == ENV else None
            )

    return result


def machine_value(path: str) -> Any:
    """機械の層 (config.toml と環境変数) だけを見て 1 項目を解決する.

    **Pass2/3 (record / render / voice) から設定を読む唯一の入口。**
    プロジェクトや video.md を見ないので、同じ plan.json が置き場所によって
    違う動画になることが起こり得ない。だから機械に置ける項目しか通さない。

    通すのは `bake="runtime"` の項目だけ。声の既定のように「機械にも書けるが
    plan.json に焼かれる」値は通さない (それを実行時に読むと、plan.json に
    書いてある声と違う声で喋る)。「読む値をこの関数に絞る」という形で
    不変条件を守っている。ここから取りたくなったら、それは Pass1 の仕事。
    """
    from . import paths

    setting = SETTINGS.get(path)
    if setting is None or setting.bake != "runtime":
        raise SettingsError(
            f"{path!r} は実行時に読める設定ではありません"
            " (plan.json に焼かれる値は Pass1 で解決してください)"
        )
    return resolve(machine=paths.load_config()).get(path)


def _where(layer: str, source: Path | None) -> str:
    return str(source) if source else LAYER_LABEL.get(layer, layer)


def load(
    spec: str | Path | None = None,
    cli: dict[str, Any] | None = None,
    video: dict[str, Any] | None = None,
) -> Resolved:
    """既定の置き場所から 3 層を読んで解決する.

    spec は video.md か plan.json のパス。そこから上へ gmp.toml を探す。
    video.md のフロントマターは呼び側が渡す (spec.parse が持っているため)。
    """
    from . import paths

    # 機械の層は paths.load_config() を通す。読み口を 1 つにしておかないと
    # 出力ルートの解決 (paths.output_home) と食い違う
    machine_path = paths.config_path()
    project_path = find_project_file(spec) if spec else find_project_file(Path.cwd())

    return resolve(
        machine=paths.load_config(),
        project=read_toml(project_path) if project_path else {},
        video=video or {},
        cli=cli or {},
        machine_path=machine_path if machine_path.exists() else None,
        project_path=project_path,
        video_path=Path(spec) if spec and video else None,
    )


# --- 書き出し ---------------------------------------------------------
def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_scalar(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_scalar(v)}" for k, v in value.items()) + " }"
    # Windows のパスはバックスラッシュを含むので、エスケープの要らない
    # リテラル文字列 ('...') に入れる
    text = str(value).replace("\\", "/")
    if "'" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"'{text}'"


def _key(name: str) -> str:
    ok = name and all(c.isalnum() or c in "-_" for c in name) and name.isascii()
    return name if ok else _scalar(name)


def dump(values: dict[str, Any], header: str = "", comments: bool = True) -> str:
    """ドット区切りの dict を、ネストした TOML にする.

    スキーマの順に並べ、知らないキーは末尾に残す (手で足した設定を消さない)。
    """
    flat = {k: v for k, v in normalize(values).items() if v is not None}

    groups: dict[str, list[tuple[str, Any, Setting | None]]] = {}
    for setting in SCHEMA:
        if setting.path in flat:
            section, _, leaf = setting.path.rpartition(".")
            if setting.kind == "table":
                section, leaf = setting.path, None
            groups.setdefault(section, []).append((leaf, flat.pop(setting.path), setting))
    for path in sorted(flat):
        section, _, leaf = path.rpartition(".")
        groups.setdefault(section, []).append((leaf, flat[path], None))

    lines: list[str] = [f"# {header}", ""] if header else []
    for section, entries in groups.items():
        if section:
            lines.append(f"[{section}]")
        for leaf, value, setting in entries:
            if leaf is None:                      # kind="table": 区画そのもの
                for key, item in value.items():
                    lines.append(f"{_key(key)} = {_scalar(item)}")
                continue
            if comments and setting and setting.help:
                lines.append(f"# {setting.help}")
            lines.append(f"{_key(leaf)} = {_scalar(value)}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def _section_of(line: str) -> str | None:
    """`[voice.dict]` のような区画見出しなら、その名前を返す."""
    text = line.strip()
    if text.startswith("[") and text.endswith("]") and not text.startswith("[["):
        return text[1:-1].strip()
    return None


def _key_of(line: str) -> str | None:
    """`speaker = '...'` のような代入なら、キー名を返す (コメント行は None)."""
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    raw = text.split("=", 1)[0].strip()
    if raw[:1] in ("'", '"') and raw[-1:] == raw[:1]:
        raw = raw[1:-1]
    return raw or None


def patch_toml(text: str, changes: dict[str, Any]) -> str:
    """既存の TOML に変更だけを当てる. **コメントと並び順を保つ.**

    gmp.toml は人が手で書くファイルで、なぜその値なのかをコメントに書く。
    dump() で書き直すとそれが消えるので、UI からの保存はこちらを通す。
    値が None の項目は消す。dict (kind="table") は区画ごと置き換える。
    """
    tables = {k: v for k, v in changes.items() if isinstance(v, dict)}
    scalars = {k: v for k, v in changes.items() if not isinstance(v, dict)}

    lines = text.splitlines()
    out: list[str] = []
    section = ""
    done: set[str] = set()
    dropped_tables = set(tables)

    for line in lines:
        header = _section_of(line)
        if header is not None:
            # 置き換える表の区画は、見出しごと落とす
            section = header
            if header in dropped_tables:
                continue
            out.append(line)
            continue
        if section in dropped_tables:
            continue   # 落とした区画の中身

        key = _key_of(line)
        full = f"{section}.{key}" if section and key else key
        if full in scalars:
            done.add(full)
            if scalars[full] is not None:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f"{indent}{_key(key)} = {_scalar(scalars[full])}")
            continue   # None なら行ごと消す
        out.append(line)

    # 既存の行に無かったものを足す
    remaining = {
        k: v for k, v in scalars.items() if k not in done and v is not None
    }
    if remaining:
        out = _insert_new_keys(out, remaining)
    for path, value in tables.items():
        if value:
            out += ["", f"[{path}]"]
            out += [f"{_key(k)} = {_scalar(v)}" for k, v in value.items()]

    return "\n".join(out).rstrip("\n") + "\n"


def _insert_new_keys(lines: list[str], remaining: dict[str, Any]) -> list[str]:
    """新しいキーを、対応する区画の末尾へ入れる (無ければ区画ごと作る)."""
    by_section: dict[str, dict[str, Any]] = {}
    for path, value in remaining.items():
        head, _, leaf = path.rpartition(".")
        by_section.setdefault(head, {})[leaf] = value

    out = list(lines)
    for head, entries in by_section.items():
        block = [f"{_key(k)} = {_scalar(v)}" for k, v in entries.items()]
        # 区画の最後の行を探す (次の見出しの直前)
        end = None
        section = ""
        for i, line in enumerate(out):
            header = _section_of(line)
            if header is not None:
                if section == head:
                    end = i
                    break
                section = header
        if section == head and end is None:
            end = len(out)
        if end is None:
            # 区画そのものが無い。root は先頭、それ以外は末尾に作る
            if head:
                out += ["", f"[{head}]", *block]
            else:
                first = next(
                    (i for i, x in enumerate(out) if _section_of(x) is not None), len(out)
                )
                out[first:first] = block
            continue
        while end > 0 and not out[end - 1].strip():
            end -= 1     # 区画末尾の空行より前に入れる
        out[end:end] = block
    return out


def write_layer(path: str | Path, changes: dict[str, Any]) -> Path:
    """設定ファイルに変更を書く. 既にあればコメントを保ったまま当てる."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        patched = patch_toml(target.read_text(encoding="utf-8"), changes)
    else:
        patched = dump(
            {k: v for k, v in changes.items() if v is not None},
            header="GhostMoviePlay の設定",
        )
    target.write_text(patched, encoding="utf-8")
    return target


def parse_value(path: str, text: str) -> Any:
    """`gmp config --set key=value` の右辺を、その設定の型に直す."""
    setting = SETTINGS.get(path)
    if setting is None:
        known = ", ".join(sorted(SETTINGS))
        raise SettingsError(f"未知の設定 {path!r}\n  使えるキー: {known}")
    if setting.kind == "list":
        return [x.strip() for x in text.split(",") if x.strip()]
    if setting.kind == "table":
        raise SettingsError(f"{path!r} はテーブルなので設定ファイルを直接編集してください")
    return _coerce(setting, text)


PROJECT_TEMPLATE = """# GhostMoviePlay — このプロジェクトの既定
#
# ここに置いた値は、下の video.md すべてに効く。**git に入れる。**
# この動画だけ変えたいものは video.md のフロントマターで上書きする。
# いま効いている値と、その由来は `gmp config` で見られる。

project = '{project}'

# **収録対象。ここを埋めないと台本は書けない。**
# 設定画面 (gmp ui) の「対象と動画」からも入れられる。
[app]
{app}cwd = '.'                        # ソースを読ませるフォルダ (このファイルからの相対)

[voice]
speaker = 'ずんだもん'
style = 'ノーマル'
speed = 1.0

# 読みの指定。用語は動画をまたいで共通なのでここに置く。
# 1本ずつ持つと、1本目で直した読みが2本目で戻る。
# **TOML の裸のキーは ASCII だけ。日本語の表記は必ずクォートする。**
[voice.dict]
# '語' = 'ゴ'
# '冪等' = {{ pronunciation = 'ベキトウ', accent = 0 }}

[persona]
style = '落ち着いた解説口調。詰まるところは責めずに理由を淡々と説明する'

[series]
audience = '初心者。インストール直後の状態を想定'
topics = ['基本操作', '設定', 'つまずきやすいところ']
count = 3
target_seconds = 90.0
# avoid = ['課金画面', '未実装のエクスポート']

[determinism]
# 全動画で日付表示を揃えるために、開始時刻をプロジェクトで決めておく
time = '2026-01-01T09:00:00'
seed = 12345
"""


# 何も推測できなかったときに置く見本。**値としては書かない** ——
# 「設定済みに見える嘘」は、画面から直せない値としてプロジェクトに残る
APP_SAMPLE = """# url = 'http://localhost:5173'  # ← 実際の URL に書き換えてコメントを外す
# ready = 'text=スタート'        # これが見えたら準備完了
# start = 'npm run dev'          # 既に応答していれば起動しない
"""


def app_block(guesses) -> str:
    """推測を [app] の行にする. **由来をコメントで必ず添える.**"""
    if not guesses:
        return APP_SAMPLE
    lines = []
    for guess in guesses:
        leaf = guess.path.rpartition(".")[2]
        lines.append(f"{leaf} = {guess.value!r}".replace('"', "'")
                     + f"   # ← {guess.why}")
    lines.append("# 当たっていなければ書き換える (設定画面の「対象と動画」からでも)")
    return "\n".join(lines) + "\n"


def init_project(directory: str | Path, project: str | None = None,
                 force: bool = False, detect: bool = True) -> Path:
    """<project>/gmp.toml の雛形を置く. 戻り値は書いたファイル.

    収録対象は**プロジェクトを読んで埋める** (`detect.probe`)。ここが空だと
    Pass1 が「本物のアプリを指してくれ」と訊いて終わるので、埋められるものは
    埋めておく。推測なので当たらないことがあり、**由来をコメントで添えて**
    人が見て直せるようにする。
    """
    given = Path(directory)
    target = given if given.name == PROJECT_FILE else given / PROJECT_FILE
    if target.exists() and not force:
        raise SettingsError(f"{target} は既にあります")
    target.parent.mkdir(parents=True, exist_ok=True)
    name = project or target.parent.resolve().name

    guesses = []
    if detect:
        from .detect import probe

        try:
            guesses = probe(target.parent)
        except OSError:
            guesses = []            # 読めないだけ。雛形は置く

    target.write_text(
        PROJECT_TEMPLATE.format(project=name, app=app_block(guesses)),
        encoding="utf-8",
    )
    return target
