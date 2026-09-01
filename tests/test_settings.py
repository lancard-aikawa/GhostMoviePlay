import tomllib
from pathlib import Path

import pytest

from ghostmovieplay import paths, settings


# --- 層の優先順位 -----------------------------------------------------
def test_layers_override_in_order():
    got = settings.resolve(
        machine={"voice": {"speaker": "ずんだもん", "speed": 1.0}},
        project={"voice": {"speaker": "四国めたん"}},
        video={"voice": {"speed": 1.2}},
        use_env=False,
    )
    assert got.get("voice.speaker") == "四国めたん"   # プロジェクトが機械に勝つ
    assert got.get("voice.speed") == 1.2              # 1本ぶんが最も強い
    assert got.origin("voice.speaker").layer == settings.PROJECT
    assert got.origin("voice.speed").layer == settings.VIDEO


def test_cli_beats_every_file():
    got = settings.resolve(
        machine={"voice": {"speaker": "a"}},
        project={"voice": {"speaker": "b"}},
        video={"voice": {"speaker": "c"}},
        cli={"voice": {"speaker": "d"}},
        use_env=False,
    )
    assert got.get("voice.speaker") == "d"
    assert got.origin("voice.speaker").layer == settings.CLI


def test_env_beats_machine_but_loses_to_project(monkeypatch, tmp_path):
    monkeypatch.setenv(settings.env_var_name("home"), str(tmp_path / "env"))
    got = settings.resolve(machine={"home": str(tmp_path / "cfg")})
    assert got.get("home") == str(tmp_path / "env")
    assert got.origin("home").short() == "GHOSTMOVIEPLAY_HOME"


def test_env_only_touches_machine_settings(monkeypatch):
    """環境変数は機械の設定を差し替える口. プロジェクト固有の事実には効かない."""
    monkeypatch.setenv(settings.env_var_name("app.url"), "http://sneaky")
    monkeypatch.setenv(settings.env_var_name("determinism.seed"), "1")
    assert "app.url" not in settings.env_layer()
    assert "determinism.seed" not in settings.env_layer()

    # 声の既定のように「機械に置ける」ものは環境変数でも差し替えられるが、
    # プロジェクトが書いていればそちらが勝つ
    monkeypatch.setenv(settings.env_var_name("voice.speaker"), "波音リツ")
    assert settings.resolve().get("voice.speaker") == "波音リツ"
    assert settings.resolve(project={"voice": {"speaker": "ずんだもん"}}).get(
        "voice.speaker"
    ) == "ずんだもん"


def test_unset_values_come_from_code_defaults():
    got = settings.resolve(use_env=False)
    assert got.get("video.fps") == 30
    assert not got.is_explicit("video.fps")
    assert got.origin("video.fps").layer == settings.DEFAULT


# --- マージするもの ---------------------------------------------------
def test_voice_dict_merges_across_layers():
    """読みはプロジェクトで持ち、1本ぶんで足す (上書きで消えると事故る)."""
    got = settings.resolve(
        project={"voice": {"dict": {"語": "ゴ", "冪等": "ベキトウ"}}},
        video={"voice": {"dict": {"語": "カタリ"}}},
        use_env=False,
    )
    assert got.get("voice.dict") == {"語": "カタリ", "冪等": "ベキトウ"}


def test_lists_are_replaced_not_merged():
    got = settings.resolve(
        project={"series": {"topics": ["a", "b"]}},
        video={"series": {"avoid": ["課金"]}},
        use_env=False,
    )
    assert got.get("series.topics") == ["a", "b"]
    assert got.get("series.avoid") == ["課金"]


# --- 置ける層の検査 ---------------------------------------------------
def test_machine_cannot_hold_project_facts():
    """同じ機械で 2 つ目のプロジェクトを撮った瞬間に嘘になる値は弾く."""
    got = settings.resolve(machine={"app": {"url": "http://x"}}, use_env=False)
    assert got.get("app.url") is None
    assert any("app.url" in w for w in got.warnings)


def test_unknown_key_warns_instead_of_silently_vanishing():
    got = settings.resolve(video={"bogus": 1}, use_env=False)
    assert any("bogus" in w for w in got.warnings)


