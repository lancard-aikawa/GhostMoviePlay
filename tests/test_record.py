"""Pass2 の「止めない失敗」を数えて残す.

`gmp record` が通ったことは、狙った画面が映っている証明にはならない
(開始 URL がダッシュボードのままの台本が、エラーも出さずに 47 秒間まちがった
画面を映した)。光らせ損ね・選択のずれ・音声の欠落はどれも収録を止めないので、
機械が数えて timing.json に残さないと、流れていくログを目で追っていた人にしか
届かない。

Playwright は起動しない。Recorder に偽の page を渡して分岐だけ見る。
"""

import json

from ghostmovieplay import record as record_module
from ghostmovieplay.cli import main
from ghostmovieplay.plan import Beat, Plan, Scene
from ghostmovieplay.record import Recorded, Recorder


class FakeLocator:
    def __init__(self, box, text=None):
        self._box = box
        self._text = text

    def inner_text(self, timeout=None):
        if self._text is None:
            raise RuntimeError("見つかりません")
        return self._text

    @property
    def first(self):
        return self

    def bounding_box(self):
        return self._box

    def scroll_into_view_if_needed(self, timeout=None):
        pass


class FakeMouse:
    def __init__(self):
        self.trace = []

    def move(self, x, y):
        self.trace.append(("move", x, y))

    def down(self):
        self.trace.append(("down",))

    def up(self):
        self.trace.append(("up",))


class FakePage:
    """Recorder が触るところだけ生やした page.

    見つからない selector は矩形を返さない (Playwright は None を返すか
    PWError を投げるが、do() はどちらも「見つからなかった」に畳んでいる)。
    """

    def __init__(self, boxes=None, rect=None, selected="", texts=None):
        self.boxes = boxes or {}
        self.texts = texts or {}      # 達成条件が読む文字
        self.rect = rect            # FIND_TEXT_JS の戻り (None = 見つからない)
        self.selected = selected    # SNAP_RANGE_JS の戻り (確定した選択)
        self.mouse = FakeMouse()

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, expr, arg=None):
        if expr is record_module.FIND_TEXT_JS:
            return self.rect
        if expr is record_module.SNAP_RANGE_JS:
            return self.selected
        return None

    def locator(self, selector):
        return FakeLocator(self.boxes.get(selector), self.texts.get(selector))


def recorder(page, tmp_path):
    """**verbose=False で作る。** 警告を verbose に隠していたころは、
    台本が別の画面を指していても画面にもログにも何も出なかった。"""
    return Recorder(page, Plan(), tmp_path, "burn", verbose=False)


# --- highlight --------------------------------------------------------
def test_a_highlight_that_finds_nothing_is_recorded(tmp_path):
    rec = recorder(FakePage(), tmp_path)
    rec.where = "s1#0"
    rec.do({"type": "highlight", "selector": "#missing"})

    assert [w["kind"] for w in rec.warnings] == ["highlight_missing"]
    assert rec.warnings[0]["where"] == "s1#0"
    # どのセレクタを直せばいいのかまで言えていないと、件数は数えられても
    # 台本のどこを見ればいいのか分からない
    assert "#missing" in rec.warnings[0]["message"]


def test_a_highlight_that_lands_says_nothing(tmp_path):
    """当たっているのに警告を出すと、件数が信用されなくなる."""
    page = FakePage(boxes={"#tile": {"x": 1, "y": 2, "width": 30, "height": 20}})
    rec = recorder(page, tmp_path)
    rec.do({"type": "highlight", "selector": "#tile"})

    assert rec.warnings == []


# --- select_text ------------------------------------------------------
def test_text_that_is_not_on_the_page_is_recorded(tmp_path):
    rec = recorder(FakePage(rect=None), tmp_path)
    rec.where = "s2#1"
    rec.do({"type": "select_text", "text": "ほげ", "selector": "article"})

    assert [w["kind"] for w in rec.warnings] == ["select_text_missing"]
    assert rec.warnings[0]["where"] == "s2#1"


def test_a_selection_that_lands_elsewhere_is_recorded(tmp_path):
    """測り直しても違う文字列を掴んだままなら残す (3 回試して 1 件)."""
    rect = {"left": 10, "top": 20, "right": 90, "bottom": 40, "width": 80, "height": 20}
    page = FakePage(rect=rect, selected="ちがう文字列")
    rec = recorder(page, tmp_path)
    rec.do({"type": "select_text", "text": "ねらった文字列", "selector": "article"})

    assert [w["kind"] for w in rec.warnings] == ["select_text_mismatch"]
    assert "ちがう文字列" in rec.warnings[0]["message"]


# --- 音声 -------------------------------------------------------------
def test_a_missing_wav_is_recorded(tmp_path):
    """plan.json に書いてある wav が無い = そのビートだけ無音で撮れてしまう."""
    rec = recorder(FakePage(), tmp_path)
    beat = Beat(say="こんにちは", hold=0.0, audio="voice/s1-000.wav")
    entry = rec.play_beat(Scene(id="s1"), beat, 0)

    assert entry["audio"] is None
    assert [w["kind"] for w in rec.warnings] == ["audio_missing"]
    assert rec.warnings[0]["where"] == "s1#0"


