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
  # **収録対象。ここを埋めないと台本は書けない** (何を撮るのか決まらない)。
  # 見本のままにせず、実際の値に書き換えてコメントを外すこと。
  # url: http://localhost:5173   # ローカルファイルなら file:///C:/... でも良い
  # ready: "text=スタート"        # これが見えたら準備完了とみなす
  # start: npm run dev           # 起動コマンド (自分で起動するなら要らない)
  cwd: .                         # ソースを読ませたいプロジェクトフォルダ

persona:
  voice: zundamon
  style: 落ち着いた解説口調。失敗は責めずに理由を淡々と説明する

video:
  size: [1280, 720]
  fps: 30
  lang: ja

""" + SCENES_BLOCK


# `gmp init` の雛形が置く見本値。**ここを直さずに Pass1 を呼ぶと、AI は
# 「本物のアプリを指してくれ」と訊いてくる** —— `-p` (対話なし) には答える人が
# いないので、台本を書かずに終わる。呼ぶ前に気づけるように 1 か所に持つ。
# TEMPLATE と同じ値を書くこと (tests/test_request.py が突き合わせている)。
TEMPLATE_HINTS: dict[str, tuple[str, str]] = {
    "app.url": ("http://localhost:5173", "収録する URL"),
    "app.start": ("npm run dev", "起動コマンド"),
    "app.ready": ("text=スタート", "準備完了のセレクタ"),
}


def unfilled(resolved) -> list[str]:
    """雛形の見本値のままの項目 (画面に出す見出し).

    `app.cwd = '.'` は入れない —— 本当にそこを指すことがある。
    1 つだけなら偶然もある (Vite の既定は本当に 5173) ので、**2 つ以上
    そろって初めて**「雛形のまま」と言う。呼ぶ側で数を見る。
    """
    return [
        label for path, (sample, label) in TEMPLATE_HINTS.items()
        if resolved.get(path) == sample
    ]


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
        "# この動画だけ変えたいときだけ、コメントを外して書き換える。\n"
        + "\n".join(lines)
        + "\n"
    )


def template(resolved=None, project_file: Path | None = None) -> str:
    """video.md の雛形.

    プロジェクトの既定 (gmp.toml) がある場合、共通の項目を雛形に書き込むと
    **この動画が常にプロジェクトを上書きしてしまう**。継承されるものは
    コメントにして、この動画の指示 (title と scenes) だけ残す。
    """
    if resolved is None or project_file is None:
        return TEMPLATE

    return f"""---
# この動画の指示。共通の既定は {project_file.name} にある:
#   {project_file}
# いま効いている値と由来: gmp config <このファイル>
title: 動画タイトル

{_inherited_block(resolved)}
{SCENES_BLOCK}"""


def split_front(text: str) -> tuple[str, str]:
    """(フロントマター, 本文). フロントマターが無ければ ("", 全部)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return "", text
    return "".join(lines[1:end]), "".join(lines[end + 1:])


def rebuild_text(text: str, resolved=None, project_file: Path | None = None,
                 without_video=None) -> tuple[str, list[str]]:
    """構成を雛形から作り直す. 戻り値は (新しい中身, 落とした上書き).

    **人が書いたものは必ず残す** —— `title` と `scenes` と本文の散文。
    落とすのは**他の層と同じ値になっている上書き**だけで、それは書き写された
    共通の値。残っていると「この動画が常にプロジェクトを上書きし続ける」
    (CLAUDE.md) ので、雛形もわざと書き写さないようにしてある。

    `gmp init --force` と違って**上書き保存はしない**。呼び出し側 (エディタ) が
    中身として見せ、人が見てから保存する。
    """
    import yaml

    from . import settings

    front, body = split_front(text)
    try:
        data = yaml.safe_load(front) if front.strip() else {}
    except yaml.YAMLError:
        data = {}       # 壊れていても作り直せること (直したくて押すのだから)
    if not isinstance(data, dict):
        data = {}

    title = data.get("title") or "動画タイトル"
    scenes = data.get("scenes")
    rest = {k: v for k, v in data.items() if k not in ("title", "scenes")}

    dropped: list[str] = []
    if without_video is not None:
        for path, value in settings.normalize(rest).items():
            setting = settings.SETTINGS.get(path)
            if setting is None or setting.kind == "path":
                # **相対パスは層をまたいで比べられない。** `app.cwd = '.'` は
                # video.md では動画のフォルダ、gmp.toml ではプロジェクトルート
                # で、文字列が同じでも別の場所を指す (CLAUDE.md)。同じに見えた
                # からと落とすと、黙って収録対象がずれる
                continue
            if without_video.get(path) == value:
                dropped.append(path)
        rest = _prune(rest, dropped)

    head = ["---"]
    if project_file is not None:
        head += [f"# この動画の指示。共通の既定は {project_file.name} にある:",
                 f"#   {project_file}"]
    head.append("# いま効いている値と由来: gmp config <このファイル>")
    head.append(f"title: {title}")
    head.append("")
    if resolved is not None and project_file is not None:
        head.append(_inherited_block(resolved).rstrip("\n"))
        head.append("")
    if rest:
        head.append("# この動画だけの上書き")
        head.append(yaml.safe_dump(rest, allow_unicode=True,
                                   sort_keys=False, default_flow_style=False).rstrip("\n"))
        head.append("")
    if scenes:
        head.append(yaml.safe_dump({"scenes": scenes}, allow_unicode=True,
                                   sort_keys=False, default_flow_style=False).rstrip("\n"))
    else:
        head.append(SCENES_BLOCK.split("---")[0].rstrip("\n"))
    head.append("---")

    tail = body if body.strip() else "\n## 補足\n\nここに自由に書く。\n"
    return "\n".join(head) + "\n" + tail, dropped


