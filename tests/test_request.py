"""Pass1 の依頼文 (PLAN_REQUEST.md) が設定を焼き込めているか.

ここが効いていないと、gmp.toml に書いた声も読みも題材も無視される。
"""

import json
import re

import pytest

from ghostmovieplay import paths, settings
from ghostmovieplay.cli import main
from ghostmovieplay.spec import build_request, parse


@pytest.fixture
def project(tmp_path):
    """gmp.toml を持つプロジェクトに video.md を 1 本置く."""
    root = tmp_path / "repo"
    video_dir = root / "docs" / "video" / "intro"
    video_dir.mkdir(parents=True)
    (root / settings.PROJECT_FILE).write_text(
        "project = 'MyApp'\n"
        "[app]\n"
        "url = 'http://localhost:5173'\n"
        "start = 'npm run dev'\n"
        "cwd = '.'\n"
        "[voice]\n"
        "speaker = 'ずんだもん'\n"
        "style = 'ノーマル'\n"
        "[voice.dict]\n"
        "'語' = 'ゴ'\n"        # TOML の裸のキーは ASCII だけ
        "[persona]\n"
        "style = '淡々と説明する'\n"
        "[series]\n"
        "audience = '初心者'\n"
        "topics = ['基本操作', '設定']\n"
        "count = 2\n"
        "avoid = ['課金画面']\n"
        "[subtitle]\n"
        "max_chars = 20\n"
        "[determinism]\n"
        "seed = 42\n",
        encoding="utf-8",
    )
    (video_dir / "video.md").write_text(
        "---\ntitle: はじめての操作\n---\n\n本文の補足\n", encoding="utf-8"
    )
    return video_dir / "video.md"


def _values(text: str) -> dict:
    """依頼文の「そのまま使う値」ブロックを取り出す."""
    block = re.search(r"### そのまま使う値.*?```json\n(.*?)\n```", text, re.S)
    assert block, "確定値のブロックが依頼文に無い"
    return json.loads(block.group(1))


# --- 設定が依頼文に載るか ---------------------------------------------
def test_project_settings_land_in_the_plan_values(project):
    values = _values(build_request(parse(project)))

    assert values["meta"] == {"title": "はじめての操作", "lang": "ja", "project": "MyApp"}
    assert values["app"]["url"] == "http://localhost:5173"
    assert values["app"]["start"] == "npm run dev"
    assert values["voice"]["speaker"] == "ずんだもん"
    assert values["determinism"]["seed"] == 42
    assert values["version"] == 1


def test_reading_dictionary_is_baked_in(project):
    """読みはプロジェクトに置く. 依頼文に載らないと plan.json に入らない."""
    assert _values(build_request(parse(project)))["voice"]["dict"] == {"語": "ゴ"}


def test_empty_sections_are_omitted(tmp_path):
    """空の dict を書くと plan.json が無駄に汚れる."""
    (tmp_path / "video.md").write_text("---\napp:\n  url: http://x\n---\n", encoding="utf-8")
    values = _values(build_request(parse(tmp_path / "video.md")))
    assert "dict" not in values["voice"]
    assert "determinism" not in values


def test_video_md_overrides_the_project(project):
    project.write_text(
        "---\npersona:\n  voice: 四国めたん\n---\n", encoding="utf-8"
    )
    text = build_request(parse(project))
    assert _values(text)["voice"]["speaker"] == "四国めたん"
    assert _values(text)["voice"]["style"] == "ノーマル"    # プロジェクトから継承


# --- 相対パスの基準 ---------------------------------------------------
def test_cwd_is_rebased_onto_the_plan_directory(project):
    """gmp.toml の cwd='.' はプロジェクトルート. plan.json は 3 階層下にある.

    書いたファイルごとに基準が違うので、直さないと claude が別の場所を読む。
    """
    assert _values(build_request(parse(project)))["app"]["cwd"] == "../../.."


def test_cwd_written_in_video_md_is_relative_to_video_md(project):
    project.write_text("---\napp:\n  cwd: ../..\n---\n", encoding="utf-8")
    # video.md から ../.. = <root>/docs -> plan.json (intro/) から見て ../..
    assert _values(build_request(parse(project)))["app"]["cwd"] == "../.."


# --- 口調と題材 (plan.json には残らないぶん) ---------------------------
def test_brief_carries_persona_and_series(project):
    text = build_request(parse(project))
    assert "淡々と説明する" in text
    assert "初心者" in text
    assert "基本操作 / 設定" in text
    assert "課金画面" in text
    assert "2 本の予定" in text
    # 口調は say の文面に焼かれるだけで plan.json には入らない
    assert "persona" not in _values(text)


def test_subtitle_limits_reach_the_guide(project):
    text = build_request(parse(project))
    assert "2 行・20 文字/行" in text        # max_chars はプロジェクトの 20
    assert "文字数 / 8.0 秒 + 0.6 秒" in text


# --- CLI 経由 ---------------------------------------------------------
def test_plan_uses_the_project_name_for_the_output_dir(project, capsys):
    assert main(["plan", str(project)]) == 0
    outdir = paths.output_home() / "MyApp" / "intro"
    assert (outdir / "PLAN_REQUEST.md").exists()
    assert "gmp.toml" in capsys.readouterr().out


def test_plan_warns_about_unknown_keys(project, capsys):
    project.write_text("---\nbogus: 1\n---\n", encoding="utf-8")
    assert main(["plan", str(project)]) == 0
    assert "bogus" in capsys.readouterr().out


def test_init_does_not_repeat_the_project_defaults(project, capsys):
    """雛形が共通の値を書き写すと、1本ぶんが常にプロジェクトを上書きする."""
    import yaml

    root = project.parents[3]
    assert main(["init", str(root / "docs" / "video" / "second")]) == 0

    text = (root / "docs" / "video" / "second" / "video.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])

    assert "title" in meta
    assert "scenes" in meta
    for inherited in ("project", "app", "persona", "voice", "series"):
        assert inherited not in meta, f"{inherited} を書き写すとプロジェクトが死ぬ"
    # 何が継承されているかは見えるようにする (コメントで)
    assert "# app:" in text and "ずんだもん" in text
    assert "継承" in capsys.readouterr().out


def test_init_template_inherits_the_project_name(project):
    root = project.parents[3]
    assert main(["init", str(root / "docs" / "video" / "second")]) == 0

    second = root / "docs" / "video" / "second" / "video.md"
    values = _values(build_request(parse(second)))
    assert values["meta"]["project"] == "MyApp"
    assert values["voice"]["speaker"] == "ずんだもん"
    assert values["app"]["cwd"] == "../../.."


def test_init_writes_the_full_template_without_a_project_file(tmp_path):
    import yaml

    assert main(["init", str(tmp_path / "intro")]) == 0
    text = (tmp_path / "intro" / "video.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["app"]["url"]          # 1本目は全部ここに書く
    assert meta["persona"]["voice"]


def test_plan_warns_when_no_url_is_configured(tmp_path, capsys):
    (tmp_path / "video.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    assert main(["plan", str(tmp_path / "video.md")]) == 0
    assert "app.url" in capsys.readouterr().out
