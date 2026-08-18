"""video.md (人間が書く指示ファイル) の読み込みと、Pass1 依頼文の生成.

video.md = フロントマター(何を撮るか) + 本文(自由な補足).
Pass1 は現状 Claude Code に依頼文を渡す運用。gmp plan がその依頼文を書き出す。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .plan import PLAN_VERSION

SCENES_BLOCK = """scenes:
  - id: fail
    goal: よくある失敗を実演する
  - id: why
    goal: 何が悪かったかを画面を指しながら説明する
  - id: good
    goal: 正解ルートでクリアしてみせる
---

## 補足

ここに自由に書く。狙う視聴者、触れてほしい仕様、避けてほしい表現など。
"""

# プロジェクトの既定 (gmp.toml) が無いときの雛形。1本目はここに全部書く。
TEMPLATE = """---
# 生成物は <出力ルート>/<project>/<このフォルダ名>/ に出る (gmp where で確認)
# 2本目を作る前に `gmp config --init-project <プロジェクトルート>` を実行すると、
# ここに書いた共通のもの (対象URL・声・口調) をプロジェクト側に移せる。
project: MyProject

app:
  # 収録対象。ローカルファイルなら file:///C:/... でも良い
  url: http://localhost:5173
  ready: "text=スタート"      # これが見えたら準備完了とみなす
  cwd: .                      # ソースを読ませたいプロジェクトフォルダ
  start: npm run dev          # 起動コマンド (自分で起動する場合は空でよい)

persona:
  voice: zundamon
  style: 落ち着いた解説口調。失敗は責めずに理由を淡々と説明する

video:
  size: [1280, 720]
  fps: 30
  lang: ja

""" + SCENES_BLOCK


# gmp.toml から継承できるもののうち、1本ごとに変えたくなるもの。
# 雛形では「いま継承している値」をコメントで見せる (何を上書きするのか
# 分からないまま書き足すと、プロジェクト側の設定を黙って殺す)。
OVERRIDABLE: tuple[str, ...] = (
    "app.url",
    "app.ready",
    "voice.speaker",
    "voice.style",
    "persona.style",
    "series.audience",
    "series.target_seconds",
)


def _inherited_block(resolved) -> str:
    """継承中の値を、コメントアウトした YAML として並べる."""
    lines: list[str] = []
    section = None
    for key in OVERRIDABLE:
        if not resolved.is_explicit(key):
            continue
        head, _, leaf = key.rpartition(".")
        if head != section:
            section = head
            lines.append(f"# {head}:")
        value = resolved.get(key)
        lines.append(f"#   {leaf}: {value}")

    if not lines:
        return (
            "# 上書きしたい項目だけ書く (何が継承されているかは gmp config で見る)\n"
            "# app:\n"
            "#   url: http://localhost:5173\n"
        )
    return (
        "# 下は gmp.toml から継承している値。**書かなくても効く。**\n"
        "# この1本だけ変えたいときだけ、コメントを外して書き換える。\n"
        + "\n".join(lines)
        + "\n"
    )


def template(resolved=None, project_file: Path | None = None) -> str:
    """video.md の雛形.

    プロジェクトの既定 (gmp.toml) がある場合、共通の項目を雛形に書き込むと
    **1本ぶんが常にプロジェクトを上書きしてしまう**。継承されるものは
    コメントにして、この1本ぶんの指示 (title と scenes) だけ残す。
    """
    if resolved is None or project_file is None:
        return TEMPLATE

    return f"""---
# この1本ぶんの指示。共通の既定は {project_file.name} にある:
#   {project_file}
# いま効いている値と由来: gmp config <このファイル>
title: 動画タイトル