def test_bad_type_warns_and_keeps_the_default():
    got = settings.resolve(video={"video": {"fps": "はやい"}}, use_env=False)
    assert got.get("video.fps") == 30
    assert got.warnings


# --- 人が書きやすい形の吸収 -------------------------------------------
def test_video_size_splits_into_width_and_height():
    got = settings.resolve(video={"video": {"size": [1920, 1080]}}, use_env=False)
    assert (got.get("video.width"), got.get("video.height")) == (1920, 1080)


def test_persona_voice_is_an_alias_of_voice_speaker():
    """video.md の雛形が persona.voice で書いている."""
    got = settings.resolve(video={"persona": {"voice": "zundamon"}}, use_env=False)
    assert got.get("voice.speaker") == "zundamon"


def test_section_drops_the_prefix():
    got = settings.resolve(video={"voice": {"speaker": "x"}}, use_env=False)
    section = got.section("voice")
    assert section["speaker"] == "x"
    assert section["speed"] == 1.0
    assert got.section("voice", explicit_only=True) == {"speaker": "x"}


# --- gmp.toml の探索 --------------------------------------------------
def test_project_file_is_found_upwards(tmp_path):
    root = tmp_path / "repo"
    deep = root / "docs" / "video" / "intro"
    deep.mkdir(parents=True)
    (root / settings.PROJECT_FILE).write_text("project = 'X'\n", encoding="utf-8")

    assert settings.find_project_file(deep / "video.md") == root / settings.PROJECT_FILE


def test_missing_project_file_is_not_an_error(tmp_path):
    (tmp_path / "a").mkdir()
    assert settings.find_project_file(tmp_path / "a", limit=2) is None


def test_nearest_project_file_wins(tmp_path):
    outer, inner = tmp_path / "o", tmp_path / "o" / "i"
    inner.mkdir(parents=True)
    (outer / settings.PROJECT_FILE).write_text("project = 'o'\n", encoding="utf-8")
    (inner / settings.PROJECT_FILE).write_text("project = 'i'\n", encoding="utf-8")
    assert settings.find_project_file(inner) == inner / settings.PROJECT_FILE


# --- 書き出し ---------------------------------------------------------
def test_dump_writes_nested_tables():
    text = settings.dump({"engine.voicevox.url": "http://h:1", "render.crf": 18})
    data = tomllib.loads(text)
    assert data["engine"]["voicevox"]["url"] == "http://h:1"
    assert data["render"]["crf"] == 18          # 数字が文字列にならない


def test_dump_survives_windows_paths():
    text = settings.dump({"home": r"C:\Users\thero\Videos"})
    assert tomllib.loads(text)["home"] == "C:/Users/thero/Videos"


def test_dump_keeps_tables_inline():
    text = settings.dump({"voice.dict": {"語": "ゴ", "冪等": {"pronunciation": "ベキトウ"}}})
    data = tomllib.loads(text)
    assert data["voice"]["dict"]["語"] == "ゴ"
    assert data["voice"]["dict"]["冪等"]["pronunciation"] == "ベキトウ"


def test_dump_does_not_drop_hand_written_keys():
    """知らないキーを黙って消すと、手で足した設定が消える."""
    text = settings.dump({"render.crf": 20, "experiment.thing": "keep"})
    assert tomllib.loads(text)["experiment"]["thing"] == "keep"


