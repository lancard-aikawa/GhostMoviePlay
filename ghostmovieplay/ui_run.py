"""「撮る」面 (tkinter). `gmp ui --run` で最初から開く.

**ここは CLI を別プロセスで呼ぶだけの画面**にしてある。`record()` や `render()`
を関数として呼び込むと、GUI が設定を独自に解決して渡す経路ができ、「設定は
Pass1 で plan.json に焼き切る」がそこで破れる。渡すのは plan.json のパスと、
絵と音を変えない `--headed` だけ。

同じ理由で、**絵と音を変える引数は画面に出さない。** `--no-subtitles` /
`--no-audio` / `--no-credit` / `--sync-offset` は CLI に置いたままにする。
とくに `--no-credit` をチェックボックスにすると、VOICEVOX のクレジットを
ワンクリックで落とせてしまう (「音声を乗せたらクレジットも焼く」を破る)。

別プロセスにするもう 1 つの理由は尺で、Playwright と ffmpeg は数分かかる。
同じスレッドで呼ぶと画面が固まり、中止もできない。

画面を作らずに決まる部分 (成果物の状態・押せる段・組み立てるコマンド) は
モジュール関数にしてある。tests/test_ui_run.py が見ている。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from . import paths

# --- 成果物の状態 -----------------------------------------------------
READY, STALE, PARTIAL, MISSING = "ready", "stale", "partial", "missing"

MARK = {READY: "✓", STALE: "!", PARTIAL: "…", MISSING: "·"}
# 太字などはテーマ次第で効かないので、色で差をつける
STATE_COLOR = {READY: "#2e7d32", STALE: "#b00000", PARTIAL: "#b06000", MISSING: "#999999"}


@dataclass(frozen=True)
class Item:
    """成果物 1 つの状態."""

    key: str
    label: str          # 「台本」
    what: str           # 「plan.json」
    path: Path | None   # 新しさを見るファイル (この行の代表)
    state: str
    detail: str
    # 押したときに開く先。**代表と違うことがある** —— 収録の行は timing.json で
    # 新しさを見るが、人が見たいのは撮れた映像 (raw.webm) のほう
    opens: Path | None = None


@dataclass(frozen=True)
class Survey:
    """いま選ばれている 1 本の、成果物の揃いぐあい."""

    spec: Path | None = None
    plan: Path | None = None
    outdir: Path | None = None
    request: Path | None = None      # PLAN_REQUEST.md (Pass1 を手でやる逃げ道)
    title: str = ""
    error: str = ""
    estimate: float | None = None
    measured: bool = False
    warning: str = ""                # 止めはしないが先に言うこと
    items: tuple[Item, ...] = ()
    # **支援収録の 1 本か** (app.window がある = 人が操作して撮る)。
    # 段は同じ (「収録する」が組み立てに回る) が、ショットを貯める道が要る
    assisted: bool = False

    def item(self, key: str) -> Item | None:
        return next((i for i in self.items if i.key == key), None)

    def state(self, key: str) -> str:
        found = self.item(key)
        return found.state if found else MISSING


def _mtime(path: Path | None) -> float | None:
    try:
        return path.stat().st_mtime if path else None
    except OSError:
        return None


def _stamp(when: float) -> str:
    return datetime.fromtimestamp(when).strftime("%m/%d %H:%M")


def survey(spec: Path | None) -> Survey:
    """動画 1 本ぶんの成果物を見て回る. plan.json が壊れていても落ちない."""
    if spec is None:
        return Survey()
    spec = Path(spec)
    plan_path = spec.parent / "plan.json"
    # **鎖の先頭は video.md そのもの。** ここを出さないと「台本を作る」の
    # 手前に何があるのかが画面から分からない
    resolved = _resolve(spec)
    written = _spec_item(spec, resolved)
    warning = _template_warning(resolved)
    script = _script_item(spec, plan_path)
    if not plan_path.is_file():
        # 台本が無くても出力先は決まる (依頼文はそこに出る)。「台本を作ると
        # 決まります」と言っていたころは、Pass1 が失敗したときに**依頼文が
        # どこに出たのか画面から辿れなかった**
        outdir = _outdir(spec, resolved)
        return Survey(spec=spec, plan=plan_path, outdir=outdir, warning=warning,
                      request=(outdir / "PLAN_REQUEST.md") if outdir else None,
                      items=(written, script))

    from .plan import PlanError, estimate, load

    try:
        loaded = load(plan_path)
    except (PlanError, OSError, ValueError) as exc:
        # PlanError は先頭にフルパスが付く。行にも理由の欄にも plan.json とは
        # 書いてあるので、**パスで埋めると肝心の理由が見えなくなる**
        reason = str(exc).removeprefix(f"{plan_path}: ")
        broken = replace(script, state=STALE, detail=f"読めません: {reason}")
        return Survey(spec=spec, plan=plan_path, error=reason, warning=warning,
                      items=(written, broken))

    outdir = paths.resolve_outdir(plan_path, project=loaded.project, app_cwd=loaded.app.cwd)
    seconds, measured = estimate(loaded, outdir)
    assisted = loaded.app.assisted
    rows = [written, script]
    if assisted:
        # **ショットの行は支援収録のときだけ出す。** 自動収録では撮る段がショットも
        # 作るので、行を分けると段と行が 1 対 1 でなくなる
        rows.append(_shots_item(loaded, outdir))
    rows += [_voice_item(loaded, outdir),
             _record_item(plan_path, outdir, assisted), _output_item(outdir)]
    return Survey(
        spec=spec, plan=plan_path, outdir=outdir, warning=warning,
        request=outdir / "PLAN_REQUEST.md", title=loaded.title,
        estimate=seconds, measured=measured, assisted=assisted,
        items=tuple(rows),
    )


def _resolve(spec: Path):
    """3 層を解決する. 読めなければ None (画面は開く).

    設定を読むのは**置き場所と、雛形のままかを知るためだけ**。絵と音には
    触らない (Pass2/3 が設定を読んではいけない、とは別の話)。
    """
    from . import settings
    from .spec import parse

    try:
        return settings.load(spec=spec, video=parse(spec).raw)
    except Exception:                                   # noqa: BLE001
        return None


def _outdir(spec: Path, resolved) -> Path | None:
    """台本がまだ無いときの出力先. `gmp plan` と同じ解き方をする."""
    if resolved is None:
        return None
    try:
        return paths.resolve_outdir(
            spec, project=resolved.get("project"),
            app_cwd=resolved.rebase_path("app.cwd", spec.parent),
        )
    except Exception:                                   # noqa: BLE001
        return None


def _stale_fields(resolved) -> list[str]:
    """雛形の見本値のままの項目. 1 つだけなら偶然もあるので 2 つ以上で言う."""
    if resolved is None:
        return []
    from .spec import unfilled

    found = unfilled(resolved)
    return found if len(found) >= 2 else []


def _template_warning(resolved) -> str:
    """Pass1 を呼ぶ前に言うこと. 空なら言うことは無い."""
    stale = _stale_fields(resolved)
    if stale:
        return ("構成が雛形の見本値のままです (" + " / ".join(stale) + ")。"
                "「claude に書かせる」で埋められます")
    if resolved is not None and not resolved.get("app.url"):
        # 見本値を焼かなくなったぶん、こちらが普通の未設定状態になる
        return ("収録する URL が決まっていません。"
                "「claude に書かせる」でソースから調べさせられます")
    return ""


def _spec_item(spec: Path, resolved=None) -> Item:
    """video.md = 構成 (シーンと狙いを人が書く).

    **台本 (plan.json) ではない。** セリフ (say) とト書き (actions) が
    入っているのは plan.json だけで、video.md が持つのはシーンと狙い。
    """
    made = _mtime(spec)
    if made is None:
        return Item("spec", "構成", "video.md", spec, MISSING, "まだありません")
    stale = _stale_fields(resolved)
    if stale:
        # **雛形のままだと Pass1 は必ず訊き返してくる。** 呼ぶ前に見せる
        return Item("spec", "構成", "video.md", spec, PARTIAL,
                    "雛形の既定のまま: " + " / ".join(stale))
    return Item("spec", "構成", "video.md", spec, READY, _stamp(made))


def _script_item(spec: Path, plan_path: Path) -> Item:
    made = _mtime(plan_path)
    if made is None:
        return Item("plan", "台本", "plan.json", plan_path, MISSING, "まだありません")
    source = _mtime(spec)
    if source is not None and source > made:
        return Item("plan", "台本", "plan.json", plan_path, STALE,
                    "video.md のほうが新しい")
    return Item("plan", "台本", "plan.json", plan_path, READY, _stamp(made))


def _voice_item(loaded, outdir: Path) -> Item:
    """音声は **揃っているかどうかだけ** を見る.

    新しいかどうかは `voice/manifest.json` のフィンガープリントが判定する
    (原稿と声の設定のハッシュ)。ここで mtime を比べても嘘になる ——
    `gmp voice` は manifest を書いたあとに plan.json を書き戻すので、
    合成した直後でも plan.json のほうが必ず新しい。
    """
    directory = outdir / "voice"
    want = [b for _, b in loaded.beats if (b.say or "").strip()]
    if not want:
        return Item("voice", "音声", "voice/", directory, READY, "読み上げるビートがありません")
    have = [b for b in want if b.audio and (outdir / b.audio).is_file()]
    if not have:
        return Item("voice", "音声", "voice/", directory, MISSING, f"0 / {len(want)} ビート")
    if len(have) < len(want):
        return Item("voice", "音声", "voice/", directory, PARTIAL,
                    f"{len(have)} / {len(want)} ビート")
    return Item("voice", "音声", "voice/", directory, READY,
                f"{len(have)} ビート (原稿か声を変えた分だけ作り直します)")


# **収録は 2 つ作る。** 無音の映像 (素材) と、ビートの実測時刻。片方しか
# 書いていないと、「収録する」を押すと何が出来るのかが画面から分からない
WHAT_RECORD = "raw.webm + timing.json"
# 支援収録は撮らずに並べるので、出るものも名前も違う (mp4 を組み立てる)
WHAT_ASSEMBLE = "raw.mp4 + timing.json"


def _shots_item(loaded, outdir: Path) -> Item:
    """人が撮ったショット. **揃っているかどうかだけ**を見る.

    新しいかどうかは言えない —— 撮り直しの効かないショットなので、mtime を比べても
    「アプリが変わったのに絵が古い」は分からない (`gmp check` が効かないのと
    同じ理由。docs/ideas/desktop.md)。
    """
    directory = outdir / "shots"
    want = [b for _, b in loaded.beats]
    have = [b for b in want if b.shot and (outdir / b.shot).is_file()]
    if not have:
        return Item("shots", "ショット", "shots/", directory, MISSING,
                    f"0 / {len(want)} ビート")
    if len(have) < len(want):
        return Item("shots", "ショット", "shots/", directory, PARTIAL,
                    f"{len(have)} / {len(want)} ビート")
    return Item("shots", "ショット", "shots/", directory, READY,
                f"{len(have)} ビート")


def _record_item(plan_path: Path, outdir: Path, assisted: bool = False) -> Item:
    timing = outdir / "timing.json"
    what = WHAT_ASSEMBLE if assisted else WHAT_RECORD
    made = _mtime(timing)
    if made is None:
        return Item("timing", "収録", what, timing, MISSING, "まだ撮っていません")
    source = _mtime(plan_path)
    if source is not None and source > made:
        # 音声を作り直すと plan.json に尺が書き戻される。**音声の尺がビートの
        # 尺そのもの**なので、そのときは本当に撮り直しが要る
        return Item("timing", "収録", what, timing, STALE,
                    "plan.json のほうが新しい (撮り直しが要ります)")
    facts = _timing(timing)
    # **どの映像が出来たかは timing.json が知っている。** 名前を決め打ちすると
    # 支援収録 (raw.mp4) で「再生」が押せない行になる
    raw = outdir / str(facts.get("source_video") or "raw.webm")
    opens = raw if raw.is_file() else None
    detail = _stamp(made)
    try:
        detail += f"   {float(facts['duration']):.1f} 秒"
    except (KeyError, TypeError, ValueError):
        pass

    # **収録が通ったことは、狙った画面が映っている証明にはならない。**
    # 光らせ損ね・選択のずれ・音声の欠落は録画を止めないので、残っている
    # 警告をここで出す。仕上げは止めない (blocker が見るのは MISSING だけ) ——
    # 撮れてはいるので、直すのは台本のほうだと言えれば足りる
    warnings = facts.get("warnings") or []
    if warnings:
        detail += f"   ! 警告 {len(warnings)} 件: {_first_message(warnings)}"
        return Item("timing", "収録", WHAT_RECORD, timing, STALE, detail, opens)
    return Item("timing", "収録", WHAT_RECORD, timing, READY, detail, opens)


def _output_item(outdir: Path) -> Item:
    video = outdir / "output.mp4"
    made = _mtime(video)
    if made is None:
        return Item("output", "完成", "output.mp4", video, MISSING, "まだありません")
    source = _mtime(outdir / "timing.json")
    if source is not None and source > made:
        return Item("output", "完成", "output.mp4", video, STALE,
                    "収録のほうが新しい (仕上げ直しが要ります)")
    return Item("output", "完成", "output.mp4", video, READY, _stamp(made))


# 行を開くと何が起きるか。**ダブルクリックできることが画面に書いていない**と、
# 知らない人は辿り着けない (実際に辿り着けなかった)。行に動詞を出す
ACTION = {"spec": "編集", "plan": "編集", "output": "再生",
          "voice": "フォルダ", "shots": "フォルダ"}


def action_label(item: Item) -> str:
    """その行を押すと何が起きるか. 押せない行は空文字."""
    # **ショットの行はフォルダではなく撮る画面を開く。** ここをボタンにすると
    # 行の複製になる (「開く操作は表の行に集約」)
    if item.key == "shots":
        return "撮る"
    target = item.opens or item.path
    if target is None:
        return ""
    if not target.exists():
        # まだ無い行は、出来る場所を開く (どこに出るのかを見せる)
        return "出る場所"
    if target.suffix in (".mp4", ".webm"):
        return "再生"
    return ACTION.get(item.key, "開く")


def _timing(timing: Path) -> dict:
    """timing.json の中身. 読めなければ空 (画面は落ちない)."""
    import json

    try:
        data = json.loads(timing.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_message(warnings: list) -> str:
    """いちばん上の警告の文. 件数だけでは何を直すのか分からない."""
    head = warnings[0]
    return str(head.get("message", "")) if isinstance(head, dict) else str(head)


# --- 段 ---------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    key: str
    title: str
    note: str
    needs: str          # 揃っていないと押せないもの ("spec" / "plan" / "timing")
    makes: str = ""     # その段が作る行 (表の呼び名と同じ言葉にする)


# **段は表の行を 1 つずつ作る。** どの段がどの行を作るのかを画面に出さないと、
# 「収録する」と「仕上げる」の境目が読めない (実際に読めなかった)
STEPS: tuple[Step, ...] = (
    Step("plan", "台本を作る", "対話の claude を開いて plan.json を書かせる (Pass1)",
         "spec", "台本"),
    Step("voice", "声を作る", "say を読み上げて wav にし、plan.json に尺を書き戻す",
         "plan", "音声"),
    Step("record", "収録する",
         "plan.json のとおりに操作して録画する。字幕も音声もまだ乗らない (Pass2)",
         "plan", "収録"),
    Step("render", "仕上げる",
         "撮れた素材に字幕と音声を乗せて mp4 にする。撮り直しは要らない (Pass3)",
         "timing", "完成"),
    Step("build", "通しで作る", "声 → 収録 → 仕上げ を続けて実行する",
         "plan", "音声〜完成"),
)


def blocker(step: Step, found: Survey) -> str:
    """その段を押せない理由. 押せるなら空文字."""
    if found.spec is None:
        return "上の「動画の構成」で、撮るものを選んでください"
    if found.error and step.key != "plan":
        return f"台本が読めません: {found.error}"
    # 台本が無いときに仕上げへ「先に収録します」と言っても遠回りになる。
    # いちばん手前の欠けを言う
    if step.needs in ("plan", "timing") and not (found.plan and found.plan.is_file()):
        return "先に台本を作ります"
    if step.needs == "timing" and found.state("timing") == MISSING:
        return "先に収録します"
    return ""


def argv(step: Step, found: Survey, headed: bool = False) -> list[str]:
    """その段が叩く `gmp` の引数.

    **絵と音を変える引数は組み立てない。** それらは plan.json に書いてある
    情報であって、画面のチェックボックスで決めてよいものではない。
    """
    show = ["--headed"] if headed else []
    if step.key == "plan":
        # **`--run` (-p) ではなく `--open`。** 収録対象やセレクタが決まって
        # いないと claude は訊いてくるが、-p には答える相手がいないので、
        # 何も書かずに終わる (実際に終わった)
        return ["plan", str(found.spec), "--open"]
    if step.key == "voice":
        return ["voice", str(found.plan)]
    if step.key == "record":
        return ["record", str(found.plan), *show]
    if step.key == "render":
        return ["render", str(found.outdir / "timing.json")]
    if step.key == "build":
        return ["build", str(found.plan), "--voice", *show]
    raise ValueError(f"未知の段: {step.key}")


# --- 新しい動画 --------------------------------------------------------
def video_home(directory: Path, existing: list[Path]) -> Path:
    """新しい動画のフォルダを置く場所.

    **既に 1 本でもあるなら、その隣に揃える。** プロジェクトごとに置き場所の
    流儀が違う (docs/video/ とは限らない) ので、既定を押しつけると散らばる。
    """
    if existing:
        return existing[0].parent.parent
    return directory / "docs" / "video"


def init_target(directory: Path, existing: list[Path], name: str) -> Path | None:
    """作る video.md の置き場所. 名前が空か、使えない字だけなら None."""
    clean = paths.sanitize(name.strip(), fallback="")
    if not clean:
        return None
    return video_home(directory, existing) / clean / "video.md"


def command(args: list[str]) -> list[str]:
    """実際に起動する argv.

    PATH の `gmp` ではなく **いま動いている python** の -m で叩く。
    venv の外から拾った別バージョンに当たると、画面と中身がずれる。
    """
    return [sys.executable, "-m", "ghostmovieplay", *args]


def child_env() -> dict[str, str]:
    """子プロセスの環境.

    Windows の既定コンソールは cp932 で、パイプ越しだと `—` や `…` を
    書けずに落ちる。読む側も書く側も utf-8 に揃える。行が溜まると進捗が
    見えないのでバッファリングも切る。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def open_path(path: Path) -> None:
    """OS の既定のアプリで開く (tkinter に動画を出す手立ては無い)."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))                     # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        messagebox.showerror("開けません", f"{path}\n\n{exc}")


# --- 走らせる ---------------------------------------------------------
class Runner:
    """`gmp` を 1 つだけ走らせ、出力を行単位で渡す."""

    # 子が死んだあと、孫がパイプを掴んだままのときに待つ上限 (秒)
    DRAIN = 2.0

    def __init__(self, widget: tk.Misc, on_line, on_done):
        self.widget = widget
        self.on_line = on_line
        self.on_done = on_done
        self.proc: subprocess.Popen | None = None
        self.run_id = 0          # 前の実行の残りを捨てるための世代
        self.done = True

    @property
    def busy(self) -> bool:
        return not self.done

    def start(self, args: list[str], cwd: Path) -> bool:
        if self.busy:
            return False
        self.on_line("$ gmp " + " ".join(args))
        try:
            self.proc = subprocess.Popen(
                command(args), cwd=str(cwd), env=child_env(),
                stdin=subprocess.DEVNULL,          # 訊かれても答えられない
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            self.on_line(f"起動できません: {exc}")
            self.on_done(-1)
            return False
        self.run_id += 1
        self.done = False
        pump = threading.Thread(target=self._pump, args=(self.proc, self.run_id), daemon=True)
        pump.start()
        threading.Thread(target=self._watch, args=(self.proc, self.run_id, pump),
                         daemon=True).start()
        return True

    def _pump(self, proc: subprocess.Popen, run_id: int) -> None:
        """子の出力を本スレッドへ渡す.

        ウィンドウを閉じたあとも数行は流れてくる (中止しても子は即死しない)。
        渡し先が消えていたら黙って諦める —— 捨てないと、閉じるたびに
        スレッドの例外がコンソールへ出る。
        """
        try:
            for line in proc.stdout:                   # type: ignore[union-attr]
                self.widget.after(0, self._line, run_id, line.rstrip("\n"))
        except (RuntimeError, tk.TclError, ValueError, OSError):
            pass

    def _watch(self, proc: subprocess.Popen, run_id: int, pump: threading.Thread) -> None:
        """**完了はプロセスの終了で判定する。パイプの EOF では判定しない。**

        `gmp plan --run` が起こす claude は、MCP サーバのような孫を残すことが
        ある。孫は stdout のパイプを継いでいるので、gmp が終わってもパイプは
        閉じない。EOF を待つと**画面が「実行中」のまま固まり、台本が出来ている
        のに次の段が押せない**（実際にそうなった）。

        ふつうは最後の行を出しきってから終わりたいので、少しだけ pump を待つ。
        掴まれたままなら諦めて先へ進む。
        """
        code = proc.wait()
        pump.join(timeout=self.DRAIN)
        stuck = pump.is_alive()
        try:
            self.widget.after(0, self._finish, run_id, code, stuck)
        except (RuntimeError, tk.TclError):
            pass

    def _line(self, run_id: int, text: str) -> None:
        if run_id == self.run_id:
            self.on_line(text)

    def _finish(self, run_id: int, code: int, stuck: bool = False) -> None:
        # 二重に終わらせない (前の実行の後始末が遅れて届くことがある)
        if run_id != self.run_id or self.done:
            return
        self.done = True
        if stuck:
            self.on_line("-- 出力の受け口が閉じません"
                         " (孫プロセスが残っています)。先へ進みます --")
        self.on_done(code)

    def stop(self) -> None:
        """中止. **子孫ごと**落とす.

        record は chromium を、render は ffmpeg を、plan は claude を
        それぞれ子として抱えている。親だけ terminate すると、画面上は
        止まったのに録画やエンコードが裏で走り続ける。
        """
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, check=False,
            )
        else:
            proc.terminate()


# --- 画面 -------------------------------------------------------------
class RunPane:
    """撮る面. 親フレームに収まる (ウィンドウは ui.AppWindow が持つ).

    画面の言葉づかいは README の「呼び名」に揃える。**video.md = 構成、
    plan.json = 台本。** セリフとト書きが入っているのは plan.json だけで、
    紹介動画のナレーションも「台本」を plan.json の意味で喋っている。
    **「1本」は数え方なので物の名前には使わない** ——「台本を作る」の隣に
    「1本を作る」を置くと台本の数に読める。数えるときだけ
    「動画が 1 本もありません」と使う。
    """

    LOG_LIMIT = 4000        # 行. 長い収録を流しっぱなしにしても膨らませない

    def __init__(self, parent: tk.Misc, state):
        self.body = parent
        self.state = state
        self.survey = Survey()
        self.headed = tk.BooleanVar(value=False)
        self.buttons: dict[str, tk.Button] = {}
        self.cells: dict[str, tuple] = {}    # 表の行 (ダブルクリックで開く)
        self.running: str = ""
        self.running_key: str = ""           # いま走らせている段
        self.failed_step: str = ""           # 直前に落ちた段 (逃げ道の出し分け)
        self.pending: Path | None = None     # 作り終えたら選ぶ動画
        self.last_error = ""                # 直前の実行が出した `gmp: ` の行
        self.more_error = False             # その続き (直し方) を拾っている最中か
        self.failure = ""                   # 直前の実行の失敗 (次を始めるまで残す)
        self.runner = Runner(parent, self.on_line, self.on_done)

        # 上から順に積んで、最後にログだけ expand させる。ログより下に何も
        # 置かないので、フッターが押し出される罠 (CLAUDE.md) は起きない
        self._build_head()
        self._build_table()
        self._build_steps()
        self._build_failure()
        self._build_log()

        # **「調べ直す」ボタンは置かない。** 外で video.md や plan.json を直して
        # 戻ってきたときに押させるためのボタンだったので、**戻ってきたことを
        # 見て自分で調べ直す**
        parent.winfo_toplevel().bind("<FocusIn>", self._on_focus, add="+")

        self.refresh()

    def _on_focus(self, event) -> None:
        top = self.body.winfo_toplevel()
        if event.widget is not top:
            return                      # 子ウィジェットからも上がってくる
        if self.runner.busy or not self.body.winfo_ismapped():
            return
        self.refresh()

    # --- 組み立て ----------------------------------------------------
    def _build_head(self) -> None:
        head = tk.Frame(self.body)
        head.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(8, 2))
        self.title_label = tk.Label(head, text="", anchor="w", font=("", 11, "bold"))
        self.title_label.pack(side=tk.TOP, fill=tk.X)
        self.outdir_label = tk.Label(head, text="", anchor="w", fg="#666")
        self.outdir_label.pack(side=tk.TOP, fill=tk.X)

    def _build_table(self) -> None:
        self.table = tk.Frame(self.body)
        self.table.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(6, 0))
        self.table.columnconfigure(3, weight=1)
        # **行を開けるようにしたので、「構成を編集」「出力フォルダを開く」
        # 「完成した動画を再生」の 3 つは消した。** 行にはもうファイル名が
        # 出ているので、あの 3 つは表の複製だった
        tk.Label(self.body, fg="#999", anchor="w",
                 text="行をダブルクリックすると開きます"
                      "（完成した動画は再生。まだ無い行はそのフォルダ）").pack(
            side=tk.TOP, fill=tk.X, padx=10, pady=(2, 0))

    def _build_steps(self) -> None:
        box = tk.Frame(self.body)
        box.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(8, 2))
        # **段の手前に「構成を作る」を置く。** ここが無いと、video.md が 1 つも
        # 無いプロジェクトを選んだ人は全部のボタンが押せないまま行き止まる。
        # 「1本」は数え方なので物の名前には使わない (台本の隣だと台本の数に読める)
        self.init_button = tk.Button(box, text="構成を作る", width=12, command=self.on_init)
        self.init_button.grid(row=0, column=0, padx=(0, 6))
        tk.Label(box, text="→", fg="#999").grid(row=0, column=1, padx=(0, 6))
        for column, step in enumerate(STEPS, start=2):
            button = tk.Button(box, text=step.title, width=12,
                               command=lambda s=step: self.on_step(s))
            button.grid(row=0, column=column, padx=(0, 6))
            self.buttons[step.key] = button
            # **段が作る行を、表と同じ言葉でボタンの下に出す。** これが無いと
            # 「収録する」と「仕上げる」の境目が画面から読めない
            tk.Label(box, text=f"→ {step.makes}", fg="#999").grid(
                row=1, column=column, sticky="w")
            # 詳しい説明は乗せたときだけ (常に出すと帯が説明で埋まる)
            button.bind("<Enter>", lambda _e, s=step: self._hint(s))
            button.bind("<Leave>", lambda _e: self._refresh_buttons())
        tk.Checkbutton(box, text="ブラウザを見ながら撮る", variable=self.headed).grid(
            row=0, column=len(STEPS) + 2, padx=12)
        # 中止は段の裏返しなので段の並びに置く (走っている間だけ効く)
        self.stop_button = tk.Button(box, text="中止", width=8, state=tk.DISABLED,
                                     command=self.on_stop)
        self.stop_button.grid(row=0, column=len(STEPS) + 3, padx=6)
        self.steps_box = box

        note = tk.Frame(self.body)
        note.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 4))
        # **指摘するだけで終わらせない。** 収録対象は project か video にしか
        # 置けず、設定画面は video.md を書かない。押せる直し口が無いと、
        # 「画面から直せない値を画面が指摘する」行き止まりになる
        # **素人に「URL と起動コマンドとセレクタを調べて書いて」は無理筋。**
        # 読める者に読ませる。**画面が代わりに決める機能を並べない** ——
        # 収録対象を画面から直す道も持っていたが、claude に書かせるほうが
        # 上位互換 (シーン構成まで書く) で、同じ場所に 2 つ並ぶだけだった
        self.write_button = tk.Button(note, text="claude に書かせる",
                                      command=self.on_write_spec)
        self.step_note = tk.Label(note, text="", anchor="w", fg="#666",
                                  justify=tk.LEFT, wraplength=760)
        self.step_note.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_failure(self) -> None:
        """失敗したときだけ出る帯.

        **逃げ道は要るときにだけ出す。** `依頼文を書く` も `前提を調べる` も、
        うまくいっている間は押す理由が無い。常に並べていたので、詰まるたびに
        ボタンが増えていった（機能が足りないのではなく、画面が状態を伝えて
        いない穴をボタンで塞いでいた）。
        """
        self.failure_bar = tk.Frame(self.body)
        self.doctor_button = tk.Button(self.failure_bar, text="前提を調べる",
                                       command=self.on_doctor)
        self.doctor_button.pack(side=tk.RIGHT, padx=(6, 0))
        self.failure_label = tk.Label(self.failure_bar, text="", anchor="w",
                                      fg="#b00000", justify=tk.LEFT, wraplength=620)
        self.failure_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_log(self) -> None:
        frame = tk.Frame(self.body)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(2, 0))
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        # 横スクロールバーを出さないので折り返す。none にすると長い行 (パスや
        # ffmpeg のコマンド) が右へ消えたまま読めなくなる。日本語が混じるので
        # word ではなく char で折る
        self.log = tk.Text(frame, height=12, wrap="char", state=tk.DISABLED,
                           bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.configure(command=self.log.yview)

    # --- 中身の入れ替え ----------------------------------------------
    def _hint(self, step: Step) -> None:
        """段の説明を下の帯に出す (乗っている間だけ)."""
        if self.runner.busy:
            return
        why = blocker(step, self.survey)
        self.step_note.config(text=f"{step.title}: {step.note}"
                                   + (f"   —— いまは押せません ({why})" if why else ""),
                              fg="#666")

    def refresh(self) -> None:
        """成果物を見直して、表と押せるボタンを作り直す."""
        try:
            self.survey = survey(self.state.spec)
        except OSError as exc:
            self.survey = Survey(spec=self.state.spec, error=str(exc))

        found = self.survey
        if found.spec is None:
            # **行き止まりにしない。** 1 本も無いプロジェクトを選んだときは、
            # 「選べ」ではなく「作れ」を出す (選べるものが無いのだから)
            if self.state.specs():
                self.title_label.config(text="撮る動画を選んでください")
                self.outdir_label.config(
                    text="上の「動画の構成」を選ぶと、"
                         "その動画の状態と、次に押す段が出ます"
                )
            else:
                self.title_label.config(text="このプロジェクトには動画が 1 本もありません")
                self.outdir_label.config(
                    text="「構成を作る」でフォルダと構成 (シーンと狙いを手で書く"
                         "video.md) の雛形を作ります。   撮る対象や声の既定を「設定」面で"
                         "先に入れておくと、2 本目からは書かずに済みます"
                )
        else:
            length = ""
            if found.estimate:
                how = "実測ぶんを含む" if found.measured else "音声を作る前の見積り"
                length = f"   見積り {found.estimate:.0f} 秒 ({how})"
            self.title_label.config(text=(found.title or found.spec.parent.name) + length)
            self.outdir_label.config(
                text=f"{found.spec}   →   {found.outdir or '(台本を作ると決まります)'}"
            )

        for child in self.table.winfo_children():
            child.destroy()
        self.cells.clear()
        for row, item in enumerate(found.items):
            cells = (
                tk.Label(self.table, text=MARK[item.state], width=2,
                         fg=STATE_COLOR[item.state]),
                tk.Label(self.table, text=item.label, width=6, anchor="w"),
                tk.Label(self.table, text=item.what, width=14, anchor="w", fg="#666"),
                tk.Label(self.table, text=item.detail, anchor="w",
                         fg=STATE_COLOR[item.state]),
                # **押せることを行に書く。** ボタン行に戻すと行の複製になるので
                # (前にそれで 3 つ並べて消した)、行の中にリンクとして出す
                tk.Label(self.table, text=action_label(item), anchor="w",
                         fg="#0b57d0", font=("", 9, "underline")),
            )
            for column, cell in enumerate(cells):
                cell.grid(row=row, column=column, sticky="w", padx=(0, 6))
                cell.configure(cursor="hand2")
                cell.bind("<Double-Button-1>", lambda _e, i=item: self.open_item(i))
            # 動詞のところだけは 1 回押せば開く (リンクに見えるものを 2 回
            # 押させない)
            cells[-1].bind("<Button-1>", lambda _e, i=item: self.open_item(i))
            self.cells[item.key] = cells

        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        busy = self.runner.busy
        reasons: list[str] = []
        for step in STEPS:
            why = blocker(step, self.survey)
            self.buttons[step.key].config(state=tk.DISABLED if (why or busy) else tk.NORMAL)
            # **押せない理由は必ず出す。** 前は 1 本も選ばれていないときに
            # 空にしていたので、全部灰色なのに理由がどこにも出なかった。
            # 段ごとに書くと同じ理由が 5 回並ぶのでまとめる
            if why:
                label = "" if self.survey.spec is None else f"{step.title}: "
                if not any(r.endswith(why) for r in reasons):
                    reasons.append(label + why)
        self.init_button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if busy else tk.DISABLED)
        if self.survey.warning:
            # 止めはしない (Vite の既定は本当に 5173 なので、当たることもある)。
            # ただし**先に言う** —— AI を 1 回焼いてから気づくのは高い
            reasons.insert(0, self.survey.warning)
        self.step_note.config(
            text=f"実行中: {self.running}   (中止で止まります)" if busy
            else "   ".join(reasons[:2]),
            fg="#b06000" if (self.survey.warning and not busy) else "#666",
        )
        if self.survey.warning and not busy:
            self.write_button.pack(side=tk.RIGHT, padx=(6, 0))
        else:
            self.write_button.pack_forget()

        # **失敗はボタンのすぐ下に残す。** 下の帯 (status) は次の操作で
        # 上書きされるし、ログは長い実行のあとだと上へ流れている
        if self.failure and not busy:
            self.failure_label.config(text=self.failure)
            self.failure_bar.pack(after=self.steps_box, fill=tk.X, padx=10, pady=(2, 0))
        else:
            self.failure_bar.pack_forget()

    # --- 操作 --------------------------------------------------------
    def on_step(self, step: Step) -> None:
        why = blocker(step, self.survey)
        if why:
            self.state.status.set(why)
            return
        # 台本の作り直しは、**書き戻された音声の割り当てごと**消える。
        # ここだけは押し間違いが痛いので訊く
        if step.key == "plan" and self.survey.state("plan") != MISSING:
            if not messagebox.askyesno(
                "台本を作り直しますか",
                f"{self.survey.plan}\n\nを作り直します。いまの台本と、そこに"
                "書き戻された音声の割り当ては上書きされます。\n\n"
                "git に入れてあれば戻せます。",
                default=messagebox.NO,
            ):
                return
        self.running, self.running_key = step.title, step.key
        self.begin()
        if self.runner.start(argv(step, self.survey, self.headed.get()), self.state.directory):
            self.state.status.set(f"{step.title}… 実行中")
        self._refresh_buttons()

    def on_init(self) -> None:
        """`gmp init` で動画 1 本ぶんの構成 (video.md) を作り、そのまま選ぶ."""
        if self.runner.busy:
            return
        existing = self.state.specs()
        home = video_home(self.state.directory, existing)
        name = simpledialog.askstring(
            "構成を作る",
            f"動画 1 本ぶんのフォルダ名を入れてください。\n\n{home} の下に作ります。",
            initialvalue="getting-started",
            parent=self.body,
        )
        if name is None:
            return
        target = init_target(self.state.directory, existing, name)
        if target is None:
            self.state.status.set("フォルダ名を入れてください")
            return
        if target.exists():
            self.state.status.set(f"{target} は既にあります")
            return
        self.pending = target
        self.running, self.running_key = "構成を作る", "init"
        self.begin()
        self.runner.start(["init", str(target.parent)], self.state.directory)
        self._refresh_buttons()

    def open_item(self, item: Item) -> None:
        """表の行を開く. 完成した動画なら既定のプレイヤーで再生になる.

        構成だけは**画面の中のエディタ**で開く。シーンと狙い・本文・タイトルは
        構成にしか置けず、設定画面は video.md を書かないので、外のエディタに
        頼ると画面が自己完結しない。

        台本も同じ。**出来た動画を観てから「ここだけ」直す**とき、1 行のために
        Claude に台本全体を書き直させたくない (メモ帳で生 JSON を触らせるのも
        同じくらい嫌なので、間に画面を置く)。直せるのは文と間だけ。
        """
        if item.path is None:
            return
        # 収録の行は timing.json で新しさを見るが、押したら**撮れた映像**を出す
        target = item.opens or item.path
        if item.key == "spec" and item.path.is_file():
            from .ui_spec import SpecEditor

            SpecEditor(self.body, item.path, on_saved=self.refresh)
            return
        if item.key == "shots":
            # **支援収録は人が撮る。** 画面はショットを貯めて、どのビートのものかを
            # 覚えておくだけ (操作は代わりにやらない)
            from .ui_shoot import open_window

            open_window(self.body, self.survey.plan, on_saved=self.refresh)
            return
        if item.key == "plan" and item.path.is_file():
            from .ui_plan import PlanEditor

            try:
                PlanEditor(self.body, item.path, self.survey.outdir,
                           on_saved=self.refresh)
            except ValueError as exc:
                # 読めない台本はエディタで直せない (行にも理由は出ている)
                self.state.status.set(f"台本を開けません: {exc}")
            return
        if target.exists():
            if item.key == "output" and item.state == STALE:
                self.state.status.set(
                    "再生します (収録のほうが新しいので、これは古い動画です)")
            if item.key == "timing":
                self.state.status.set("撮れた素材を再生します (字幕も音声もまだ乗っていません)")
            open_path(target)
            return
        # まだ無い行は、出来る場所を開く (どこに出るのかを見せる)
        folder = target.parent
        if folder.is_dir():
            open_path(folder)
            self.state.status.set(f"{item.what} はまだありません (出る場所を開きました)")
        else:
            self.state.status.set(f"{item.what} はまだありません")

    def on_write_spec(self) -> None:
        """対話の claude を開いて構成を書かせる.

        収録対象もシーン構成も、そのプロジェクトを読まないと決まらない。
        人に調べさせるのがいちばん詰まるので、読める者に読ませる。
        **画面が代わりに決める道は持たない** —— 持っていたが、これの下位互換に
        しかならず、同じ場所にボタンが 2 つ並ぶだけだった。
        """
        if self.runner.busy or self.survey.spec is None:
            return
        self.running, self.running_key = "claude に書かせる", "spec"
        self.begin()
        self.runner.start(["init", str(self.survey.spec.parent), "--open"],
                          self.state.directory)
        self._refresh_buttons()

    def on_doctor(self) -> None:
        if self.runner.busy:
            return
        self.running, self.running_key = "前提を調べる", "doctor"
        self.begin()
        self.runner.start(["doctor"], self.state.directory)
        self._refresh_buttons()

    def on_stop(self) -> None:
        if not self.runner.busy:
            return
        self.append("-- 中止しました (途中の生成物が残ることがあります) --")
        self.runner.stop()

    def begin(self) -> None:
        """1 回ぶんの実行を始める前の後始末."""
        self.failed_step = ""
        self.last_error = ""
        self.more_error = False
        self.failure = ""
        self.append("")

    def on_line(self, text: str) -> None:
        """`gmp: ` で始まる行 (= 失敗の理由) を覚えておく.

        長い実行のあとだとログの上へ流れて見えなくなる。**exit 1 とだけ言われても
        何をすればいいか分からない**ので、終わったあとにもう一度出せるようにする。
        """
        if text.startswith("gmp: ") and not self.last_error:
            self.last_error = text[len("gmp: "):].strip()
            self.more_error = True
        elif getattr(self, "more_error", False):
            # `gmp:` のメッセージは複数行で、**直し方は 2 行目以降にある**
            # (「--run を外して PLAN_REQUEST.md を手で渡してください」など)
            if text.startswith("  ") and len(self.last_error) < 300:
                self.last_error += "  " + text.strip()
            else:
                self.more_error = False
        self.append(text)

    def on_done(self, code: int) -> None:
        self.append(f"-- 終了 (exit {code}) --")
        message = (f"{self.running}: 完了" if code == 0
                   else f"{self.running}: 失敗 (exit {code})")
        if code != 0:
            message = f"{self.running}: 失敗 —— {self.last_error or '理由はログに出ています'}"
            self.failure = message
            self.failed_step = self.running_key
        # 作った 1 本は**その場で選ぶ**。選び直させると、作った直後にもう一度
        # 行き止まったように見える
        made = self.pending if (code == 0 and self.pending
                                and self.pending.is_file()) else None
        if made:
            try:
                self.state.spec_path.set(str(made.relative_to(self.state.directory)))
            except ValueError:
                self.state.spec_path.set(str(made))
            self.state.rescan()
            message = (f"作成: {made}   —— 上の「構成」の行をダブルクリックして"
                       "タイトルとシーンの狙いを書いたら、「台本を作る」を押します")
        if code == 0 and self.running_key in ("plan", "spec"):
            # 対話の claude は別の窓で走る。**こちらは終わりを知らない**ので、
            # 戻ってきたときに調べ直す (フォーカスで自動的に走る)
            message = (f"{self.running}: claude の窓を開きました。"
                       "書き終えてこの画面に戻ると、自動で調べ直します")
        self.pending = None
        self.running = self.running_key = ""
        self.refresh()
        if made:
            self.state.changed()     # 設定面にも新しい 1 本を見せる
        # **status は最後に置く。** 設定面の reload も status を書くので、
        # 先に置くと「次に何をするか」が編集中の層の話で上書きされる
        self.state.status.set(message)

    # --- ログ --------------------------------------------------------
    def append(self, text: str) -> None:
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        excess = int(self.log.index("end-1c").split(".")[0]) - self.LOG_LIMIT
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)
