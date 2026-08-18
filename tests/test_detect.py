"""収録対象の推測.

ここが空だと Pass1 は台本を書けない (AI が「本物のアプリを指してくれ」と訊いて
終わる)。**動かさずに読むだけ**で、埋められるものだけ埋める。
"""

import json

import pytest

from ghostmovieplay import settings
from ghostmovieplay.detect import probe


def make(root, files: dict) -> object:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def found(root) -> dict:
    return {g.path: g.value for g in probe(root)}


def why(root, path) -> str:
    return next(g.why for g in probe(root) if g.path == path)


# --- 起動コマンド -----------------------------------------------------
def test_the_package_manager_comes_from_the_lockfile(tmp_path):
    """`npm run dev` と決め打つと、bun のプロジェクトで動かない."""
    for lock, expected in (("bun.lockb", "bun run dev"),
                           ("pnpm-lock.yaml", "pnpm dev"),
                           ("yarn.lock", "yarn dev"),
                           ("package-lock.json", "npm run dev")):
        root = tmp_path / lock
        make(root, {"package.json": json.dumps({"scripts": {"dev": "vite"}}), lock: ""})
        assert found(root)["app.start"] == expected


def test_scripts_are_tried_in_order(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"scripts": {"serve": "x", "start": "y"}})})
    assert found(tmp_path)["app.start"] == "npm run start"


def test_a_static_site_is_served_by_a_throwaway_server(tmp_path):
    """静的なページでも `file://` を焼かない (CLAUDE.md).

    plan.json に絶対パスが入ると、clone した人の手元で落ちる。
    """
    make(tmp_path, {"site/index.html": "<h1>x</h1>"})
    assert found(tmp_path)["app.start"] == "python -m http.server 8765 --directory site"
    assert found(tmp_path)["app.url"].startswith("http://")


# --- ポート -----------------------------------------------------------
def test_an_explicit_port_in_the_script_wins(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"dev": "bun run src/index.ts --port 7474"},
                                    "devDependencies": {"vite": "^5"}}),
    })
    assert found(tmp_path)["app.url"] == "http://localhost:7474/"
    assert "scripts.dev" in why(tmp_path, "app.url")


def test_the_config_file_beats_the_framework_default(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"dev": "vite"},
                                    "devDependencies": {"vite": "^5"}}),
        "vite.config.ts": "export default { server: { port: 4000 } }",
    })
    assert found(tmp_path)["app.url"] == "http://localhost:4000/"


def test_dotenv_is_read(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"serve": "node server.js"}}),
        ".env": "NODE_ENV=development\nPORT=8080\n",
    })
    assert found(tmp_path)["app.url"] == "http://localhost:8080/"


def test_bun_serve_in_the_source_is_read(tmp_path):
    """Bun は設定ファイルを持たないことが多い."""
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"start": "bun src/server.ts"}}),
        "bun.lock": "",
        "src/server.ts": "Bun.serve({ port: 7474, fetch() {} })",
    })
    assert found(tmp_path)["app.url"] == "http://localhost:7474/"
    assert "Bun.serve" in why(tmp_path, "app.url")


def test_the_framework_default_is_the_last_resort(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"dev": "next dev"},
                                    "dependencies": {"next": "14"}}),
    })
    assert found(tmp_path)["app.url"] == "http://localhost:3000/"
    assert "既定" in why(tmp_path, "app.url")


# --- 準備完了のセレクタ -----------------------------------------------
def test_the_mount_point_is_preferred_over_the_first_div(tmp_path):
    """**先頭の <div id> を無条件に採ると章立ての id を掴む** (実際に掴んだ)."""
    make(tmp_path, {
        "index.html": '<div id="pass1">章</div><div id="app"></div>',
    })
    assert found(tmp_path)["app.ready"] == "#app"


def test_a_page_without_a_mount_point_falls_back_to_the_heading(tmp_path):
    make(tmp_path, {"site/index.html": '<div id="intro">章</div><h1>タイトル</h1>'})
    assert found(tmp_path)["app.ready"] == "h1"


# --- 分からないとき ---------------------------------------------------
def test_nothing_is_invented(tmp_path):
    """**それらしい既定を書かない。** 「設定済みに見える嘘」が一番困る."""
    make(tmp_path, {"README.md": "何も無い"})
    assert probe(tmp_path) == []


def test_every_guess_says_where_it_came_from(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"dev": "vite --port 3333"},
                                    "devDependencies": {"vite": "^5"}}),
        "bun.lockb": "",
        "index.html": '<div id="root"></div>',
    })
    for guess in probe(tmp_path):
        assert guess.why, f"{guess.path} の由来が空"


# --- gmp.toml に流し込むところ ----------------------------------------
def test_init_project_fills_in_what_it_found(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"scripts": {"dev": "vite --port 3333"}}),
        "bun.lockb": "",
        "index.html": '<div id="root"></div>',
    })
    written = settings.init_project(tmp_path)
    text = written.read_text(encoding="utf-8")

    resolved = settings.load(spec=tmp_path)
    assert resolved.get("app.start") == "bun run dev"
    assert resolved.get("app.url") == "http://localhost:3333/"
    assert resolved.get("app.ready") == "#root"
    # **由来がコメントで残る** (推測なので、なぜその値かが要る)
    assert "scripts.dev" in text and "bun.lockb" in text


def test_init_project_keeps_the_sample_when_it_finds_nothing(tmp_path):
    make(tmp_path, {"README.md": "何も無い"})
    written = settings.init_project(tmp_path)
    text = written.read_text(encoding="utf-8")

    assert "# url = 'http://localhost:5173'" in text     # 見本はコメントのまま
    assert settings.load(spec=tmp_path).get("app.url") in (None, "")


def test_detection_can_be_turned_off(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"scripts": {"dev": "vite"}})})
    written = settings.init_project(tmp_path, detect=False)
    assert "# start =" in written.read_text(encoding="utf-8")


@pytest.mark.parametrize("broken", ["{壊れた", "", "[]"])
def test_a_broken_package_json_does_not_crash(tmp_path, broken):
    make(tmp_path, {"package.json": broken})
    probe(tmp_path)      # 例外を投げないこと
