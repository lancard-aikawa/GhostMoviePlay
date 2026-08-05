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


def test_missing_output_is_reported(tmp_path, monkeypatch):
    rec = {"out": tmp_path / "plan.json"}
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")
    monkeypatch.setattr(agent.subprocess, "run", fake_run(rec))  # 何も書かない
    with pytest.raises(agent.AgentError, match="plan.json が作られませんでした"):
        agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path, verbose=False)


def test_timeout_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: "claude.exe")

    def boom(cmd, cwd=None, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout or 0)

    monkeypatch.setattr(agent.subprocess, "run", boom)
    with pytest.raises(agent.AgentError, match="終わりませんでした"):
        agent.run(tmp_path / "req.md", tmp_path / "plan.json", tmp_path,
                  timeout=1, verbose=False)


# --- CLI 経由 ---------------------------------------------------------
def test_plan_without_run_only_writes_request(spec_file, capsys):
    assert main(["plan", str(spec_file)]) == 0
    assert (spec_file.parent / "PLAN_REQUEST.md").exists()
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
