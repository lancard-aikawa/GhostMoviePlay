from ghostmovieplay.subtitles import _ts, build_ass, wrap

TIMING = {
    "video": {"width": 1280, "height": 720, "fps": 30},
    "beats": [
        {"caption": "最初の字幕", "start": 1.0, "end": 3.5},
        {"caption": "", "start": 3.5, "end": 4.0},          # 空はイベントにしない
        {"caption": "みじかい", "start": 4.0, "end": 4.05},  # 短すぎる尺は伸ばす
    ],
}


def test_timestamp_format():
    assert _ts(0) == "0:00:00.00"
    assert _ts(1.5) == "0:00:01.50"
    assert _ts(75.25) == "0:01:15.25"
    assert _ts(3725.5) == "1:02:05.50"
    assert _ts(-1) == "0:00:00.00"


def test_wrap_breaks_after_punctuation():
    text = "あいうえおかきくけこ、さしすせそたちつてと。"
    assert wrap(text, 8) == "あいうえおかきくけこ、\\Nさしすせそたちつてと。"


def test_wrap_keeps_existing_newlines():
    assert wrap("ab\ncd", 40) == "ab\\Ncd"


def test_wrap_forces_break_without_punctuation():
    out = wrap("あ" * 40, 10)
    assert "\\N" in out


def test_build_ass_skips_empty_captions():
    ass = build_ass(TIMING)
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 2


def test_build_ass_extends_too_short_beats():
    ass = build_ass(TIMING)
    last = [line for line in ass.splitlines() if line.startswith("Dialogue:")][-1]
    assert "0:00:04.00,0:00:04.40" in last


def test_build_ass_uses_video_resolution():
    ass = build_ass(TIMING)
    assert "PlayResX: 1280" in ass
    assert "PlayResY: 720" in ass


def test_build_ass_escapes_braces():
    ass = build_ass({"video": {}, "beats": [{"caption": "a{b}c", "start": 0, "end": 2}]})
    assert "a(b)c" in ass
