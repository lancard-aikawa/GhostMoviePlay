import json
import subprocess
import sys
from pathlib import Path

import pytest

from ghostmovieplay import agent
from ghostmovieplay.cli import main

MINIMAL_PLAN = {
    "version": 1,
    "meta": {"title": "自動生成"},
    "app": {"url": "http://x"},
    "scenes": [
        {"id": "fail", "title": "失敗", "beats": [{"say": "しっぱい", "hold": 1.0}]},
        {"id": "good", "title": "正解", "beats": [{"say": "せいかい", "hold": 1.0}]},
    ],
}


@pytest.fixture
def spec_file(tmp_path):
    (tmp_path / "video.md").write_text(
        "---\napp:\n  url: http://x\n  cwd: .\npersona:\n  style: 淡々と\n"
        "scenes:\n  - id: fail\n    goal: 失敗を見せる\n---\n補足なし\n",
        encoding="utf-8",
    )
    return tmp_path / "video.md"


def fake_run(recorder, *, returncode=0, writes: dict | None = None):
    def _run(cmd, cwd=None, timeout=None):
        recorder["cmd"] = cmd
        recorder["cwd"] = cwd
        if writes is not None:
            # プロンプト内に書かれた出力先へ plan.json を落とす体裁
            Path(recorder["out"]).write_text(
                json.dumps(writes, ensure_ascii=False), encoding="utf-8"
            )
        return subprocess.CompletedProcess(cmd, returncode)

    return _run


def test_missing_claude_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    with pytest.raises(agent.AgentError, match="claude コマンドが見つかりません"):
        agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path)


def test_missing_cwd_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    with pytest.raises(agent.AgentError, match="作業ディレクトリ"):
        agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path / "nope")


def test_command_carries_request_and_dirs(tmp_path, monkeypatch):
    rec = {"out": tmp_path / "plan.json"}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec, writes=MINIMAL_PLAN))

    req = tmp_path / "req.md"
    req.write_text("x", encoding="utf-8")
    agent.run(req, tmp_path / "plan.json", tmp_path, model="opus", verbose=False)

    cmd = rec["cmd"]
    assert cmd[0] == "claude.exe"
    assert "-p" in cmd and "--permission-mode" in cmd
    assert "--add-dir" in cmd and str(req.parent) in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert str(req) in cmd[cmd.index("-p") + 1]      # 依頼文の場所
    assert str(tmp_path / "plan.json") in cmd[cmd.index("-p") + 1]  # 出力先
    assert rec["cwd"] == str(tmp_path)


def test_cmd_shim_is_launched_through_cmd_exe(tmp_path, monkeypatch):
    rec = {"out": tmp_path / "plan.json"}
    monkeypatch.setattr(agent.shutil, "which", lambda name: r"C:\npm\claude.CMD")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec, writes=MINIMAL_PLAN))

    req = tmp_path / "req.md"
    req.write_text("x", encoding="utf-8")
    agent.run(req, tmp_path / "plan.json", tmp_path, verbose=False)

    assert rec["cmd"][:3] == ["cmd", "/c", r"C:\npm\claude.CMD"]


def test_nonzero_exit_is_reported(tmp_path, monkeypatch):
    rec = {"out": tmp_path / "plan.json"}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec, returncode=2))
    with pytest.raises(agent.AgentError, match="exit 2"):
        agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path, verbose=False)


def test_the_output_is_seeded_before_claude_starts(tmp_path, monkeypatch):
    """**新規作成ではなく編集にする。**

    既定の `acceptEdits` が自動で通すのは編集で、`-p` (対話なし) では承認を
    求められた時点で行き止まる。出力先を先に作っておけば編集になる。
    """
    out = tmp_path / "plan.json"
    rec = {"out": out, "seen": None}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")

    def spy(cmd, cwd=None, timeout=None):
        rec["seen"] = out.read_text(encoding="utf-8")   # 起動した時点の中身
        out.write_text(json.dumps(MINIMAL_PLAN, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent.subprocess, "run", spy)
    agent.run(tmp_path / "req.md", out, tmp_path, verbose=False)

    assert rec["seen"] == agent.placeholder_text(), "雛形を置かずに起動している"
    assert json.loads(out.read_text(encoding="utf-8")) == MINIMAL_PLAN


def test_the_prompt_asks_to_edit_not_to_create(tmp_path, monkeypatch):
    rec = {"out": tmp_path / "plan.json"}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec, writes=MINIMAL_PLAN))
    agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path, verbose=False)

    prompt = rec["cmd"][rec["cmd"].index("-p") + 1]
    assert "編集して" in prompt


def test_an_untouched_placeholder_is_a_failure_and_leaves_nothing(tmp_path, monkeypatch):
    """雛形のままなら消して失敗にする.

    残すと、画面には台本があるように見えて `gmp record` で初めて落ちる。
    """
    out = tmp_path / "plan.json"
    rec = {"out": out}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec))  # 何も書かない

    with pytest.raises(agent.AgentError, match="雛形のまま"):
        agent.run(tmp_path / "req.md", out, tmp_path, verbose=False)
    assert not out.exists(), "雛形が残っている"


