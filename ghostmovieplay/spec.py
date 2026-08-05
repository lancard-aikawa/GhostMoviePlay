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

TEMPLATE = """---
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

scenes:
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


@dataclass
class Spec:
    app: dict[str, Any] = field(default_factory=dict)
    persona: dict[str, Any] = field(default_factory=dict)
    video: dict[str, Any] = field(default_factory=dict)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    source: Path | None = None


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
        app=meta.get("app") or {},
        persona=meta.get("persona") or {},
        video=meta.get("video") or {},
        scenes=meta.get("scenes") or [],
        notes=body.strip(),
        source=path,
    )


PLAN_SCHEMA_DOC = """```jsonc
{
  "version": 1,
  "meta": { "title": "動画タイトル", "lang": "ja" },
  "app":   { "url": "...", "ready": "セレクタ(任意)" },
  "video": { "width": 1280, "height": 720, "fps": 30, "leader": 2.5, "trailer": 1.5 },
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
3. **1ビート1メッセージ。** 字幕は 2 行・26 文字/行 で収まる長さに。長い説明はビートを割る。
4. **hold は読み切れる長さに。** 目安は 字幕の文字数 / 8 秒 + 0.6 秒。
   音声 (`gmp voice`) を付ける場合は音声の尺が優先されるので、hold は下限として効く。
5. **セレクタは実在を確認する。** Playwright MCP で実際に触り、開いた状態のDOMから取る。
   推測で書いたセレクタは収録時に必ず落ちる。
6. **解説ビートでは操作しない。** highlight と sleep だけ置いて、画面を止めて喋らせる。
7. **決定論性。** 乱数や時刻に依存する挙動があれば、seed 固定や eval での状態注入で潰す。
"""


def build_request(spec: Spec) -> str:
    """Claude Code にそのまま渡せる Pass1 依頼文を組む."""
    persona = spec.persona or {}
    scenes = spec.scenes or []
    scene_lines = "\n".join(
        f"{i + 1}. `{s.get('id', f'scene{i}')}` — {s.get('goal', '')}"
        for i, s in enumerate(scenes)
    ) or "(指定なし: 内容から適切に構成すること)"

    app_json = json.dumps(spec.app, ensure_ascii=False, indent=2)
    video_json = json.dumps(spec.video, ensure_ascii=False, indent=2)

    return f"""# 依頼: 実演解説動画の plan.json を作る

あなたは GhostMoviePlay の Pass1 を担当します。対象アプリを理解し、
**実演の台本 (plan.json)** を書き出してください。動画の収録・書き出しは
このあと `gmp record` / `gmp render` が決定論的に行うので、あなたは
台本だけを完成させます。

## 対象

```json
{app_json}
```

プロジェクトフォルダ: `{spec.app.get('cwd', '.')}`

## 口調

- voice: `{persona.get('voice', '(指定なし)')}`
- style: {persona.get('style', '(指定なし)')}

`say` はこの口調で書いてください。`subtitle` は口調を保ったまま短く整えます。
plan.json の `voice.speaker` にはこの voice をそのまま入れてください
(`gmp voice` が VOICEVOX の話者名として解決します)。

## 構成

{scene_lines}

## 出力仕様

`plan.json` を書き出してください。スキーマ:

{PLAN_SCHEMA_DOC}

video の既定値:

```json
{video_json}
```

{GUIDE}

## 補足指示

{spec.notes or "(なし)"}

## 完了条件

`plan.json` を書いたら `gmp record plan.json` を実行し、収録が最後まで
通ることを確認してください。落ちたセレクタがあれば直して再実行します。
"""
