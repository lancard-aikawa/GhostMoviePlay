"""クレジット表記まわり.

VOICEVOX は生成音声を使った作品にキャラクター名を含むクレジットを求めるので、
音声を焼いたら必ずクレジットも焼かれる、という関係を壊さないようにする。
"""

import json

import pytest

from ghostmovieplay import tts
from ghostmovieplay.plan import Voice, load
from ghostmovieplay.subtitles import build_ass
from ghostmovieplay.tts.voicevox import VoiceVox

SPEAKERS = [
    {"name": "ずんだもん", "styles": [{"name": "ノーマル", "id": 3}, {"name": "あまあま", "id": 1}]},
    {"name": "四国めたん", "styles": [{"name": "ノーマル", "id": 2}]},
]

TIMING = {
    "video": {"width": 1280, "height": 720},
    "duration": 30.0,
    "credit": "VOICEVOX:ずんだもん",
    "beats": [{"caption": "字幕", "start": 1.0, "end": 3.0}],
}


def engine_for(**kw):
    e = VoiceVox(Voice(**kw))
    e.speakers = lambda: SPEAKERS
    return e


# --- 話者名の解決 -----------------------------------------------------
def test_credit_uses_resolved_name():
    e = engine_for(speaker="zundamon")
    e.resolve_speaker()
    assert e.credit() == "VOICEVOX:ずんだもん"


def test_credit_from_numeric_id_is_looked_up():
    e = engine_for(speaker=2)
    assert e.resolve_speaker() == 2
    assert e.credit() == "VOICEVOX:四国めたん"


def test_unknown_numeric_id_still_works_without_name():
    e = engine_for(speaker=999)
    assert e.resolve_speaker() == 999
    assert e.credit() == "VOICEVOX"


def test_credit_survives_style_selection():
    e = engine_for(speaker="ずんだもん", style="あまあま")
    assert e.resolve_speaker() == 1
    assert e.credit() == "VOICEVOX:ずんだもん"


# --- plan への反映 ----------------------------------------------------
class FakeEngine:
    def resolve_speaker(self):
        return 3

    def credit(self):
        return "VOICEVOX:ずんだもん"

    def synthesize(self, text, speaker_id):
        return b"RIFF____WAVEfmt "


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({
        "version": 1,
        "app": {"url": "http://x"},
        "voice": {"speaker": "ずんだもん"},
        "scenes": [{"id": "s", "beats": [{"say": "こんにちは"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_synthesize_fills_credit(plan_file, monkeypatch):
    monkeypatch.setattr(tts, "_engine", lambda voice: FakeEngine())
    plan = load(plan_file)
    tts.synthesize(plan, verbose=False)
    assert plan.voice.credit == "VOICEVOX:ずんだもん"


def test_handwritten_credit_is_kept(plan_file, monkeypatch):
    monkeypatch.setattr(tts, "_engine", lambda voice: FakeEngine())
    plan = load(plan_file)
    plan.voice.credit = "自前の表記"
    tts.synthesize(plan, verbose=False)
    assert plan.voice.credit == "自前の表記"


def test_credit_is_persisted_by_write_back(plan_file, monkeypatch):
    monkeypatch.setattr(tts, "_engine", lambda voice: FakeEngine())
    plan = load(plan_file)
    tts.synthesize(plan, verbose=False)
    tts.write_back(plan)
    assert load(plan_file).voice.credit == "VOICEVOX:ずんだもん"


# --- 焼き込み ---------------------------------------------------------
def credit_lines(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:") and ",Credit,," in ln]


def test_credit_spans_the_whole_video():
    lines = credit_lines(build_ass(TIMING))
    assert len(lines) == 1
    assert "0:00:00.00,0:00:30.00" in lines[0]
    assert "VOICEVOX:ずんだもん" in lines[0]


def test_credit_style_is_defined():
    assert "Style: Credit," in build_ass(TIMING)


def test_credit_can_be_disabled():
    assert credit_lines(build_ass(TIMING, credit=False)) == []


def test_no_credit_line_without_credit_text():
    timing = dict(TIMING, credit=None)
    assert credit_lines(build_ass(timing)) == []


def test_no_credit_line_without_duration():
    timing = dict(TIMING, duration=0)
    assert credit_lines(build_ass(timing)) == []


def test_subtitles_still_rendered_alongside_credit():
    ass = build_ass(TIMING)
    assert len([ln for ln in ass.splitlines() if ",Default,," in ln]) == 1
