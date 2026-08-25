"""支援収録の窓.

人が操作して撮る道なので、**画面が壊れると素材が迷子になる**。ここで見るのは
「どのビートに入るのか」「打った文字が消えないか」「保存で他人の変更を潰さないか」。
"""

from __future__ import annotations

import json

import pytest

from ghostmovieplay import capture, ui_shoot
from ghostmovieplay.shoot import Doc, Row, skeleton


def make_plan(tmp_path, window="電卓"):
    directory = tmp_path / "docs" / "video" / "demo"
    directory.mkdir(parents=True)
    target = directory / "plan.json"
    target.write_text(
        json.dumps(skeleton("テスト", window, 800, 600), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return target


# --- 画面を作らずに決まる部分 -----------------------------------------
def row(**kwargs):
    base = dict(scene_index=0, beat_index=0, scene_id="s1", scene_title="",
                say="", subtitle="", shot=None, audio=None)
    base.update(kwargs)
    return Row(**base)


def test_summary_counts_shots_not_beats(tmp_path):
    assert "0 / 2" in ui_shoot.summary([row(), row(beat_index=1)])
    assert "揃いました" in ui_shoot.summary([row(shot="shots/a.png")])


def test_summary_survives_an_empty_plan():
    assert ui_shoot.summary([]) == "ビートがありません"


def test_preview_needs_the_file_to_exist(tmp_path):
    """plan.json に書いてあっても、実体が無ければ出せない."""
    assert ui_shoot.preview_source(row(shot="shots/a.png"), tmp_path) is None
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "a.png").write_bytes(b"")
    assert ui_shoot.preview_source(row(shot="shots/a.png"), tmp_path) is not None


def test_preview_of_a_beat_without_a_shot(tmp_path):
    assert ui_shoot.preview_source(row(), tmp_path) is None
    assert ui_shoot.preview_source(None, tmp_path) is None


def test_default_title_uses_the_folder(tmp_path):
    """1 本ぶんのフォルダ名がそのまま題名の既定になる."""
    assert ui_shoot.default_title(tmp_path / "getting-started" / "plan.json") \
        == "getting-started"


# --- 窓 ---------------------------------------------------------------
@pytest.fixture
def shooter(tk_root, tmp_path, monkeypatch):
    """撮る窓を 1 つ開く. 確認ダイアログは既定「いいえ」に潰す.

    潰さないと、想定外のところで開いたモーダルがテストごと止める。
    """
    monkeypatch.setattr(ui_shoot.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(ui_shoot.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(ui_shoot.messagebox, "showinfo", lambda *a, **k: None)
    # 実際の窓は数えない (走らせる機械によって結果が変わる)
    monkeypatch.setattr(capture, "windows", lambda **k: [
        capture.Window(handle=1, title="電卓", process="calc.exe",
                       width=800, height=600)])
    window = ui_shoot.ShootWindow(tk_root, make_plan(tmp_path))
    yield window
    window.window.destroy()


def test_the_tree_lists_every_beat(shooter):
    assert len(shooter.rows) == 1
    shooter.doc.add_beat(0, 0)
    shooter.current = None
    shooter.refresh()
    assert len(shooter.rows) == 2


def test_the_bottom_bar_stays_on_screen(shooter):
    """**下の帯は本体より先に pack する。** あとから pack すると、expand=True の
    本体が cavity を食い尽くして帯が画面外へ出る (CLAUDE.md に同じ罠が 2 か所).
    """
    window = shooter.window
    window.update_idletasks()
    for child in window.pack_slaves():
        assert child.winfo_y() < window.winfo_height(), \
            "下の帯が窓の外に出ている"


def test_typing_survives_moving_between_beats(shooter):
    """**観ながら直す道具なので、行を行き来して文字が消えるのは致命的。**"""
    shooter.doc.add_beat(0, 0)
    shooter.current = None
    shooter.refresh()
    first, second = shooter.rows[0], shooter.rows[1]

    shooter.show(first)
    shooter.say.insert("1.0", "ひとつめの説明")
    shooter.show(second)
    shooter.show(shooter.doc.rows()[0])

    assert shooter.doc.rows()[0].say == "ひとつめの説明"


def test_choosing_a_window_writes_it_into_the_plan(shooter):
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.window == "電卓"


def test_the_video_size_follows_the_window_until_the_first_shot(shooter):
    """撮り始めてから変えると、それまでの素材が黒帯つきで並ぶ."""
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.size == (800, 600)

    shooter.doc.set_shot(0, 0, "shots/0001-scene1.png")
    shooter.current = None
    shooter.refresh()
    shooter.found = [capture.Window(handle=2, title="電卓", process="calc.exe",
                                    width=1000, height=700)]
    shooter.picker.configure(values=[w.label for w in shooter.found])
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.size == (800, 600), "撮ったあとに大きさを変えてはいけない"


def test_dropping_a_shot_keeps_the_file(shooter, tmp_path):
    """**参照を外すだけ。** 撮り直しの効かない素材を画面から消させない."""
    shots = shooter.outdir / "shots"
    shots.mkdir(parents=True)
    (shots / "0001-scene1.png").write_bytes(b"")
    shooter.doc.set_shot(0, 0, "shots/0001-scene1.png")
    shooter.current = None
    shooter.refresh()

    shooter.on_drop_shot()
    assert shooter.doc.rows()[0].shot is None
    assert (shots / "0001-scene1.png").is_file()


def test_saving_without_a_window_is_refused(shooter):
    """窓が決まっていない plan.json を保存すると、読めない台本が残る."""
    shooter.doc.set_window("")
    assert shooter.on_save() is False


def test_saving_asks_before_clobbering_someone_elses_edit(shooter, monkeypatch):
    """**Claude が同じ plan.json の say を書いている最中に黙って上書きしない。**"""
    monkeypatch.setattr(type(shooter.doc), "stale", lambda self: True)
    # 既定「いいえ」なので保存しない
    assert shooter.on_save() is False

    monkeypatch.setattr(ui_shoot.messagebox, "askyesno", lambda *a, **k: True)
    assert shooter.on_save() is True


def test_saving_writes_a_loadable_plan(shooter):
    from ghostmovieplay.plan import load

    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.on_save() is True
    assert load(shooter.path).app.window == "電卓"


def test_the_last_beat_cannot_be_dropped(shooter):
    shooter.on_drop_beat()
    assert len(shooter.doc.rows()) == 1


def test_the_shot_lands_on_the_selected_beat(shooter, monkeypatch):
    """**選んでいるビートに入る。** ここがずれると素材が迷子になる."""
    taken: list = []
    monkeypatch.setattr(capture, "shot",
                        lambda handle, out: taken.append(out) or out)
    shooter.picker.current(0)
    shooter._on_pick_window()
    shooter.advance.set(False)

    shooter.on_shot()
    assert taken, "撮っていない"
    assert shooter.doc.rows()[0].shot == f"shots/{taken[0].name}"


def test_advancing_creates_the_next_beat(shooter, monkeypatch):
    """「1 ステップに何枚も」は**階層ではなくビートの数**で表す
    (1 画像 1 コメントがそのまま守れる).
    """
    monkeypatch.setattr(capture, "shot", lambda handle, out: out)
    shooter.picker.current(0)
    shooter._on_pick_window()
    shooter.advance.set(True)

    shooter.on_shot()
    rows = shooter.doc.rows()
    assert len(rows) == 2
    assert rows[0].shot is not None
    assert rows[1].shot is None
    assert shooter.current.beat_index == 1


def test_a_failed_capture_leaves_the_beat_alone(shooter, monkeypatch):
    def boom(handle, out):
        raise capture.CaptureError("最小化されている")

    monkeypatch.setattr(capture, "shot", boom)
    shooter.picker.current(0)
    shooter._on_pick_window()
    shooter.on_shot()
    assert shooter.doc.rows()[0].shot is None
    assert len(shooter.doc.rows()) == 1


def test_shooting_without_a_window_does_nothing(shooter, monkeypatch):
    monkeypatch.setattr(capture, "shot",
                        lambda handle, out: pytest.fail("窓を選ばずに撮った"))
    shooter.picker.set("")
    shooter.on_shot()