{_inherited_block(resolved)}
{SCENES_BLOCK}"""


@dataclass
class Spec:
    project: str | None = None
    app: dict[str, Any] = field(default_factory=dict)
    persona: dict[str, Any] = field(default_factory=dict)
    video: dict[str, Any] = field(default_factory=dict)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    source: Path | None = None
    # フロントマター全体。settings が「この1本」の層として読む
    # (個別フィールドに割った後だと、どのキーが書かれていたか分からない)
    raw: dict[str, Any] = field(default_factory=dict)


def parse(path: str | Path) -> Spec:
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2]

    return Spec(
        project=meta.get("project"),
        app=meta.get("app") or {},
        persona=meta.get("persona") or {},
        video=meta.get("video") or {},
        scenes=meta.get("scenes") or [],
        notes=body.strip(),
        source=path,
        raw={k: v for k, v in meta.items() if k != "scenes"},
    )


PLAN_SCHEMA_DOC = """```jsonc
{
  "version": 1,
  "meta": { "title": "動画タイトル", "lang": "ja", "project": "プロジェクト名" },
  "app":   { "url": "...", "ready": "セレクタ(任意)" },
  "video": { "width": 1280, "height": 720, "fps": 30, "leader": 2.5, "trailer": 1.2 },
  "voice": { "engine": "voicevox", "speaker": "ずんだもん", "style": "ノーマル", "speed": 1.0 },
  "scenes": [
    {
      "id": "fail-greedy",
      "title": "よくある失敗",
      "beats": [
        {
          "say": "ナレーション原稿(音声用)",
          "subtitle": "字幕(省略時は say をそのまま使う)",
          "hold": 1.6,          // 操作後の最低保持秒。読み切れる長さにする
          "actions": [
            { "type": "click",     "selector": "#start" },
            { "type": "wait_for",  "selector": ".board", "state": "visible" },
            { "type": "highlight", "selector": "#tile-0", "duration": 1.2 },
            { "type": "type",      "selector": "#name", "text": "ghost" },
            { "type": "press",     "key": "Enter" },
            { "type": "scroll_to", "selector": "#result" },
            { "type": "sleep",     "seconds": 0.6 },
            { "type": "eval",      "expr": "window.scrollTo(0,0)" },
            { "type": "goto",      "url": "..." }
          ]
        }
      ]
    }
  ]
}
```"""

GUIDE = """## Pass1 で守ること

1. **先にソースを読む。** ルール・スコア計算・勝敗条件を把握してから演目を組む。
   何が「良い手」かを理解していない状態で書いた失敗例は、ただ下手なだけで教材にならない。
2. **失敗は狙って作る。** 「この項を無視すると詰む」という具体的な因果があるものを選ぶ。
3. **1ビート1メッセージ。** 字幕は {max_lines} 行・{max_chars} 文字/行 で収まる長さに。
   長い説明はビートを割る。
4. **hold は読み切れる長さに。** 目安は 字幕の文字数 / {reading_cps} 秒 + {pad} 秒。
   音声 (`gmp voice`) を付ける場合は音声の尺が優先されるので、hold は下限として効く。
5. **セレクタは実在を確認する。** Playwright MCP で実際に触り、開いた状態のDOMから取る。
   推測で書いたセレクタは収録時に必ず落ちる。
