"""Windows の自動収録のうち、アプリを起こさずに決まる部分.

**セレクタの解釈**と**使える action の判定**はウィンドウに依らないので、ここで
固定する。実際に押すところ (`Driver` の入力) は実アプリが要るので見ない。
"""

from __future__ import annotations

import pytest

from ghostmovieplay import record_windows as rw
from ghostmovieplay import windows as w
from ghostmovieplay.plan import App, Beat, Goal, Plan, Scene
from ghostmovieplay.windows import DriveError, Node


def node(cls="Button", text="", cid=0, box=(10, 20, 110, 60)) -> Node:
    left, top, right, bottom = box
    return Node(hwnd=1, cls=cls, text=text, cid=cid,
                left=left, top=top, right=right, bottom=bottom)


class FakeDriver:
    """押した順だけ覚えるドライバ."""

    def __init__(self):
        self.trace: list[tuple] = []

    def click(self, selector, double=False, modifiers=""):
        kind = "dblclick" if double else "click"
        self.trace.append((kind, selector) if not modifiers
                          else (kind, selector, modifiers))

    def select(self, selector, value):
        self.trace.append(("select", selector, value))

    def hover(self, selector):
        self.trace.append(("hover", selector))

    def type_text(self, selector, text):
        self.trace.append(("type", selector, text))

    def key(self, name):
        self.trace.append(("key", name))

    def wait_for(self, selector, seconds=None):
        self.trace.append(("wait", selector))

    def scroll_to(self, selector):
        self.trace.append(("scroll", selector))


def plan_with(*actions_per_beat):
    return Plan(scenes=[Scene(id="s", beats=[
        Beat(actions=list(a)) for a in actions_per_beat])])


# --- セレクタ ---------------------------------------------------------
def test_a_selector_needs_a_prefix():
    """**推測しない。** 何で探しているのか台本から読めなくなる."""
    with pytest.raises(DriveError, match="接頭辞"):
        w.matches(node(text="OK"), "OK")


def test_name_and_class_and_cid_match():
    button = node(cls="Button", text="OK", cid=1)
    assert w.matches(button, "name=OK")
    assert w.matches(button, "name*=O")
    assert w.matches(button, "class=Button")
    assert w.matches(button, "cid=1")
    assert not w.matches(button, "name=キャンセル")
    assert not w.matches(button, "cid=2")


def test_rows_are_not_matched_against_the_tree():
    """`row=` は一覧の中を読む担当. ここで当たると、同名のウィンドウを掴む."""
    assert not w.matches(node(text="給与明細.pdf"), "row=給与明細.pdf")


def test_an_unknown_prefix_is_reported():
    with pytest.raises(DriveError, match="知らないセレクタ"):
        w.matches(node(), "xpath=//button")


# --- 座標 -------------------------------------------------------------
def test_a_point_is_taken_inside_the_window():
    """**ウィンドウの中の割合。** 画素で焼くと、別の大きさで違うところを押す."""
    assert w.point_at("at=0.5,0.5", (100, 200, 300, 400)) == (200, 300)
    assert w.point_at("at=0,1", (100, 200, 300, 400)) == (100, 400)


def test_a_point_outside_the_window_is_refused():
    with pytest.raises(DriveError, match="0〜1"):
        w.point_at("at=1.5,0.5", (0, 0, 100, 100))
    with pytest.raises(DriveError, match="2 つの数"):
        w.point_at("at=まんなか", (0, 0, 100, 100))


def test_other_selectors_are_not_points():
    assert w.point_at("name=OK", (0, 0, 100, 100)) is None


# --- 使える action ----------------------------------------------------
def test_only_what_works_on_windows_is_allowed():
    """**効かないものを書けるままにしない** (台本にあるのに何も起きない行が残る)."""
    plan = plan_with(
        [{"type": "click", "selector": "name=OK"}],
        [{"type": "highlight", "selector": "name=OK"}],
        [{"type": "select_text", "text": "ここ"}],
    )
    bad = rw.unsupported(plan)
    assert [b.split(": ")[1] for b in bad] == ["highlight", "select_text"]


def test_the_supported_list_is_a_subset_of_the_schema():
    """台本に書けない action を「使える」と言わないこと."""
    from ghostmovieplay.plan import ACTION_SPECS

    assert set(rw.SUPPORTED) <= set(ACTION_SPECS)