def test_a_crash_leaves_no_placeholder(tmp_path, monkeypatch):
    out = tmp_path / "plan.json"
    rec = {"out": out}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec, returncode=2))

    with pytest.raises(agent.AgentError, match="exit 2"):
        agent.run(tmp_path / "req.md", out, tmp_path, verbose=False)
    assert not out.exists()


def test_an_existing_plan_is_left_alone(tmp_path, monkeypatch):
    """作り直しのときは雛形を置かない.

    既にある台本を消してから起動すると、claude が落ちた時点で**元の台本ごと
    失われる**。変わらなかったことを失敗とも呼べない (そのままで良いこともある)。
    """
    out = tmp_path / "plan.json"
    out.write_text(json.dumps(MINIMAL_PLAN, ensure_ascii=False), encoding="utf-8")
    rec = {"out": out}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec))  # 何も書かない

    agent.run(tmp_path / "req.md", out, tmp_path, verbose=False)
    assert json.loads(out.read_text(encoding="utf-8")) == MINIMAL_PLAN


def test_the_placeholder_is_not_a_usable_plan():
    """そのまま残っても完成した台本と見分けがつくこと."""
    from ghostmovieplay.plan import PlanError, load

    path = Path(__file__).parent / "_placeholder.json"
    path.write_text(agent.placeholder_text(), encoding="utf-8")
    try:
        with pytest.raises(PlanError):
            load(path)
    finally:
        path.unlink()


def test_timeout_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")

    def boom(cmd, cwd=None, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout or 0)

    monkeypatch.setattr(agent.subprocess, "run", boom)
    out = tmp_path / "plan.json"
    with pytest.raises(agent.AgentError, match="終わりませんでした"):
        agent.run(tmp_path / "req.md", out, tmp_path, timeout=1, verbose=False)
    assert not out.exists(), "落ちた経路で雛形が残っている"


# --- CLI 経由 ---------------------------------------------------------
def test_plan_without_run_only_writes_request(spec_file, capsys):
    """依頼文は生成物なので出力側。プロジェクトには何も増えない."""
    from ghostmovieplay import paths

    assert main(["plan", str(spec_file)]) == 0

    outdir = paths.resolve_outdir(spec_file, app_cwd=".")
    assert (outdir / "PLAN_REQUEST.md").exists()
    assert not (spec_file.parent / "PLAN_REQUEST.md").exists()
    assert not (spec_file.parent / "plan.json").exists()
    assert "--run" in capsys.readouterr().out


