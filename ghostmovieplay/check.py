"""全部の台本を撮り直して、まだアプリに当たっているかを見る.

`gmp record` は要するに**ナレーション付きの Playwright スクリプト**なので、
落ちたということは UI が変わったということ。動画のためだけに置いてある
plan.json を CI で回せば、*説明が古くなったら自動で分かる*仕組みになる
(render も AI も要らない)。

**新しい判定は増やさない。** 止めない失敗はすでに Recorder.warn() が
timing.json に残しているので、ここがやるのは**束ねること**だけ ——
プロジェクトの下の plan.json を全部見つけ、1 本ずつ撮って、赤を数える。

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

# **印は ASCII で置く。** Windows の既定コンソールは cp932 で、`✓` は
# `?` に化ける (`_lenient_output` が落ちない代わりに潰す)。飾りが化けるのは
# 我慢できるが、化けるのが**判定そのもの**だと読めない
MARK = {OK: "ok", STALE: "!", BROKEN: "NG"}


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
        return self.state != OK


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


def classify(warnings) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """警告を (台本を直すべきもの, 環境の話) に分ける."""
    stale = tuple(w for w in warnings if w.get("kind") not in ENV_KINDS)
    ignored = tuple(w for w in warnings if w.get("kind") in ENV_KINDS)
    return stale, ignored


def check_one(path: Path, record_fn) -> Result:
    """台本 1 本を読んで撮る. **例外は Result に畳む** (1 本で掃きが止まらない).

    `record_fn(plan, path)` は Recorded を返すもの。実際に Playwright を
    起動する部分を外から渡すので、ここはウィンドウもブラウザも要らない。
    """
    from .plan import PlanError, load

    path = Path(path)
    try:
        plan = load(path)
    except (PlanError, OSError, ValueError) as exc:
        # PlanError は先頭にフルパスが付く。行にパスは出ているので落とす
        return Result(path, BROKEN, str(exc).removeprefix(f"{path}: "))

    try:
        recorded = record_fn(plan, path)
    except Exception as exc:   # noqa: BLE001 — 落ちた理由そのものが結果
        return Result(path, BROKEN, f"収録が落ちました: {type(exc).__name__}: {exc}")

    stale, ignored = classify(getattr(recorded, "warnings", []) or [])
    seconds = getattr(recorded, "duration", None)
    if stale:
        detail = f"警告 {len(stale)} 件 (台本を直す)"
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

    def summary(self) -> str:
        total = len(self.results)
        red = len(self.red)
        head = f"{total - red} / {total} 本が通りました"
        if red:
            head += f" (赤 {red} 本)"
        if self.ignored:
            # **黙って捨てない。** 無視した警告があることは必ず言う
            head += f"   ※ 環境の警告 {self.ignored} 件は赤に数えていません"
        return head
