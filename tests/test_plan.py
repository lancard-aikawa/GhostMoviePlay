import json

import pytest

from ghostmovieplay.plan import PlanError, load

BASE = {
    "version": 1,
    "meta": {"title": "t"},
    "app": {"url": "http://x"},
    "scenes": [{"id": "s", "beats": [{"say": "hello", "hold": 1.0, "actions": []}]}],
}


def write(tmp_path, data):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_minimal_plan_loads(tmp_path):
    plan = load(write(tmp_path, BASE))
    assert plan.title == "t"
    assert len(plan.beats) == 1
    assert plan.video.width == 1280  # 既定値


def test_subtitle_falls_back_to_say(tmp_path):
    plan = load(write(tmp_path, BASE))
    assert plan.beats[0][1].caption == "hello"


def test_subtitle_overrides_say(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["subtitle"] = "短い方"
    plan = load(write(tmp_path, data))
    assert plan.beats[0][1].caption == "短い方"


def test_missing_url_rejected(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["app"] = {}
    with pytest.raises(PlanError, match="app.url"):
        load(write(tmp_path, data))


def test_unknown_action_rejected(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["actions"] = [{"type": "teleport"}]
    with pytest.raises(PlanError, match="teleport"):
        load(write(tmp_path, data))


def test_action_missing_required_key_rejected(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["actions"] = [{"type": "click"}]
    with pytest.raises(PlanError, match="selector"):
        load(write(tmp_path, data))


def test_wait_for_needs_selector_or_seconds(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["actions"] = [{"type": "wait_for"}]
    with pytest.raises(PlanError, match="wait_for"):
        load(write(tmp_path, data))

    data["scenes"][0]["beats"][0]["actions"] = [{"type": "wait_for", "seconds": 1}]
    assert load(write(tmp_path, data))


def test_select_text_requires_text(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["actions"] = [{"type": "select_text", "selector": "article"}]
    with pytest.raises(PlanError, match="text"):
        load(write(tmp_path, data))


def test_select_text_accepts_occurrence(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["scenes"][0]["beats"][0]["actions"] = [
        {"type": "select_text", "selector": "article", "text": "リンク", "occurrence": 2}
    ]
    plan = load(write(tmp_path, data))
    assert plan.beats[0][1].actions[0]["occurrence"] == 2


def test_example_plan_is_valid():
    from pathlib import Path

    plan = load(Path(__file__).parent.parent / "examples" / "demo" / "plan.json")
    assert len(plan.scenes) == 4
    assert all(b.caption for _, b in plan.beats)


# --- リポジトリに入る plan.json の不変条件 -----------------------------
def test_committed_plans_survive_a_move_to_another_machine():
    """git に入る plan.json に、機械依存の値を焼かないこと.

    examples/demo/plan.json には file:///C:/Repos/... が入っていた。作った
    マシンでしか動かないので、clone した人の手元で必ず落ちる。誰も別の場所から
    実行しなかったので残っていた。
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    plans = [p for p in root.glob("**/plan.json")
             if ".venv" not in p.parts and "node_modules" not in p.parts]
    assert plans, "検査対象の plan.json が見つからない"

    for path in plans:
        raw = path.read_text(encoding="utf-8")
        assert "file:///" not in raw, f"{path}: file:// の絶対パス"
        assert not re.search(r'"[A-Za-z]:[\/]', raw), f"{path}: ドライブ名つきの絶対パス"
        assert '"url"' not in json.loads(raw).get("voice", {}), \
            f"{path}: voice.url は機械ごとに違うので焼かない"
