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


# --- 撮らずに分かるもの (--dry) ---------------------------------------
def dry(tmp_path, **overrides):
    plan = json.loads(json.dumps(PLAN))
    for key, value in overrides.items():
        plan[key] = {**plan.get(key, {}), **value} if isinstance(value, dict) else value
    return check.check_one(write_plan(tmp_path / "one", plan))


def test_a_baked_file_url_is_red(tmp_path):
    """作った機械では動き続けるので、誰かが clone するまで露見しない."""
    result = dry(tmp_path, app={"url": "file:///C:/Repos/demo/index.html"})

    assert result.red
    assert result.stale[0]["kind"] == "machine_path"


def test_a_baked_drive_letter_is_red(tmp_path):
    result = dry(tmp_path, app={"cwd": "C:\\Repos\\demo"})

    assert result.red
    assert result.stale[0]["kind"] == "machine_path"


def test_a_baked_voice_url_is_red(tmp_path):
    """接続先は機械ごとに違う. 焼くと別のマシンで繋がらない先が残る."""
    result = dry(tmp_path, voice={"url": "http://127.0.0.1:50021"})

    assert result.red
    assert result.stale[0]["kind"] == "machine_url"


def test_a_caption_that_will_not_fit_is_red(tmp_path):
    """**上限は依頼文に書いてあるだけで、誰も数えていなかった。**

    行数は `subtitles.wrap` に数えさせる (検査と実際の折り返しが別実装だと、
    通った字幕が本番で 3 行になる)。
    """
    long = "この字幕はとても長いので既定の上限では二行に収まらず、読み切る前に" \
           "次のビートへ進んでしまいます。だから撮る前に数えて言う必要があります。"
    plan = json.loads(json.dumps(PLAN))
    plan["scenes"][0]["beats"][0]["subtitle"] = long
    result = check.check_one(write_plan(tmp_path / "one", plan))

    assert result.red
    assert result.stale[0]["kind"] == "subtitle_too_long"
    assert result.stale[0]["where"] == "s1#0"


def test_a_clean_plan_reads_green_without_recording(tmp_path):
    result = dry(tmp_path)

    assert result.state == check.OK
    assert result.detail == "読めました"
    assert result.seconds is None      # 撮っていないので尺は無い


def test_recording_also_reports_what_reading_found(tmp_path):
    """**速いほうで赤だったものが本番で緑になったら検査の意味が無い。**"""
    plan = json.loads(json.dumps(PLAN))
    plan["app"]["url"] = "file:///C:/Repos/demo/index.html"
    plan_path = write_plan(tmp_path / "one", plan)

    result = check.check_one(plan_path, lambda plan, path: recorded())
    assert result.red
    assert result.stale[0]["kind"] == "machine_path"


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


def test_dry_does_not_record(project, monkeypatch):
    def never(*a, **k):
        raise AssertionError("--dry は撮らない")

    monkeypatch.setattr(record_module, "record", never)
    assert main(["check", str(project), "--dry"]) == 0


def test_dry_is_red_on_a_baked_absolute_path(project, monkeypatch, capsys):
    plan = json.loads(json.dumps(PLAN))
    plan["app"]["url"] = "file:///C:/Repos/demo/index.html"
    write_plan(project / "docs" / "video" / "intro", plan)

    monkeypatch.setattr(record_module, "record", lambda *a, **k: recorded())
    assert main(["check", str(project), "--dry"]) == 1
    assert "file://" in capsys.readouterr().out


# --- 支援収録は撮り直せない -------------------------------------------
ASSIST_PLAN = {
    "meta": {"title": "手で撮った 1 本"},
    "app": {"window": "電卓"},
    "scenes": [{"id": "s1", "beats": [{"say": "ひとこと", "shot": "shots/a.png"}]}],
}


def _assist(tmp_path, plan=None):
    target = tmp_path / "plan.json"
    target.write_text(json.dumps(plan or ASSIST_PLAN, ensure_ascii=False),
                      encoding="utf-8")
    return target


def test_an_assisted_plan_is_not_recorded(tmp_path):
    """**素材は生成物でプロジェクトの外にある。** 撮り直しようがない."""
    def boom(plan, path):
        pytest.fail("支援収録を撮り直そうとした")

    result = check.check_one(_assist(tmp_path), boom)
    assert result.state == check.SKIP


def test_a_skipped_plan_is_not_red(tmp_path):
    """検査できないだけで、壊れてはいない (CI を赤にしない)."""
    result = check.check_one(_assist(tmp_path), lambda plan, path: None)
    assert result.red is False


def test_a_skipped_plan_does_not_count_as_passing(tmp_path):
    """**「赤が無い = 全部当たっている」を嘘にしない。**"""
    report = check.Report()
    report.results.append(check.check_one(_assist(tmp_path), lambda p, q: None))
    text = report.summary()
    assert "0 / 1 本が通りました" in text
    assert "撮り直せないので検査していません" in text


def test_faults_visible_without_recording_still_go_red(tmp_path):
    """撮らなくても分かる欠陥は支援収録でも赤にする (二重基準を作らない)."""
    plan = json.loads(json.dumps(ASSIST_PLAN))
    plan["app"]["cwd"] = r"C:\Repos\mywork\GhostMoviePlay"
    result = check.check_one(_assist(tmp_path, plan), lambda p, q: None)
    assert result.state == check.STALE
    assert result.red is True


# --- 撮り直せるかどうかの見分け ----------------------------------------
def android_plan(directory, actions):
    """Android の 1 本。`actions` があれば機械が撮れる."""
    doc = {
        "meta": {"title": "Android の 1 本", "project": "proj"},
        "app": {"package": "com.example.app"},
        "scenes": [{"id": "s1", "beats": [{"say": "ひとつめ", "actions": actions}]}],
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "plan.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_plan_people_shoot_is_not_counted_as_checked(tmp_path):
    """人が撮った素材は clone した機械に無いので、撮り直せない."""
    path = android_plan(tmp_path / "hand", [])
    result = check.check_one(path, lambda plan, p: pytest.fail("撮ってはいけない"))
    assert result.state == check.SKIP


def test_an_android_plan_with_actions_is_actually_checked(tmp_path):
    """**`gmp record` が自動で撮れるものを「検査していない」に混ぜない。**

    `assisted` だけで見ていたころ、record は自動で撮るのに check は
    「撮り直せません」と数えていた。
    """
    path = android_plan(tmp_path / "auto", [{"type": "click", "selector": "desc=投稿"}])
    result = check.check_one(path, lambda plan, p: recorded())
    assert result.state == check.OK


def test_a_missing_device_is_not_red(tmp_path):
    """端末が無いのは台本のせいではない。赤にすると CI が常に赤になる."""
    path = android_plan(tmp_path / "auto", [{"type": "click", "selector": "desc=投稿"}])

    def no_device(plan, p):
        raise check.Cannot("端末で撮り直せません: 端末が繋がっていません")

    result = check.check_one(path, no_device)
    assert result.state == check.SKIP
    assert "端末" in result.detail


def test_the_summary_does_not_call_every_skip_a_hand_shot():
    """理由は行に出る。まとめで 1 つに決めると、もう片方が嘘になる."""
    report = check.Report(results=[
        check.Result("a", check.SKIP, "人が撮ったので撮り直せません"),
        check.Result("b", check.SKIP, "端末が繋がっていません"),
    ])
    summary = report.summary()
    assert "2 本は撮り直せないので検査していません" in summary
    assert "支援収録" not in summary
