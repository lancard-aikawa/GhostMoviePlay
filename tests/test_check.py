"""全部の台本を撮り直して、まだアプリに当たっているかを見る (`gmp check`).

判定そのものは `gmp record` の警告に乗っているので、ここが見るのは
**束ね方** —— どの plan.json を拾うか、何を赤と数えるか、1 本落ちても
掃きが止まらないか。Playwright は起動しない (収録は差し替える)。
"""

import json

import pytest

from ghostmovieplay import check
from ghostmovieplay import record as record_module
from ghostmovieplay.cli import main
from ghostmovieplay.record import Recorded

PLAN = {
    "meta": {"title": "テスト動画", "project": "proj"},
    "app": {"url": "http://127.0.0.1:8000/"},
    "scenes": [{"id": "s1", "beats": [{"say": "ひとつめ"}]}],
}


def write_plan(directory, plan=None):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "plan.json"
    target.write_text(json.dumps(plan or PLAN, ensure_ascii=False), encoding="utf-8")
    return target


def recorded(warnings=(), duration=12.5):
    return Recorded(video=None, timing=None, duration=duration, skew=0.0,
                    warnings=list(warnings))


def warning(kind, where="s1#0", message="なにか"):
    return {"kind": kind, "where": where, "message": message}


# --- 探す -------------------------------------------------------------
def test_plans_are_found_under_the_project(tmp_path):
    write_plan(tmp_path / "docs" / "video" / "intro")
    write_plan(tmp_path / "examples" / "demo")

    found = check.find_plans(tmp_path)
    # 掃く順はパス順にする (走らせるたびに入れ替わると、CI のログを
    # 前回と見比べられない)
    assert [p.parent.name for p in found] == ["intro", "demo"]


def test_dependencies_and_generated_trees_are_not_walked(tmp_path):
    """plan.json はプロジェクトが git に入れるもの. 依存の中を掘る意味が無い."""
    write_plan(tmp_path / "docs" / "video" / "intro")
    write_plan(tmp_path / "node_modules" / "somepkg")
    write_plan(tmp_path / ".venv" / "x")
    write_plan(tmp_path / ".git" / "y")

    found = check.find_plans(tmp_path)
    assert [p.parent.name for p in found] == ["intro"]


def test_a_single_plan_can_be_given_directly(tmp_path):
    plan_path = write_plan(tmp_path / "one")
    assert check.find_plans(plan_path) == [plan_path]


# --- 数える -----------------------------------------------------------
def test_a_recording_without_warnings_is_green(tmp_path):
    plan_path = write_plan(tmp_path / "one")
    result = check.check_one(plan_path, lambda plan, path: recorded())

    assert result.state == check.OK
    assert not result.red
    assert result.seconds == 12.5


def test_a_selector_that_no_longer_exists_is_red(tmp_path):
    """**これが腐敗検知の本体。** 説明の指し先が消えたら赤."""
    plan_path = write_plan(tmp_path / "one")
    result = check.check_one(plan_path, lambda plan, path: recorded([
        warning("highlight_missing", message="光らせる相手が見つかりません: #tile"),
    ]))

    assert result.state == check.STALE
    assert result.red
    assert "#tile" in result.stale[0]["message"]


def test_the_environment_warnings_are_counted_but_not_red(tmp_path):
    """wav はプロジェクトの外に出る生成物、leader は機械の速さ.

    clone したばかりの CI では必ず出るので、赤にすると毎回赤になる。
    **黙って捨てはしない** —— 件数は必ず出す。
    """
    plan_path = write_plan(tmp_path / "one")
    result = check.check_one(plan_path, lambda plan, path: recorded([
        warning("audio_missing"), warning("leader_short", where=None),
    ]))

    assert result.state == check.OK
    assert len(result.ignored) == 2

    report = check.Report([result])
    assert "環境の警告 2 件" in report.summary()


def test_an_unknown_kind_is_red(tmp_path):
    """分類し忘れは**赤に倒す**. 素通りさせると「赤が無い」が嘘になる."""
    plan_path = write_plan(tmp_path / "one")
    result = check.check_one(plan_path, lambda plan, path: recorded([
        warning("something_new_nobody_classified"),
    ]))

    assert result.red


def test_the_marks_survive_a_japanese_console():
    """cp932 のコンソールでは `✓` が `?` に化ける.

    飾りが化けるのは我慢できるが、化けるのが**判定そのもの**だと読めない。
    """
    for mark in check.MARK.values():
        assert mark.isascii()


# --- 落ちても止まらない -----------------------------------------------
def test_a_broken_plan_is_red_without_a_traceback(tmp_path):
    directory = tmp_path / "one"
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text("{ not json", encoding="utf-8")

    result = check.check_one(directory / "plan.json", lambda plan, path: recorded())
    assert result.state == check.BROKEN
    # 理由の頭にフルパスを付けない (行にパスは出ている)
    assert not result.detail.startswith(str(directory))


def test_a_recording_that_dies_is_red_and_the_sweep_goes_on(tmp_path):
    plan_path = write_plan(tmp_path / "one")

    def die(plan, path):
        raise RuntimeError("chromium が落ちました")

    result = check.check_one(plan_path, die)
    assert result.state == check.BROKEN
    assert "chromium" in result.detail


# --- CLI --------------------------------------------------------------
@pytest.fixture
def project(tmp_path):
    write_plan(tmp_path / "docs" / "video" / "intro")
    write_plan(tmp_path / "docs" / "video" / "second")
    return tmp_path


def test_check_lists_without_recording(project, monkeypatch, capsys):
    def never(*a, **k):
        raise AssertionError("--list は撮らない")

    monkeypatch.setattr(record_module, "record", never)
    assert main(["check", str(project), "--list"]) == 0
    assert capsys.readouterr().out.count("plan.json") == 2


def test_check_is_green_when_every_plan_still_lands(project, monkeypatch):
    monkeypatch.setattr(record_module, "record", lambda *a, **k: recorded())
    assert main(["check", str(project)]) == 0


def test_check_is_red_when_a_plan_has_gone_stale(project, monkeypatch, capsys):
    monkeypatch.setattr(record_module, "record", lambda *a, **k: recorded([
        warning("highlight_missing", message="光らせる相手が見つかりません: #gone"),
    ]))
    assert main(["check", str(project)]) == 1

    out = capsys.readouterr().out
    assert "赤 2 本" in out
    # 収録は 1 本ずつ長い。上に流れた警告は CI のログでは遠すぎるので、
    # 最後にもう一度まとめて出す
    assert out.rstrip().endswith("#gone")


def test_check_says_so_when_there_is_nothing_to_check(tmp_path):
    assert main(["check", str(tmp_path)]) == 1
