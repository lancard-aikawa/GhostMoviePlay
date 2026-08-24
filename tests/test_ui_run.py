"""「撮る」面のうち、ウィンドウを作らずに決まる部分.

成果物の揃いぐあい・押せる段・組み立てるコマンドはモジュール関数にしてある。
tkinter を起動しないので CI でも走る。
"""

import json
import os
import sys

import pytest

from ghostmovieplay import ui_run

PLAN = {
    "meta": {"title": "テスト動画", "project": "proj"},
    "app": {"url": "http://127.0.0.1:8000/"},
    "scenes": [
        {"id": "s1", "beats": [
            {"say": "ひとつめ"},
            {"say": "ふたつめ"},
        ]},
    ],
}


@pytest.fixture
def one(tmp_path):
    """video.md が 1 本だけあるプロジェクト."""
    directory = tmp_path / "docs" / "video" / "demo"
    directory.mkdir(parents=True)
    (directory / "video.md").write_text("# demo\n", encoding="utf-8")
    return directory / "video.md"


def write_plan(spec, plan=None):
    target = spec.parent / "plan.json"
    target.write_text(json.dumps(plan or PLAN, ensure_ascii=False), encoding="utf-8")
    return target


def touch(path, when):
    """mtime を明示的に置く (作った順に頼ると解像度の粗い環境で揺れる)."""
    os.utime(path, (when, when))


# --- 何も選ばれていないとき -------------------------------------------
def test_nothing_selected_blocks_every_step():
    found = ui_run.survey(None)
    assert found.items == ()
    for step in ui_run.STEPS:
        assert "選んでください" in ui_run.blocker(step, found)


# --- 構成 (video.md) --------------------------------------------------
def test_the_chain_starts_at_the_video_md(one):
    """鎖の先頭は手で書く構成. 出さないと台本の手前が画面から分からない."""
    found = ui_run.survey(one)
    assert found.items[0].key == "spec"
    assert found.items[0].label == "構成"
    assert found.state("spec") == ui_run.READY


def test_a_video_md_left_at_the_template_defaults_is_flagged(tmp_path):
    """**雛形のまま Pass1 を呼ばせない。**

    `gmp init` が置く見本値 (5173 / npm run dev / text=スタート) のままだと、
    AI は「本物のアプリを指してくれ」と訊いてくる。`-p` には答える人がいない
    ので台本を書かずに終わる —— AI を 1 回焼いてから気づくのは高い。
    """
    spec = tmp_path / "docs" / "video" / "demo" / "video.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\nproject: X\napp:\n  url: http://localhost:5173\n"
        "  start: npm run dev\n  ready: \"text=スタート\"\n---\n",
        encoding="utf-8",
    )
    found = ui_run.survey(spec)

    assert found.state("spec") == ui_run.PARTIAL
    assert "雛形の既定のまま" in found.item("spec").detail
    assert "収録する URL" in found.warning
    # **止めはしない** (当たっていることもある)。先に言うだけ
    assert ui_run.blocker(ui_run.STEPS[0], found) == ""


def test_a_filled_in_video_md_is_ready(one):
    spec = one
    spec.write_text(
        "---\nproject: X\napp:\n  url: http://127.0.0.1:7474/\n"
        "  start: bun run dev\n  ready: \"#app\"\n---\n", encoding="utf-8")
    found = ui_run.survey(spec)
    assert found.state("spec") == ui_run.READY
    assert found.warning == ""


def test_an_unset_url_is_flagged_too(one):
    """雛形が見本値を焼かなくなったぶん、未設定が普通の入口になる."""
    one.write_text("---\nproject: X\n---\n", encoding="utf-8")
    found = ui_run.survey(one)
    assert "URL" in found.warning


