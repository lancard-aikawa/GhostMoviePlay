"""全部の台本を撮り直して、まだアプリに当たっているかを見る.

`gmp record` は要するに**ナレーション付きの Playwright スクリプト**なので、
落ちたということは UI が変わったということ。動画のためだけに置いてある
plan.json を CI で回せば、*説明が古くなったら自動で分かる*仕組みになる
(render も AI も要らない)。

**撮って分かる判定は増やさない。** 止めない失敗はすでに Recorder.warn() が
timing.json に残しているので、ここがやるのは**束ねること**だけ ——
プロジェクトの下の plan.json を全部見つけ、1 本ずつ撮って、赤を数える。

もう 1 つ、**撮らなくても分かる欠陥**だけを inspect() が見る (別の機械で落ちる
焼き込みと、上限を超える字幕)。`--dry` はそこで止まる道で、撮れば同じものが
必ず一緒に出る —— **速いほうで赤だったものが本番で緑になったら検査の意味が無い**。
撮れば分かることをこちらに書き足さないこと (二重実装になる)。

赤にしないものが 2 つだけある (ENV_KINDS)。どちらも**撮った環境の話**で、
台本が古いこととは関係が無いのに、CI ではほぼ必ず出る:

- `audio_missing` —— wav は生成物でプロジェクトの外に出る。clone した
  ばかりの機械には無い
- `leader_short` —— 録画開始の遅れは機械の速さで決まる

**それ以外は知らない kind でも赤にする。** 見落として素通りするより、
分類し忘れに気づくほうがいい (足したときは CLAUDE.md の表に従って
ここも直す)。無視したぶんも件数は必ず出す —— 黙って捨てると
「赤が無い = 全部当たっている」が嘘になる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 歩かないディレクトリ。plan.json はプロジェクトが git に入れるものなので、
# 依存や生成物の中を掘る意味が無い
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
})

# 撮った環境の話であって、台本が古いことの証拠ではない警告
ENV_KINDS = frozenset({"audio_missing", "leader_short"})

OK, STALE, BROKEN = "ok", "stale", "broken"
# **撮り直せないので検査できない** —— 支援収録は人が撮った素材が要り、それは
# 生成物なのでプロジェクトの外にある。並べ直しても「アプリがまだ当たっているか」
# は 1 文字も分からない。赤にはしないが、**通ったとも言わない**
SKIP = "skip"

# **印は ASCII で置く。** Windows の既定コンソールは cp932 で、`✓` は
# `?` に化ける (`_lenient_output` が落ちない代わりに潰す)。飾りが化けるのは
# 我慢できるが、化けるのが**判定そのもの**だと読めない
MARK = {OK: "ok", STALE: "!", BROKEN: "NG", SKIP: "--"}


@dataclass(frozen=True)
class Result:
    """台本 1 本ぶんの結果."""

    plan: Path
    state: str
    detail: str = ""
    stale: tuple[dict, ...] = ()      # 台本を直すべき警告
    ignored: tuple[dict, ...] = ()    # 環境の話なので赤にしなかった警告
    seconds: float | None = None

    @property
    def red(self) -> bool:
        return self.state not in (OK, SKIP)


def find_plans(root: Path, limit: int = 200) -> list[Path]:
    """root の下の plan.json. 見つかった順ではなくパス順に返す."""
    root = Path(root)
    if root.is_file():
        return [root]
    found: list[Path] = []
    stack = [root]
    while stack and len(found) < limit:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.name == "plan.json":
                found.append(entry)
    return sorted(found)


# git に入る plan.json に焼いてはいけない値。作った機械では動き続けるので、
# **誰かが clone するまで露見しない** (実際に examples/demo が絶対パスのままだった)
DRIVE_PATH = re.compile(r'"[A-Za-z]:[\\/]')


def _finding(kind: str, where: str | None, message: str) -> dict:
    """撮ったときの警告と同じ形にしておく (報告する側が分岐しないで済む)."""
    return {"kind": kind, "where": where, "message": message}


def inspect(path: Path, plan) -> tuple[dict, ...]:
    """撮らずに分かる欠陥を並べる.

    **赤にするのは 2 種類だけ** —— 別の機械で落ちるものと、読めない字幕。
    言い回しや尺の詰めのような好みの問題は入れない (入れると赤が信用されなくなる)。

    設定 (`subtitle.*`) を読むが、**警告を出すためだけ**に読む。
    `cli._report_length` が `series.target_seconds` を読むのと同じ立場で、
    ここで読んだ値が絵や音に混ざる経路は無い。
    """
    found: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""

    if "file:///" in raw:
        found.append(_finding(
            "machine_path", None,
            "file:// の絶対パスが焼かれています (clone した機械では落ちます)"))
    hit = DRIVE_PATH.search(raw)
    if hit:
        found.append(_finding(
            "machine_path", None,
            f"ドライブ名つきの絶対パスが焼かれています ({hit.group()}…)"))
    if plan.voice.url:
        found.append(_finding(
            "machine_url", None,
            "voice.url は機械ごとに違うので plan.json に焼かない"))

    return tuple(found) + _long_captions(path, plan)


def _long_captions(path: Path, plan) -> tuple[dict, ...]:
    """字幕が上限の行数に収まるか.

    **折り返しは `subtitles.wrap` に数えさせる。** 同じ数え方をここに書き直すと、
    検査が通った字幕が実際には 3 行になる (`AUDIO_TAIL` と同じ話)。
    """
    from . import settings
    from .subtitles import layout, wrap

    try:
        resolved = settings.load(spec=path)
        max_chars = int(resolved.get("subtitle.max_chars"))
        max_lines = int(resolved.get("subtitle.max_lines"))
    except (settings.SettingsError, OSError, TypeError, ValueError):
        return ()   # 設定が読めないことを台本のせいにしない

    # **実際に折り返す幅で数える。** 設定の上限だけ見ていると、縦画面のように
    # 幅の狭い 1 本で「通ったのに 4 行になる」ことになる
    max_chars = layout(plan.video.width, plan.video.height, max_chars)["limit"]

    found: list[dict] = []
    for scene in plan.scenes:
        for index, beat in enumerate(scene.beats):
            caption = beat.caption
            if not caption:
                continue
            lines = wrap(caption, max_chars).split("\\N")
            if len(lines) > max_lines:
                found.append(_finding(
                    "subtitle_too_long", f"{scene.id}#{index}",
                    f"字幕が {len(lines)} 行になります (上限 {max_lines} 行): "
                    f"{caption[:20]}…"))
    return tuple(found)


def classify(warnings) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """警告を (台本を直すべきもの, 環境の話) に分ける."""
    stale = tuple(w for w in warnings if w.get("kind") not in ENV_KINDS)
    ignored = tuple(w for w in warnings if w.get("kind") in ENV_KINDS)
    return stale, ignored


def check_one(path: Path, record_fn=None) -> Result:
    """台本 1 本を読んで、渡されていれば撮る.

    **例外は Result に畳む** (1 本で掃きが止まらない)。`record_fn(plan, path)` は
    Recorded を返すもので、実際に Playwright を起動する部分は外から渡す
    (ここはウィンドウもブラウザも要らない)。`None` なら**読むだけ** —— 撮らずに
    分かる欠陥は撮っても同じなので、速いほうだけ回す道を残してある。
    """
    from .plan import PlanError, load

    path = Path(path)
    try:
        plan = load(path)
    except (PlanError, OSError, ValueError) as exc:
        # PlanError は先頭にフルパスが付く。行にパスは出ているので落とす
        return Result(path, BROKEN, str(exc).removeprefix(f"{path}: "))

    # 撮る前に分かるものは、撮るときにも見る (通した数が多いほうが厳しい、
    # を保つ。--dry で赤だったものが本番で緑になったら検査の意味が無い)
    found = inspect(path, plan)

    if record_fn is None:
        detail = f"直すところ {len(found)} 件" if found else "読めました"
        return Result(path, STALE if found else OK, detail, found)

    # **支援収録は撮り直せない。** 素材は人が撮ったもので、生成物なので
    # clone した機械には無い。並べ直しても「まだアプリに当たっているか」は
    # 分からないので、**通ったことにしない** (docs/ideas/desktop.md)。
    # 撮らずに分かる欠陥だけは同じように見る
    if plan.app.assisted:
        if found:
            return Result(path, STALE, f"直すところ {len(found)} 件", found)
        return Result(path, SKIP, "支援収録なので撮り直せません (この検査は効きません)")

    try:
        recorded = record_fn(plan, path)
    except Exception as exc:   # noqa: BLE001 — 落ちた理由そのものが結果
        return Result(path, BROKEN, f"収録が落ちました: {type(exc).__name__}: {exc}",
                      found)

    warned, ignored = classify(getattr(recorded, "warnings", []) or [])
    stale = found + warned
    seconds = getattr(recorded, "duration", None)
    if stale:
        detail = f"直すところ {len(stale)} 件"
    else:
        detail = "通りました"
    return Result(path, STALE if stale else OK, detail, stale, ignored, seconds)


@dataclass
class Report:
    """掃き終わったあとの数え上げ."""

    results: list[Result] = field(default_factory=list)

    @property
    def red(self) -> list[Result]:
        return [r for r in self.results if r.red]

    @property
    def ignored(self) -> int:
        return sum(len(r.ignored) for r in self.results)

    @property
    def skipped(self) -> list[Result]:
        return [r for r in self.results if r.state == SKIP]

    def summary(self) -> str:
        total = len(self.results)
        red = len(self.red)
        skipped = len(self.skipped)
        head = f"{total - red - skipped} / {total} 本が通りました"
        if red:
            head += f" (赤 {red} 本)"
        if skipped:
            # **検査できなかったものを「通った」に混ぜない。** 混ぜると
            # 「赤が無い = 全部当たっている」がまた嘘になる
            head += f"   ※ 支援収録 {skipped} 本は撮り直せないので検査していません"
        if self.ignored:
            # **黙って捨てない。** 無視した警告があることは必ず言う
            head += f"   ※ 環境の警告 {self.ignored} 件は赤に数えていません"
        return head
