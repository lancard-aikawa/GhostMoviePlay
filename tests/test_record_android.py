"""Android の自動収録のうち、端末を繋がずに決まる部分."""

from __future__ import annotations

import pytest

from ghostmovieplay import record_android as ra
from ghostmovieplay.android import DriveError
from ghostmovieplay.plan import Beat, Goal, Plan, Scene


class FakeDriver:
    """押した順だけ覚えるドライバ."""

    width, height = 720, 1604

    def __init__(self, has=()):
        self.trace: list[tuple] = []
        self.has = set(has)

    def tap(self, selector):
        self.trace.append(("tap", selector))

    def type_text(self, selector, text):
        self.trace.append(("type", selector, text))

    def key(self, name):
        self.trace.append(("key", name))

    def wait_for(self, selector, timeout=10.0):
        self.trace.append(("wait", selector))

    def swipe(self, *a):
        self.trace.append(("swipe",))

    def refresh(self):
        pass

    def find(self, selector):
        return object() if selector in self.has else None


def plan_with(*actions_per_beat):
    return Plan(scenes=[Scene(id="s", beats=[
        Beat(actions=list(a)) for a in actions_per_beat])])


# --- 使える action ------------------------------------------------------
def test_only_what_works_on_android_is_allowed():
    """**効かないものを書けるままにしない。**

    台本にあるのに何も起きない行が残ると、動画と説明が黙ってずれる。
    """
    bad = ra.unsupported(plan_with(
        [{"type": "click", "selector": "desc=送信"}],
        [{"type": "highlight", "selector": "desc=x"}, {"type": "goto", "url": "x"}],
    ))
    assert bad == ["s#1: highlight", "s#1: goto"]


def test_highlight_is_not_supported():
    """疑似カーソルも枠も DOM に注入した JS なので、他人のアプリには出せない."""
    assert "highlight" not in ra.SUPPORTED


def test_a_clean_plan_has_nothing_to_report():
    assert ra.unsupported(plan_with([{"type": "click", "selector": "desc=送信"}])) == []


# --- 1 つずつの操作 -----------------------------------------------------
def test_a_click_becomes_a_tap(monkeypatch):
    monkeypatch.setattr(ra.time, "sleep", lambda s: None)
    d = FakeDriver()
    ra.do(d, {"type": "click", "selector": "desc=送信"})
    assert d.trace == [("tap", "desc=送信")]


def test_typing_goes_through_the_field(monkeypatch):
    monkeypatch.setattr(ra.time, "sleep", lambda s: None)
    d = FakeDriver()
    ra.do(d, {"type": "type", "selector": "id=title", "text": "9月の全体連絡"})
    assert d.trace == [("type", "id=title", "9月の全体連絡")]


def test_wait_for_without_a_selector_just_waits(monkeypatch):
    slept = []
    monkeypatch.setattr(ra.time, "sleep", slept.append)
    d = FakeDriver()
    ra.do(d, {"type": "wait_for", "seconds": 2})
    assert d.trace == [] and slept == [2.0]


def test_an_unsupported_action_is_refused():
    with pytest.raises(DriveError, match="使えない action"):
        ra.do(FakeDriver(), {"type": "eval", "expr": "1"})


# --- 送って探す ---------------------------------------------------------
def test_scrolling_stops_as_soon_as_it_shows(monkeypatch):
    monkeypatch.setattr(ra.time, "sleep", lambda s: None)
    d = FakeDriver(has={"desc=送信"})
    ra.scroll_to(d, "desc=送信")
    assert d.trace == []          # 見えているなら送らない


def test_scrolling_gives_up_loudly(monkeypatch):
    """**出なければ落とす。** 見えていない画面を撮ると、黙って別の絵になる."""
    monkeypatch.setattr(ra.time, "sleep", lambda s: None)
    d = FakeDriver()
    with pytest.raises(DriveError, match="送っても出ません"):
        ra.scroll_to(d, "desc=ありえない")
    assert len([x for x in d.trace if x[0] == "swipe"]) == ra.SCROLL_TRIES


# --- 端末を選ぶ ---------------------------------------------------------
def device(handle):
    from ghostmovieplay.capture_android import Device

    return Device(handle, "moto g05", "Android 15", 720, 1604)


def test_one_device_is_picked_without_asking(monkeypatch):
    monkeypatch.setattr(ra.capture_android, "windows", lambda: [device("AAA")])
    assert ra.pick_device().handle == "AAA"


def test_two_devices_need_a_choice(monkeypatch):
    """**黙って 1 台目を選ばない。** 別の端末で撮れてしまう."""
    monkeypatch.setattr(ra.capture_android, "windows",
                        lambda: [device("AAA"), device("BBB")])
    with pytest.raises(DriveError, match="2 台あります"):
        ra.pick_device()


def test_no_device_says_how_to_check(monkeypatch):
    monkeypatch.setattr(ra.capture_android, "windows", lambda: [])
    with pytest.raises(DriveError, match="adb devices"):
        ra.pick_device()


# --- シーンの達成条件 ---------------------------------------------------
class GoalDriver(FakeDriver):
    """画面の文字を決め打ちで返すドライバ."""

    def __init__(self, texts):
        super().__init__()
        self.texts = texts

    def text(self, selector):
        return self.texts.get(selector)


def goal_warnings(texts, goal):
    got: list[tuple] = []
    scene = Scene(id="s", goal=goal, beats=[Beat()])
    ra.check_goal(GoalDriver(texts), scene,
                  lambda kind, where, message: got.append((kind, where, message)))
    return got


def test_a_met_goal_says_nothing():
    """**当たっているときに出さない** —— 件数が信用されなくなる."""
    goal = Goal(says="送信済みになる", selector="id=row", contains="送信済み")
    assert goal_warnings({"id=row": "9月の全体連絡 送信済み"}, goal) == []


def test_a_missed_goal_is_a_warning():
    goal = Goal(says="送信済みになる", selector="id=row", contains="送信済み")
    kind, where, message = goal_warnings({"id=row": "9月の全体連絡 下書き"}, goal)[0]
    assert kind == "goal_failed" and where == "s"
    assert "送信済みになる" in message      # 人が読む言い方をそのまま出す


def test_a_forbidden_state_is_a_warning():
    """`absent` は「動いたが別のことをした」を捕まえる (contains では捕まらない)."""
    goal = Goal(says="アンケートは付かない", selector="id=row", absent="要回答")
    assert goal_warnings({"id=row": "9月の全体連絡 要回答"}, goal)[0][0] == "goal_failed"


def test_a_goal_that_cannot_be_read_is_a_warning():
    """**確かめられないことを、満たしたことにしない**."""
    goal = Goal(says="送信済みになる", selector="id=row", contains="送信済み")
    assert "見つかりません" in goal_warnings({}, goal)[0][2]


def test_no_goal_is_not_a_warning():
    assert goal_warnings({}, None) == []