def test_the_project_defaults_to_where_gmp_ui_was_started(tk_root, tmp_path, monkeypatch):
    """**動画のフォルダをプロジェクトの既定にしない。**

    1 本ぶんのフォルダをプロジェクトだと思われると、`収録対象を直す` がそこへ
    gmp.toml を作り、プロジェクト共通のはずの既定が 1 本にしか効かなくなる
    (実際にそこへ作った)。
    """
    from ghostmovieplay import ui

    spec = tmp_path / "docs" / "video" / "demo" / "video.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("---\ntitle: x\n---\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert ui.AppState(spec).directory == tmp_path

    # 起動した場所の外にある1本なら、そこは推測できないのでそのまま
    outside = tmp_path.parent / "elsewhere" / "video.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("---\ntitle: x\n---\n", encoding="utf-8")
    assert ui.AppState(outside).directory == outside.parent


def test_the_remedy_hides_once_the_target_is_set(tk_root, one):
    import tkinter as tk

    from ghostmovieplay import ui

    one.write_text(
        "---\nproject: X\napp:\n  url: http://127.0.0.1:7474/\n---\n",
        encoding="utf-8")
    top = tk.Toplevel(tk_root)
    top.withdraw()
    pane = ui_run.RunPane(top, ui.AppState(one))
    try:
        assert pane.survey.warning == ""
        assert not pane.write_button.winfo_manager()
    finally:
        top.destroy()


def test_the_screen_does_not_decide_the_target_itself(tk_root, one):
    """**画面が Claude の代わりをしない。**

    収録対象を画面から直す道 (`収録対象を直す`) も持っていたが、
    `claude に書かせる` が上位互換 (シーン構成まで書く) で、同じ場所に 2 つ
    並ぶだけだった。詰まるたびに widget を足したのが操作の多さの正体。
    """
    assert not hasattr(ui_run.RunPane, "on_fix_target")
    assert not hasattr(ui_run, "strip_samples")


# --- 台本 -------------------------------------------------------------
def test_a_video_without_a_plan_can_only_be_planned(one):
    found = ui_run.survey(one)
    assert found.state("plan") == ui_run.MISSING
    assert ui_run.blocker(ui_run.STEPS[0], found) == ""          # 台本を作る
    for step in ui_run.STEPS[1:]:
        # 仕上げにも「先に収録します」ではなく、いちばん手前の欠けを言う
        assert ui_run.blocker(step, found) == "先に台本を作ります"


def test_a_plan_older_than_the_video_md_is_stale(one):
    plan = write_plan(one)
    touch(plan, 1_000)
    touch(one, 2_000)
    assert ui_run.survey(one).state("plan") == ui_run.STALE


def test_a_plan_newer_than_the_video_md_is_ready(one):
    plan = write_plan(one)
    touch(one, 1_000)
    touch(plan, 2_000)
    assert ui_run.survey(one).state("plan") == ui_run.READY


def test_a_broken_plan_does_not_crash_the_screen(one):
    (one.parent / "plan.json").write_text("{ こわれている", encoding="utf-8")
    found = ui_run.survey(one)
    assert found.error
    assert found.state("plan") == ui_run.STALE
    # 直す道 (台本を作り直す) だけは残す
    assert ui_run.blocker(ui_run.STEPS[0], found) == ""
    assert "読めません" in ui_run.blocker(ui_run.STEPS[1], found)


# --- 音声 -------------------------------------------------------------
def test_voice_counts_the_beats_that_have_a_wav(one):
    plan = dict(PLAN)
    write_plan(one, plan)
    found = ui_run.survey(one)
    assert found.state("voice") == ui_run.MISSING
    assert "0 / 2" in found.item("voice").detail


def test_voice_is_partial_until_every_beat_has_its_wav(one):
    plan = json.loads(json.dumps(PLAN))
    plan["scenes"][0]["beats"][0]["audio"] = "voice/000_s1.wav"
    write_plan(one, plan)
    outdir = ui_run.survey(one).outdir
    (outdir / "voice").mkdir(parents=True)
    (outdir / "voice" / "000_s1.wav").write_bytes(b"")

    found = ui_run.survey(one)
    assert found.state("voice") == ui_run.PARTIAL
    assert "1 / 2" in found.item("voice").detail


