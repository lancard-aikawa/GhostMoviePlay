"""構成のエディタ (画面の中で video.md を書く).

設定画面は video.md を書かない (人の散文とコメントを壊すため)。だが構成にしか
置けないものがある —— シーンと狙い・本文・タイトル。**どこかの道筋で直せないと
画面が自己完結しない**ので、ここが最後の道筋になる。
"""

import tkinter as tk

import pytest

from ghostmovieplay import settings
from ghostmovieplay.spec import rebuild_text, split_front

WRITTEN = """---
title: 手で書いたタイトル
voice:
  speaker: ずんだもん
app:
  url: http://127.0.0.1:9999/
scenes:
  - id: fail
    goal: 手で書いた狙い
---

## 補足

人が書いた散文。
"""


# --- 作り直し ---------------------------------------------------------
def project(tmp_path):
    (tmp_path / settings.PROJECT_FILE).write_text(
        "project = 'X'\n[app]\nurl = 'http://127.0.0.1:9999/'\n"
        "[voice]\nspeaker = '四国めたん'\n", encoding="utf-8")
    return tmp_path / settings.PROJECT_FILE


def test_rebuilding_keeps_what_a_person_wrote(tmp_path):
    made, _ = rebuild_text(WRITTEN)
    assert "手で書いたタイトル" in made
    assert "手で書いた狙い" in made
    assert "人が書いた散文" in made


def test_rebuilding_drops_overrides_that_match_the_project(tmp_path):
    """書き写された共通の値は、この動画が常にプロジェクトを上書きし続ける."""
    project_file = project(tmp_path)
    spec = tmp_path / "video.md"
    spec.write_text(WRITTEN, encoding="utf-8")
    without = settings.load(spec=spec, video={})

    made, dropped = rebuild_text(WRITTEN, without_video=without,
                                 project_file=project_file)

    assert dropped == ["app.url"]             # プロジェクトと同じ値
    assert "http://127.0.0.1:9999/" not in split_front(made)[0]
    # 違う値の上書きは**残す** (この動画のためにわざと変えてある)
    assert "ずんだもん" in made


def test_relative_paths_are_never_dropped(tmp_path):
    """**相対パスは層をまたいで比べられない。**

    `app.cwd = '.'` は video.md では動画のフォルダ、gmp.toml ではプロジェクト
    ルート。文字列が同じでも別の場所を指すので、同じに見えたからと落とすと
    黙って収録対象がずれる (CLAUDE.md)。
    """
    project(tmp_path)
    spec = tmp_path / "video.md"
    text = "---\ntitle: x\napp:\n  cwd: .\n---\n"
    spec.write_text(text, encoding="utf-8")

    made, dropped = rebuild_text(
        text, without_video=settings.load(spec=spec, video={}),
        project_file=tmp_path / settings.PROJECT_FILE)

    assert "app.cwd" not in dropped
    assert "cwd: ." in made


def test_rebuilding_a_broken_front_matter_still_gives_something(tmp_path):
    made, dropped = rebuild_text("---\n[こわれた\n---\n本文\n")
    assert "title:" in made and "scenes:" in made
    assert dropped == []


def test_splitting_a_file_without_front_matter(tmp_path):
    assert split_front("本文だけ\n") == ("", "本文だけ\n")


# --- ウィンドウ -------------------------------------------------------
@pytest.fixture
def editor(tk_root, tmp_path, monkeypatch):
    from ghostmovieplay import ui_spec
    from ghostmovieplay.ui_spec import SpecEditor

    # **確認ダイアログは既定で「いいえ」に潰しておく。** 潰さないと、想定外の
    # ところで開いたモーダルが CI ごと止める (実際に止めた)
    monkeypatch.setattr(ui_spec.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(ui_spec.messagebox, "showerror", lambda *a, **k: None)

    spec = tmp_path / "video.md"
    spec.write_text(WRITTEN, encoding="utf-8")
    made = SpecEditor(tk_root, spec)
    made.window.withdraw()
    yield made
    if made.window.winfo_exists():
        made.window.destroy()


def test_the_file_is_shown_as_it_is(editor):
    """**構造を触らない。** 人が打った文字をそのまま出して、そのまま保存する."""
    assert editor.content == WRITTEN
    assert not editor.changed


def test_saving_writes_exactly_what_is_on_screen(editor):
    editor.text.insert(tk.END, "\n手で足した行。\n")
    assert editor.on_save()

    saved = editor.path.read_text(encoding="utf-8")
    assert saved.endswith("手で足した行。\n")
    assert "人が書いた散文" in saved      # 元の中身は 1 文字も変えない
    assert not editor.changed


def test_a_broken_front_matter_is_caught_before_saving(editor, monkeypatch):
    from ghostmovieplay import ui_spec

    editor.text.delete("1.0", "end")
    editor.text.insert("1.0", "---\n  [こわれた: [\n---\n")
    assert editor.front_matter_error()

    assert editor.on_save() is False      # 既定は「いいえ」
    assert "手で書いたタイトル" in editor.path.read_text(encoding="utf-8")

    monkeypatch.setattr(ui_spec.messagebox, "askyesno", lambda *a, **k: True)
    assert editor.on_save() is True      # 訊いた上でなら通す


def test_rebuilding_does_not_save(editor, monkeypatch):
    """`gmp init --force` と違って、見てから保存できる."""
    from ghostmovieplay import ui_spec

    monkeypatch.setattr(ui_spec.messagebox, "askyesno", lambda *a, **k: True)
    editor.on_rebuild()

    assert editor.changed                                   # 中身は変わった
    assert editor.path.read_text(encoding="utf-8") == WRITTEN   # ファイルはそのまま
    assert "手で書いた狙い" in editor.content
