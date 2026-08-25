"""台本のエディタ (画面の中で plan.json の文と間を直す).

出来た動画を観てから「ここだけ」を直す道。1 行のために Claude に台本全体を
書き直させたくないし、メモ帳で生 JSON を触らせたくもない。

**直せるのは文と間だけ。** actions と selector は入れない（そのプロジェクトを
読まないと決まらないので Claude の領分）。
"""

import json

import pytest

from ghostmovieplay import plan as plan_module
from ghostmovieplay import ui_plan
from ghostmovieplay.plan import load, patch

PLAN = {
    "version": 1,
    "meta": {"title": "テスト動画", "project": "proj"},
    "app": {"url": "http://127.0.0.1:8000/"},
    "scenes": [
        {"id": "why", "title": "なぜ", "beats": [
            {"say": "ひとつめ", "hold": 2.4,
             "actions": [{"type": "highlight", "selector": "#tile"}],
             "audio": "voice/000_why.wav"},
            {"say": "ふたつめ", "subtitle": "短い字幕", "hold": 1.0, "actions": []},
        ]},
        {"id": "good", "beats": [{"say": "みっつめ", "hold": 3.0, "actions": []}]},
    ],
}

TIMING = {
    "beats": [
        {"scene": "why", "index": 0, "start": 2.5, "end": 6.0},
        {"scene": "why", "index": 1, "start": 6.0, "end": 8.4},
        {"scene": "good", "index": 0, "start": 8.4, "end": 12.0},
    ],
}