def test_voice_is_not_judged_by_mtime(one):
    """`gmp voice` は manifest を書いたあとに plan.json を書き戻す.

    mtime で比べると、合成した直後でも「古い」になってしまう。新しさの判定は
    manifest のフィンガープリントに任せ、ここは揃っているかだけを見る。
    """
    plan = json.loads(json.dumps(PLAN))
    for index, beat in enumerate(plan["scenes"][0]["beats"]):
        beat["audio"] = f"voice/{index:03d}_s1.wav"
    plan_path = write_plan(one, plan)
    outdir = ui_run.survey(one).outdir
    (outdir / "voice").mkdir(parents=True)
    for index in range(2):
        wav = outdir / "voice" / f"{index:03d}_s1.wav"
        wav.write_bytes(b"")
        touch(wav, 1_000)
    touch(plan_path, 9_000)          # 書き戻しでいちばん新しくなる

    assert ui_run.survey(one).state("voice") == ui_run.READY


def test_a_plan_without_any_say_needs_no_voice(one):
    plan = json.loads(json.dumps(PLAN))
    for beat in plan["scenes"][0]["beats"]:
        beat["say"] = ""
    write_plan(one, plan)
    assert ui_run.survey(one).state("voice") == ui_run.READY


# --- 収録と仕上げ -----------------------------------------------------
def test_render_waits_for_a_recording(one):
    write_plan(one)
    found = ui_run.survey(one)
    render = next(s for s in ui_run.STEPS if s.key == "render")
    assert ui_run.blocker(render, found) == "先に収録します"


def test_a_recording_older_than_the_plan_needs_a_retake(one):
    """声を作り直すと plan.json に尺が書き戻される. 尺が変われば撮り直し."""
    plan_path = write_plan(one)
    found = ui_run.survey(one)
    (found.outdir).mkdir(parents=True, exist_ok=True)
    timing = found.outdir / "timing.json"
    timing.write_text(json.dumps({"duration": 12.5}), encoding="utf-8")
    touch(timing, 1_000)
    touch(plan_path, 2_000)

    after = ui_run.survey(one)
    assert after.state("timing") == ui_run.STALE
    # 仕上げ自体はできる (撮り直しが要ることは画面に出す)
    render = next(s for s in ui_run.STEPS if s.key == "render")
    assert ui_run.blocker(render, after) == ""


def test_the_recorded_length_is_shown(one):
    plan_path = write_plan(one)
    found = ui_run.survey(one)
    found.outdir.mkdir(parents=True, exist_ok=True)
    timing = found.outdir / "timing.json"
    timing.write_text(json.dumps({"duration": 12.5}), encoding="utf-8")
    touch(plan_path, 1_000)
    touch(timing, 2_000)

    after = ui_run.survey(one)
    assert after.state("timing") == ui_run.READY
    assert "12.5 秒" in after.item("timing").detail


