"""使い捨ての試し場を組み立てる (`gmp demo`).

**目で見て確かめる場所。** テストが緑でも、画面が期待どおりに出ているかは
人が見るしかない。かといって `docs/video/intro` で試すと、紹介動画の素材に
差分が出る（台本をエディタで保存したら本物が変わる）し、100 秒の収録を
待つことになる。だから**捨てられる場所に、10 秒の 1 本を作る**。

組み立ては[使い方](../README.md)の手順そのままで、コマンドも同じものを叩く
（`gmp config --init-project` → `gmp init` → `gmp record` → `gmp render`）。
手順が腐ればここで落ちる。

**Pass1 だけは代わりに書く。** 台本づくりは AI の段なので、試し撮りのたびに
claude を焼くわけにいかない。ここが手順書と違う唯一の場所。
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

PROJECT = "gmp-demo"
VIDEO_DIR = Path("docs") / "video" / "try"

# 収録対象。**依存も外部リソースも無い 1 枚**にしてある (捨てられる場所に
# 置くので、npm も要らないほうがよい)
PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>試し撮り</title>
<style>
  body { margin: 0; background: #0d1117; color: #e6edf3;
         font-family: "Yu Gothic UI", sans-serif; display: flex;
         min-height: 100vh; align-items: center; justify-content: center; }
  main { text-align: center; }
  h1 { font-size: 30px; font-weight: 600; margin: 0 0 28px; letter-spacing: .04em; }
  #tiles { display: flex; gap: 14px; justify-content: center; }
  .tile { width: 82px; height: 82px; border: 2px solid #30363d; border-radius: 10px;
          background: #161b22; color: #e6edf3; font-size: 26px; cursor: pointer; }
  .tile.taken { background: #1f6f3f; border-color: #2ea043; }
  #score { margin-top: 26px; font-size: 22px; }
  #score b { color: #ffd400; font-size: 28px; }
  #note { margin-top: 10px; height: 24px; color: #8b949e; }
</style>
</head>
<body>
<main id="app">
  <h1 id="title">試し撮り用のページ</h1>
  <div id="tiles">
    <button class="tile" id="tile-3">3</button>
    <button class="tile" id="tile-7">7</button>
    <button class="tile" id="tile-5">5</button>
  </div>
  <div id="score">合計 <b id="total">0</b></div>
  <div id="note"></div>
</main>
<script>
  let total = 0;
  for (const tile of document.querySelectorAll('.tile')) {
    tile.addEventListener('click', () => {
      if (tile.classList.contains('taken')) return;
      tile.classList.add('taken');
      total += Number(tile.textContent);
      document.getElementById('total').textContent = total;
      document.getElementById('note').textContent = '取りました';
    });
  }
</script>
</body>
</html>
"""

SPEC = """---
title: 試し撮り
scenes:
  - id: intro
    goal: 何のページかを見せる
  - id: pick
    goal: タイルを取ると合計が増えることを見せる
---

## 補足

`gmp demo` が組み立てた**使い捨ての 1 本**。ここを直しても誰も困らないので、
画面の手触りを確かめるのに使う。台本 (plan.json) は Pass1 の代わりに
`ghostmovieplay/demo.py` が書いている。
"""


def free_port() -> int:
    """空いているポートを 1 つ. 試し場は何度も作り直すので固定値にしない."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def plan_for(url: str, start: str) -> dict[str, Any]:
    """Pass1 の代わりに書く台本. **10 秒ほどで終わる長さにする.**

    静止画で見分けが付くよう、ビートごとに画が変わるようにしてある
    (台本エディタのサムネイルが全部同じだと、確かめたことにならない)。
    """
    return {
        "version": 1,
        "meta": {"title": "試し撮り", "lang": "ja", "project": PROJECT},
        "app": {"url": url, "ready": "#title", "start": start, "cwd": "../../.."},
        "video": {"width": 960, "height": 540, "fps": 30, "leader": 2.5, "trailer": 1.0},
        "scenes": [
            {
                "id": "intro",
                "title": "何のページか",
                "beats": [
                    {"say": "試し撮り用のページです。数字のタイルが3つあります。",
                     "hold": 2.0,
                     "actions": [{"type": "highlight", "selector": "#tiles",
                                  "duration": 1.4}]},
                ],
            },
            {
                "id": "pick",
                "title": "取ってみる",
                "beats": [
                    {"say": "7を取ると、合計が7になります。", "hold": 1.6,
                     "actions": [{"type": "click", "selector": "#tile-7"}]},
                    {"say": "3も取れば、合計は10。", "hold": 1.6,
                     "actions": [{"type": "click", "selector": "#tile-3"}]},
                    {"say": "合計はここに出ます。", "hold": 1.8,
                     "actions": [{"type": "highlight", "selector": "#score",
                                  "duration": 1.4}]},
                ],
            },
        ],
    }


def build(root: str | Path, port: int | None = None, verbose: bool = True) -> Path:
    """試し場を組み立てて、構成 (video.md) のパスを返す.

    既にあるものは上書きする —— **毎回同じ初期状態から始められる**のが
    試し場の値打ちなので、前回いじった台本が残っていては困る。
    """
    from . import settings

    root = Path(root)
    (root / VIDEO_DIR).mkdir(parents=True, exist_ok=True)
    port = port or free_port()
    url = f"http://127.0.0.1:{port}/"
    start = f"python -m http.server {port} --directory ."

    say = print if verbose else (lambda *a, **k: None)

    # 1. 収録対象 (プロジェクトのソースにあたるもの)
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    say(f"  収録対象   {root / 'index.html'}")

    # 2. gmp config --init-project —— 収録対象は detect が読んで埋める。
    #    ポートだけは空きを取り直すので、変えた行だけ当てる
    project_file = settings.init_project(root, project=PROJECT, force=True)
    project_file.write_text(
        settings.patch_toml(project_file.read_text(encoding="utf-8"),
                            {"app.url": url, "app.start": start}),
        encoding="utf-8",
    )
    say(f"  設定       {project_file}")

    # 3. gmp init —— 構成の雛形を置いて、人が書く分を代わりに書く
    spec = root / VIDEO_DIR / "video.md"
    spec.write_text(SPEC, encoding="utf-8")
    say(f"  構成       {spec}")

    # 4. Pass1 の代わり。**ここだけ手順書と違う** (AI を焼かない)
    import json

    plan = spec.parent / "plan.json"
    plan.write_text(json.dumps(plan_for(url, start), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    say(f"  台本       {plan}   ← Pass1 の代わりに demo.py が書いた")
    return spec