# --- CLI --------------------------------------------------------------
PLAN = {
    "meta": {"title": "テスト動画", "project": "proj"},
    "app": {"url": "http://127.0.0.1:8000/"},
    "scenes": [{"id": "s1", "beats": [{"say": "ひとつめ"}]}],
}


def _fake_record(monkeypatch, tmp_path, warnings):
    result = Recorded(
        video=tmp_path / "raw.webm",
        timing=tmp_path / "timing.json",
        duration=12.5,
        skew=0.4,
        warnings=warnings,
    )
    monkeypatch.setattr(record_module, "record", lambda *a, **k: result)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
    return plan_path


def test_warnings_are_reported_but_do_not_fail_by_default(monkeypatch, tmp_path, capsys):
    """既定では止めない。飾りを 1 つ光らせ損ねただけで撮り直しにはしない."""
    plan_path = _fake_record(monkeypatch, tmp_path, [
        {"kind": "highlight_missing", "where": "s1#0", "message": "光らせる相手が見つかりません: #x"},
    ])
    assert main(["record", str(plan_path)]) == 0

    out = capsys.readouterr().out
    assert "警告 1 件" in out
    assert "#x" in out          # 件数だけでは直せない
    assert "s1#0" in out        # どのビートかも要る


def test_strict_turns_warnings_into_a_failure(monkeypatch, tmp_path):
    """CI で回すとき (docs の腐敗検知) は、通ったかどうかを終了コードで受ける."""
    plan_path = _fake_record(monkeypatch, tmp_path, [
        {"kind": "audio_missing", "where": "s1#0", "message": "音声が見つかりません"},
    ])
    assert main(["record", str(plan_path), "--strict"]) == 1


def test_strict_passes_a_clean_recording(monkeypatch, tmp_path):
    plan_path = _fake_record(monkeypatch, tmp_path, [])
    assert main(["record", str(plan_path), "--strict"]) == 0


# --- フローの達成条件 ---------------------------------------------------
def scene_with(goal):
    from ghostmovieplay.plan import Goal, Scene

    return Scene(id="good-game", goal=Goal(**goal))


def test_a_met_goal_says_nothing(tmp_path):
    """**当たっているときに出さない。** 出すと件数が信用されなくなる."""
    rec = recorder(FakePage(texts={"#result": "GOOD GAME!  21 点 (満点)"}), tmp_path)
    rec.check_goal(scene_with({"says": "満点", "selector": "#result",
                               "contains": "21 点 (満点)"}))
    assert rec.warnings == []


def test_an_unmet_goal_is_counted(tmp_path):
    """**操作が全部通っても目的を果たしたとは限らない。**

    examples/demo の盤面を釣り合いのために変えたら、セレクタは全部生きていて
    クリックも通り、gmp check まで緑のまま、ナレーションだけが嘘になった。
    """
    rec = recorder(FakePage(texts={"#result": "終了  20 点 / 満点 21"}), tmp_path)
    rec.check_goal(scene_with({"says": "満点 21 点で終わっている",
                               "selector": "#result", "contains": "21 点 (満点)"}))
    assert [w["kind"] for w in rec.warnings] == ["goal_failed"]
    assert "20 点" in rec.warnings[0]["message"]      # 実際に何だったかを出す
    assert rec.warnings[0]["where"] == "good-game"


def test_a_forbidden_state_is_counted(tmp_path):
    """「動いたが別のことをした」を捕まえるのは absent のほう."""
    rec = recorder(FakePage(texts={"#to": "宛先: 全員"}), tmp_path)
    rec.check_goal(scene_with({"says": "全員に送っていない", "selector": "#to",
                               "absent": "全員"}))
    assert [w["kind"] for w in rec.warnings] == ["goal_failed"]


def test_an_unreadable_goal_is_counted(tmp_path):
    """**確かめられないことを「通った」にしない。** 見に行った先が無いのは赤."""
    rec = recorder(FakePage(), tmp_path)
    rec.check_goal(scene_with({"says": "満点", "selector": "#gone",
                               "contains": "21"}))
    assert [w["kind"] for w in rec.warnings] == ["goal_failed"]


def test_a_scene_without_a_goal_is_left_alone(tmp_path):
    from ghostmovieplay.plan import Scene

    rec = recorder(FakePage(), tmp_path)
    rec.check_goal(Scene(id="why"))
    assert rec.warnings == []


def test_the_goal_failure_is_not_environmental():
    """**ENV_KINDS に入れない。** これは撮った環境の話ではなく台本の欠陥."""
    from ghostmovieplay.check import ENV_KINDS

    assert "goal_failed" not in ENV_KINDS