@pytest.fixture
def plan_file(tmp_path):
    target = tmp_path / "plan.json"
    target.write_text(json.dumps(PLAN, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


# --- 書き戻し ---------------------------------------------------------
def test_the_committed_plans_round_trip_byte_for_byte():
    """**1 行直したら 1 行だけの差分になること。**

    plan.json は git に入る。dataclass から書き戻すと AI が書いたキーの並びが
    崩れて、何を直したのか差分から読めなくなる。
    """
    from pathlib import Path

    from ghostmovieplay import check

    for path in check.find_plans(Path(__file__).resolve().parent.parent):
        raw = path.read_text(encoding="utf-8")
        again = json.dumps(json.loads(raw), ensure_ascii=False, indent=2) + "\n"
        assert again == raw, f"{path}: 書式が変わる"


def test_only_the_edited_field_moves(plan_file):
    before = json.loads(plan_file.read_text(encoding="utf-8"))
    changed = patch(plan_file, {"why#1": {"subtitle": "直した字幕"}})
    after = json.loads(plan_file.read_text(encoding="utf-8"))

    assert changed == ["subtitle"]
    assert after["scenes"][0]["beats"][1]["subtitle"] == "直した字幕"
    # ほかは 1 文字も動かない (actions も audio も meta も)
    before["scenes"][0]["beats"][1]["subtitle"] = "直した字幕"
    assert after == before


def test_an_empty_subtitle_drops_the_key(plan_file):
    """空にしたら say をそのまま字幕に使う (plan.json の既定に戻す)."""
    patch(plan_file, {"why#1": {"subtitle": ""}})
    beat = json.loads(plan_file.read_text(encoding="utf-8"))["scenes"][0]["beats"][1]

    assert "subtitle" not in beat
    assert load(plan_file).scenes[0].beats[1].caption == "ふたつめ"


def test_editing_the_script_drops_the_old_wav(plan_file):
    """**直した原稿の画に古い読み上げを乗せない。** wav は gmp voice が作り直す."""
    patch(plan_file, {"why#0": {"say": "書き直した原稿"}})
    beat = json.loads(plan_file.read_text(encoding="utf-8"))["scenes"][0]["beats"][0]

    assert beat["say"] == "書き直した原稿"
    assert "audio" not in beat
    assert beat["actions"] == [{"type": "highlight", "selector": "#tile"}]


def test_nothing_is_written_when_nothing_changed(plan_file):
    before = plan_file.read_text(encoding="utf-8")
    changed = patch(plan_file, {"why#0": {"say": "ひとつめ", "hold": 2.4}})

    assert changed == []
    assert plan_file.read_text(encoding="utf-8") == before


def test_a_zero_hold_drops_the_key(plan_file):
    patch(plan_file, {"good#0": {"hold": 0}})
    beat = json.loads(plan_file.read_text(encoding="utf-8"))["scenes"][1]["beats"][0]
    assert "hold" not in beat


def test_an_unknown_address_is_ignored(plan_file):
    before = plan_file.read_text(encoding="utf-8")
    assert patch(plan_file, {"nowhere#9": {"say": "x"}}) == []
    assert plan_file.read_text(encoding="utf-8") == before


def test_the_editable_fields_do_not_include_the_picture():
    """selector を打たせない。**画面は Claude の代わりをしない。**"""
    assert set(plan_module.EDITABLE) == {"say", "subtitle", "hold"}


# --- どこからやり直すか -----------------------------------------------
def test_a_subtitle_only_change_just_needs_a_re_render():
    """ここが自分で直す動機そのもの: 言い回しの直しは数十秒で終わる."""
    step, note = ui_plan.redo_for(["subtitle"])
    assert step == "render"
    assert "仕上げ" in note


def test_a_hold_change_needs_a_retake():
    assert ui_plan.redo_for(["hold"])[0] == "record"


def test_a_script_change_needs_the_voice_again():
    assert ui_plan.redo_for(["say"])[0] == "voice"


def test_the_deepest_change_wins():
    assert ui_plan.redo_for(["subtitle", "say", "hold"])[0] == "voice"


def test_no_change_means_nothing_to_redo():
    assert ui_plan.redo_for([]) is None


# --- 一覧 -------------------------------------------------------------
def test_rows_carry_the_measured_time_when_there_is_a_recording(plan_file):
    made = ui_plan.rows(load(plan_file), TIMING)

    assert [r.address for r in made] == ["why#0", "why#1", "good#0"]
    assert made[0].seconds == pytest.approx(3.5)
    assert made[0].middle == pytest.approx(4.25)
    assert made[0].when == "0:02.5"


def test_rows_work_without_a_recording(plan_file):
    made = ui_plan.rows(load(plan_file), None)

    assert made[0].start is None
    assert made[0].seconds is None
    assert made[0].when == "-"
    assert made[1].caption == "短い字幕"        # 字幕があればそちら
    assert made[2].caption == "みっつめ"        # 無ければ原稿


# --- ウィンドウ -------------------------------------------------------
@pytest.fixture
def editor(tk_root, plan_file, tmp_path, monkeypatch):
    from ghostmovieplay.ui_plan import PlanEditor

    # 確認ダイアログは既定で「いいえ」に潰す (モーダルがテストごと止める)
    monkeypatch.setattr(ui_plan.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(ui_plan.messagebox, "showerror", lambda *a, **k: None)

    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "timing.json").write_text(json.dumps(TIMING), encoding="utf-8")
    made = PlanEditor(tk_root, plan_file, outdir)
    made.window.withdraw()
    yield made
    if made.window.winfo_exists():
        made.window.destroy()


def test_the_first_beat_is_shown_on_open(editor):
    assert editor.current.address == "why#0"
    assert editor.say.get("1.0", "end-1c") == "ひとつめ"
    assert editor.hold.get() == "2.4"


def test_edits_survive_moving_between_beats(editor):
    """行を移ったら消える、では「観ながら直す」ができない."""
    editor._set(editor.say, "直しかけ")
    editor.show(next(r for r in editor.rows if r.address == "good#0"))
    editor.show(next(r for r in editor.rows if r.address == "why#0"))

    assert editor.say.get("1.0", "end-1c") == "直しかけ"


def test_picking_a_row_in_the_table_switches_the_beat(editor):
    """表から選ぶ道でも同じところを通ること (取り込み → 表示)."""
    editor.table.selection_set("good#0")
    editor.window.update()

    assert editor.current.address == "good#0"
    assert editor.say.get("1.0", "end-1c") == "みっつめ"


def test_saving_writes_only_what_was_touched(editor, plan_file):
    editor._set(editor.subtitle, "画面から直した字幕")
    assert editor.on_save() is True

    beat = json.loads(plan_file.read_text(encoding="utf-8"))["scenes"][0]["beats"][0]
    assert beat["subtitle"] == "画面から直した字幕"
    assert beat["say"] == "ひとつめ"
    assert "仕上げ" in editor.status.get()      # 何をやり直せば効くかを言う


def test_a_hold_that_is_not_a_number_is_refused(editor, plan_file):
    before = plan_file.read_text(encoding="utf-8")
    editor.hold.delete(0, "end")
    editor.hold.insert(0, "にびょう")

    assert editor.on_save() is False
    assert plan_file.read_text(encoding="utf-8") == before


def test_saving_nothing_says_so(editor):
    assert editor.on_save() is False
    assert "ありません" in editor.status.get()


def test_a_broken_plan_does_not_open_a_window(tk_root, tmp_path):
    from ghostmovieplay.ui_plan import PlanEditor

    broken = tmp_path / "plan.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        PlanEditor(tk_root, broken)


ONE_PIXEL = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_a_still_is_shown_at_its_own_size(editor, tmp_path, monkeypatch):
    """**Label の height は、テキストなら行数・画像ならピクセル。**

    画が無いときの値 (11 行のつもり) を残したまま画像を入れると 11px に潰れ、
    画の上端だけが見える (実際にそうなった)。
    """
    import base64

    png = tmp_path / "shot.png"
    png.write_bytes(base64.b64decode(ONE_PIXEL))
    monkeypatch.setattr(type(editor), "shot_for", lambda self, row: png)

    editor.show(editor.rows[1])
    assert int(editor.shot.cget("height")) == 0     # 中身の大きさに任せる
    assert editor.shot.cget("text") == ""


def test_without_a_still_the_space_is_kept(editor):
    """画が無いときは高さを空けておく (行を移るたびに画面が跳ねない)."""
    editor.show(editor.rows[0])
    assert int(editor.shot.cget("height")) == ui_plan.SHOT_LINES
    assert "収録すると" in editor.shot.cget("text")


def test_no_recording_means_no_still(editor, tmp_path):
    """撮る前でも編集はできる (画が出ないだけ)."""
    row = editor.rows[0]
    assert editor.shot_for(row) is None       # raw.webm がまだ無い