def _prune(raw: dict, paths: list[str]) -> dict:
    """ドット区切りのキーを nested dict から落とす. 空になった枝も落とす."""
    import copy

    out = copy.deepcopy(raw)
    for dotted in paths:
        *head, leaf = dotted.split(".")
        node = out
        chain = [out]
        for part in head:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
            chain.append(node)
        if isinstance(node, dict):
            node.pop(leaf, None)
        for parent, key in zip(reversed(chain[:-1]), reversed(head)):
            if isinstance(parent.get(key), dict) and not parent[key]:
                parent.pop(key)
    return out


@dataclass
class Spec:
    """video.md の中身.

    フロントマターは **raw のまま持つ**。project / app / persona のように
    項目ごとへ割っていたが、値の解決は settings に移ったので割る意味が無くなった
    (どのキーが書かれていたかも raw でないと分からない)。ここに残すのは、
    設定にできないもの —— シーン構成と自由記述だけ。
    """

    scenes: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    source: Path | None = None
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
        scenes=meta.get("scenes") or [],
        notes=body.strip(),
        source=path,
        raw={k: v for k, v in meta.items() if k != "scenes"},
    )


PLAN_SCHEMA_DOC = """```jsonc
{
  "version": 1,
  "meta": { "title": "動画タイトル", "lang": "ja", "project": "プロジェクト名" },
  // app は「そのまま使う値」に解決済みのものが来る。勝手に足さない
  //   start=開発サーバの起動コマンド / setup=収録前に走らせる仕込み
  //   teardown=収録後の後片付け (仕込みは start より前に走る)
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
            { "type": "click",       "selector": "#start" },
            { "type": "dblclick",    "selector": "#row-3" },
            { "type": "hover",       "selector": "#menu" },
            { "type": "wait_for",    "selector": ".board", "state": "visible" },
            { "type": "highlight",   "selector": "#tile-0", "duration": 1.2 },
            { "type": "type",        "selector": "#name", "text": "ghost" },
            { "type": "press",       "key": "Enter" },
            { "type": "select",      "selector": "#plan", "value": "pro" },
            { "type": "select_text", "text": "なぞりたい文字列" },
            { "type": "scroll_to",   "selector": "#result" },
            { "type": "sleep",       "seconds": 0.6 },
            { "type": "eval",        "expr": "window.scrollTo(0,0)" },
            { "type": "goto",        "url": "..." }
          ]
        }
      ]
    }
  ]
}
```"""

