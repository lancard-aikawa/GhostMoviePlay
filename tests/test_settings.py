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
