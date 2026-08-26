"""支援収録のウィンドウ.

人が操作して撮る道なので、**画面が壊れるとショットが迷子になる**。ここで見るのは
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
                say="", subtitle="", do="", shot=None, audio=None)
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


# --- ウィンドウ ---------------------------------------------------------------
@pytest.fixture
def shooter(tk_root, tmp_path, monkeypatch):
    """撮るウィンドウを 1 つ開く. 確認ダイアログは既定「いいえ」に潰す.

    潰さないと、想定外のところで開いたモーダルがテストごと止める。
    """
    monkeypatch.setattr(ui_shoot.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(ui_shoot.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(ui_shoot.messagebox, "showinfo", lambda *a, **k: None)
    # 実際のウィンドウは数えない (走らせる機械によって結果が変わる)
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
            "下の帯がウィンドウの外に出ている"


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
    """撮り始めてから変えると、それまでのショットが黒帯つきで並ぶ."""
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
    """**参照を外すだけ。** 撮り直しの効かないショットを画面から消させない."""
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
    """ウィンドウが決まっていない plan.json を保存すると、読めない台本が残る."""
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
    """**選んでいるビートに入る。** ここがずれるとショットが迷子になる."""
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
                        lambda handle, out: pytest.fail("ウィンドウを選ばずに撮った"))
    shooter.picker.set("")
    shooter.on_shot()


# --- ウィンドウを選び直す -----------------------------------------------------
def dialog(title="圧縮"):
    return capture.Window(handle=9, title=title, process="7zG.exe",
                          width=630, height=491)


def test_picking_a_dialog_does_not_steal_the_target(shooter, monkeypatch):
    """**1 つのアプリの操作はウィンドウ 1 つでは終わらない。** ダイアログを撮った拍子に
    「この 1 本の対象」がダイアログになってはいけない.
    """
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.window == "電卓"

    monkeypatch.setattr(capture, "windows", lambda **k: [dialog()])
    shooter.reload_windows()
    shooter.picker.current(0)
    shooter._on_pick_window()

    assert shooter.doc.window == "電卓"
    assert shooter.target.title == "圧縮"


def test_a_dialog_does_not_resize_the_video(shooter, monkeypatch):
    """ダイアログの大きさに合わせると本体が縮む."""
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.size == (800, 600)

    monkeypatch.setattr(capture, "windows", lambda **k: [dialog()])
    shooter.reload_windows()
    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.doc.size == (800, 600)


def test_refreshing_keeps_the_window_you_picked(shooter, monkeypatch):
    """撮る直前に相手が黙って入れ替わらないこと."""
    both = [dialog(), capture.Window(handle=1, title="電卓", process="calc.exe",
                                     width=800, height=600)]
    monkeypatch.setattr(capture, "windows", lambda **k: both)
    shooter.reload_windows()
    shooter.picker.current(0)          # ダイアログを選ぶ
    shooter._on_pick_window()

    shooter.reload_windows()           # 一覧を数え直しても
    assert shooter.target.title == "圧縮"


def test_refreshing_falls_back_to_the_target(shooter, monkeypatch):
    """選んでいたウィンドウが消えたら、主な対象に戻る (開くたびに選ばせない)."""
    both = [dialog(), capture.Window(handle=1, title="電卓", process="calc.exe",
                                     width=800, height=600)]
    monkeypatch.setattr(capture, "windows", lambda **k: both)
    shooter.reload_windows()
    shooter.picker.current(0)
    shooter._on_pick_window()

    monkeypatch.setattr(capture, "windows", lambda **k: [both[1]])
    shooter.reload_windows()
    assert shooter.target.title == "電卓"


# --- 仕込みと後片付け -------------------------------------------------
def with_hooks(shooter, **app):
    shooter.doc.raw["app"].update(app)
    return shooter


def test_setup_runs_before_start(shooter, monkeypatch):
    """**仕込みは start より前。** 仕込んだデータをアプリが読む."""
    order: list = []
    from ghostmovieplay import server

    monkeypatch.setattr(server, "run_hook",
                        lambda cmd, cwd, label, verbose=True: order.append(label))
    monkeypatch.setattr(ui_shoot.subprocess, "Popen",
                        lambda *a, **k: order.append("start") or _FakeProc())
    with_hooks(shooter, setup="python seed.py", start="app.exe")
    shooter.on_launch()
    assert order == ["仕込み", "start"]


def test_a_failed_setup_does_not_start_the_app(shooter, monkeypatch):
    """**仕込めていない画面を撮っても意味が無い。**"""
    from ghostmovieplay import server

    def boom(cmd, cwd, label, verbose=True):
        raise server.HookError("仕込みが失敗しました")

    started: list = []
    monkeypatch.setattr(server, "run_hook", boom)
    monkeypatch.setattr(ui_shoot.subprocess, "Popen",
                        lambda *a, **k: started.append(1) or _FakeProc())
    with_hooks(shooter, setup="python seed.py", start="app.exe")
    shooter.on_launch()
    assert started == []


def test_teardown_runs_after_the_app_is_closed(shooter, monkeypatch):
    """**掴まれたままのファイルを消しに行かない。**"""
    order: list = []
    from ghostmovieplay import server

    monkeypatch.setattr(server, "run_hook",
                        lambda cmd, cwd, label, verbose=True: order.append(label))
    monkeypatch.setattr(server, "kill_tree", lambda proc: order.append("kill"))
    monkeypatch.setattr(ui_shoot.subprocess, "Popen", lambda *a, **k: _FakeProc())
    with_hooks(shooter, start="app.exe", teardown="python seed.py --clean")
    shooter.on_launch()
    shooter.on_launch()          # 2 回目は「終了」
    assert order == ["kill", "後片付け"]


def test_a_failed_teardown_does_not_block(shooter, monkeypatch):
    """撮り終えたものを片付けの失敗で捨てない。ただし黙りもしない."""
    from ghostmovieplay import server

    def boom(cmd, cwd, label, verbose=True):
        raise server.HookError("後片付けが失敗しました")

    monkeypatch.setattr(server, "run_hook", boom)
    monkeypatch.setattr(server, "kill_tree", lambda proc: None)
    monkeypatch.setattr(ui_shoot.subprocess, "Popen", lambda *a, **k: _FakeProc())
    with_hooks(shooter, start="app.exe", teardown="python seed.py --clean")
    shooter.on_launch()
    shooter.on_launch()
    assert "後片付けが失敗しました" in shooter.status.get()


class _FakeProc:
    def poll(self):
        return None


# --- 撮れない理由を出す -----------------------------------------------
def test_a_found_target_is_selected_without_asking(shooter):
    """開くたびに選ばせない (台本が覚えているウィンドウに自分で当てる)."""
    assert shooter.target is not None
    assert shooter.why_blocked() == ""
    assert shooter.shot_button.cget("state") == "normal"


def test_a_missing_target_says_so(shooter, monkeypatch):
    """**黙って未選択にしない。** 撮ろうとして初めてモーダルで言うのでは遅い."""
    monkeypatch.setattr(capture, "windows", lambda **k: [dialog("無関係なウィンドウ")])
    shooter.reload_windows()

    why = shooter.why_blocked()
    assert "電卓" in why, "何を探して見つからなかったのかを言っていない"
    assert shooter.shot_button.cget("state") == "disabled"
    assert shooter.capture_note.cget("text") == why


def test_the_reason_points_at_the_launch_button_when_there_is_one(shooter, monkeypatch):
    """行き止まりを作らない —— 開く手があるならそれを指す."""
    monkeypatch.setattr(capture, "windows", lambda **k: [])
    shooter.doc.raw["app"]["start"] = "app.exe"
    shooter.reload_windows()
    assert "「起動」" in shooter.why_blocked()

    shooter.doc.raw["app"].pop("start")
    shooter.reload_windows()
    assert "「起動」" not in shooter.why_blocked()
    assert "調べ直す" in shooter.why_blocked()


def test_picking_any_window_clears_the_reason(shooter, monkeypatch):
    """対象でなくても、選べば撮れる (ダイアログを撮る道)."""
    monkeypatch.setattr(capture, "windows", lambda **k: [dialog()])
    shooter.reload_windows()
    assert shooter.why_blocked() != ""

    shooter.picker.current(0)
    shooter._on_pick_window()
    assert shooter.why_blocked() == ""
    assert shooter.shot_button.cget("state") == "normal"


def test_an_unsupported_platform_says_why(shooter, monkeypatch):
    monkeypatch.setattr(capture, "supported", lambda: False)
    shooter.reload_windows()
    assert "Windows" in shooter.why_blocked()
    assert shooter.shot_button.cget("state") == "disabled"


# --- 撮る人への指示 ---------------------------------------------------
def test_the_list_shows_what_to_do(shooter):
    """**開いただけでは何をすればいいのか分からない**、を埋める列."""
    shooter.doc.set_text(0, 0, do="ファイルを 4 つとも選ぶ")
    shooter.current = None
    shooter.refresh()
    values = shooter.tree.item(shooter._iid(shooter.rows[0]))["values"]
    assert "ファイルを 4 つとも選ぶ" in str(values)


def test_a_beat_without_an_instruction_says_so(shooter):
    """**空欄にしない** —— 指示が無いのか見落としたのかが分からなくなる."""
    values = shooter.tree.item(shooter._iid(shooter.rows[0]))["values"]
    assert ui_shoot.MISSING_DO in str(values)


def test_editing_the_instruction_sticks(shooter):
    shooter.do.insert("1.0", "ツールバーの「追加」を押す")
    shooter.capture_text()
    assert shooter.doc.rows()[0].do == "ツールバーの「追加」を押す"


def test_the_instruction_survives_moving_between_beats(shooter):
    shooter.doc.add_beat(0, 0)
    shooter.current = None
    shooter.refresh()

    shooter.show(shooter.rows[0])
    shooter.do.insert("1.0", "ひとつめの操作")
    shooter.show(shooter.rows[1])
    assert shooter.doc.rows()[0].do == "ひとつめの操作"
