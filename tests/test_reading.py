"""読みの指定 (voice.dict).

TTS は文脈の薄い単語を誤読する (「語」→カタリ)。エンジンのユーザー辞書は
利用者と共有の状態なので、入れたものだけを確実に戻すことが要件。
"""

import json

import pytest

from ghostmovieplay import tts
from ghostmovieplay.plan import Voice, load
from ghostmovieplay.tts.voicevox import VoiceVox


class FakeVV(VoiceVox):
    """HTTP を呼ばずに push/pop の挙動だけ見る."""

    def __init__(self, existing=()):
        super().__init__(Voice())
        self.existing = list(existing)
        self.added: list[dict] = []
        self.deleted: list[str] = []
        self._n = 0

    def user_dict(self):
        return {f"u{i}": {"surface": s} for i, s in enumerate(self.existing)}

    def _request(self, path, params, body=None, method="POST"):
        if path == "/user_dict_word":
            self._n += 1
            self.added.append(params)
            return json.dumps(f"uuid-{self._n}").encode()
        if path.startswith("/user_dict_word/"):
            self.deleted.append(path.rsplit("/", 1)[1])
            return b""
        raise AssertionError(path)


def test_string_spec_becomes_a_word():
    e = FakeVV()
    assert e.push_dict({"語": "ゴ"}) == ["uuid-1"]
    assert e.added[0]["surface"] == "語"
    assert e.added[0]["pronunciation"] == "ゴ"
    assert e.added[0]["accent_type"] == 0  # 既定
    assert e.added[0]["word_type"] == "COMMON_NOUN"


def test_dict_spec_carries_accent_and_type():
    e = FakeVV()
    e.push_dict({"冪等": {"pronunciation": "ベキトウ", "accent": 2, "type": "PROPER_NOUN"}})
    assert e.added[0]["accent_type"] == 2
    assert e.added[0]["word_type"] == "PROPER_NOUN"


def test_existing_words_are_left_alone():
    """利用者が自分で登録した読みを触らない (消してしまわないため)."""
    e = FakeVV(existing=["語"])
    assert e.push_dict({"語": "ゴ", "冪等": "ベキトウ"}) == ["uuid-1"]
    assert [a["surface"] for a in e.added] == ["冪等"]


def test_empty_dict_is_a_noop():
    e = FakeVV()
    assert e.push_dict({}) == []
    assert e.added == []


def test_pop_deletes_only_what_was_added():
    e = FakeVV(existing=["語"])
    added = e.push_dict({"語": "ゴ", "冪等": "ベキトウ"})
    e.pop_dict(added)
    assert e.deleted == ["uuid-1"]


# --- 合成との組み合わせ -----------------------------------------------
class DictEngine:
    def __init__(self):
        self.pushed = self.popped = 0
        self.order: list[str] = []

    def resolve_speaker(self):
        return 3

    def credit(self):
        return "VOICEVOX:テスト"

    def push_dict(self, entries):
        self.pushed += 1
        self.order.append("push")
        return ["u1"]

    def pop_dict(self, uuids):
        self.popped += 1
        self.order.append("pop")

    def synthesize(self, text, speaker_id):
        self.order.append("say")
        return b"RIFF____WAVEfmt "


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({
        "version": 1,
        "app": {"url": "http://x"},
        "voice": {"speaker": "ずんだもん", "dict": {"語": "ゴ"}},
        "scenes": [{"id": "s", "beats": [{"say": "この語は"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_dict_is_pushed_before_and_popped_after(plan_file, monkeypatch):
    engine = DictEngine()
    monkeypatch.setattr(tts, "_engine", lambda voice: engine)
    tts.synthesize(load(plan_file), plan_file.parent, verbose=False)
    assert engine.order == ["push", "say", "pop"]


def test_dict_is_popped_even_when_synthesis_fails(plan_file, monkeypatch):
    engine = DictEngine()
    engine.synthesize = lambda t, s: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(tts, "_engine", lambda voice: engine)
    with pytest.raises(RuntimeError):
        tts.synthesize(load(plan_file), plan_file.parent, verbose=False)
    assert engine.popped == 1  # 辞書を残したまま終わらない


def test_reading_change_invalidates_the_cache(plan_file, monkeypatch):
    """読みを変えれば音が変わるので、再合成されねばならない."""
    engine = DictEngine()
    monkeypatch.setattr(tts, "_engine", lambda voice: engine)

    tts.synthesize(load(plan_file), plan_file.parent, verbose=False)
    first = engine.order.count("say")

    plan = load(plan_file)
    plan.voice.dict = {"語": "カタリ"}
    tts.synthesize(plan, plan_file.parent, verbose=False)
    assert engine.order.count("say") == first + 1


def test_same_reading_reuses_the_cache(plan_file, monkeypatch):
    engine = DictEngine()
    monkeypatch.setattr(tts, "_engine", lambda voice: engine)
    tts.synthesize(load(plan_file), plan_file.parent, verbose=False)
    tts.synthesize(load(plan_file), plan_file.parent, verbose=False)
    assert engine.order.count("say") == 1
