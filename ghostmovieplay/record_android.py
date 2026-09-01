"""Android を自動で操作して撮る (Pass2 の Android 版).

**人が撮る道 (`gmp shoot`) と出るものが同じ。** ビートごとに `actions` を実行して
1 枚撮り、`beat.shot` に差してから [assemble.py](assemble.py) に渡す。
だから `render` も `check` も 1 行も変わらない。

**plan.json は書き換えない。** ショットの place はメモリ上の `Plan` にだけ差す
(`beat.audio` を `gmp voice` が書き戻すのとは別。あちらは合成の結果を残す必要が
あるが、ショットは撮るたびに作り直されるので焼く意味が無い)。

**撮り直しが安くなるのがこの段の値打ち。** 人が撮ると、途中で状態が変わったまま
撮り足して**同じ画面のはずの 2 枚で表示が食い違う**ことが起きる (実際に起きた)。
機械が通しで撮ればそれが無くなる。

操作は [android.py](android.py) の `Driver` が受け持つ。使える action は下の
`SUPPORTED` だけで、**それ以外は撮る前に落とす** —— 効かないものを書けるままに
すると、台本にあるのに何も起きない行が残る。
"""

from __future__ import annotations

import time
from pathlib import Path

from . import capture_android, paths
from .android import DriveError, Driver
from .assemble import Assembled, assemble
from .plan import Plan
from .server import prepared
from .shoot import auto_shot_path

# Android で意味のある action。**`highlight` は入れない** —— 疑似カーソルや
# 枠は DOM に注入した JS なので、他人のアプリの上には出せない
# (docs/ideas/android.md の「render 時に合成する」が入るまで書けない)
SUPPORTED = ("click", "type", "press", "wait_for", "sleep", "scroll_to")

SCROLL_TRIES = 6        # scroll_to で送る回数
SETTLE = 0.6            # 押したあと画面が落ち着くまで


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
        driver.tap(action["selector"])
    elif kind == "type":
        driver.type_text(action["selector"], action["text"])
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
        scroll_to(driver, action["selector"])
        return
    else:
        raise DriveError(f"Android では使えない action です: {kind}")
    time.sleep(SETTLE)


def scroll_to(driver: Driver, selector: str) -> None:
    """出てくるまで送る. **出なければ落とす** (見えていない画面を撮らない)."""
    for _ in range(SCROLL_TRIES):
        if driver.find(selector) is not None:
            return
        driver.swipe(driver.width // 2, int(driver.height * 0.75),
                     driver.width // 2, int(driver.height * 0.30))
        time.sleep(SETTLE)
        driver.refresh()
    if driver.find(selector) is None:
        raise DriveError(f"{selector} は {SCROLL_TRIES} 回送っても出ません")


def check_goal(driver: Driver, scene, warn) -> None:
    """シーンの達成条件を見る. **`record.Recorder.check_goal` と同じ意味にする**.

    **書いてあるのに効かない、が最悪。** `goal` は台本に書ける (`plan.Goal`) ので、
    Android だけ黙って読み飛ばすと「達成条件を入れたから安心」が嘘になる。
    語彙は web と同じ `contains` / `absent` だけ (Pass2 に AI を入れない)。

    見る場所は Android のセレクタで、**その矩形の中の文字**を読む
    (`android.text_within`)。
    """
    goal = getattr(scene, "goal", None)
    if goal is None:
        return
    driver.refresh()
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


def pick_device(serial: str = "") -> capture_android.Device:
    """撮る端末を選ぶ. **1 台に決まらないなら落とす**.

    シリアルは plan.json に無い (機械ごとに違うので焼かない) ので、
    繋がっているものから選ぶ。2 台あるなら呼び側が指定する。
    """
    found = capture_android.windows()
    if serial:
        hit = capture_android.find(serial)
        if hit is None:
            raise DriveError(f"端末 {serial} が見つかりません")
        return hit
    if not found:
        raise DriveError("端末が繋がっていません (adb devices で確認してください)")
    if len(found) > 1:
        names = " / ".join(d.handle for d in found)
        raise DriveError(f"端末が {len(found)} 台あります。1 台を選んでください: {names}")
    return found[0]


def record(plan: Plan, outdir: str | Path, verbose: bool = True,
           serial: str = "", base: Path | None = None) -> Assembled:
    """自動で操作して撮り、そのまま組み立てる."""
    outdir = Path(outdir)
    bad = unsupported(plan)
    if bad:
        raise DriveError(
            "Android では使えない action があります (先に台本を直してください):\n  "
            + "\n  ".join(bad)
            + f"\n使えるのは {' / '.join(SUPPORTED)} です")

    device = pick_device(serial)
    driver = Driver(device.handle, (device.width, device.height))
    if verbose:
        print(f"  端末: {device.label}")

    problems: list[str] = []
    warnings: list[dict] = []

    def warn(kind: str, where: str | None, message: str) -> None:
        """**止めない失敗を数えられる形で残す** (`record.Recorder.warn` と同じ)."""
        warnings.append({"kind": kind, "where": where, "message": message})
        print(f"    ! {message}")

    root = base or paths.record_base(plan.project, plan.source, plan.app.cwd)
    # **仕込みと起動は Web と同じ道を通す。** 順序の不変条件 (仕込みは start より
    # 前、後片付けはアプリを畳んでから) をここで作り直さない
    with prepared(plan.app, root, verbose=verbose, problems=problems):
        if plan.app.start:
            from .server import run_hook

            run_hook(plan.app.start, root, "起動", verbose)
            time.sleep(2.0)         # アプリが出るまで
        if plan.app.ready:
            driver.wait_for(plan.app.ready, float(plan.app.start_timeout))

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
                dest, relative = auto_shot_path(outdir, scene.id, index)
                capture_android.shot(device.handle, dest)
                # **メモリ上の plan にだけ差す** (plan.json は書き換えない)
                beat.shot = relative
                if verbose:
                    print(f"    {where}  {relative}")
            check_goal(driver, scene, warn)

    # 後片付けの失敗は収録を失敗にしないが、黙って捨てもしない
    # (`prepared` が積むのは with を抜けたあとなので、ここで混ぜる)
    for message in problems:
        warn("teardown_failed", None, message)

    return assemble(plan, outdir, verbose=verbose, warnings=warnings)
