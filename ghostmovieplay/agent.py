"""Pass1 を Claude CLI に投げる.

`gmp plan video.md --run` から呼ばれる。対象プロジェクトを作業ディレクトリに
して claude を起動し、PLAN_REQUEST.md の指示どおりに plan.json を書かせる。

台本作りは「ソースを読む」「実際に触る」を伴う。**`-p` (対話なし) には訊く
相手がいない**ので、収録対象が決まっていなかったりセレクタが要ったりすると、
claude は「本物のアプリを指してくれ」と訊いて何も書かずに終わる (実際に終わった)。
そこで入口を 2 つ持つ:

- `open_session()` — **対話の claude を新しいコンソールで開く**。訊かれたら人が
  答えられるし、承認もその場で出せる。画面 (`gmp ui`) はこちらを使う
- `run()` — `-p` で回しきる。答える人がいない前提なので自動化向け
  (`gmp plan --run`)。収録対象が決まっているときは速い

**先に空の雛形を置いてから起動する。** 既定の `acceptEdits` が自動で通すのは
「編集」で、`-p` (対話なし) では承認を求められた時点で行き止まる。出力先を
先に作っておけば新規作成ではなく編集になる。雛形のままなら消して失敗にする
ので、中途半端な plan.json は残らない。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_PERMISSION_MODE = "acceptEdits"

# 出力先に先に置く雛形。**わざと未完成にしてある** ——
# scenes が空なので、そのまま残っても `gmp record` は通らず、画面にも
# 「読めません: scenes が空です」と出る (完成した台本と見分けがつく)
PLACEHOLDER: dict = {
    "version": 1,
    "meta": {"title": "", "lang": "ja"},
    "app": {"url": ""},
    "scenes": [],
}


def placeholder_text() -> str:
    return json.dumps(PLACEHOLDER, ensure_ascii=False, indent=2) + "\n"


class AgentError(RuntimeError):
    pass


LAUNCHER = "gmp-claude.cmd"
PROMPT_FILE = "gmp-claude-prompt.txt"


def spec_prompt(spec: Path, hints: list | None = None) -> str:
    """構成 (video.md) を埋めさせる依頼.

    **台本 (plan.json) は書かせない。** ここで決めるのは「何を撮るか」だけで、
    セリフとト書きは Pass1 (`gmp plan`) の仕事。1 回で全部やらせると、3 段に
    分けた意味が消える (CLAUDE.md)。
    """
    found = "".join(f"\n  {g.path} = {g.value}   ({g.why} から推測)"
                    for g in (hints or []))
    return (
        f"{spec} は GhostMoviePlay の「構成」ファイルです。"
        "このプロジェクトの実演解説動画を 1 本作るための指示を書きます。"
        "**新しく作らずにこのファイルを編集してください。**\n\n"
        "1. このプロジェクトのソースを読んで、何のアプリかを掴む\n"
        "2. フロントマターの app を実際の値にする"
        " (url=収録する URL / start=起動コマンド / ready=起動し終わったと分かる"
        "セレクタ / cwd=ソースのフォルダ。**cwd はこの video.md からの相対**)。"
        "コメントで継承と書いてあるものは、変えたいときだけ書く\n"
        "3. title と scenes を書く。scenes は id と goal だけの箇条書きで、"
        "**失敗例 → 何が悪かったか → 正解ルート** の 3 幕を基本にする\n"
        "4. --- より下の本文に、狙う視聴者や触れてほしい仕様を書く\n\n"
        "セリフや操作手順 (plan.json) はここに書かないこと。それは次の段の仕事です。"
        "推測でセレクタを埋めず、実際に読んで確かめてください。"
        "人が書いたコメントと本文は残してください。"
        + (f"\n\n静的に読んで推測した値 (確かめてから使ってください):{found}"
           if found else "")
    )


def open_session(prompt: str, cwd: Path, allow, *, where: Path,
                 model: str | None = None, verbose: bool = True,
                 title: str = "claude を開きます") -> Path:
    """**対話の claude を新しいコンソールで開く.** 戻り値は起こしたランチャ.

    `where` は**書き出す先**（ランチャと貼り付け用のプロンプト）。`cwd` は
    claude を動かす場所で、**対象プロジェクトのルート**になる。既定で `cwd` に
    落とす作りにしていたが、それだと呼び側が 1 つ忘れただけで
    `gmp-claude.cmd` と `gmp-claude-prompt.txt` が**人のリポジトリに残る**。
    生成物は出力先に置くのが決まりなので、省略できないようにしてある。

    `-p` と違って、訊かれたら人が答えられる。承認もその場で出せるので
    `bypassPermissions` に落とす必要もない。収録対象やセレクタは、そのプロジェクトを
    見ないと決まらないことが多く、**素人に「調べて書いてください」と頼むのが
    いちばん詰まる**ところなので、訊ける相手ごと開く。

    起動は使い捨ての `.cmd` を経由する。プロンプトが長く日本語も入るので、
    コマンドラインに直接並べると引用符で壊れる。**ファイルに書けば壊れないし、
    出来上がったものを人が読み直して再実行できる**。
    """
    exe = shutil.which("claude")
    if not exe:
        raise AgentError(
            "claude コマンドが見つかりません。\n"
            "  Claude Code をインストールするか、画面のエディタで手で書いてください。"
        )
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise AgentError(f"作業ディレクトリが見つかりません: {cwd}")

    target = Path(where) / LAUNCHER
    target.parent.mkdir(parents=True, exist_ok=True)

    # **貼り付けを 1 操作にする。** claude が引数の指示で自分から始めなかった
    # とき、長い 1 行を手で打たせるのは無理がある。clip に流しておけば
    # Ctrl+V → Enter で済む。**clip は UTF-16LE (BOM つき) しか正しく読めない**
    # ので、コンソールの chcp とは別にこちらで用意する
    prompt_file = target.parent / PROMPT_FILE
    prompt_file.write_text(" ".join(prompt.split()), encoding="utf-16")
    # **newline="" で書く。** 既定だと Python が改行を CRLF に直すので、
    # こちらの CRLF が CR CR LF になり、**cmd が行を読み違えて引数が渡らない**
    target.write_text(
        _launcher_text(exe, prompt, cwd, allow, model, title, prompt_file),
        encoding="utf-8", newline="")

    if sys.platform != "win32":
        raise AgentError(
            "対話の claude を開けるのは Windows だけです。\n"
            f"  次を手で実行してください (cwd={cwd}):\n"
            f"    claude \"{prompt}\""
        )
    try:
        os.startfile(str(target))                       # noqa: S606
    except OSError as exc:
        raise AgentError(f"claude を開けません: {exc}") from exc
    if verbose:
        print(f"  claude を開きました (cwd={cwd})")
        print(f"  ランチャ: {target}  (同じことをやり直せます)")
    return target


def _launcher_text(exe: str, prompt: str, cwd: Path, allow, model,
                   title: str = "claude を開きます",
                   prompt_file: Path | None = None) -> str:
    """使い捨ての .cmd.

    - cp932 では日本語のプロンプトを書けないので `chcp 65001` を先に打つ
    - **窓の中に指示そのものを出す。** claude がそのまま始めなかったとき、
      何を打てばいいのか分からないまま止まる (実際に止まった)。貼り付けられる
      1 行として見せておけば、そこから進める
    """
    call = "call " if exe.lower().endswith((".cmd", ".bat")) else ""
    # **`--add-dir=<path>` の形で渡す。** 空白区切りだと複数のディレクトリを
    # 取るオプションなので、**後ろに置いたプロンプトまで飲み込まれる** ——
    # claude は指示を受け取らないまま空の画面で立ち上がる (実際にそうなった)
    dirs = "".join(f' --add-dir="{d}"' for d in sorted({str(Path(d)) for d in allow}))
    model_arg = f' --model "{model}"' if model else ""
    # 1 行に畳む (改行は .cmd で切れる)。**二重引用符は畳めない** ——
    # プロンプト全体を "..." で囲むので、中に " があるとそこで引数が切れる
    single = " ".join(prompt.split()).replace('"', "'")
    shown = single.replace("%", "%%").replace("^", "^^").replace("&", "^&")
    crlf = chr(13) + chr(10)
    lines = [
        "@echo off",
        "chcp 65001 > nul",
        f'cd /d "{cwd}"',
        f"echo GhostMoviePlay - {title}",
        "echo.",
    ]
    if prompt_file is not None:
        lines += [
            f'clip < "{prompt_file}"',
            "echo 指示をクリップボードに入れました。",
            "echo claude が自分で始めないときは Ctrl+V を押して Enter してください。",
        ]
    lines += [
        f"echo   {shown}",
        "echo.",
        f'{call}"{exe}"{dirs}{model_arg} "{single}"',
        "echo.",
        "echo 終わったらこの窓を閉じて、GhostMoviePlay の画面に戻ってください。",
        "pause",
        "",
    ]
    return crlf.join(lines)


def _prompt(request: Path, out_plan: Path) -> str:
    return (
        f"{request} を読んで、その指示に従って実演の台本を作ってください。\n"
        f"{out_plan} に空の雛形を置いてあります。**新しく作らずにこれを編集して**"
        "完成させてください。\n"
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

    # **新規作成ではなく編集にする。** 既に台本があるなら触らない (作り直しの
    # ときは、変わらなかったことを失敗と呼べない —— そのままで良いこともある)
    seeded = not out_plan.exists()
    if seeded:
        out_plan.parent.mkdir(parents=True, exist_ok=True)
        out_plan.write_text(placeholder_text(), encoding="utf-8")

    if verbose:
        print(f"  claude を起動 (cwd={cwd}, permission-mode={permission_mode})")
        if seeded:
            print(f"  雛形を置いた: {out_plan}  (新規作成ではなく編集させる)")
        print(f"  依頼文: {request}\n" + "-" * 60)

    try:
        # 出力はそのまま流す (長時間走るので進捗が見えないと不安になる)
        proc = subprocess.run(cmd, cwd=str(cwd), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _drop_placeholder(out_plan, seeded)
        raise AgentError(f"claude が {timeout:.0f} 秒で終わりませんでした") from exc
    except OSError as exc:
        _drop_placeholder(out_plan, seeded)
        raise AgentError(f"claude の起動に失敗しました: {exc}") from exc

    if verbose:
        print("-" * 60)
    if proc.returncode != 0:
        _drop_placeholder(out_plan, seeded)
        raise AgentError(f"claude が異常終了しました (exit {proc.returncode})")
    if not out_plan.exists():
        raise AgentError(
            f"plan.json が作られませんでした: {out_plan}\n"
            "  --permission-mode を bypassPermissions にするか、\n"
            "  PLAN_REQUEST.md を手で Claude Code に渡してください。"
        )
    if _drop_placeholder(out_plan, seeded):
        # 雛形のまま = 編集すら通っていない。**書き込みの承認ではなく別の
        # ところで止まっている**ので、次に試すことが変わる
        raise AgentError(
            f"plan.json が雛形のままです (claude は書いていません): {out_plan}\n"
            "  --permission-mode を bypassPermissions にするか、\n"
            "  PLAN_REQUEST.md を手で Claude Code に渡してください。"
        )
    return out_plan


def _drop_placeholder(out_plan: Path, seeded: bool) -> bool:
    """雛形のままなら消す. 戻り値は「雛形のままだった」か.

    残すと、画面には台本があるように見えて record で初めて落ちる。
    """
    if not seeded or not out_plan.exists():
        return False
    try:
        untouched = out_plan.read_text(encoding="utf-8") == placeholder_text()
    except OSError:
        return False
    if untouched:
        out_plan.unlink(missing_ok=True)
    return untouched
