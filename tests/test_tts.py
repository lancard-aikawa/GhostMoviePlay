import json

import pytest

from ghostmovieplay import tts
from ghostmovieplay.plan import Voice, load
from ghostmovieplay.tts.voicevox import VoiceVox, VoiceVoxError

PLAN = {
    "version": 1,
    "meta": {"title": "t"},
    "app": {"url": "http://x"},
    "voice": {"speaker": "ずんだもん", "speed": 1.2},
    "scenes": [
        {"id": "a", "beats": [{"say": "ひとつめ", "hold": 1.0}, {"say": "", "hold": 1.0}]},
        {"id": "b", "beats": [{"say": "みっつめ", "hold": 1.0}]},
    ],
}


class FakeEngine:
    """合成のかわりに呼ばれた回数を数えるだけのエンジン."""

    def __init__(self):
        self.calls = []

    def resolve_speaker(self):
        return 3

    def synthesize(self, text, speaker_id):
        self.calls.append((text, speaker_id))
        return b"RIFF____WAVEfmt "


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def fake(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(tts, "_engine", lambda voice: engine)
    return engine


def test_voice_config_is_loaded(plan_file):
    plan = load(plan_file)
    assert plan.voice.speaker == "ずんだもん"
    assert plan.voice.speed == 1.2
    assert plan.voice.engine == "voicevox"  # 既定値


def test_synthesize_skips_empty_say(plan_file, fake):
    plan = load(plan_file)
    tts.synthesize(plan, verbose=False)
    assert [t for t, _ in fake.calls] == ["ひとつめ", "みっつめ"]
    assert plan.beats[1][1].audio is None


def test_synthesize_sets_audio_paths(plan_file, fake):
    plan = load(plan_file)
    tts.synthesize(plan, verbose=False)
    assert plan.beats[0][1].audio == "voice/000_a.wav"
    assert plan.beats[2][1].audio == "voice/002_b.wav"
    assert (plan_file.parent / "voice" / "000_a.wav").exists()


def test_second_run_reuses_cached_audio(plan_file, fake):
    tts.synthesize(load(plan_file), verbose=False)
    assert len(fake.calls) == 2
    tts.synthesize(load(plan_file), verbose=False)
    assert len(fake.calls) == 2  # 増えない


def test_force_resynthesizes(plan_file, fake):
    tts.synthesize(load(plan_file), verbose=False)
    tts.synthesize(load(plan_file), force=True, verbose=False)
    assert len(fake.calls) == 4


def test_changed_voice_params_invalidate_cache(plan_file, fake):
    tts.synthesize(load(plan_file), verbose=False)
    plan = load(plan_file)
    plan.voice.speed = 0.9
    tts.synthesize(plan, verbose=False)
    assert len(fake.calls) == 4


def test_changed_text_invalidates_cache(plan_file, fake):
    tts.synthesize(load(plan_file), verbose=False)
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    data["scenes"][0]["beats"][0]["say"] = "ひとつめ(改)"
    plan_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tts.synthesize(load(plan_file), verbose=False)
    assert len(fake.calls) == 3  # 変わった1本だけ


def test_write_back_persists_audio_fields(plan_file, fake):
    plan = load(plan_file)
    tts.synthesize(plan, verbose=False)
    tts.write_back(plan)

    reloaded = load(plan_file)
    assert reloaded.beats[0][1].audio == "voice/000_a.wav"
    assert reloaded.beats[1][1].audio is None
    assert reloaded.voice.speaker == "ずんだもん"


def test_unknown_engine_rejected(plan_file):
    plan = load(plan_file)
    plan.voice.engine = "espeak"
    with pytest.raises(tts.TTSError, match="espeak"):
        tts.synthesize(plan, verbose=False)


# --- 話者の解決 -------------------------------------------------------
SPEAKERS = [
    {"name": "ずんだもん", "styles": [{"name": "ノーマル", "id": 3}, {"name": "あまあま", "id": 1}]},
    {"name": "四国めたん", "styles": [{"name": "ノーマル", "id": 2}]},
]


def engine_for(**kw):
    e = VoiceVox(Voice(**kw))
    e.speakers = lambda: SPEAKERS
    return e


def test_resolve_speaker_by_numeric_id():
    assert engine_for(speaker=7).resolve_speaker() == 7
    assert engine_for(speaker="7").resolve_speaker() == 7


def test_resolve_speaker_by_romaji_alias():
    assert engine_for(speaker="zundamon").resolve_speaker() == 3


def test_resolve_speaker_by_name_and_style():
    assert engine_for(speaker="ずんだもん", style="あまあま").resolve_speaker() == 1


def test_resolve_speaker_defaults_to_first_style():
    assert engine_for(speaker="四国めたん").resolve_speaker() == 2


def test_unknown_speaker_lists_choices():
    with pytest.raises(VoiceVoxError, match="四国めたん"):
        engine_for(speaker="だれか").resolve_speaker()


def test_unknown_style_lists_choices():
    with pytest.raises(VoiceVoxError, match="あまあま"):
        engine_for(speaker="ずんだもん", style="ささやき").resolve_speaker()
