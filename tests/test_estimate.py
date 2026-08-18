"""尺の見積り.

「90 秒で」と依頼文に書いても守られないので、機械側で数えて言う。
"""

import wave

import pytest

from ghostmovieplay import settings
from ghostmovieplay.cli import _report_length
from ghostmovieplay.plan import AUDIO_TAIL, Beat, Plan, Scene, Video, estimate


def make_plan(beats, leader=2.5, trailer=1.2) -> Plan:
    return Plan(
        video=Video(leader=leader, trailer=trailer),
        scenes=[Scene(id="a", beats=beats)],
    )


def write_wav(path, seconds: float, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))


# --- 音声が無いとき ---------------------------------------------------
def test_leader_and_trailer_are_included():
    seconds, measured = estimate(make_plan([]))
    assert seconds == pytest.approx(3.7)
    assert measured is False


def test_hold_is_the_floor():
    seconds, _ = estimate(make_plan([Beat(say="", hold=4.0)]))
    assert seconds == pytest.approx(3.7 + 4.0)


def test_long_captions_need_more_than_hold():
    """読み切れない字幕は hold より長く見積もる (hold の付け忘れを拾う)."""
    beat = Beat(say="あ" * 80, hold=0.5)
    seconds, _ = estimate(make_plan([beat]), reading_cps=8.0, pad=0.6)
    assert seconds == pytest.approx(3.7 + 80 / 8.0 + 0.6)


def test_reading_speed_changes_the_estimate():
    beat = Beat(say="あ" * 40, hold=0.0)
    slow, _ = estimate(make_plan([beat]), reading_cps=4.0, pad=0.0)
    fast, _ = estimate(make_plan([beat]), reading_cps=8.0, pad=0.0)
    assert slow - fast == pytest.approx(5.0)


# --- 音声があるとき ---------------------------------------------------
def test_audio_length_wins_and_is_reported_as_measured(tmp_path):
    """音声の尺がビートの尺そのもの. あるなら実測で数える."""
    (tmp_path / "voice").mkdir()
    write_wav(tmp_path / "voice" / "0.wav", 3.0)

    plan = make_plan([Beat(say="みじかい", hold=0.5, audio="voice/0.wav")])
    seconds, measured = estimate(plan, tmp_path)

    assert measured is True
    assert seconds == pytest.approx(3.7 + 3.0 + AUDIO_TAIL, abs=0.01)


def test_hold_still_applies_over_a_short_audio(tmp_path):
    (tmp_path / "voice").mkdir()
    write_wav(tmp_path / "voice" / "0.wav", 0.5)

    plan = make_plan([Beat(say="みじかい", hold=6.0, audio="voice/0.wav")])
    seconds, _ = estimate(plan, tmp_path)
    assert seconds == pytest.approx(3.7 + 6.0)


def test_missing_audio_falls_back_to_hold(tmp_path):
    """合成前の plan.json でも数えられること."""
    plan = make_plan([Beat(say="ない", hold=2.0, audio="voice/nope.wav")])
    seconds, measured = estimate(plan, tmp_path)
    assert measured is False
    assert seconds == pytest.approx(3.7 + 2.0)


def test_estimate_matches_record_margin():
    """record が使う余白と同じ定数で数えること (別々に書くとズレる)."""
    from ghostmovieplay import record

    assert record.AUDIO_TAIL == AUDIO_TAIL


# --- 目標尺との突き合わせ ---------------------------------------------
def _resolved(**project):
    return settings.resolve(project={"series": project}, use_env=False)


def test_over_target_is_reported(capsys):
    plan = make_plan([Beat(say="あ" * 400, hold=0.0)])
    _report_length(plan, _resolved(target_seconds=30.0, tolerance=0.0))

    out = capsys.readouterr().out
    assert "目標の 30 秒を" in out
    assert "超えています" in out


def test_within_tolerance_stays_quiet(capsys):
    plan = make_plan([Beat(say="あ" * 200, hold=0.0)])   # 約 29 秒
    _report_length(plan, _resolved(target_seconds=25.0, tolerance=0.5))

    out = capsys.readouterr().out
    assert "尺" in out
    assert "超えています" not in out


def test_length_is_reported_even_without_a_target(capsys):
    _report_length(make_plan([Beat(say="あ", hold=1.0)]), settings.resolve(use_env=False))
    assert "尺" in capsys.readouterr().out
