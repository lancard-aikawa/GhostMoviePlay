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
    def __init__(self, box):
        self._box = box

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

    def __init__(self, boxes=None, rect=None, selected=""):
        self.boxes = boxes or {}
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
        return FakeLocator(self.boxes.get(selector))


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
