"""Windows アプリを自動で操作して撮る (Pass2 の Windows 版).

[record_android.py](record_android.py) と同じ形。ビートごとに `actions` を実行して
1 枚撮り、`beat.shot` に差してから [assemble.py](assemble.py) に渡す。
**出るものが `gmp shoot` (人が撮る道) と同じ**なので、`render` も `check` も
1 行も変わらない。

操作は [windows.py](windows.py) の `Driver` が受け持つ。使える action は下の
`SUPPORTED` だけで、**それ以外は撮る前に落とす** —— 効かないものを書けるままに
すると、台本にあるのに何も起きない行が残る。

## 繰り返し撮れることが、この段の値打ち

人が撮ると、途中で状態が変わったまま撮り足して**同じ画面のはずの 2 枚で表示が
食い違う**ことが起きる (実際に起きた)。機械が通しで撮ればそれが無くなる。
そのために、この段は毎回**同じ状態から始める**:

- `app.setup` が使い捨てのデータを作り直す (`C:\\gmp` の下)
- `app.start` でアプリを起こし、**撮り終わったら畳む** (次の収録に持ち越さない)
- `Driver.fit` でウィンドウを `video.width/height` に合わせる —— 前回の撮影で
  リサイズされたままだと、同じ台本が違うレイアウトを撮る
- セレクタは**中身で指す** (`row=`)。「上から 3 番目」は並び順が変わると別物を押す
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import capture, paths
from .assemble import Assembled, assemble
from .plan import Plan
from .server import hook_env, kill_tree, prepared, run_hook
from .shoot import auto_shot_path
from .windows import DriveError, Driver

# Windows で意味のある action。**`highlight` は入れない** —— 疑似カーソルや枠は
# DOM に注入した JS なので、他人のアプリの上には出せない (Android と同じ)。
# **`select_text` も入れない** —— 文字の範囲は Win32 では相手依存で決まらない
SUPPORTED = ("click", "dblclick", "hover", "type", "press", "select",
             "wait_for", "sleep", "scroll_to")

SETTLE = 0.45           # 押したあと画面が落ち着くまで
WINDOW_WAIT = 30.0      # 起動してウィンドウが出るまで待つ上限


def unsupported(plan: Plan) -> list[str]:
    """使えない action を数える. **撮る前に見る** (途中で落とさない)."""
    bad: list[str] = []
    for scene in plan.scenes:
        for index, beat in enumerate(scene.beats):
            for action in beat.actions:
                kind = action.get("type", "")
                if kind not in SUPPORTED:
                    bad.append(f"{scene.id}#{index}: {kind}")
    return bad


def do(driver: Driver, action: dict) -> None:
    """1 つ操作する."""
    kind = action.get("type", "")
    if kind == "click":
        # `modifiers` は任意 (`Shift` / `Control`)。一覧の範囲選択に要る
        driver.click(action["selector"], modifiers=action.get("modifiers", ""))
    elif kind == "dblclick":
        driver.click(action["selector"], double=True,
                     modifiers=action.get("modifiers", ""))
    elif kind == "hover":
        driver.hover(action["selector"])
    elif kind == "type":
        driver.type_text(action["selector"], action["text"])
    elif kind == "select":
        # **チェックボックスとコンボは「押す」ではなく「その状態にする」。**
        # 押すと前回の状態次第で結果が変わり、2 回目の収録で絵が変わる
        driver.select(action["selector"], action["value"])
    elif kind == "press":
        driver.key(action["key"])
    elif kind == "sleep":
        time.sleep(float(action["seconds"]))
        return
    elif kind == "wait_for":
        if action.get("selector"):
            driver.wait_for(action["selector"], float(action.get("seconds", 10)))
        else:
            time.sleep(float(action.get("seconds", 1)))
        return
    elif kind == "scroll_to":
        driver.scroll_to(action["selector"])
        return
    else:
        raise DriveError(f"Windows では使えない action です: {kind}")
    time.sleep(SETTLE)


def check_goal(driver: Driver, scene, warn) -> None:
    """シーンの達成条件を見る. **`record.Recorder.check_goal` と同じ意味にする**.

    **書いてあるのに効かない、が最悪。** `goal` は台本に書けるので、Windows だけ
    黙って読み飛ばすと「達成条件を入れたから安心」が嘘になる (Android で 1 度
    やった)。語彙は web と同じ `contains` / `absent` だけ。
    """
    goal = getattr(scene, "goal", None)
    if goal is None:
        return
    got = driver.text(goal.selector)
    if got is None:
        warn("goal_failed", scene.id,
             f"達成条件を確かめられません ({goal.selector} が見つかりません): {goal.says}")
        return
    if goal.contains and goal.contains not in got:
        warn("goal_failed", scene.id,
             f"目的を果たしていません: {goal.says} ({goal.selector} = {got!r})")
        return
    if goal.absent and goal.absent in got:
        warn("goal_failed", scene.id,
             f"あってはいけない状態です: {goal.says} ({goal.selector} = {got!r})")


@contextmanager
def launched(app, root: Path, verbose: bool = True):
    """`app.start` でアプリを起こし、抜けるときに畳む.

    **`server.serve` は使えない。** あちらは URL が応答するまで待つ作りで、
    GUI アプリには待つ URL が無い。**`run_hook` も使えない** —— あちらは終わるまで
    待つので、居座るアプリでは仕込みのタイムアウトまで固まる (Android の
    `app.start` が `am start` ですぐ終わるから成り立っていた)。

    **撮り終わったら畳む。** 開いたままにすると、次の収録が前回のウィンドウを
    掴んで、前の状態のまま撮る。畳むのは `app.teardown` より先 (掴まれたままの
    ファイルを消しに行かない)。
    """
    proc = None
    if app.start:
        if verbose:
            print(f"  起動: {app.start}  (cwd={root})")
        flags = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                 if sys.platform == "win32" else {"start_new_session": True})
        proc = subprocess.Popen(
            app.start, shell=True, cwd=str(root), env=hook_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
    try:
        yield wait_for_window(app.window, WINDOW_WAIT, verbose=verbose)
    finally:
        if proc is not None:
            if verbose:
                print("  アプリを終了します")
            kill_tree(proc)
            time.sleep(0.5)


def wait_for_window(title: str, seconds: float, verbose: bool = True):
    """撮るウィンドウが出るまで待つ.

    **起動したときの PID では掴まない** (`capture.find` と同じ理由) —— ストア配信の
    アプリは launcher が別 PID に受け渡して終了する。タイトルで掴み直す。
    """
    deadline = time.monotonic() + seconds
    while True:
        found = capture.find(title)
        if found is not None:
            if verbose:
                print(f"  ウィンドウ: {found.label}")
            return found
        if time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    seen = " / ".join(w.title for w in capture.windows()[:8]) or "(無し)"
    raise DriveError(
        f"{seconds:.0f} 秒待ってもウィンドウが出ません: {title!r}\n"
        f"  開いているもの: {seen}")


def record(plan: Plan, outdir: str | Path, verbose: bool = True,
           base: Path | None = None) -> Assembled:
    """自動で操作して撮り、そのまま組み立てる."""
    outdir = Path(outdir)
    bad = unsupported(plan)
    if bad:
        raise DriveError(
            "Windows では使えない action があります (先に台本を直してください):\n  "
            + "\n  ".join(bad)
            + f"\n使えるのは {' / '.join(SUPPORTED)} です")
    if not plan.app.window:
        raise DriveError("app.window (撮るウィンドウのタイトル) がありません")

    problems: list[str] = []
    warnings: list[dict] = []

    def warn(kind: str, where: str | None, message: str) -> None:
        """**止めない失敗を数えられる形で残す** (`record.Recorder.warn` と同じ)."""
        warnings.append({"kind": kind, "where": where, "message": message})
        print(f"    ! {message}")

    root = base or paths.record_base(plan.project, plan.source, plan.app.cwd)
    # **仕込みと後片付けは Web / Android と同じ道を通す。** 順序の不変条件
    # (仕込みは start より前、後片付けはアプリを畳んでから) をここで作り直さない
    with prepared(plan.app, root, verbose=verbose, problems=problems):
        with launched(plan.app, root, verbose=verbose):
            driver = Driver(plan.app.window, timeout=float(plan.app.start_timeout))
            # **大きさを合わせてから撮る。** 前回のリサイズが残っていると、
            # 同じ台本が違うレイアウトの絵を出す
            driver.fit(plan.video.width, plan.video.height)

            for scene in plan.scenes:
                if verbose:
                    print(f"  ● scene {scene.id}")
                for index, beat in enumerate(scene.beats):
                    where = f"{scene.id}#{index}"
                    try:
                        for action in beat.actions:
                            do(driver, action)
                    except DriveError as exc:
                        raise DriveError(f"{where}: {exc}") from exc
                    # **落ち着いてから撮る。** 出たばかりのウィンドウは中身が
                    # まだ描かれていないことがあり、枠だけの白紙が撮れる
                    time.sleep(SETTLE)
                    dest, relative = auto_shot_path(outdir, scene.id, index)
                    capture.shot(driver.window.handle, dest)
                    # **メモリ上の plan にだけ差す** (plan.json は書き換えない)
                    beat.shot = relative
                    if verbose:
                        print(f"    {where}  {relative}")
                check_goal(driver, scene, warn)

    # 後片付けの失敗は収録を失敗にしないが、黙って捨てもしない
    for message in problems:
        warn("teardown_failed", None, message)

    return assemble(plan, outdir, verbose=verbose, warnings=warnings)
