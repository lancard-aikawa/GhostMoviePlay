import sys
from pathlib import Path

import pytest

from ghostmovieplay import paths


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """環境変数と設定ファイルの影響を受けないようにする."""
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    monkeypatch.setattr(paths, "load_config", lambda: {})
    monkeypatch.setattr(paths, "user_videos_dir", lambda: tmp_path / "Videos")


# --- 名前の正規化 -----------------------------------------------------
def test_sanitize_strips_invalid_characters():
    assert paths.sanitize('a/b:c*d?e"f<g>h|i') == "a-b-c-d-e-f-g-h-i"


def test_sanitize_falls_back_when_empty():
    assert paths.sanitize("", fallback="x") == "x"
    assert paths.sanitize("...", fallback="x") == "x"


# --- 出力ルートの優先順位 ---------------------------------------------
def test_default_home_is_videos_dir(tmp_path):
    assert paths.output_home() == tmp_path / "Videos" / paths.APP_DIR_NAME


def test_env_var_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "custom"))
    assert paths.output_home() == tmp_path / "custom"
    assert paths.ENV_HOME in paths.home_source()


def test_config_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "load_config", lambda: {"home": str(tmp_path / "cfg")})
    assert paths.output_home() == tmp_path / "cfg"


def test_env_var_beats_config(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "load_config", lambda: {"home": str(tmp_path / "cfg")})
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "env"))
    assert paths.output_home() == tmp_path / "env"


# --- 1本ぶんの出力先 --------------------------------------------------
def test_outdir_is_home_project_video(tmp_path):
    source = tmp_path / "repo" / "docs" / "video" / "getting-started" / "plan.json"
    out = paths.resolve_outdir(source, project="MyApp")
    assert out == tmp_path / "Videos" / paths.APP_DIR_NAME / "MyApp" / "getting-started"


def test_explicit_out_wins(tmp_path):
    source = tmp_path / "a" / "b" / "plan.json"
    assert paths.resolve_outdir(source, project="X", explicit=tmp_path / "here") == tmp_path / "here"


def test_project_falls_back_to_app_cwd_name(tmp_path):
    project_dir = tmp_path / "GlossPop"
    project_dir.mkdir()
    source = project_dir / "docs" / "intro" / "plan.json"
    out = paths.resolve_outdir(source, app_cwd="../..")
    assert out.parent.name == "GlossPop"


def test_project_falls_back_to_grandparent(tmp_path):
    source = tmp_path / "examples" / "demo" / "plan.json"
    out = paths.resolve_outdir(source)
    assert out.parent.name == "examples"
    assert out.name == "demo"


def test_project_name_is_sanitized(tmp_path):
    out = paths.resolve_outdir(tmp_path / "a" / "b" / "plan.json", project="my/app:1")
    assert out.parent.name == "my-app-1"


# --- 収録が走る場所 ---------------------------------------------------
def test_record_base_is_next_to_the_plan_by_default(tmp_path):
    source = tmp_path / "docs" / "intro" / "plan.json"
    assert paths.record_base(None, source) == source.parent


def test_record_base_uses_the_registered_project(monkeypatch, tmp_path):
    """素材を外に置いた 1 本は、機械に登録したフォルダで走る."""
    target = tmp_path / "Repos" / "a-lamo"
    monkeypatch.setattr(
        paths, "load_config", lambda: {"projects": {"a-lamo": str(target)}},
    )
    source = tmp_path / "home" / "a-lamo" / "intro" / "plan.json"
    assert paths.record_base("a-lamo", source) == target


def test_record_base_keeps_app_cwd_relative_to_the_plan(monkeypatch, tmp_path):
    """**app.cwd があれば基準を動かさない。** 動かすと既存の台本が別の場所を指す."""
    target = tmp_path / "Repos" / "a-lamo"
    monkeypatch.setattr(
        paths, "load_config", lambda: {"projects": {"a-lamo": str(target)}},
    )
    source = tmp_path / "a-lamo" / "docs" / "video" / "intro" / "plan.json"
    assert paths.record_base("a-lamo", source, "../../..") == source.parent


def test_record_base_ignores_unregistered_projects(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "load_config", lambda: {"projects": {"other": "X:/x"}})
    source = tmp_path / "home" / "a-lamo" / "intro" / "plan.json"
    assert paths.record_base("a-lamo", source) == source.parent


def test_record_base_finds_the_project_by_folder_name(monkeypatch, tmp_path):
    """meta.project が無くても、置き場所の <project> で引ける."""
    target = tmp_path / "Repos" / "a-lamo"
    monkeypatch.setattr(
        paths, "load_config", lambda: {"projects": {"a-lamo": str(target)}},
    )
    source = tmp_path / "home" / "a-lamo" / "intro" / "plan.json"
    assert paths.record_base(None, source) == target


# --- プラットフォーム差 -----------------------------------------------
def test_videos_dir_differs_per_platform(monkeypatch):
    """macOS は Movies、Windows/Linux は Videos。共通の名前は無い."""
    monkeypatch.undo()  # isolated の差し替えを外す
    real = paths.user_videos_dir()
    if sys.platform == "darwin":
        assert real.name == "Movies"
    else:
        assert real.name == "Videos"


def test_config_path_is_platform_specific():
    p = paths.config_path()
    assert p.name == "config.toml"
    if sys.platform == "win32":
        assert "Roaming" in str(p) or "AppData" in str(p)


# --- 設定ファイルの読み書き -------------------------------------------
def test_config_roundtrip_with_windows_path(monkeypatch, tmp_path):
    """バックスラッシュを含むパスが TOML として壊れずに往復する."""
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: cfg)

    paths.save_config({"home": r"C:\Users\thero\Videos\GhostMoviePlay"})
    loaded = paths.load_config.__wrapped__() if hasattr(paths.load_config, "__wrapped__") else None

    import tomllib
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert Path(data["home"]) == Path("C:/Users/thero/Videos/GhostMoviePlay")


def test_broken_config_is_ignored(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not = = toml", encoding="utf-8")
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    monkeypatch.undo()
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    assert paths.load_config() == {}
