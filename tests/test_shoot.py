"""支援収録の plan.json 操作 (画面を作らずに決まる部分)."""

from __future__ import annotations

import json

import pytest

from ghostmovieplay.plan import PlanError, load
from ghostmovieplay import shoot
from ghostmovieplay.shoot import Doc, ShootError, next_shot_path, progress, skeleton


def write(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def base(tmp_path):
    return write(tmp_path / "plan.json", skeleton("見出し", "電卓", 800, 600))


# --- 骨 ---------------------------------------------------------------
def test_skeleton_loads(tmp_path):
    """骨がそのまま plan.load() を通る (通らないと撮る面が開けない)."""
    plan = load(base(tmp_path))
    assert plan.app.window == "電卓"
    assert plan.title == "見出し"
    assert len(plan.scenes) == 1


def test_skeleton_has_no_url(tmp_path):
    """**支援収録は url を要らない。** ブラウザを開かないので焼く値が無い."""
    plan = load(base(tmp_path))
    assert not plan.app.url


def test_plan_without_url_or_window_still_fails(tmp_path):
    """url も window も無ければ、どこを撮るのか決まっていない."""
    doc = skeleton("t", "", 800, 600)
    doc["app"] = {}
    write(tmp_path / "plan.json", doc)
    with pytest.raises(PlanError, match="app.url"):
        load(tmp_path / "plan.json")


# --- 読み書き ---------------------------------------------------------
def test_unknown_keys_survive(tmp_path):
    """**AI が書いたキーを落とさない。** 生の JSON に当てる意味がそこにある."""
    doc = skeleton("t", "電卓", 800, 600)
    doc["scenes"][0]["beats"][0]["actions"] = [{"type": "sleep", "seconds": 1}]
    doc["meta"]["project"] = "demo"
    path = write(tmp_path / "plan.json", doc)

    edited = Doc.load(path)
    edited.set_text(0, 0, say="ひとこと")
    edited.save()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["scenes"][0]["beats"][0]["actions"] == [{"type": "sleep", "seconds": 1}]
    assert raw["meta"]["project"] == "demo"
    assert raw["scenes"][0]["beats"][0]["say"] == "ひとこと"


def test_say_change_drops_audio(tmp_path):
    """原稿を直したら、そのビートの音声を落とす (`plan._apply` と同じ規則).

    残すと、直した原稿に古い読み上げが乗ったまま組み立てられる。
    """
    doc = skeleton("t", "電卓", 800, 600)
    doc["scenes"][0]["beats"][0].update({"say": "まえ", "audio": "voice/a.wav"})
    path = write(tmp_path / "plan.json", doc)

    edited = Doc.load(path)
    assert edited.set_text(0, 0, say="あと") == ["say"]
    assert "audio" not in edited.raw["scenes"][0]["beats"][0]


def test_same_say_keeps_audio(tmp_path):
    """直していないなら落とさない (触るたびに全部合成し直させない)."""
    doc = skeleton("t", "電卓", 800, 600)
    doc["scenes"][0]["beats"][0].update({"say": "そのまま", "audio": "voice/a.wav"})
    path = write(tmp_path / "plan.json", doc)

    edited = Doc.load(path)
    assert edited.set_text(0, 0, say="そのまま") == []
    assert edited.raw["scenes"][0]["beats"][0]["audio"] == "voice/a.wav"


def test_empty_subtitle_removes_key(tmp_path):
    """字幕を空にしたら say をそのまま使う (キーを残さない)."""
    doc = skeleton("t", "電卓", 800, 600)
    doc["scenes"][0]["beats"][0]["subtitle"] = "字幕"
    path = write(tmp_path / "plan.json", doc)

    edited = Doc.load(path)
    assert edited.set_text(0, 0, subtitle="") == ["subtitle"]
    assert "subtitle" not in edited.raw["scenes"][0]["beats"][0]


def test_stale_detects_outside_change(tmp_path):
    """**他所で書き換わったら気づく。** このウィンドウは構造ごと書き戻すので、
    Claude が say を書いている最中に黙って上書きしてはいけない.
    """
    path = base(tmp_path)
    edited = Doc.load(path)
    assert not edited.stale()

    later = json.loads(path.read_text(encoding="utf-8"))
    later["scenes"][0]["beats"][0]["say"] = "claude が書いた"
    write(path, later)
    import os
    os.utime(path, (edited.mtime + 10, edited.mtime + 10))

    assert edited.stale()


# --- 構造 -------------------------------------------------------------
def test_add_beat_after_current(tmp_path):
    edited = Doc.load(base(tmp_path))
    at = edited.add_beat(0, 0)
    assert at == 1
    assert len(edited.rows()) == 2


def test_add_scene_carries_one_beat(tmp_path):
    """**空のシーンを作らない。** load() が beats の無いシーンを拒む."""
    edited = Doc.load(base(tmp_path))
    edited.add_scene("あとから")
    edited.save()
    plan = load(edited.path)
    assert [s.title for s in plan.scenes] == ["", "あとから"]
    assert all(s.beats for s in plan.scenes)


def test_scene_ids_stay_unique(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.add_scene()
    edited.add_scene()
    ids = [s["id"] for s in edited.scenes]
    assert len(set(ids)) == len(ids)


def test_last_beat_is_not_removable(tmp_path):
    """最後の 1 ビートを消せると、台本が読めなくなる (beats が空になる)."""
    edited = Doc.load(base(tmp_path))
    assert edited.remove_beat(0, 0) is False
    edited.add_beat(0, 0)
    assert edited.remove_beat(0, 1) is True


def test_last_scene_is_not_removable(tmp_path):
    edited = Doc.load(base(tmp_path))
    assert edited.remove_scene(0) is False


# --- ショット -------------------------------------------------------------
def test_set_and_clear_shot(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.set_shot(0, 0, "shots/0001-scene1.png")
    assert edited.rows()[0].shot == "shots/0001-scene1.png"
    assert edited.rows()[0].kind == "静止画"
    edited.set_shot(0, 0, None)
    assert edited.rows()[0].shot is None
    assert "shot" not in edited.raw["scenes"][0]["beats"][0]


def test_clip_is_labelled_as_video(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.set_shot(0, 0, "shots/0002-scene1.mp4")
    assert edited.rows()[0].kind == "動画"


def test_shot_round_trips_through_load(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.set_shot(0, 0, "shots/0001-scene1.png")
    edited.save()
    assert load(edited.path).scenes[0].beats[0].shot == "shots/0001-scene1.png"


def test_missing_beat_is_an_error(tmp_path):
    edited = Doc.load(base(tmp_path))
    with pytest.raises(ShootError):
        edited.set_shot(0, 9, "shots/x.png")


# --- ファイル名 -------------------------------------------------------
def test_next_shot_path_does_not_collide(tmp_path):
    """**通し番号にする。** ビートの添字を名前にすると、あいだに挿した
    とたんに名前と中身がずれる (ショットは移動しないので).
    """
    first, rel1 = next_shot_path(tmp_path, "intro")
    first.write_bytes(b"x")
    second, rel2 = next_shot_path(tmp_path, "intro")
    assert first != second
    assert rel1.startswith("shots/") and rel2.startswith("shots/")
    assert rel1 != rel2


def test_next_shot_path_marks_clips(tmp_path):
    _still, still_rel = next_shot_path(tmp_path, "intro", clip=False)
    _clip, clip_rel = next_shot_path(tmp_path, "intro", clip=True)
    assert still_rel.endswith(".png")
    assert clip_rel.endswith(".mp4")


def test_progress_counts_shots(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.add_beat(0, 0)
    edited.set_shot(0, 0, "shots/0001-scene1.png")
    assert progress(edited.rows()) == (1, 2)


def test_a_clip_and_a_still_never_share_a_number(tmp_path):
    """拡張子だけ違う同じ番号が並ぶと、人が探すときに取り違える."""
    still, _ = next_shot_path(tmp_path, "intro", clip=False)
    still.write_bytes(b"x")
    clip, _ = next_shot_path(tmp_path, "intro", clip=True)
    assert still.stem != clip.stem


# --- 撮る人への指示 (do) ----------------------------------------------
def test_do_round_trips_through_load(tmp_path):
    """**`say` は観る人への言葉、`do` は撮る人へのやること。** 別物として持つ."""
    edited = Doc.load(base(tmp_path))
    edited.set_text(0, 0, do="zip をダブルクリックして開く")
    edited.save()
    beat = load(edited.path).scenes[0].beats[0]
    assert beat.do == "zip をダブルクリックして開く"
    assert beat.say == ""


def test_changing_do_keeps_the_audio(tmp_path):
    """**`do` は絵にも音にも触らない。** 指示を直しただけで合成し直させない
    (`say` を直したときは落とす)。
    """
    doc = skeleton("t", "電卓", 800, 600)
    doc["scenes"][0]["beats"][0].update({"say": "そのまま", "audio": "voice/a.wav"})
    path = write(tmp_path / "plan.json", doc)

    edited = Doc.load(path)
    assert edited.set_text(0, 0, do="ボタンを押す") == ["do"]
    assert edited.raw["scenes"][0]["beats"][0]["audio"] == "voice/a.wav"


def test_an_empty_do_removes_the_key(tmp_path):
    edited = Doc.load(base(tmp_path))
    edited.set_text(0, 0, do="なにか")
    assert edited.set_text(0, 0, do="") == ["do"]
    assert "do" not in edited.raw["scenes"][0]["beats"][0]


# --- 自動収録のショット -------------------------------------------------
def test_an_auto_shot_keeps_the_same_name(tmp_path):
    """**撮り直しても増やさない。** 自動収録は plan.json に書き戻さないので、
    通し番号にすると誰も参照しないショットだけが溜まる (実際に 64 枚溜まった)."""
    first = shoot.auto_shot_path(tmp_path, "compose", 3)
    first[0].write_bytes(b"x")
    again = shoot.auto_shot_path(tmp_path, "compose", 3)
    assert first == again
    assert again[1] == "shots/compose-03.png"


def test_auto_shots_do_not_collide_with_the_ones_people_take(tmp_path):
    """人が撮ったほうは通し番号のまま (あいだにビートを挿しても動かない)."""
    auto = shoot.auto_shot_path(tmp_path, "compose", 0)[1]
    hand = shoot.next_shot_path(tmp_path, "compose")[1]
    assert auto != hand
