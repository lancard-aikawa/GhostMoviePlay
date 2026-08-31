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


def test_init_never_writes_a_configured_looking_lie(tmp_path):
    """**雛形は「設定済みに見える嘘」を焼かない。**

    見本の URL を焼くと、`app.url` は project と video にしか置けず設定画面は
    video.md を書かないので、**画面から直せない値がプロジェクトに焼き付く**
    (しかも video.md のほうが強いので gmp.toml で直しても効かない)。
    """
    import yaml

    assert main(["init", str(tmp_path / "intro")]) == 0
    text = (tmp_path / "intro" / "video.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert not (meta.get("app") or {}).get("url"), "見本の URL が焼かれている"
    assert "http://localhost:5173" in text, "書き方の見本はコメントで残す"
    assert meta["persona"]["voice"]       # 声のような無害な既定は焼いてよい


def test_plan_warns_when_no_url_is_configured(tmp_path, capsys):
    (tmp_path / "video.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    assert main(["plan", str(tmp_path / "video.md")]) == 0
    assert "app.url" in capsys.readouterr().out


# --- 雛形の見本値 -----------------------------------------------------
def test_the_sample_values_match_the_template():
    """**TEMPLATE_HINTS は TEMPLATE の写し。** ずれると検出できなくなる."""
    from ghostmovieplay.spec import TEMPLATE, TEMPLATE_HINTS

    for sample, _label in TEMPLATE_HINTS.values():
        assert sample in TEMPLATE, f"雛形に無い見本値: {sample}"


def test_untouched_defaults_are_reported():
    """雛形のまま Pass1 を呼ぶと、AI は「本物を指してくれ」と訊いて終わる."""
    from ghostmovieplay import settings
    from ghostmovieplay.spec import unfilled

    fresh = settings.load(video={
        "app": {"url": "http://localhost:5173", "start": "npm run dev",
                "ready": "text=スタート"},
    })
    assert len(unfilled(fresh)) == 3

    filled = settings.load(video={
        "app": {"url": "http://127.0.0.1:7474/", "start": "bun run dev",
                "ready": "#app"},
    })
    assert unfilled(filled) == []


def test_a_single_coincidence_is_not_enough():
    """Vite の既定は本当に 5173. 1 つだけで「雛形のまま」と言わない."""
    from ghostmovieplay import settings
    from ghostmovieplay.spec import unfilled

    real = settings.load(video={
        "app": {"url": "http://localhost:5173", "start": "bun run dev",
                "ready": "#app"},
    })
    assert len(unfilled(real)) == 1      # 画面と CLI は 2 つ以上で言う


def test_schema_doc_lists_every_action():
    """AI に渡す仕様が action を取りこぼしていないか.

    `PLAN_SCHEMA_DOC` は **AI に渡す仕様として正** なので、ここに無い action は
    「無い」ものとして扱われる。実際に `select` が漏れていたときは、AI が
    `<select>` を `eval` で書き換える台本を書いた (操作として不自然な上に、
    change イベントを見ているアプリでは動かない)。
    """
    from ghostmovieplay.plan import ACTION_SPECS
    from ghostmovieplay.spec import PLAN_SCHEMA_DOC

    missing = [kind for kind in ACTION_SPECS
               if f'"type": "{kind}"' not in PLAN_SCHEMA_DOC]
    assert not missing, f"AI に渡す仕様から漏れている action: {missing}"


# --- 支援収録の依頼文 -------------------------------------------------
@pytest.fixture
def assisted(project):
    """`app.window` を足して、支援収録の 1 本にする."""
    (project.parent / "video.md").write_text(
        "---\ntitle: 手で撮る 1 本\napp:\n  window: 電卓\n---\n\n本文\n",
        encoding="utf-8")
    return project


def test_the_window_is_baked_into_the_plan_values(assisted):
    """撮るウィンドウも設定なので、Pass1 で plan.json に焼き切る."""
    assert _values(build_request(parse(assisted)))["app"]["window"] == "電卓"


def test_assisted_request_asks_for_the_window_not_the_url(assisted):
    text = build_request(parse(assisted))
    assert "撮るウィンドウ: `電卓`" in text
    assert "人がこのウィンドウを操作します" in text


def test_assisted_request_forbids_actions(assisted):
    """**書いた操作は誰も実行しない。** 書かせると台本に嘘が残る."""
    text = build_request(parse(assisted))
    assert "`actions` を書かないでください" in text
    assert "`shot` を書かないでください" in text


def test_assisted_request_does_not_ask_to_run_record(assisted):
    """素材を撮る前に `gmp record` を叩かせない (黒画だけの動画が出来る)."""
    text = build_request(parse(assisted))
    assert "gmp record plan.json` を実行し" not in text
    assert "gmp shoot" in text


def test_automated_request_is_unchanged(project):
    """**支援収録の説明を自動収録に混ぜない** —— `shot` を見せると、
    撮ってもいない素材のパスを AI が書く.
    """
    text = build_request(parse(project))
    assert "支援収録" not in text
    assert "`shot` を書かないでください" not in text
    assert "gmp record plan.json` を実行し" in text


def test_assisted_request_asks_for_the_operator_instructions(assisted):
    """**`do` が空だと撮る人は何をすればいいのか分からない。** 必ず書かせる."""
    text = build_request(parse(assisted))
    assert "`do` を必ず書いてください" in text
    assert "撮る人への指示" in text


def test_automated_request_never_mentions_do(project):
    """自動収録に撮る人はいない (混ぜると actions の代わりに書き始める)."""
    assert "`do` を必ず書いてください" not in build_request(parse(project))


# --- 撮る価値の前提 -----------------------------------------------------
def test_the_request_is_not_narrowed_to_failures(project):
    """**軸は「分からなくて離れてしまうか」で、失敗はその一種でしかない。**

    ここを「失敗を作れ」に狭めると、7-Zip の 1 本のような「操作は全部通るのに
    目的を果たしていない」題材が選べなくなる (あの zip は正常に作られる)。
    """
    text = build_request(parse(project))
    assert "離れ" in text, "離脱の軸が依頼文から消えている"
    for shape in ("通るのに目的を果たしていない", "選べない・見つからない",
                  "順序に縛られる", "引き返せない"):
        assert shape in text, f"障害の型が漏れている: {shape}"


def test_the_quality_bar_survives(project):
    """広げても「ただ下手なだけ」は落とす (具体的な因果があるものを選ばせる)."""
    text = build_request(parse(project))
    assert "ただ下手なだけ" in text
    assert "分かっている人でも引っかかる" in text