def test_a_recording_with_warnings_is_flagged(one):
    """**通ったことは、狙った画面が映っている証明にはならない。**

    光らせ損ねや選択のずれは録画を止めないので、timing.json に残った警告を
    画面が拾わないと、ログを閉じた時点で消える。ただし**仕上げは止めない**
    (撮れてはいるので、直すのは台本のほう)。
    """
    plan_path = write_plan(one)
    outdir = ui_run.survey(one).outdir
    outdir.mkdir(parents=True, exist_ok=True)
    timing = outdir / "timing.json"
    timing.write_text(json.dumps({
        "duration": 12.5,
        "warnings": [
            {"kind": "highlight_missing", "where": "s1#0",
             "message": "光らせる相手が見つかりません: #tile"},
            {"kind": "audio_missing", "where": "s1#1", "message": "音声が見つかりません"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    touch(plan_path, 1_000)
    touch(timing, 2_000)

    found = ui_run.survey(one)
    assert found.state("timing") == ui_run.STALE
    detail = found.item("timing").detail
    assert "警告 2 件" in detail
    # 件数だけでは何を直すのか分からないので、先頭の 1 件は文ごと出す
    assert "#tile" in detail
    render = next(s for s in ui_run.STEPS if s.key == "render")
    assert ui_run.blocker(render, found) == ""


def test_a_recording_without_warnings_stays_clean(one):
    plan_path = write_plan(one)
    outdir = ui_run.survey(one).outdir
    outdir.mkdir(parents=True, exist_ok=True)
    timing = outdir / "timing.json"
    timing.write_text(json.dumps({"duration": 12.5, "warnings": []}), encoding="utf-8")
    touch(plan_path, 1_000)
    touch(timing, 2_000)

    found = ui_run.survey(one)
    assert found.state("timing") == ui_run.READY
    assert "警告" not in found.item("timing").detail


def test_an_output_older_than_the_recording_is_stale(one):
    write_plan(one)
    outdir = ui_run.survey(one).outdir
    outdir.mkdir(parents=True, exist_ok=True)
    timing = outdir / "timing.json"
    timing.write_text(json.dumps({"duration": 3.0}), encoding="utf-8")
    video = outdir / "output.mp4"
    video.write_bytes(b"")
    touch(video, 1_000)
    touch(timing, 2_000)

    assert ui_run.survey(one).state("output") == ui_run.STALE


# --- 出力先 -----------------------------------------------------------
def test_the_outdir_is_the_same_one_the_cli_uses(one, isolate_output_home):
    write_plan(one)
    found = ui_run.survey(one)
    assert found.outdir == isolate_output_home / "proj" / "demo"


# --- 1本も無いプロジェクト ---------------------------------------------
def test_a_new_video_goes_next_to_the_existing_ones(one):
    """置き場所の流儀はプロジェクトごとに違う. 既にあるならそこへ揃える."""
    project = one.parent.parent.parent          # <tmp>/docs/video/demo -> <tmp>
    assert ui_run.video_home(project, [one]) == one.parent.parent


def test_the_first_video_of_a_project_gets_a_default_home(tmp_path):
    assert ui_run.video_home(tmp_path, []) == tmp_path / "docs" / "video"


def test_a_new_video_name_is_made_safe_for_a_folder(tmp_path):
    target = ui_run.init_target(tmp_path, [], "a/b:c")
    assert target == tmp_path / "docs" / "video" / "a-b-c" / "video.md"


def test_a_blank_name_makes_nothing(tmp_path):
    assert ui_run.init_target(tmp_path, [], "") is None
    assert ui_run.init_target(tmp_path, [], "   ") is None


# --- Pass1 を手でやる逃げ道 -------------------------------------------
def test_the_request_is_locatable_before_the_plan_exists(one, isolate_output_home):
    """`台本を作る` が落ちたとき、依頼文がどこに出たのか画面から辿れること.

    claude を -p で動かすと、承認の要る操作を拒否されて台本を書かずに正常終了
    することがある (`plan.json が作られませんでした`)。CLI はそのとき
    「PLAN_REQUEST.md を手で渡してください」と言う。
    """
    found = ui_run.survey(one)
    assert found.state("plan") == ui_run.MISSING      # 台本はまだ無い
    assert found.outdir is not None, "台本が無いと出力先が出せない"
    assert found.request == found.outdir / "PLAN_REQUEST.md"


def test_the_request_sits_next_to_the_other_output(one):
    write_plan(one)
    found = ui_run.survey(one)
    assert found.request == found.outdir / "PLAN_REQUEST.md"


def test_a_broken_video_md_still_opens_the_screen(tmp_path):
    """出力先が解けなくても画面は開く (依頼文が出せないだけ)."""
    spec = tmp_path / "docs" / "video" / "demo" / "video.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("---\n[こわれた YAML\n---\n", encoding="utf-8")
    found = ui_run.survey(spec)
    assert found.spec == spec
    assert found.state("spec") == ui_run.READY


# --- 組み立てるコマンド -----------------------------------------------
def test_each_step_builds_its_command(one):
    write_plan(one)
    found = ui_run.survey(one)
    built = {s.key: ui_run.argv(s, found) for s in ui_run.STEPS}

    # **`--run` (-p) ではなく `--open`。** 収録対象やセレクタが決まっていないと
    # claude は訊いてくるが、-p には答える相手がいないので何も書かずに終わる
    assert built["plan"] == ["plan", str(one), "--open"]
    assert built["voice"] == ["voice", str(found.plan)]
    assert built["record"] == ["record", str(found.plan)]
    assert built["render"] == ["render", str(found.outdir / "timing.json")]
    assert built["build"] == ["build", str(found.plan), "--voice"]


def test_headed_is_the_only_switch_the_screen_adds(one):
    write_plan(one)
    found = ui_run.survey(one)
    record = next(s for s in ui_run.STEPS if s.key == "record")
    assert ui_run.argv(record, found, headed=True)[-1] == "--headed"


def test_the_screen_never_builds_a_flag_that_changes_the_picture_or_sound(one):
    """絵と音は plan.json が決める. GUI のチェックボックスで変えられてはいけない.

    とくに `--no-credit` を画面から打てるようにすると、VOICEVOX のクレジットを
    ワンクリックで落とせてしまう (音声を乗せたらクレジットも焼く、が破れる)。
    """
    write_plan(one)
    found = ui_run.survey(one)
    forbidden = {"--no-credit", "--no-audio", "--no-subtitles", "--sync-offset", "--out"}
    for step in ui_run.STEPS:
        for headed in (False, True):
            assert not forbidden & set(ui_run.argv(step, found, headed))


def test_the_command_runs_this_interpreter_not_whatever_is_on_path():
    import sys

    assert ui_run.command(["doctor"])[:3] == [sys.executable, "-m", "ghostmovieplay"]


def test_the_child_reads_and_writes_utf8():
    """Windows の既定コンソールは cp932. パイプ越しに `—` で落ちる."""
    env = ui_run.child_env()
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"


# --- 走らせる ---------------------------------------------------------
class FakeWidget:
    """Tk の代わり. after を即座に呼ぶ (スレッドから直接呼ばれる)."""

    def after(self, _delay, fn, *args):
        fn(*args)


def run_argv(tmp_path, script: str, timeout: float = 20.0):
    """script を書いて Runner で走らせ、(終了コード, 行) を返す."""
    import threading
    import time

    source = tmp_path / "child.py"
    source.write_text(script, encoding="utf-8")

    lines: list[str] = []
    finished: list[int] = []
    ended = threading.Event()

    def done(code):
        finished.append(code)
        ended.set()

    runner = ui_run.Runner(FakeWidget(), lines.append, done)
    monkey = ui_run.command
    ui_run.command = lambda args: [sys.executable, *args]
    try:
        assert runner.start([str(source)], tmp_path)
        deadline = time.time() + timeout
        while not ended.is_set() and time.time() < deadline:
            time.sleep(0.05)
    finally:
        ui_run.command = monkey
        runner.stop()
    return (finished[0] if finished else None), lines


@pytest.mark.slow
def test_a_finished_command_is_reported(tmp_path):
    code, lines = run_argv(tmp_path, "print('こんにちは')\n")
    assert code == 0
    assert "こんにちは" in lines


@pytest.mark.slow
def test_a_grandchild_holding_the_pipe_does_not_freeze_the_screen(tmp_path):
    """**完了はプロセスの終了で判定する。パイプの EOF では判定しない。**

    `gmp plan --run` の claude は MCP サーバのような孫を残すことがある。孫は
    stdout のパイプを継いでいるので、gmp が終わってもパイプは閉じない。EOF を
    待っていたころは、台本が出来ているのに画面が「実行中」のまま固まり、
    次の段が 1 つも押せなかった。
    """
    child = (
        "import subprocess, sys\n"
        # stdout を継いだまま長く生きる孫を残して、親はすぐ終わる
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print('台本を書きました')\n"
    )
    code, lines = run_argv(tmp_path, child)

    assert code == 0, "孫がパイプを掴んでいると終わりを見逃す"
    assert "台本を書きました" in lines
    assert any("孫プロセスが残っています" in line for line in lines)


@pytest.mark.slow
def test_a_failing_command_reports_its_code(tmp_path):
    code, _ = run_argv(tmp_path, "import sys; sys.exit(3)\n")
    assert code == 3


# --- 画面が要るぶん ---------------------------------------------------
def test_an_empty_project_is_not_a_dead_end(tk_root, tmp_path):
    """video.md が 1 つも無いプロジェクトでも、次にやることが画面に出ること.

    段は全部押せないので、**作る導線と理由**が無いと行き止まりになる
    (実際になった。全部灰色で、理由もどこにも出ていなかった)。
    """
    import tkinter as tk

    from ghostmovieplay import ui

    top = tk.Toplevel(tk_root)
    top.withdraw()
    state = ui.AppState()
    state.project_dir.set(str(tmp_path))
    pane = ui_run.RunPane(top, state)
    try:
        assert pane.survey.spec is None
        assert all(b["state"] == tk.DISABLED for b in pane.buttons.values())
        assert pane.init_button["state"] == tk.NORMAL      # ここから始められる
        assert not hasattr(pane, "edit_button"), "開く操作は行へ集約した"
        assert pane.step_note["text"], "押せない理由がどこにも出ていない"
        assert "1 本もありません" in pane.title_label["text"]
        # 「1本」は数え方。物の名前として使わない (台本の数に読める)
        assert pane.init_button["text"] == "構成を作る"
    finally:
        top.destroy()



def fail_step(pane, key, title, lines=()):
    pane.running, pane.running_key = title, key
    pane.begin()
    for line in lines:
        pane.on_line(line)
    pane.on_done(1)


def test_a_failed_step_keeps_its_reason_on_screen(tk_root, one):
    """exit 1 とだけ言われても何をすればいいか分からない.

    理由 (`gmp: ...`) は長い実行のあとだとログの上へ流れるので、段のすぐ下の
    帯に残す。下の帯 (status) は次の操作で上書きされる。
    """
    import tkinter as tk

    from ghostmovieplay import ui

    top = tk.Toplevel(tk_root)
    top.withdraw()
    pane = ui_run.RunPane(top, ui.AppState(one))
    try:
        fail_step(pane, "plan", "台本を作る", (
            "作成: PLAN_REQUEST.md",
            "gmp: claude コマンドが見つかりません",
            "  --run を外して PLAN_REQUEST.md を手で渡してください",
        ))

        shown = pane.failure_label["text"]
        assert "claude コマンドが見つかりません" in shown
        # 直し方は 2 行目以降にある。1 行目だけ拾うと何をすればいいか分からない
        assert "PLAN_REQUEST.md" in shown
        assert "claude コマンドが見つかりません" in pane.state.status.get()
        assert pane.failure_bar.winfo_manager(), "失敗の帯が出ていない"

        # 次を始めたら消える (前の失敗が残り続けない)
        pane.running = "声を作る"
        pane.begin()
        pane._refresh_buttons()
        assert not pane.failure_bar.winfo_manager()
    finally:
        top.destroy()


def test_the_escape_hatch_shows_up_only_when_it_helps(tk_root, one):
    """**逃げ道は要るときにだけ出す。** 普段は帯ごと出さない."""
    import tkinter as tk

    from ghostmovieplay import ui

    top = tk.Toplevel(tk_root)
    top.withdraw()
    pane = ui_run.RunPane(top, ui.AppState(one))
    try:
        assert not pane.failure_bar.winfo_manager()

        fail_step(pane, "record", "収録する", ("gmp: chromium が起動できません",))
        assert pane.failure_bar.winfo_manager()
        assert pane.doctor_button.winfo_manager(), "前提を調べるはどの失敗でも要る"
    finally:
        top.destroy()


def test_writing_the_spec_opens_an_interactive_claude(tk_root, tmp_path, monkeypatch):
    """**素人に「URL と起動コマンドとセレクタを調べて書いて」は無理筋。**

    収録対象もシーン構成も、そのプロジェクトを読まないと決まらない。読める者に
    読ませるほうが素直なので、警告の帯から対話の claude を開く。
    """
    import tkinter as tk

    from ghostmovieplay import ui

    spec = tmp_path / "docs" / "video" / "demo" / "video.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("---\ntitle: x\n---\n", encoding="utf-8")

    started: list = []
    monkeypatch.setattr(ui_run.Runner, "start",
                        lambda self, args, cwd: started.append(args) or True)

    top = tk.Toplevel(tk_root)
    top.withdraw()
    state = ui.AppState()
    state.project_dir.set(str(tmp_path))
    state.spec_path.set(str(spec))
    pane = ui_run.RunPane(top, state)
    try:
        assert pane.survey.warning              # 収録対象が決まっていない
        assert pane.write_button.winfo_manager(), "書かせる道が出ていない"

        pane.on_write_spec()
        assert started == [["init", str(spec.parent), "--open"]]
    finally:
        top.destroy()


def test_a_step_that_fails_without_a_gmp_line_still_says_something(tk_root, one):
    import tkinter as tk

    from ghostmovieplay import ui

    top = tk.Toplevel(tk_root)
    top.withdraw()
    pane = ui_run.RunPane(top, ui.AppState(one))
    try:
        fail_step(pane, "record", "収録する")
        assert pane.failure_label["text"], "失敗したのに画面に何も出ていない"
    finally:
        top.destroy()


def test_every_artifact_row_can_be_opened(tk_root, one, monkeypatch):
    """開く操作は行に集約した.

    「構成を編集」「出力フォルダを開く」「完成した動画を再生」の 3 ボタンは、
    ファイル名が出ている表の複製だった。まだ無い行は、出る場所を開く。
    """
    import tkinter as tk

    from ghostmovieplay import ui

    write_plan(one)
    opened: list = []
    monkeypatch.setattr(ui_run, "open_path", opened.append)

    top = tk.Toplevel(tk_root)
    top.withdraw()
    pane = ui_run.RunPane(top, ui.AppState(one))
    try:
        assert set(pane.cells) == {"spec", "plan", "voice", "timing", "output"}

        # 構成だけは画面の中のエディタで開く (外のエディタには渡さない)
        pane.open_item(pane.survey.item("spec"))
        assert opened == []
        editors = [w for w in top.winfo_children() if isinstance(w, tk.Toplevel)]
        assert editors, "構成のエディタが開いていない"
        editors[0].destroy()

        pane.open_item(pane.survey.item("plan"))
        assert opened == [pane.survey.plan]          # 台本は既定のアプリへ

        opened.clear()
        pane.survey.outdir.mkdir(parents=True, exist_ok=True)
        pane.open_item(pane.survey.item("output"))   # まだ無い → 出る場所
        assert opened == [pane.survey.outdir]
        assert "まだありません" in pane.state.status.get()
    finally:
        top.destroy()


def test_the_pane_shows_every_artifact(tk_root, one):
    """表の行が成果物と 1 対 1 で並ぶこと (数だけ見る)."""
    import tkinter as tk

    from ghostmovieplay import ui

    write_plan(one)
    top = tk.Toplevel(tk_root)
    top.withdraw()
    state = ui.AppState(one)
    pane = ui_run.RunPane(top, state)
    try:
        # 構成 → 台本 → 音声 → 収録 → 完成
        assert [i.key for i in pane.survey.items] == [
            "spec", "plan", "voice", "timing", "output"]
        assert pane.buttons["record"]["state"] == tk.NORMAL
        assert pane.buttons["render"]["state"] == tk.DISABLED
    finally:
        top.destroy()
