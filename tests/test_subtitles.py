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


# --- 縦画面 -------------------------------------------------------------
def test_the_font_follows_the_short_side():
    """**大きさは短いほうの辺で決める。**

    height から出していたので、縦長 (720x1604) では 98px の文字を幅 720 に
    並べることになり、字幕が両端で切れた (実際に切れた)。横長では height が
    たまたま短いほうの辺だったので、縦の 1 本を撮るまで露見しなかった。
    """
    from ghostmovieplay.subtitles import layout

    assert layout(1280, 720)["size"] == layout(720, 1280)["size"]
    assert layout(720, 1604)["size"] == layout(1280, 720)["size"]


def test_the_landscape_default_does_not_move():
    """既存の 1 本の折り返しを変えない (変えると全部を仕上げ直すことになる)."""
    from ghostmovieplay.subtitles import layout

    assert layout(1280, 720, 26)["limit"] == 26


def test_a_narrow_screen_wraps_sooner():
    """狭い画面では設定の上限より先に幅が効く."""
    from ghostmovieplay.subtitles import layout

    assert layout(720, 1604, 26)["limit"] < 26


def test_the_hard_break_still_fits_the_width():
    """**`wrap` は句読点が無ければ limit + 6 まで伸ばす。** そこまで入ること.

    上限だけ見ていると、句読点の無い原稿でだけ黙ってはみ出す。
    """
    from ghostmovieplay.subtitles import CHAR_EM, layout

    for width, height in ((1280, 720), (720, 1604), (1080, 1920), (1920, 1080)):
        box = layout(width, height, 26)
        usable = width - 2 * box["margin_h"]
        assert (box["limit"] + 6) * box["size"] * CHAR_EM <= usable, (width, height)
