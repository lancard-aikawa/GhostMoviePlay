"""設定のスキーマと、層をまたいだ解決.

設定は 3 層ある (弱い順)。それぞれ「何を置いてよいか」が違う:

  1. config.toml        この機械の既定。git に入らない
  2. <project>/gmp.toml  プロジェクトの既定。**git に入る**
  3. video.md           1本ぶん。フロントマターで上書きする

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

# 弱い順。resolve() はこの順に上書きしていく
ORDER = (DEFAULT, MACHINE, ENV, PROJECT, VIDEO, CLI)

# 設定ファイルとして書ける層 (DEFAULT/ENV/CLI はファイルではない)
WRITABLE = (MACHINE, PROJECT, VIDEO)

PROJECT_FILE = "gmp.toml"
ENV_PREFIX = "GHOSTMOVIEPLAY_"

LAYER_LABEL = {
    DEFAULT: "コード既定",
    MACHINE: "機械の設定",
    ENV: "環境変数",
    PROJECT: "プロジェクト",
    VIDEO: "この1本",
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
    Setting("engine.voicevox.exe", "path", None, _M, "runtime",
            "ENGINE の実行ファイル。未起動のときに自分で起動する用"),
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
    Setting("app.ready", "str", None, _PV, "plan",
            "これが見えたら準備完了とみなすセレクタ"),
    Setting("app.start", "str", None, _PV, "plan",
            "開発サーバの起動コマンド。既に応答していれば起動しない"),
    Setting("app.cwd", "path", None, _PV, "plan",
            "ソースを読ませるプロジェクトフォルダ (書いたファイルからの相対)"),
    Setting("app.start_timeout", "float", 60.0, _PV, "plan",
            "start の応答待ち上限(秒)"),

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


def _read_toml(path: Path) -> dict[str, Any]:
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
            # 空の辞書・配列は「書いていない」と同じ扱い。0 や False は残す
            if not path.startswith(head) or value is None or value == {} or value == []:
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
        project=_read_toml(project_path) if project_path else {},
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


def writable_keys(layer: str) -> list[str]:
    return [s.path for s in SCHEMA if layer in s.layers]


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
# 1本だけ変えたいものは video.md のフロントマターで上書きする。
# いま効いている値と、その由来は `gmp config` で見られる。

project = '{project}'

[app]
url = 'http://localhost:5173'
# ready = 'text=スタート'      # これが見えたら準備完了
# start = 'npm run dev'        # 既に応答していれば起動しない
cwd = '.'                      # ソースを読ませるフォルダ (このファイルからの相対)

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
style = '落ち着いた解説口調。失敗は責めずに理由を淡々と説明する'

[series]
audience = '初心者。インストール直後の状態を想定'
topics = ['基本操作', '設定', 'よくある失敗']
count = 3
target_seconds = 90.0
# avoid = ['課金画面', '未実装のエクスポート']

[determinism]
# 全動画で日付表示を揃えるために、開始時刻をプロジェクトで決めておく
time = '2026-01-01T09:00:00'
seed = 12345
"""


def init_project(directory: str | Path, project: str | None = None,
                 force: bool = False) -> Path:
    """<project>/gmp.toml の雛形を置く. 戻り値は書いたファイル."""
    given = Path(directory)
    target = given if given.name == PROJECT_FILE else given / PROJECT_FILE
    if target.exists() and not force:
        raise SettingsError(f"{target} は既にあります")
    target.parent.mkdir(parents=True, exist_ok=True)
    name = project or target.parent.resolve().name
    target.write_text(PROJECT_TEMPLATE.format(project=name), encoding="utf-8")
    return target
