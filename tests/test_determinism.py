import json

from ghostmovieplay import determinism
from ghostmovieplay.plan import Determinism, load


class FakeClock:
    def __init__(self):
        self.installed = None
        self.resumed = False

    def install(self, time=None):
        self.installed = time

    def resume(self):
        self.resumed = True


class FakePage:
    def __init__(self):
        self.clock = FakeClock()
        self.scripts = []

    def add_init_script(self, script):
        self.scripts.append(script)


def test_seed_script_embeds_the_seed():
    js = determinism.seed_script(12345)
    assert "12345" in js
    assert "Math.random" in js


def test_seed_script_coerces_to_int():
    assert "77" in determinism.seed_script("77")  # type: ignore[arg-type]


def test_nothing_applied_when_unset():
    page = FakePage()
    assert determinism.apply(page, Determinism(), verbose=False) == []
    assert page.scripts == []
    assert page.clock.installed is None


def test_seed_is_injected_as_init_script():
    page = FakePage()
    applied = determinism.apply(page, Determinism(seed=42), verbose=False)
    assert len(page.scripts) == 1
    assert "42" in page.scripts[0]
    assert any("seed=42" in a for a in applied)


def test_clock_is_installed_then_resumed():
    """install だけだと時計が止まりアニメーションが凍るので resume まで必須."""
    page = FakePage()
    determinism.apply(page, Determinism(time="2026-01-01T09:00:00"), verbose=False)
    assert page.clock.installed == "2026-01-01T09:00:00"
    assert page.clock.resumed is True


def test_both_can_be_applied():
    page = FakePage()
    applied = determinism.apply(
        page, Determinism(seed=1, time="2026-01-01T00:00:00"), verbose=False
    )
    assert len(applied) == 2


def test_determinism_loads_from_plan(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({
        "version": 1,
        "app": {"url": "http://x"},
        "determinism": {"seed": 999, "time": "2026-03-01T12:00:00", "unknown": 1},
        "scenes": [{"id": "s", "beats": [{"say": "x"}]}],
    }), encoding="utf-8")

    plan = load(p)
    assert plan.determinism.seed == 999
    assert plan.determinism.time == "2026-03-01T12:00:00"


def test_determinism_defaults_to_off(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({
        "version": 1,
        "app": {"url": "http://x"},
        "scenes": [{"id": "s", "beats": [{"say": "x"}]}],
    }), encoding="utf-8")

    plan = load(p)
    assert plan.determinism.seed is None
    assert plan.determinism.time is None