# --- 操作の振り分け ---------------------------------------------------
def test_each_action_reaches_the_driver():
    driver = FakeDriver()
    for action in (
        {"type": "click", "selector": "name=OK"},
        {"type": "dblclick", "selector": "row=sample.zip"},
        {"type": "hover", "selector": "class=Button"},
        {"type": "type", "selector": "class=Edit", "text": "C:/gmp"},
        {"type": "press", "key": "Enter"},
        {"type": "select", "selector": "cid=3803", "value": "on"},
        {"type": "click", "selector": "row=給与明細.pdf", "modifiers": "Shift"},
        {"type": "wait_for", "selector": "row*=給与"},
        {"type": "scroll_to", "selector": "row*=給与"},
    ):
        rw.do(driver, action)

    assert driver.trace == [
        ("click", "name=OK"),
        ("dblclick", "row=sample.zip"),
        ("hover", "class=Button"),
        ("type", "class=Edit", "C:/gmp"),
        ("key", "Enter"),
        ("select", "cid=3803", "on"),
        ("click", "row=給与明細.pdf", "Shift"),
        ("wait", "row*=給与"),
        ("scroll", "row*=給与"),
    ]


def test_an_unsupported_action_is_refused_by_name():
    with pytest.raises(DriveError, match="highlight"):
        rw.do(FakeDriver(), {"type": "highlight", "selector": "name=OK"})


# --- 達成条件 ---------------------------------------------------------
class GoalDriver:
    def __init__(self, value):
        self.value = value

    def text(self, selector):
        return self.value


def collect():
    seen: list[tuple] = []
    return seen, lambda kind, where, message: seen.append((kind, where, message))


def test_a_goal_that_holds_says_nothing():
    """**当たっているときに出さない** (件数が信用されなくなる)."""
    seen, warn = collect()
    scene = Scene(id="s", goal=Goal(says="並んでいる", selector="cid=1001",
                                    contains="給与明細"))
    rw.check_goal(GoalDriver("給与明細_2026-07.pdf 取引先リスト.csv"), scene, warn)
    assert seen == []


def test_a_goal_that_fails_is_counted():
    seen, warn = collect()
    scene = Scene(id="s", goal=Goal(says="並んでいる", selector="cid=1001",
                                    contains="給与明細"))
    rw.check_goal(GoalDriver("(空)"), scene, warn)
    assert seen and seen[0][0] == "goal_failed"


def test_a_goal_that_cannot_be_read_is_counted():
    """**読めなかったと空だったは別。** 黙って通すと、達成条件が飾りになる."""
    seen, warn = collect()
    scene = Scene(id="s", goal=Goal(says="並んでいる", selector="cid=9999",
                                    contains="給与明細"))
    rw.check_goal(GoalDriver(None), scene, warn)
    assert seen and "確かめられません" in seen[0][2]


def test_absent_catches_what_contains_cannot():
    seen, warn = collect()
    scene = Scene(id="s", goal=Goal(says="消えている", selector="cid=1001",
                                    absent="下書き"))
    rw.check_goal(GoalDriver("下書き.docx"), scene, warn)
    assert seen and seen[0][0] == "goal_failed"


# --- 誰が撮るか -------------------------------------------------------
def test_a_window_with_actions_is_driven():
    """**判定は plan.driven の 1 か所。** record と check が同じ答えを出すこと."""
    plan = Plan(app=App(window=r"gmp\sample"),
                scenes=[Scene(id="s", beats=[
                    Beat(actions=[{"type": "click", "selector": "name=OK"}])])])
    assert plan.driven


def test_a_window_without_actions_stays_a_human_job():
    """既に撮ってある 1 本 (assist-krita) はショットだけを持っている.

    ここで「機械が撮れる」に変わると、撮り直しの効かないショットが捨てられる。
    """
    plan = Plan(app=App(window=r"gmp\sample"),
                scenes=[Scene(id="s", beats=[Beat(shot="shots/0001.png")])])
    assert plan.app.assisted
    assert not plan.driven


def test_a_plan_without_a_window_is_refused(tmp_path):
    with pytest.raises(DriveError, match="app.window"):
        rw.record(plan_with([{"type": "click", "selector": "name=OK"}]), tmp_path)


# --- 押すのではなく、その状態にする ------------------------------------
def test_a_checkbox_is_set_to_a_state_not_toggled():
    """**押すと前回の状態次第で結果が変わる。** 7-Zip は「パスワードを表示」を
    憶えているので、2 回目の収録でチェックが外れた (伏字のまま撮れた)。
    """
    import ghostmovieplay.windows as mod

    class Fake(w.Driver):
        def __init__(self, checked):
            self.title, self.timeout = "x", 1.0
            self._nodes = [node(cls="Button", text="表示", cid=3803)]
            self.checked, self.clicks = checked, 0

        def wait_for(self, selector, seconds=None):
            return (0, 0, 1, 1)

        def click(self, selector, double=False, modifiers=""):
            self.clicks += 1

    monkey = mod._api
    mod._api = lambda: (type("U", (), {
        "SendMessageW": staticmethod(lambda *a: 1 if driver.checked else 0)})(), None)
    try:
        driver = Fake(checked=True)
        driver.select("cid=3803", "on")
        assert driver.clicks == 0, "既にその状態なら押さない"

        driver = Fake(checked=False)
        driver.select("cid=3803", "on")
        assert driver.clicks == 1
    finally:
        mod._api = monkey