@pytest.mark.slow
def test_plan_run_end_to_end_with_a_stub_claude(spec_file, tmp_path, monkeypatch, capsys):
    """PATH に置いたスタブで、依頼文生成 → 起動 → 検証 → 要約 まで通す."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    writer = bin_dir / "write_plan.py"
    writer.write_text(
        "import json,sys,pathlib\n"
        f"pathlib.Path(r'{spec_file.parent / 'plan.json'}').write_text("
        f"json.dumps({MINIMAL_PLAN!r}, ensure_ascii=False), encoding='utf-8')\n",
        encoding="utf-8",
    )
    shim = bin_dir / "claude.cmd"
    shim.write_text(f'@echo off\r\n"{sys.executable}" "{writer}"\r\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_dir) + ";" + str(Path.cwd()))

    assert main(["plan", str(spec_file), "--run"]) == 0

    out = capsys.readouterr().out
    assert "2 シーン / 2 ビート" in out
    assert (spec_file.parent / "plan.json").exists()


# --- 対話で開く -------------------------------------------------------
def test_the_launcher_survives_quotes_and_japanese(tmp_path, monkeypatch):
    """プロンプトは長くて日本語も入る.

    コマンドラインに直接並べると引用符で壊れるので、使い捨ての .cmd に書く。
    **ファイルなら壊れないし、出来上がったものを人が読み直して再実行できる。**
    """
    monkeypatch.setattr(agent.shutil, "which", lambda name: r"C:\bin\claude.CMD")
    monkeypatch.setattr(agent.sys, "platform", "win32")
    opened = []
    monkeypatch.setattr(agent.os, "startfile", opened.append, raising=False)

    launcher = agent.open_session(
        '「台本」を作って。"引用符" も改行も\n入る',
        tmp_path, allow={tmp_path}, where=tmp_path, model="opus", verbose=False)

    text = launcher.read_text(encoding="utf-8")
    assert launcher.name == agent.LAUNCHER
    assert opened == [str(launcher)]
    assert "chcp 65001" in text                  # cp932 で書けない字が入る
    assert 'call "C:\\bin\\claude.CMD"' in text   # .cmd はシムなので call
    assert f'--add-dir="{tmp_path}"' in text
    assert '--model "opus"' in text
    line = next(one for one in text.splitlines() if one.startswith("call "))
    assert "も改行も 入る" in line               # 改行は空白に畳む
    assert "'引用符'" in line                    # " は畳めないので ' に置き換える
    assert line.count('"') % 2 == 0, "引用符の数が合わない (引数が切れる)"
    assert "pause" in text                       # 読んでから閉じられる

    # **改行は CRLF ちょうど。** write_text の既定だと LF が CRLF に直され、
    # こちらの CRLF が CR CR LF になって、cmd が行を読み違える。実際に
    # **引数がまるごと渡らず、claude が空の画面で立ち上がった**
    raw = launcher.read_bytes()
    assert bytes([13, 13, 10]) not in raw
    assert raw.count(bytes([13, 10])) == raw.count(bytes([10]))

    # 窓の中に指示そのものを出す (claude が自分で始めないと打つものが分からない)
    assert any(one.startswith("echo   ") and "引用符" in one
               for one in text.splitlines()), "貼り付けられる 1 行が出ていない"


def test_add_dir_binds_exactly_one_value(tmp_path, monkeypatch):
    """**`--add-dir` は空白区切りだと複数取る。**

    後ろにプロンプトを置くと**ディレクトリとして飲み込まれ**、claude は指示を
    受け取らないまま空の画面で立ち上がる (実際にそうなった)。`=` で束ねる。
    """
    monkeypatch.setattr(agent.shutil, "which", lambda name: r"C:\bin\claude.exe")
    monkeypatch.setattr(agent.sys, "platform", "win32")
    monkeypatch.setattr(agent.os, "startfile", lambda path: None, raising=False)

    launcher = agent.open_session("しじ", tmp_path, allow={tmp_path, tmp_path / "x"},
                                  where=tmp_path, verbose=False)
    line = next(one for one in launcher.read_text(encoding="utf-8").splitlines()
                if one.startswith('"C:'))

    assert f'--add-dir="{tmp_path}"' in line
    assert " --add-dir " not in line, "空白区切りだとプロンプトを飲み込む"
    assert line.rstrip().endswith('"しじ"'), "プロンプトが最後の引数として残らない"


def test_the_prompt_is_put_on_the_clipboard(tmp_path, monkeypatch):
    """claude が自分で始めなくても、Ctrl+V → Enter で進める.

    長い 1 行を手で打たせるのは無理がある。**clip は UTF-16LE (BOM つき) しか
    正しく読めない**ので、コンソールの chcp とは別にこちらで用意する。
    """
    monkeypatch.setattr(agent.shutil, "which", lambda name: r"C:\bin\claude.exe")
    monkeypatch.setattr(agent.sys, "platform", "win32")
    monkeypatch.setattr(agent.os, "startfile", lambda path: None, raising=False)

    launcher = agent.open_session("台本を作ってください", tmp_path, allow={tmp_path},
                                  where=tmp_path, verbose=False)
    prompt_file = launcher.parent / agent.PROMPT_FILE

    assert prompt_file.is_file()
    raw = prompt_file.read_bytes()
    assert raw[:2] == bytes([0xFF, 0xFE]), "clip が読めない符号化"
    assert raw.decode("utf-16") == "台本を作ってください"
    assert f'clip < "{prompt_file}"' in launcher.read_text(encoding="utf-8")


def test_opening_without_claude_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    with pytest.raises(agent.AgentError, match="claude コマンドが見つかりません"):
        agent.open_session("x", tmp_path, allow={tmp_path}, where=tmp_path,
                           verbose=False)


def test_the_launcher_is_not_left_in_the_project(tmp_path, monkeypatch):
    """**書き出す先は省略できない。** 省けたころは `cwd` に落ちる作りだったので、
    呼び側が 1 つ忘れると人のリポジトリに `.cmd` と原稿が残る。
    """
    monkeypatch.setattr(agent.shutil, "which", lambda name: r"C:\bin\claude.exe")
    monkeypatch.setattr(agent.sys, "platform", "win32")
    monkeypatch.setattr(agent.os, "startfile", lambda path: None, raising=False)

    project, out = tmp_path / "project", tmp_path / "out"
    project.mkdir()

    launcher = agent.open_session("しじ", project, allow={project}, where=out,
                                  verbose=False)

    assert launcher.parent == out
    assert (out / agent.PROMPT_FILE).is_file()
    assert not list(project.iterdir()), "対象プロジェクトに書き出している"

    with pytest.raises(TypeError):        # where を省けないこと
        agent.open_session("しじ", project, allow={project}, verbose=False)


def test_the_spec_prompt_does_not_ask_for_the_script(tmp_path):
    """**構成を書かせる段で台本まで書かせない。** 3 段に分けた意味が消える."""
    prompt = agent.spec_prompt(tmp_path / "video.md")
    assert "video.md" in prompt
    assert "plan.json) はここに書かない" in prompt
    assert "失敗例" in prompt          # 3 幕の型は伝える


def test_the_spec_prompt_carries_the_static_guesses(tmp_path):
    from ghostmovieplay.detect import Guess

    prompt = agent.spec_prompt(
        tmp_path / "video.md",
        [Guess("app.url", "http://localhost:7474/", "src/index.ts の Bun.serve")])
    assert "http://localhost:7474/" in prompt
    assert "Bun.serve" in prompt
    assert "確かめてから" in prompt     # 推測だと言ってから渡す