# 支援収録のときだけ足す説明。**PLAN_SCHEMA_DOC を汚さない** ——
# 自動収録の依頼文に `shot` を見せると、AI が撮ってもいないショットのパスを書く
ASSIST_SCHEMA_NOTE = """### この 1 本は「支援収録」です

自動操作が届かない相手なので、**画面は人が操作して撮ります。**

- **`actions` を書かないでください。** 操作するのは人で、あなたが書いた操作は
  誰も実行しません。書くと「実行されるつもりの手順」が台本に残って嘘になります
- **代わりに `do` を必ず書いてください。** これは**撮る人への指示**で、動画には
  一切出ません。`say` が観る人への言葉なのに対して、`do` は手を動かす人への
  「やること」です。**ここが空だと、画面を開いた人は何をすればいいのか
  分かりません**（シーンの意味は読めても、次の一手が読めない）

  ```jsonc
  {
    "do":  "gmp-sample.zip をダブルクリックして開く",   // 撮る人へ
    "say": "ところが、開くとパスワードを訊かれません"     // 観る人へ
  }
  ```

  1 ビート 1 操作。**具体的に書く** ——「設定を変える」ではなく
  「アーカイブ形式を 7z に変える」。操作の要らない解説ビートは
  「そのまま（画面を動かさない）」のように、**動かさないことを書く**
- **そのビートを撮る直前の状態から書いてください。** 前のビートの続きだと
  思って省くと、**入力が消えていることに気づけません** —— ダイアログを開き
  直すと打ったものは残らないのに、「チェックを入れる」とだけ書いてあると
  パスワードの入れ直しが抜ける (実際に抜けた。しかも 7-Zip はパスワードが
  空でもチェックを押させるので、暗号化されない書庫が黙って出来る)
- **どこにあるかまで書いてください。** 「追加を押す」ではなく
  「ツールバー左端の緑の『追加』を押す」。撮る人はそのアプリに詳しいとは
  限らず、**奥まったところにある操作は探しているうちに別の道を通ってしまう**
  (7-Zip の圧縮は File Manager のメニューには無く、ツールバーにしかない ——
  そう書かなかったせいで、エクスプローラーの「ファイル > 7-Zip > 圧縮」を
  探させてしまった)
- **`shot` を書かないでください。** ショットのパスは `gmp shoot` の画面が入れます
- **1 ビート = ショット 1 つ + コメント 1 つ。** 画面 1 枚につき言うことを 1 つに
  します。言うことが 2 つあるならビートを 2 つに割ってください
  (同じ画像を 2 つのビートが指してもかまいません)
- **`hold` は下限としてだけ効きます。** ビートの尺は「音声」「ショットの尺」
  「hold」のいちばん長いものになります

あなたの仕事は**シーンとビートの並びを決めて、`do` と `say` を書くこと**です。
人はその並びを上から順に読み、`do` のとおりに操作して、ビートごとに画面を撮ります。
**`do` を書けるだけ対象を理解してから書いてください** —— 分からないまま
それらしい指示を置くと、撮る人がその場で詰まります。
"""

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

    # **支援収録は依頼文の中身が変わる。** 操作するのが人なので、セレクタも
    # actions も要らず、代わりに「並びを決めて say を書く」が仕事になる
    window = values["app"].get("window")
    package = values["app"].get("package")
    if window or package:
        target = (f"- 撮るウィンドウ: `{window}` (人がこのウィンドウを操作します)"
                  if window else
                  f"- 撮る Android アプリ: `{package}` (人が端末を操作します)")
        extra = "\n" + ASSIST_SCHEMA_NOTE
        done = ("シーンとビートの並びを決めて `say` を書いたら、そこで完了です。\n"
                "このあと人が `gmp shoot` の画面でビートごとに画面を撮り、\n"
                "`gmp record` がショットと音声を並べて 1 本にします。")
    else:
        target = f"- URL: {url}"
        extra = ""
        done = ("`plan.json` を書いたら `gmp record plan.json` を実行し、収録が最後まで\n"
                "通ることを確認してください。落ちたセレクタがあれば直して再実行します。")

    return f"""# 依頼: 実演解説動画の plan.json を作る

あなたは GhostMoviePlay の Pass1 を担当します。対象アプリを理解し、
**実演の台本 (plan.json)** を書き出してください。動画の収録・書き出しは
このあと `gmp record` / `gmp render` が決定論的に行うので、あなたは
台本だけを完成させます。

## 対象

{target}
- プロジェクトフォルダ: `{values["app"].get("cwd", ".")}` (plan.json からの相対)

## 何を撮るか

{_brief(resolved)}

`say` はこの口調で書いてください。`subtitle` は口調を保ったまま短く整えます。

## 構成

{scene_lines}

## 出力仕様

`plan.json` を書き出してください。スキーマ:

{PLAN_SCHEMA_DOC}
{extra}
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

{done}
"""