6. **解説ビートでは操作しない。** highlight と sleep だけ置いて、画面を止めて喋らせる。
7. **決定論性。** 乱数や時刻に依存する挙動があれば、seed 固定や eval での状態注入で潰す。
"""


def _plan_values(resolved, plan_dir: Path) -> dict[str, Any]:
    """plan.json にそのまま入れる確定値を、解決済みの設定から作る.

    **設定の解決はここで終わらせる。** これを渡さずに「gmp.toml を読んで」と
    頼むと、plan.json が設定ファイル無しでは再現できなくなり、record/render を
    決定論に保っている前提が崩れる (CLAUDE.md「設定は Pass1 で焼き切る」)。
    """
    meta = {
        key: resolved.get(key)
        for key in ("title", "lang", "project")
        if resolved.get(key)
    }
    app = resolved.section("app")
    # cwd は「それを書いたファイル」からの相対。plan.json の隣に置き直す
    cwd = resolved.rebase_path("app.cwd", plan_dir)
    if cwd:
        app["cwd"] = cwd

    values: dict[str, Any] = {"version": PLAN_VERSION, "meta": meta, "app": app}
    for section in ("video", "voice", "determinism"):
        block = resolved.section(section)
        if block:
            values[section] = block
    return values


def _brief(resolved) -> str:
    """何を撮るか (口調・視聴者・尺・避けること). plan.json には残らない."""
    speaker = resolved.get("voice.speaker") or "(指定なし)"
    style = resolved.get("voice.style")
    lines = [
        f"- 声: `{speaker}`" + (f" ({style})" if style else ""),
        f"- 口調: {resolved.get('persona.style') or '(指定なし)'}",
        f"- 狙う視聴者: {resolved.get('series.audience') or '(指定なし)'}",
        f"- 1本の目標尺: {resolved.get('series.target_seconds'):.0f} 秒程度",
    ]
    count = resolved.get("series.count")
    if count:
        lines.append(f"- シリーズ全体で {count} 本の予定 (この依頼はそのうちの 1 本)")
    topics = resolved.get("series.topics")
    if topics:
        lines.append("- 題材の候補: " + " / ".join(str(t) for t in topics))
    avoid = resolved.get("series.avoid")
    if avoid:
        lines.append("- **触れないこと**: " + " / ".join(str(a) for a in avoid))
    return "\n".join(lines)


def build_request(spec: Spec, resolved=None, plan_dir: str | Path | None = None) -> str:
    """Claude Code にそのまま渡せる Pass1 依頼文を組む.

    resolved は settings.resolve() の結果。省略時はここで読む (spec 単体で
    依頼文を作れるようにしておくため)。plan_dir は plan.json を置く場所で、
    app.cwd をそこからの相対に直すのに使う。
    """
    from . import settings

    source = Path(spec.source) if spec.source else Path.cwd() / "video.md"
    if resolved is None:
        resolved = settings.load(spec=source, video=spec.raw)
    plan_dir = Path(plan_dir) if plan_dir else source.parent

    scenes = spec.scenes or []
    scene_lines = "\n".join(
        f"{i + 1}. `{s.get('id', f'scene{i}')}` -- {s.get('goal', '')}"
        for i, s in enumerate(scenes)
    ) or "(指定なし: 題材と補足から適切に構成すること)"

    values = _plan_values(resolved, plan_dir)
    url = values["app"].get("url") or "(未設定: video.md か gmp.toml に app.url を書く)"

    return f"""# 依頼: 実演解説動画の plan.json を作る

あなたは GhostMoviePlay の Pass1 を担当します。対象アプリを理解し、
**実演の台本 (plan.json)** を書き出してください。動画の収録・書き出しは
このあと `gmp record` / `gmp render` が決定論的に行うので、あなたは
台本だけを完成させます。

## 対象

- URL: {url}
- プロジェクトフォルダ: `{values["app"].get("cwd", ".")}` (plan.json からの相対)

## 何を撮るか

{_brief(resolved)}

`say` はこの口調で書いてください。`subtitle` は口調を保ったまま短く整えます。

## 構成

{scene_lines}

## 出力仕様

`plan.json` を書き出してください。スキーマ:

{PLAN_SCHEMA_DOC}

### そのまま使う値

以下は設定 (config.toml / gmp.toml / video.md) から解決済みです。
**この内容をそのまま plan.json に写してください。** 値を勝手に変えたり
省いたりしないこと (収録と音声合成がこの値で回ります):

```json
{json.dumps(values, ensure_ascii=False, indent=2)}
```

{GUIDE.format(
    max_lines=resolved.get("subtitle.max_lines"),
    max_chars=resolved.get("subtitle.max_chars"),
    reading_cps=resolved.get("subtitle.reading_cps"),
    pad=resolved.get("subtitle.pad"),
)}
## 補足指示

{spec.notes or "(なし)"}

## 完了条件

`plan.json` を書いたら `gmp record plan.json` を実行し、収録が最後まで
通ることを確認してください。落ちたセレクタがあれば直して再実行します。
"""
