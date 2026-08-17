"""Pass2: plan.json を決定論的にリプレイして録画する.

AI は一切呼ばない。同じ plan.json からは何度でも同じ動画が録れる。

時刻の扱い:
  Playwright の録画は new_page() の時点から始まるが、最初のフレームが
  実際に載るまでに数百ms のブレがある。録画終了後に
      skew = (実測の経過時間) - (webm の尺)
  で開始側の遅れを推定し、全ビートの時刻から差し引いて timing.json に書く。
  ズレが残る場合は --sync-offset で手動補正できる。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from . import determinism, ffmpeg
from .overlay import OVERLAY_JS
from .plan import Beat, Plan, Scene
from .server import serve

CURSOR_MOVE_MS = 420  # カーソルが目標まで滑る時間
POST_CLICK_PAUSE = 0.25
DRAG_STEPS = 18  # テキスト選択のドラッグを何段階で見せるか

# 指定テキストの矩形を取る。見えていなければ先にスクロールする。
FIND_TEXT_JS = """
({ selector, text, occurrence }) => {
  const root = document.querySelector(selector);
  if (!root) return null;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node, seen = 0;
  while ((node = walk.nextNode())) {
    let i = -1;
    while ((i = node.textContent.indexOf(text, i + 1)) >= 0) {
      if (seen++ !== occurrence) continue;
      const range = document.createRange();
      range.setStart(node, i);
      range.setEnd(node, i + text.length);
      let box = range.getBoundingClientRect();
      if (box.top < 40 || box.bottom > innerHeight - 40) {
        (node.parentElement || root).scrollIntoView({ block: 'center' });
        box = range.getBoundingClientRect();
      }
      if (!box.width && !box.height) return null;
      return { left: box.left, top: box.top, right: box.right,
               bottom: box.bottom, width: box.width, height: box.height };
    }
  }
  return null;
}
"""

# ドラッグで作った選択を、狙った範囲ぴったりに合わせ直す。
# ボタンを離す前に呼ぶので、mouseup を見ているUIは正しい文字列を受け取る。
SNAP_RANGE_JS = """
({ selector, text, occurrence }) => {
  const root = document.querySelector(selector);
  if (!root) return '';
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node, seen = 0;
  while ((node = walk.nextNode())) {
    let i = -1;
    while ((i = node.textContent.indexOf(text, i + 1)) >= 0) {
      if (seen++ !== occurrence) continue;
      const range = document.createRange();
      range.setStart(node, i);
      range.setEnd(node, i + text.length);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return sel.toString();
    }
  }
  return '';
}
"""

# リンクの上で押し始めたドラッグは Chromium がテキスト選択を開始しないので、
# 少し手前の平文から掴む。
DRAG_LEAD_PX = 12


@dataclass
class Recorded:
    video: Path
    timing: Path
    duration: float
    skew: float


class Recorder:
    def __init__(self, page, plan: Plan, outdir: Path, subtitle_mode: str, verbose: bool):
        self.page = page
        self.plan = plan
        self.outdir = Path(outdir)
        self.subtitle_mode = subtitle_mode
        self.verbose = verbose
        self.t0 = 0.0

    # --- 時刻 ---------------------------------------------------------
    def now(self) -> float:
        return time.monotonic() - self.t0

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.page.wait_for_timeout(seconds * 1000)

    # --- オーバーレイ操作 ---------------------------------------------
    def js(self, expr: str, arg=None) -> None:
        try:
            self.page.evaluate(expr, arg)
        except PWError:
            pass  # 遷移直後などで層が無い瞬間は黙って捨てる

    def center_of(self, selector: str) -> tuple[float, float] | None:
        try:
            box = self.page.locator(selector).first.bounding_box()
        except PWError:
            return None
        if not box:
            return None
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def move_cursor(self, selector: str) -> tuple[float, float] | None:
        pos = self.center_of(selector)
        if not pos:
            return None
        self.js("([x,y,ms]) => window.__gmp && window.__gmp.moveTo(x,y,ms)",
                [pos[0], pos[1], CURSOR_MOVE_MS])
        self.sleep(CURSOR_MOVE_MS / 1000)
        return pos

    def ripple(self, pos: tuple[float, float]) -> None:
        self.js("([x,y]) => window.__gmp && window.__gmp.ripple(x,y)", [pos[0], pos[1]])

    def select_text(self, text: str, selector: str, occurrence: int, pause: float) -> None:
        """本文中の文字列を、実際のマウスドラッグでなぞって選択する.

        座標を測ってからドラッグするまでの間にページがスクロールすると
        (読書位置の復元など) 別の文字列をなぞってしまう。選択結果を毎回
        照合し、食い違ったら測り直す。
        """
        for attempt in range(3):
            got = self._drag_select(text, selector, occurrence)
            if got is None:
                print(f"    ! 選択できません: {text!r} が {selector} に見つかりません")
                return
            if got.strip() == text:
                break
            if attempt == 2:
                print(f"    ! 選択がずれました: {text!r} のつもりが {got.strip()!r}")
            else:
                self.sleep(0.4)  # レイアウトが落ち着くのを待って測り直す
        self.sleep(pause)

    def _drag_select(self, text: str, selector: str, occurrence: int) -> str | None:
        rect = self.page.evaluate(
            FIND_TEXT_JS, {"selector": selector, "text": text, "occurrence": occurrence}
        )
        if not rect:
            return None

        y = rect["top"] + rect["height"] / 2
        start_x = max(rect["left"] - DRAG_LEAD_PX, 2)
        end_x = rect["right"] - 1

        # <a> は既定で draggable なので、リンクの上で mousedown すると
        # テキスト選択ではなくリンクのドラッグが始まってしまう。
        # なぞる間だけ切っておく (見た目には影響しない)。
        self.js(
            """(sel) => {
                const root = document.querySelector(sel);
                if (!root) return;
                root.querySelectorAll('a').forEach(a => {
                  a.dataset.gmpDrag = a.draggable ? '1' : '0';
                  a.draggable = false;
                });
            }""",
            selector,
        )

        # まず行頭までカーソルを運ぶ (いきなり掴むと何が起きたか分からない)
        self.js("([x,y,ms]) => window.__gmp && window.__gmp.moveTo(x,y,ms)",
                [start_x, y, CURSOR_MOVE_MS])
        self.page.mouse.move(start_x, y)
        self.sleep(CURSOR_MOVE_MS / 1000)

        self.page.mouse.down()
        for step in range(1, DRAG_STEPS + 1):
            x = start_x + (end_x - start_x) * step / DRAG_STEPS
            self.page.mouse.move(x, y)
            # オーバーレイのカーソルも一緒に動かす (transition なしで追従)
            self.js("([x,y]) => window.__gmp && window.__gmp.moveTo(x,y,0)", [x, y])
            self.sleep(0.02)

        self.page.mouse.up()

        # ここまでで「なぞる」絵は撮れている。ただし掴み始めが 1 文字ぶん
        # 手前だったり、Chromium が mouseup で選択を畳んでしまうことがある
        # ので、離したあとに範囲を狙いどおりへ確定する。選択そのものは
        # 本物の DOM 状態で、見た目も同じ。
        selected = self.page.evaluate(
            SNAP_RANGE_JS, {"selector": selector, "text": text, "occurrence": occurrence}
        )
        # 選択ツールバーの類は mouseup を見て出るので、確定後に一度知らせる
        self.js(
            "() => document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))"
        )
        self.sleep(0.15)

        self.js(
            """(sel) => {
                const root = document.querySelector(sel);
                if (!root) return;
                root.querySelectorAll('a[data-gmp-drag]').forEach(a => {
                  a.draggable = a.dataset.gmpDrag === '1';
                  delete a.dataset.gmpDrag;
                });
            }""",
            selector,
        )
        # 確定した時点の値を返す。この後アプリ側が選択を畳むことがあるので
        # (登録ボタンは掴んだ内容を既に持っている)、ここで読むのが正しい。
        return selected

    # --- アクション ---------------------------------------------------
    def do(self, action: dict) -> None:
        kind = action["type"]
        page = self.page

        if kind == "goto":
            page.goto(action["url"], wait_until=action.get("wait_until", "load"))
            page.evaluate(OVERLAY_JS)

        elif kind in ("click", "dblclick"):
            sel = action["selector"]
            pos = self.move_cursor(sel)
            if pos:
                self.ripple(pos)
            target = page.locator(sel).first
            if kind == "click":
                target.click(timeout=action.get("timeout", 10000))
            else:
                target.dblclick(timeout=action.get("timeout", 10000))
            self.sleep(action.get("pause", POST_CLICK_PAUSE))

        elif kind == "hover":
            sel = action["selector"]
            self.move_cursor(sel)
            page.locator(sel).first.hover()

        elif kind == "type":
            sel = action["selector"]
            pos = self.move_cursor(sel)
            if pos:
                self.ripple(pos)
            page.locator(sel).first.click()
            # 1文字ずつ打つと「入力している」画が出る
            page.locator(sel).first.type(action["text"], delay=action.get("delay", 55))

        elif kind == "press":
            page.keyboard.press(action["key"])

        elif kind == "select":
            page.locator(action["selector"]).first.select_option(action["value"])

        elif kind == "select_text":
            # 本物のマウスドラッグで選択する。合成イベントだと isTrusted が立たず、
            # mouseup を見て動くUI (選択ツールバーなど) が反応しないことがある。
            self.select_text(
                action["text"],
                action.get("selector", "article"),
                int(action.get("occurrence", 0)),
                float(action.get("pause", 0.45)),
            )

        elif kind == "scroll_to":
            page.locator(action["selector"]).first.scroll_into_view_if_needed()
            self.sleep(action.get("pause", 0.3))

        elif kind == "highlight":
            sel = action["selector"]
            try:
                target = page.locator(sel).first
                # 画面外を光らせても見えないので、先に送る
                if action.get("scroll", True):
                    target.scroll_into_view_if_needed(timeout=5000)
                    self.sleep(action.get("scroll_pause", 0.45))
                box = target.bounding_box()
            except PWError:
                box = None
            if box:
                self.js("(r) => window.__gmp && window.__gmp.highlight(r)", box)
            dur = float(action.get("duration", 0) or 0)
            if dur:
                self.sleep(dur)
                self.js("() => window.__gmp && window.__gmp.clearHighlight()")

        elif kind == "wait_for":
            if action.get("selector"):
                page.locator(action["selector"]).first.wait_for(
                    state=action.get("state", "visible"),
                    timeout=action.get("timeout", 15000),
                )
            else:
                self.sleep(float(action["seconds"]))

        elif kind == "sleep":
            self.sleep(float(action["seconds"]))

        elif kind == "eval":
            page.evaluate(action["expr"])

    # --- ビート -------------------------------------------------------
    def play_beat(self, scene: Scene, beat: Beat, index: int) -> dict:
        start = self.now()
        caption = beat.caption

        if caption and self.subtitle_mode in ("dom", "both"):
            self.js("(t) => window.__gmp && window.__gmp.caption(t)", caption)

        if self.verbose:
            print(f"    [{start:6.2f}s] {scene.id}#{index}: {caption[:48]}")

        for action in beat.actions:
            self.do(action)

        # 音声があればその尺、無ければ hold を最低保持時間として使う
        floor = beat.hold
        audio_path = self._audio_path(beat)
        if audio_path and audio_path.exists():
            dur = ffmpeg.probe_duration(audio_path)
            if dur:
                floor = max(floor, dur + 0.25)
        elif beat.audio:
            print(f"    ! 音声が見つかりません: {beat.audio} (hold を使います)")
            audio_path = None

        elapsed = self.now() - start
        if elapsed < floor:
            self.sleep(floor - elapsed)

        end = self.now()
        if self.subtitle_mode in ("dom", "both"):
            self.js("() => window.__gmp && window.__gmp.caption('')")
        self.js("() => window.__gmp && window.__gmp.clearHighlight()")

        return {
            "scene": scene.id,
            "index": index,
            "say": beat.say,
            "caption": caption,
            # timing.json は out/ に置かれ plan.json とは階層が違うので絶対パスで持つ
            "audio": str(audio_path) if audio_path else None,
            "wall_start": round(start, 3),
            "wall_end": round(end, 3),
        }

    def _audio_path(self, beat: Beat) -> Path | None:
        """beat.audio は出力ディレクトリからの相対パス (gmp voice がそこへ置く)."""
        if not beat.audio:
            return None
        return (self.outdir / beat.audio).resolve()


def record(
    plan: Plan,
    outdir: Path,
    headless: bool = True,
    subtitle_mode: str = "burn",
    sync_offset: float | None = None,
    verbose: bool = True,
) -> Recorded:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir = outdir / "_raw"
    raw_dir.mkdir(exist_ok=True)

    v = plan.video
    entries: list[dict] = []
    base = plan.source.parent if plan.source else Path.cwd()

    with serve(plan.app, base, verbose=verbose), sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--hide-scrollbars", "--force-device-scale-factor=1"],
        )
        context = browser.new_context(
            viewport={"width": v.width, "height": v.height},
            record_video_dir=str(raw_dir),
            record_video_size={"width": v.width, "height": v.height},
            device_scale_factor=1,
            reduced_motion="no-preference",
        )
        context.add_init_script(OVERLAY_JS)

        page = context.new_page()
        video = page.video
        wall_start = time.monotonic()  # ここが録画開始のおおよその基準

        rec = Recorder(page, plan, outdir, subtitle_mode, verbose)
        rec.t0 = wall_start

        # 乱数・時刻の固定は必ず goto より前に仕込む
        determinism.apply(page, plan.determinism, verbose=verbose)

        # 準備: 黒みを出したまま初期表示を整える
        page.goto(plan.app.url, wait_until="load")
        page.evaluate(OVERLAY_JS)
        rec.js("() => window.__gmp && window.__gmp.curtain(true)")
        if plan.app.ready:
            page.locator(plan.app.ready).first.wait_for(state="visible", timeout=20000)
        rec.sleep(0.35)
        rec.js("() => window.__gmp && window.__gmp.curtain(false)")
        # 録画が実際に始まるまでの遅れを吸収する。leader は「ページ生成から
        # 最初のビートまで」の最小時間なので、既に食った分は差し引く。
        remaining = v.leader - rec.now()
        if remaining > 0:
            rec.sleep(remaining)

        for scene in plan.scenes:
            if verbose:
                print(f"  ● scene {scene.id}" + (f" — {scene.title}" if scene.title else ""))
            for i, beat in enumerate(scene.beats):
                entries.append(rec.play_beat(scene, beat, i))

        rec.sleep(v.trailer)
        wall_total = time.monotonic() - wall_start

        context.close()
        browser.close()
        src = Path(video.path())

    dest = outdir / "raw.webm"
    if dest.exists():
        dest.unlink()
    src.replace(dest)
    try:
        raw_dir.rmdir()
    except OSError:
        pass

    # 録画開始側の遅れを推定して全時刻を前詰めする
    video_duration = ffmpeg.probe_duration(dest) or wall_total
    skew = wall_total - video_duration if sync_offset is None else sync_offset
    skew = max(0.0, min(skew, 10.0))

    if sync_offset is None and skew > v.leader and entries:
        print(
            f"\n  ! 録画開始の遅れ ({skew:.2f}s) が leader ({v.leader:.2f}s) を超えました。\n"
            f"    冒頭のビートが動画に入っていない可能性があります。\n"
            f"    plan.json の video.leader を {skew + 0.5:.1f} 以上にして録り直してください。"
        )

    for e in entries:
        e["start"] = round(max(0.0, e["wall_start"] - skew), 3)
        e["end"] = round(max(0.05, e["wall_end"] - skew), 3)

    timing = {
        "title": plan.title,
        "lang": plan.lang,
        # 音声を使ったときだけクレジットを持ち回す (render が焼く)
        "credit": plan.voice.credit if any(e["audio"] for e in entries) else None,
        "video": {"width": v.width, "height": v.height, "fps": v.fps},
        "source_video": dest.name,
        "duration": round(video_duration, 3),
        "wall_duration": round(wall_total, 3),
        "sync_skew": round(skew, 3),
        "beats": entries,
    }
    timing_path = outdir / "timing.json"
    timing_path.write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")

    return Recorded(video=dest, timing=timing_path, duration=video_duration, skew=skew)
