"""Pass1 を Claude CLI に投げる.

`gmp plan video.md --run` から呼ばれる。対象プロジェクトを作業ディレクトリに
して claude を起動し、PLAN_REQUEST.md の指示どおりに plan.json を書かせる。

台本作りは「ソースを読む」「実際に触る」を伴うので、依頼文を渡すだけの
運用 (--run なし) も残してある。対話しながら詰めたいときはそちらが早い。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_PERMISSION_MODE = "acceptEdits"


class AgentError(RuntimeError):
    pass


def _prompt(request: Path, out_plan: Path) -> str:
    return (
        f"{request} を読んで、その指示に従って実演の台本を作ってください。\n"
        f"完成した plan.json は {out_plan} に書き出してください。\n"
        "書き出したら実際に収録が通るところまで確認してください。"
    )


def run(
    request: Path,
    out_plan: Path,
    cwd: Path,
    model: str | None = None,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
    timeout: float | None = None,
    extra_dirs: list[Path] | None = None,
    verbose: bool = True,
) -> Path:
    """claude を起動して plan.json を作らせる. 戻り値は生成された plan.json."""
    exe = shutil.which("claude")
    if not exe:
        raise AgentError(
            "claude コマンドが見つかりません。\n"
            "  Claude Code をインストールするか、--run を外して PLAN_REQUEST.md を\n"
            "  手で Claude Code に渡してください。"
        )
    if not cwd.is_dir():
        raise AgentError(f"作業ディレクトリが見つかりません: {cwd}")

    # npm 経由だと claude.cmd のシムになることがある。Windows の CreateProcess は
    # .cmd/.bat を直接起動できないので cmd /c を噛ませる。
    launcher = ["cmd", "/c", exe] if exe.lower().endswith((".cmd", ".bat")) else [exe]

    # 依頼文は出力側、plan.json はプロジェクト側と離れているので両方許可する
    allow = {request.parent, out_plan.parent, *(extra_dirs or [])}
    cmd = [*launcher, "-p", _prompt(request, out_plan), "--permission-mode", permission_mode]
    for directory in sorted(str(d) for d in allow):
        cmd += ["--add-dir", directory]
    if model:
        cmd += ["--model", model]

    if verbose:
        print(f"  claude を起動 (cwd={cwd}, permission-mode={permission_mode})")
        print(f"  依頼文: {request}\n" + "-" * 60)

    try:
        # 出力はそのまま流す (長時間走るので進捗が見えないと不安になる)
        proc = subprocess.run(cmd, cwd=str(cwd), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AgentError(f"claude が {timeout:.0f} 秒で終わりませんでした") from exc
    except OSError as exc:
        raise AgentError(f"claude の起動に失敗しました: {exc}") from exc

    if verbose:
        print("-" * 60)
    if proc.returncode != 0:
        raise AgentError(f"claude が異常終了しました (exit {proc.returncode})")
    if not out_plan.exists():
        raise AgentError(
            f"plan.json が作られませんでした: {out_plan}\n"
            "  --permission-mode を bypassPermissions にするか、\n"
            "  PLAN_REQUEST.md を手で Claude Code に渡してください。"
        )
    return out_plan
