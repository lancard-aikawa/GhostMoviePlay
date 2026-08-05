"""gmp コマンド."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__


def _err(msg: str) -> int:
    print(f"gmp: {msg}", file=sys.stderr)
    return 1


# --- doctor -----------------------------------------------------------
def cmd_doctor(args) -> int:
    from . import ffmpeg

    ok = True
    has_ffmpeg, has_ffprobe = ffmpeg.available()
    for name, present in (("ffmpeg", has_ffmpeg), ("ffprobe", has_ffprobe)):
        print(f"  {'OK  ' if present else 'NG  '} {name}")
        ok &= present

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            try:
                b = pw.chromium.launch(headless=True)
                b.close()
                print("  OK   playwright chromium")
            except Exception:
                print("  NG   playwright chromium (`playwright install chromium` を実行)")
                ok = False
    except ImportError:
        print("  NG   playwright 未インストール (`uv sync`)")
        ok = False

    print("\n準備完了" if ok else "\n不足があります")
    return 0 if ok else 1


# --- init -------------------------------------------------------------
def cmd_init(args) -> int:
    from .spec import TEMPLATE

    path = Path(args.path)
    if path.exists() and not args.force:
        return _err(f"{path} は既にあります (--force で上書き)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    print(f"作成: {path}\n  編集したら `gmp plan {path}` で Pass1 の依頼文を出します")
    return 0


# --- plan -------------------------------------------------------------
def cmd_plan(args) -> int:
    from .spec import build_request, parse

    spec_path = Path(args.spec)
    if not spec_path.exists():
        return _err(f"{spec_path} がありません (`gmp init {spec_path}` で雛形を作れます)")

    spec = parse(spec_path)
    request = build_request(spec)
    out = Path(args.out) if args.out else spec_path.parent / "PLAN_REQUEST.md"
    out.write_text(request, encoding="utf-8")

    print(f"作成: {out}\n")
    print("次にやること — 対象プロジェクトを開いた Claude Code に、この依頼文を渡す:")
    print(f"  claude \"@{out.name} の指示に従って plan.json を作って\"")
    print("\n(Claude CLI の直接呼び出しは未実装。plan.json が出来たら `gmp build plan.json`)")
    return 0


# --- voice ------------------------------------------------------------
def cmd_voice(args) -> int:
    from .plan import PlanError, load
    from .tts import TTSError, synthesize, write_back

    try:
        plan = load(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))

    # CLI 指定は plan.json の voice より優先する (口調の差し替え用)
    for key in ("speaker", "style", "speed", "url"):
        value = getattr(args, key, None)
        if value is not None:
            setattr(plan.voice, key, value)

    print(f"合成: {plan.title}")
    try:
        synthesize(plan, force=args.force)
    except TTSError as exc:
        return _err(str(exc))

    target = write_back(plan)
    print(f"\n書き戻し: {target}\n次: gmp record {args.plan}")
    return 0


def cmd_voices(args) -> int:
    """利用可能な話者を並べる."""
    from .plan import Voice
    from .tts.voicevox import VoiceVox, VoiceVoxError

    engine = VoiceVox(Voice(url=args.url or Voice.url))
    try:
        speakers = engine.speakers()
    except VoiceVoxError as exc:
        return _err(str(exc))

    for sp in speakers:
        styles = ", ".join(f"{st['name']}({st['id']})" for st in sp.get("styles", []))
        print(f"  {sp.get('name')}\n      {styles}")
    return 0


# --- record -----------------------------------------------------------
def cmd_record(args) -> int:
    from .plan import PlanError, load
    from .record import record

    try:
        plan = load(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))

    outdir = Path(args.out) if args.out else Path(args.plan).parent / "out"
    print(f"収録: {plan.title}  ({len(plan.beats)} beats -> {outdir})")

    result = record(
        plan,
        outdir,
        headless=not args.headed,
        subtitle_mode=args.subtitle_mode,
        sync_offset=args.sync_offset,
    )
    print(f"\n  video   {result.video}  ({result.duration:.2f}s)")
    print(f"  timing  {result.timing}  (sync skew {result.skew:+.3f}s)")
    print(f"\n次: gmp render {result.timing}")
    return 0


# --- render -----------------------------------------------------------
def cmd_render(args) -> int:
    from .ffmpeg import FFmpegError
    from .render import render

    timing = Path(args.timing)
    if timing.is_dir():
        timing = timing / "timing.json"
    if not timing.exists():
        return _err(f"{timing} がありません (先に gmp record)")

    try:
        result = render(
            timing,
            out=args.out,
            font=args.font,
            crf=args.crf,
            preset=args.preset,
            burn_subtitles=not args.no_subtitles,
            with_audio=not args.no_audio,
        )
    except (FFmpegError, FileNotFoundError) as exc:
        return _err(str(exc))

    print(f"  subs    {result.subtitles}")
    print(f"  audio   {result.audio_tracks} track(s)")
    print(f"\n完成: {result.video}")
    return 0


# --- build ------------------------------------------------------------
def cmd_build(args) -> int:
    if args.voice:
        rc = cmd_voice(args)
        if rc != 0:
            return rc
        print()
    rc = cmd_record(args)
    if rc != 0:
        return rc
    outdir = Path(args.out) if args.out else Path(args.plan).parent / "out"
    args.timing = outdir / "timing.json"
    args.out = None
    return cmd_render(args)


# --- パーサ -----------------------------------------------------------
def _add_record_opts(p) -> None:
    p.add_argument("--out", help="出力ディレクトリ (既定: plan.json の隣の out/)")
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して収録する")
    p.add_argument(
        "--subtitle-mode", choices=["burn", "dom", "both"], default="burn",
        help="burn=ffmpegで焼く(既定) / dom=ページに描く / both",
    )
    p.add_argument(
        "--sync-offset", type=float, default=None,
        help="字幕タイミングの手動補正(秒)。既定は自動推定",
    )


def _add_voice_opts(p) -> None:
    p.add_argument("--speaker", help="話者名 または 話者ID (plan.json の voice より優先)")
    p.add_argument("--style", help="話者のスタイル (ノーマル / あまあま など)")
    p.add_argument("--speed", type=float, help="話速")
    p.add_argument("--url", help="VOICEVOX ENGINE の URL")
    p.add_argument("--force", action="store_true", help="変更が無くても合成しなおす")


def _add_render_opts(p) -> None:
    from .subtitles import DEFAULT_FONT

    p.add_argument("--font", default=DEFAULT_FONT, help=f"字幕フォント (既定: {DEFAULT_FONT})")
    p.add_argument("--crf", type=int, default=20, help="x264 CRF (小さいほど高画質)")
    p.add_argument("--preset", default="medium", help="x264 preset")
    p.add_argument("--no-subtitles", action="store_true", help="字幕を焼かない")
    p.add_argument("--no-audio", action="store_true", help="音声を乗せない")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gmp",
        description="GhostMoviePlay — AI が実演して解説する動画を作る",
    )
    parser.add_argument("--version", action="version", version=f"gmp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="ffmpeg / playwright の状態を見る")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("init", help="video.md の雛形を作る")
    p.add_argument("path", nargs="?", default="video.md")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("plan", help="video.md から Pass1 の依頼文を書き出す")
    p.add_argument("spec", nargs="?", default="video.md")
    p.add_argument("--out")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("voice", help="ビートの say を音声化して plan.json に書き戻す")
    p.add_argument("plan")
    _add_voice_opts(p)
    p.set_defaults(func=cmd_voice)

    p = sub.add_parser("voices", help="VOICEVOX の話者一覧を出す")
    p.add_argument("--url")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("record", help="Pass2: plan.json をリプレイして録画する")
    p.add_argument("plan")
    _add_record_opts(p)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("render", help="Pass3: 字幕と音声を乗せて mp4 にする")
    p.add_argument("timing", nargs="?", default="out/timing.json")
    p.add_argument("--out", help="出力ファイル (既定: out/output.mp4)")
    _add_render_opts(p)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("build", help="(voice +) record + render を通しで実行する")
    p.add_argument("plan")
    p.add_argument("--voice", action="store_true", help="収録前に音声を合成する")
    _add_voice_opts(p)
    _add_record_opts(p)
    _add_render_opts(p)
    p.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return _err("中断しました")


if __name__ == "__main__":
    raise SystemExit(main())