def test_machine_config_round_trips(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    paths.save_config({"voice": {"speaker": "ずんだもん"}, "render": {"crf": 18}})

    got = settings.resolve(machine=paths.load_config(), use_env=False)
    assert got.get("voice.speaker") == "ずんだもん"
    assert got.get("render.crf") == 18


def test_parse_value_uses_the_declared_type():
    assert settings.parse_value("render.crf", "18") == 18
    assert settings.parse_value("voice.speed", "1.1") == 1.1
    assert settings.parse_value("series.topics", "a, b") == ["a", "b"]
    with pytest.raises(settings.SettingsError):
        settings.parse_value("nope.nope", "1")


# --- 変更だけを当てる (UI からの保存) ---------------------------------
BASE = """# なぜこの値なのかを書いたコメント
project = 'MyApp'

[app]
url = 'http://localhost:5173'
# start = 'npm run dev'      # 自分で起動するので切ってある

[voice]
speaker = 'ずんだもん'
speed = 1.0
"""


def test_patch_keeps_comments_and_order():
    """gmp.toml は人が書くファイル. 書き直すとコメントが消える."""
    patched = settings.patch_toml(BASE, {"voice.speaker": "四国めたん"})

    assert "# なぜこの値なのかを書いたコメント" in patched
    assert "# start = 'npm run dev'      # 自分で起動するので切ってある" in patched
    assert tomllib.loads(patched)["voice"]["speaker"] == "四国めたん"
    assert tomllib.loads(patched)["voice"]["speed"] == 1.0


def test_patch_adds_a_key_to_an_existing_section():
    patched = settings.patch_toml(BASE, {"app.ready": "text=開始"})
    data = tomllib.loads(patched)
    assert data["app"]["ready"] == "text=開始"
    assert data["app"]["url"] == "http://localhost:5173"   # 元の行は動かない


def test_patch_creates_a_missing_section():
    patched = settings.patch_toml(BASE, {"determinism.seed": 42})
    assert tomllib.loads(patched)["determinism"]["seed"] == 42


def test_patch_writes_root_keys_before_the_first_section():
    patched = settings.patch_toml("[app]\nurl = 'x'\n", {"project": "New"})
    assert tomllib.loads(patched)["project"] == "New"


def test_patch_removes_a_key_when_the_value_is_none():
    patched = settings.patch_toml(BASE, {"voice.speed": None})
    assert "speed" not in tomllib.loads(patched)["voice"]
    assert tomllib.loads(patched)["voice"]["speaker"] == "ずんだもん"


def test_patch_replaces_a_whole_table():
    text = BASE + "\n[voice.dict]\n'語' = 'ゴ'\n'旧' = 'キュウ'\n"
    patched = settings.patch_toml(text, {"voice.dict": {"語": "ゴ", "冪等": "ベキトウ"}})

    data = tomllib.loads(patched)
    assert data["voice"]["dict"] == {"語": "ゴ", "冪等": "ベキトウ"}
    assert data["voice"]["speaker"] == "ずんだもん"     # 隣の区画を巻き込まない


def test_patch_drops_an_emptied_table():
    text = BASE + "\n[voice.dict]\n'語' = 'ゴ'\n"
    patched = settings.patch_toml(text, {"voice.dict": {}})
    assert "dict" not in tomllib.loads(patched).get("voice", {})


def test_write_layer_creates_the_file_when_missing(tmp_path):
    target = settings.write_layer(tmp_path / "gmp.toml", {"voice.speaker": "ずんだもん"})
    assert tomllib.loads(target.read_text(encoding="utf-8"))["voice"]["speaker"] == "ずんだもん"


def test_write_layer_patches_an_existing_file(tmp_path):
    target = tmp_path / "gmp.toml"
    target.write_text(BASE, encoding="utf-8")
    settings.write_layer(target, {"voice.speed": 1.2})

    text = target.read_text(encoding="utf-8")
    assert "# なぜこの値なのかを書いたコメント" in text
    assert tomllib.loads(text)["voice"]["speed"] == 1.2


# --- 雛形 -------------------------------------------------------------
def test_project_template_is_valid_and_fully_known(tmp_path):
    """雛形に書いたキーが全部スキーマに載っていること.

    雛形が警告を出す状態で配ると、利用者は警告を読まなくなる。
    """
    written = settings.init_project(tmp_path)
    raw = tomllib.loads(written.read_text(encoding="utf-8"))

    got = settings.resolve(project=raw, project_path=written, use_env=False)
    assert got.warnings == []
    assert got.get("voice.speaker") == "ずんだもん"
    assert got.get("series.count") == 3

    with pytest.raises(settings.SettingsError):
        settings.init_project(tmp_path)


def test_project_template_examples_are_valid_toml(tmp_path):
    """雛形のコメント例を外しても TOML として通ること.

    日本語の表記を裸のキーで書くと TOML として不正になる (読み辞書で踏む)。
    雛形が間違った書き方を教えていると、外した人が必ず落ちる。
    """
    text = settings.init_project(tmp_path).read_text(encoding="utf-8")
    live = "\n".join(
        line[2:] if line.startswith("# ") and " = " in line else line
        for line in text.splitlines()
    )
    assert "'語' = 'ゴ'" in live
    tomllib.loads(live)


# --- スキーマ自身の不変条件 -------------------------------------------
def test_plan_settings_are_writable_outside_the_machine():
    """plan.json に焼かれる値を、機械だけが決められてはいけない.

    それを許すと、plan.json がその機械なしでは再現できなくなる。
    """
    for setting in settings.SCHEMA:
        if setting.bake == "plan":
            assert settings.PROJECT in setting.layers or settings.VIDEO in setting.layers, (
                f"{setting.path} は plan.json に焼かれるのに機械しか書けない"
            )


def test_runtime_settings_are_machine_only():
    """runtime は「機械が変われば変わる値」だけ. 絵と音を変える値を入れない."""
    for setting in settings.SCHEMA:
        if setting.bake == "runtime":
            assert setting.layers == (settings.MACHINE,), setting.path


def test_every_setting_declares_a_known_bake_and_layers():
    for setting in settings.SCHEMA:
        assert setting.bake in ("plan", "brief", "runtime"), setting.path
        assert setting.layers, setting.path
        assert set(setting.layers) <= set(settings.WRITABLE), setting.path
        assert setting.kind in ("str", "int", "float", "bool", "list", "table", "path")


def test_aliases_point_at_real_settings():
    for alias, target in settings.ALIASES.items():
        assert target in settings.SETTINGS, alias
        assert alias not in settings.SETTINGS, alias


# --- Pass2/3 が読める範囲 ---------------------------------------------
def test_machine_value_reads_only_the_machine_layer(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    paths.save_config({"render": {"font": "Meiryo"}})
    assert settings.machine_value("render.font") == "Meiryo"


def test_machine_value_refuses_plan_settings():
    """record / render が plan.json に焼かれる値を実行時に読めてはいけない."""
    for key in ("voice.speaker", "app.url", "video.fps", "persona.style"):
        with pytest.raises(settings.SettingsError):
            settings.machine_value(key)


def test_machine_value_ignores_the_project_file(monkeypatch, tmp_path):
    """置き場所によって同じ plan.json の出力が変わらないこと."""
    (tmp_path / settings.PROJECT_FILE).write_text(
        "[render]\nfont = 'のっとる'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert settings.machine_value("render.font") != "のっとる"


def test_project_root_reads_the_machine_table(monkeypatch, tmp_path):
    """撮る対象のフォルダは機械の設定から引く (plan.json には焼かない)."""
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    paths.save_config({"projects": {"a-lamo": "C:/Repos/a-lamo"}})

    assert settings.project_root("a-lamo") == Path("C:/Repos/a-lamo")
    assert settings.project_root("知らない子") is None
    assert settings.project_root(None) is None


def test_projects_is_not_baked_into_the_plan():
    """焼くと、clone した別の機械に無いパスが plan.json に残る."""
    assert settings.SETTINGS["projects"].bake == "runtime"
    assert settings.SETTINGS["projects"].layers == (settings.MACHINE,)


def test_projects_survives_a_config_roundtrip(monkeypatch, tmp_path):
    """[projects] を書いて読み直せること (表なので dump の経路が別)."""
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    paths.save_config({"projects": {"a-lamo": "C:/Repos/a-lamo", "紹介": "C:/Repos/g"}})
    assert paths.load_config()["projects"] == {
        "a-lamo": "C:/Repos/a-lamo", "紹介": "C:/Repos/g",
    }


def test_env_does_not_try_to_fill_a_table(monkeypatch):
    """1 個の文字列では書けないので、拾って警告するだけにしない."""
    monkeypatch.setenv(settings.env_var_name("projects"), "C:/Repos/a-lamo")
    assert "projects" not in settings.env_layer()
    assert not settings.resolve().warnings


def test_pass23_modules_do_not_read_settings():
    """record / render / subtitles が設定ファイルを読まないこと.

    ここが設定を読み始めると、同じ plan.json が機械ごとに違う動画を出す。
    解決は CLI の境界 (と Pass1) で済ませて、値は引数で渡す。
    """
    import inspect

    from ghostmovieplay import ffmpeg, record, render, subtitles

    for module in (record, render, subtitles, ffmpeg):
        source = inspect.getsource(module)
        assert "settings" not in source, f"{module.__name__} が設定を読んでいる"


def test_render_takes_the_look_from_the_machine_config(monkeypatch, tmp_path):
    """--font 等を省いたら機械の設定が使われること."""
    from types import SimpleNamespace

    from ghostmovieplay import render as render_module
    from ghostmovieplay.cli import main

    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    paths.save_config({"render": {"font": "Meiryo", "crf": 30, "preset": "fast"}})

    seen: dict = {}

    def fake_render(timing, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(video=tmp_path / "o.mp4", subtitles=None, audio_tracks=0)

    monkeypatch.setattr(render_module, "render", fake_render)
    (tmp_path / "timing.json").write_text("{}", encoding="utf-8")

    assert main(["render", str(tmp_path / "timing.json")]) == 0
    assert (seen["font"], seen["crf"], seen["preset"]) == ("Meiryo", 30, "fast")

    seen.clear()
    assert main(["render", str(tmp_path / "timing.json"), "--crf", "10"]) == 0
    assert seen["crf"] == 10        # 引数があればそちらが勝つ


def test_every_runtime_setting_is_reachable():
    """runtime の項目は machine_value で取れること (取れない設定は死んでいる)."""
    for setting in settings.SCHEMA:
        if setting.bake == "runtime":
            settings.machine_value(setting.path)


# --- 出力ルートの二重実装を固定する -----------------------------------
def test_home_agrees_with_paths_output_home(monkeypatch, tmp_path):
    """paths.output_home() と settings の home は同じ答えを出すこと.

    解決の実装が 2 か所にあるので、食い違うと `gmp config` の表示が嘘になる。
    """
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    monkeypatch.setattr(paths, "load_config", lambda: {})
    monkeypatch.setattr(paths, "user_videos_dir", lambda: tmp_path / "Videos")
    assert Path(settings.load().get("home")) == paths.output_home()

    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "env"))
    assert Path(settings.load().get("home")) == paths.output_home()


# --- 空文字で打ち消す -------------------------------------------------
def test_an_empty_string_cancels_a_lower_layer(tmp_path, monkeypatch):
    """**下の層の値を上の層から消せる唯一の手。**

    支援収録の 1 本は、プロジェクトが持っている app.url を要らない。これが
    無いと video.md からは消せず、使いもしない URL が plan.json に焼かれる。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / settings.PROJECT_FILE).write_text(
        "project = 'X'\n[app]\nurl = 'http://127.0.0.1:8765/'\n"
        "[determinism]\nseed = 12345\n", encoding="utf-8")
    spec = tmp_path / "video.md"
    spec.write_text("---\ntitle: t\n---\n", encoding="utf-8")

    kept = settings.load(spec=spec, video={})
    assert kept.get("app.url") == "http://127.0.0.1:8765/"
    assert kept.get("determinism.seed") == 12345

    cleared = settings.load(spec=spec, video={"app": {"url": ""},
                                              "determinism": {"seed": ""}})
    assert cleared.get("app.url") is None
    # **数の項目も同じ意味にする** —— int('') で落ちて「書いたのに効かない」に
    # なっていた (プロジェクトの値がそのまま勝っていた)
    assert cleared.get("determinism.seed") is None
    assert cleared.warnings == []


def test_a_cancelled_value_is_not_baked(tmp_path, monkeypatch):
    """打ち消した値が plan.json に残ると、消したつもりが残る."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / settings.PROJECT_FILE).write_text(
        "project = 'X'\n[app]\nurl = 'http://127.0.0.1:8765/'\n", encoding="utf-8")
    spec = tmp_path / "video.md"
    spec.write_text("---\ntitle: t\n---\n", encoding="utf-8")

    resolved = settings.load(spec=spec, video={"app": {"url": "", "window": "電卓"}})
    section = resolved.section("app")
    assert "url" not in section
    assert section["window"] == "電卓"
