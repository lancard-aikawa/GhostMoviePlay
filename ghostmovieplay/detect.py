"""プロジェクトを読んで収録対象を推測する.

`gmp config --init-project` と、撮る面の `収録対象を直す` から呼ばれる。
埋めるのは `app.start` / `app.url` / `app.ready` の 3 つで、**これが決まらないと
Pass1 は台本を書けない**（AI が「本物のアプリを指してくれ」と訊いて終わる）。

守っていること:

- **動かさない。** ファイルを読むだけで、`npm run dev` を起こしたりポートを
  叩いたりしない。設定を作る手順が副作用を持つと、GUI から気軽に押せない
- **なぜその値なのかを必ず添える** (`Guess.why`)。設定は 3 層あって由来を出す
  のが決まりなのに、推測だけ出所不明では同じ事故を招く。書き込むときは
  コメントとして残す
- **分からないものは黙って諦める。** それらしい既定を書くと「設定済みに見える嘘」
  になり、画面から直せない値がプロジェクトに焼き付く (CLAUDE.md)

推測なので当たらないことがある。**当たっているかは人が見て直せる**ことが前提で、
書き込み先は必ず `gmp.toml` (設定画面から編集できる層) にする。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# 起動スクリプトの名前。左から順に探す
SCRIPTS = ("dev", "start", "serve", "preview")

# ロックファイル -> そのパッケージマネージャでの走らせ方
RUNNERS = (
    ("bun.lockb", "bun run {script}"),
    ("bun.lock", "bun run {script}"),
    ("pnpm-lock.yaml", "pnpm {script}"),
    ("yarn.lock", "yarn {script}"),
    ("package-lock.json", "npm run {script}"),
)

# 依存から分かる既定ポート (スクリプトにもconfigにも書いていないとき)
FRAMEWORK_PORTS = (
    ("vite", 5173),
    ("astro", 4321),
    ("next", 3000),
    ("nuxt", 3000),
    ("react-scripts", 3000),
    ("@angular/cli", 4200),
    ("svelte-kit", 5173),
)

# index.html を探す場所 (よくある順)
HTML_HOMES = (".", "public", "src", "app", "site", "www", "static", "dist")

# アプリを差し込む先によく使われる id。**先頭の <div id> を無条件に採ると、
# ただの章立ての id を掴む** (実際に紹介ページの <div id="pass1"> を掴んだ)
MOUNT_IDS = ("app", "root", "__next", "__nuxt", "main", "container")


@dataclass(frozen=True)
class Guess:
    """推測した 1 項目. `why` は由来 (コメントとして残す)."""

    path: str           # 設定のキー (app.start など)
    value: str
    why: str


def probe(root: Path) -> list[Guess]:
    """プロジェクトを読んで、埋められるものだけ返す."""
    root = Path(root)
    package = _package_json(root)
    found: list[Guess] = []

    script, command, why = _start_command(root, package)
    if command:
        found.append(Guess("app.start", command, why))

    port, port_why = _port(root, package, script)
    if port:
        found.append(Guess("app.url", f"http://localhost:{port}/", port_why))

    selector, selector_why = _ready(root)
    if selector:
        found.append(Guess("app.ready", selector, selector_why))

    return found


# --- package.json -----------------------------------------------------
def _package_json(root: Path) -> dict:
    """package.json. 壊れていても JSON の配列でも落ちない (人が書くファイル)."""
    try:
        loaded = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _runner(root: Path) -> tuple[str, str]:
    """ロックファイルから走らせ方を決める. 無ければ npm."""
    for name, form in RUNNERS:
        if (root / name).exists():
            return form, f"{name} と "
    return "npm run {script}", ""


def _start_command(root: Path, package: dict) -> tuple[str, str, str]:
    """(スクリプト名, 起動コマンド, 由来)."""
    scripts = package.get("scripts") or {}
    name = next((s for s in SCRIPTS if s in scripts), "")
    if name:
        form, source = _runner(root)
        return name, form.format(script=name), f"{source}package.json の scripts.{name}"

    # package.json が無いプロジェクト。置いてある HTML を配るだけで撮れる
    # (このリポジトリの紹介動画がその形)
    home = _html_home(root)
    if home is not None:
        where = "." if home == root else home.relative_to(root).as_posix()
        return "", (f"python -m http.server 8765 --directory {where}"), f"{where}/index.html"
    return "", "", ""


# --- ポート -----------------------------------------------------------
def _port(root: Path, package: dict, script: str) -> tuple[int | None, str]:
    """起動スクリプト → 設定ファイル → .env → 依存の既定、の順に探す."""
    scripts = package.get("scripts") or {}
    if script and (hit := _port_in(scripts.get(script, ""))):
        return hit, f"package.json の scripts.{script} の指定"

    for name in ("vite.config.ts", "vite.config.js", "vite.config.mjs",
                 "svelte.config.js", "astro.config.mjs", "nuxt.config.ts"):
        path = root / name
        if path.exists() and (hit := _port_in(_read(path))):
            return hit, f"{name} の port"

    for name in (".env", ".env.local", ".env.development"):
        path = root / name
        if not path.exists():
            continue
        found = re.search(r"^\s*(?:VITE_)?PORT\s*=\s*(\d{2,5})\s*$", _read(path), re.M)
        if found:
            return int(found.group(1)), f"{name} の PORT"

    # Bun は設定ファイルを持たないことが多い。ソースの Bun.serve から拾う
    for source in _sources(root):
        text = _read(source)
        if "Bun.serve" in text and (hit := _port_in(text)):
            return hit, f"{source.relative_to(root).as_posix()} の Bun.serve"

    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    for name, port in FRAMEWORK_PORTS:
        if any(name in key for key in deps):
            return port, f"{name} の既定ポート"

    if not package and _html_home(root) is not None:
        return 8765, "簡易サーバで配る前提の既定"
    return None, ""


def _port_in(text: str) -> int | None:
    """`--port 5173` `-p 5173` `port: 5173` `port=5173` から数字を拾う."""
    found = re.search(r"(?:--port|(?<![\w-])-p)[= ]\s*(\d{2,5})", text)
    if not found:
        found = re.search(r"\bport\s*[:=]\s*(\d{2,5})", text)
    return int(found.group(1)) if found else None


def _sources(root: Path) -> list[Path]:
    """入口になりそうなソース (深追いしない)."""
    names = ("index.ts", "index.js", "server.ts", "server.js", "main.ts", "main.js",
             "app.ts", "app.js")
    out = []
    for where in (root, root / "src", root / "server"):
        out += [where / name for name in names if (where / name).is_file()]
    return out[:8]


# --- 準備完了のセレクタ -----------------------------------------------
def _html_home(root: Path) -> Path | None:
    for name in HTML_HOMES:
        if (root / name / "index.html").is_file():
            return root / name
    return None


def _ready(root: Path) -> tuple[str, str]:
    """index.html のマウント先を「これが見えたら準備完了」に使う.

    `<div id="app">` `<div id="root">` の類。中身が描かれるまで空なので、
    **見えた時点で描き終わっているとは限らない** —— あくまで出発点で、
    実際の収録で足りなければ人が具体的な要素に差し替える。
    """
    home = _html_home(root)
    if home is None:
        return "", ""
    text = _read(home / "index.html")
    where = (home / "index.html").relative_to(root).as_posix()

    ids = re.findall(r'<div[^>]*\sid=["\']([\w-]+)["\']', text)
    chosen = next((one for one in ids if one in MOUNT_IDS), "")
    if chosen:
        return f"#{chosen}", f'{where} の <div id="{chosen}">'
    found = re.search(r"<h1[^>]*>", text)
    if found:
        # 章立ての id を掴むくらいなら、確実に在る見出しを指す
        return "h1", f"{where} の <h1>"
    if ids:
        return f"#{ids[0]}", f'{where} の <div id="{ids[0]}">'
    return "", ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
