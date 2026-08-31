"""gmp コマンド."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import paths
from . import __version__
from .agent import DEFAULT_PERMISSION_MODE
from .settings import PROJECT_FILE


def _load_plan(path):
    """plan.json を読み、対応する出力ディレクトリも返す."""
    from .plan import load

    plan = load(path)
    return plan, paths.resolve_outdir(
        Path(path), project=plan.project, app_cwd=plan.app.cwd,
    )


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
    if not (has_ffmpeg and has_ffprobe):
        print("       (`winget install Gyan.FFmpeg`。入れた直後は端末を"
              "開き直さないと PATH に出てきません)")

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

    # Pass1 (gmp plan --run) は claude を起動する。無くても録画と書き出しは
    # できるので落第にはしないが、**「台本を作る」だけが exit 1 になる**理由に
    # 気づけるように出す
    import shutil

    claude = shutil.which("claude")
    if claude:
        print(f"  OK   claude  ({claude})")
    else:
        print("  --   claude が見つかりません"
              " (gmp plan --run と画面の「台本を作る」が使えません。\n"
              "       Claude Code を入れるか、gmp plan で依頼文だけ書き出してください)")

    # Android の支援収録に要る。**無くても他は全部動く**ので落第にしない
    # (claude と同じ扱い —— 使えない道が 1 つあることだけ言う)
    adb = shutil.which("adb")
    if adb:
        print(f"  OK   adb  ({adb})")
    else:
        print("  --   adb が見つかりません"
              " (Android の支援収録が使えません。\n"
              "       platform-tools を入れて PATH に通してください)")

    print("\n準備完了" if ok else "\n不足があります (docs/setup.md)")
    return 0 if ok else 1


# --- where / config ---------------------------------------------------
def cmd_where(args) -> int:
    """生成物がどこに出るかを見せる (暗黙の置き場所を持つツールには必須)."""
    home = paths.output_home()
    print(f"  出力ルート  {home}")
    print(f"              ({paths.home_source()})")
    print(f"  設定ファイル {paths.config_path()}"
          + ("" if paths.config_path().exists() else "  (未作成)"))
    print(f"  動画フォルダ {paths.user_videos_dir()}")

    from .settings import find_project_file

    project_file = find_project_file(args.plan or Path.cwd())
    if project_file:
        print(f"  プロジェクトの既定 {project_file}")

    if not args.plan:
        print("\n  plan.json を渡すとその動画の出力先が出ます: gmp where plan.json")
        return 0

    from .plan import PlanError

    try:
        plan, outdir = _load_plan(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))

    print(f"\n  {plan.title}")
    print(f"    出力先    {outdir}")
    print(f"    音声      {outdir / 'voice'}")
    print(f"    成果物    {outdir / 'output.mp4'}")
    return 0


def _assign(tree: dict, dotted: str, value) -> None:
    """ネストした dict にドット区切りのキーで書き込む."""
    *head, leaf = dotted.split(".")
    node = tree
    for part in head:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[leaf] = value


def _discard(tree: dict, dotted: str) -> None:
    *head, leaf = dotted.split(".")
    node = tree
    for part in head:
        node = node.get(part)
        if not isinstance(node, dict):
            return
    node.pop(leaf, None)


def _pad(text: str, width: int) -> str:
    """全角を 2 桁として数えて桁を揃える (値に日本語が入るので必要)."""
    import unicodedata

    shown = 0
    for ch in text:
        shown += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return text + " " * max(1, width - shown)


def _clip(text: str, width: int) -> str:
    """表示幅で切る."""
    import unicodedata

    out, shown = [], 0
    for ch in text:
        shown += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if shown > width:
            return "".join(out) + ".."
        out.append(ch)
    return "".join(out)


def cmd_config(args) -> int:
    """いま効いている設定と、その由来を見せる / グローバル設定を書き換える.

    3 層あるので「どこ由来か」を出さないと必ず迷子になる。
    """
    from . import settings

    if args.init_project is not None:
        try:
            written = settings.init_project(args.init_project or ".", force=args.force)
        except settings.SettingsError as exc:
            return _err(str(exc))
        print(f"作成: {written}")
        from .detect import probe

        for guess in probe(written.parent):
            print(f"  {guess.path:10} {guess.value}   ({guess.why})")
        print("  ここに書いた値は、下の video.md すべてに効きます")
        print("  収録対象は推測です。違っていたら書き換えてください")
        return 0

    # 書き換え (グローバルだけ。プロジェクトと動画はファイルを直接編集する)
    pairs = list(args.set or [])
    removals = list(args.unset or [])
    if args.set_home:
        pairs.append(f"home={args.set_home}")
    if args.unset_home:
        removals.append("home")

    if pairs or removals:
        config = paths.load_config()
        for item in pairs:
            key, sep, raw = item.partition("=")
            if not sep:
                return _err(f"--set は KEY=VALUE の形で渡します (もらった値: {item!r})")
            key = key.strip()
            setting = settings.SETTINGS.get(key)
            if setting is None:
                return _err(f"未知の設定 {key!r} (使えるキーは gmp config で一覧できます)")
            if settings.MACHINE not in setting.layers:
                allowed = " / ".join(settings.LAYER_LABEL[x] for x in setting.layers)
                return _err(
                    f"{key!r} はグローバル設定に置けません (置ける層: {allowed})\n"
                    f"  プロジェクト共通なら <project>/{settings.PROJECT_FILE} に、"
                    "その動画だけなら video.md に書いてください"
                )
            try:
                _assign(config, key, settings.parse_value(key, raw.strip()))
            except settings.SettingsError as exc:
                return _err(str(exc))
        for key in removals:
            _discard(config, key)
        print(f"保存: {paths.save_config(config)}\n")

    # 表示
    video_meta: dict = {}
    spec_path = Path(args.spec) if args.spec else None
    if spec_path:
        if not spec_path.exists():
            return _err(f"{spec_path} がありません")
        from .spec import parse

        video_meta = parse(spec_path).raw

    try:
        resolved = settings.load(spec=spec_path, video=video_meta)
    except settings.SettingsError as exc:
        return _err(str(exc))

    print("  設定ファイル")
    print(f"    グローバル設定  {paths.config_path()}"
          + ("" if paths.config_path().exists() else "   (未作成)"))
    project_file = resolved.sources.get(settings.PROJECT)
    if project_file:
        print(f"    プロジェクト  {project_file}")
    else:
        print("    プロジェクト  (無し / gmp config --init-project で作れます)")
    if spec_path:
        print(f"    この動画     {spec_path}")

    for bake, note in (
        ("plan", "plan.json に焼かれる (Pass2/3 が読む)"),
        ("brief", "Pass1 への指示。plan.json には残らない"),
        ("runtime", "この機械でだけ効く。plan.json には入れない"),
    ):
        print(f"\n  {bake}  -- {note}")
        section = None
        for setting in resolved.baked(bake):
            head, _, leaf = setting.path.rpartition(".")
            if head != section:
                section = head
                if head:
                    print(f"    [{head}]")
            value = resolved.values.get(setting.path)
            shown = "-" if value in (None, "", {}, []) else _clip(str(value), 38)
            origin = resolved.origin(setting.path)
            # 既定のままか、誰かが決めたのかが一目で分かるようにする
            mark = " " if origin.layer == settings.DEFAULT else "*"
            print(f"    {mark} {_pad(leaf, 18)}{_pad(shown, 41)}{origin.short()}")

    if resolved.warnings:
        print()
        for warning in resolved.warnings:
            print(f"  ! {warning}")
    return 0


def cmd_ui(args) -> int:
    """画面を開く. 設定 (書けるのは機械とプロジェクトだけ) と、撮る面."""
    try:
        from .ui import open_window
    except ImportError as exc:      # tkinter が入っていない Python
        return _err(f"画面を開けません: {exc}\n  gmp config / gmp build で同じことができます")
    return open_window(args.spec, mode="run" if args.run else "settings")


def cmd_shoot(args) -> int:
    """支援収録の画面を開く. 人が操作したウィンドウを撮ってビートに貯める.

    **自動操作が届かない相手のための道** (ログインの要る業務アプリ・canvas・
    OAuth)。撮った素材は `gmp record` が並べて 1 本にする。

    plan.json がまだ無ければ骨から作る。ウィンドウを選ぶまでは保存しない ——
    「設定済みに見える嘘」を焼かないため (`gmp init` の雛形と同じ規則)。
    """
    from . import capture

    if not capture.supported():
        return _err("支援収録は Windows でだけ使えます")

    target = Path(args.plan)
    if target.is_dir():
        target = target / "plan.json"
    elif target.name == "video.md":
        target = target.parent / "plan.json"

    try:
        import tkinter as tk

        from .ui_shoot import ShootWindow
    except ImportError as exc:      # tkinter が入っていない Python
        return _err(f"画面を開けません: {exc}")

    from .shoot import ShootError

    root = tk.Tk()
    root.withdraw()
    try:
        window = ShootWindow(root, target)
    except ShootError as exc:
        root.destroy()
        return _err(str(exc))
    def close() -> None:
        # **閉じるのを断られたら抜けない** (録画中など)。抜けると mainloop が
        # 終わって、ウィンドウが出たままプロセスだけ死ぬ
        window.on_close()
        if not window.window.winfo_exists():
            root.quit()

    window.window.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0


# --- init -------------------------------------------------------------
def cmd_init(args) -> int:
    """動画 1 本ぶんのディレクトリを掘って video.md を置く.

    生成物はユーザフォルダ側に出るので、ここに .gitignore は要らない。
    """
    from . import settings
    from .spec import template

    target = Path(args.path)
    # ディレクトリを渡されたらその中に video.md を作る
    spec = target if target.suffix == ".md" else target / "video.md"

    if spec.exists() and not args.force:
        return _err(f"{spec} は既にあります (--force で上書き)")
    spec.parent.mkdir(parents=True, exist_ok=True)

    # プロジェクトの既定があるなら、雛形はそれを繰り返さない。
    # 共通の値を書き写すと、この動画が常にプロジェクトを上書きしてしまう。
    project_file = settings.find_project_file(spec.parent)
    resolved = settings.load(spec=spec.parent) if project_file else None
    spec.write_text(template(resolved, project_file), encoding="utf-8")

    print(f"作成: {spec}")
    print(f"  生成物の置き場所: {paths.output_home()}")

    if project_file:
        print(f"  プロジェクトの既定: {project_file}  (継承するので書き写さない)")
        print(f"\n  1. {spec} を編集 (タイトルとシーン構成)")
    else:
        # 2本目からは URL も口調も同じなので、プロジェクト側に既定を持つほうが早い
        print("\n  プロジェクト共通の既定 (対象URL・声・口調・題材) を置くなら:")
        print("    gmp config --init-project <プロジェクトルート>")
        print(f"\n  1. {spec} を編集 (対象URL・口調・シーン構成)")

    print(f"  2. gmp plan {spec} --open    台本 plan.json を作らせる")
    print(f"  3. gmp build {spec.parent / 'plan.json'} --voice")

    if getattr(args, "open", False):
        # **収録対象とシーン構成は、そのプロジェクトを読まないと書けない。**
        # 「URL と起動コマンドとセレクタを調べて書いてください」がいちばん詰まる
        from .agent import AgentError, open_session, spec_prompt
        from .detect import probe
        from .settings import load

        root = project_file.parent if project_file else spec.parent
        try:
            hints = probe(root)
        except OSError:
            hints = []
        try:
            resolved = load(spec=spec)
            model = resolved.get("agent.model")
        except Exception:                                   # noqa: BLE001
            resolved, model = None, None
        # **依頼文はファイルにする。** 窓に出す 1 行が短くなり、人が貼り直せる。
        # 中身は claude が読むので、長い指示はそちらへ置く (台本と同じ形)
        outdir = paths.resolve_outdir(spec, project=resolved.get("project") if resolved else None)
        outdir.mkdir(parents=True, exist_ok=True)
        request = outdir / "SPEC_REQUEST.md"
        request.write_text(spec_prompt(spec, hints), encoding="utf-8")
        print(f"作成: {request}")
        try:
            open_session(
                f"@{request} の指示に従って {spec} を書いてください。"
                "分からないことは訊いてください。",
                root, allow={spec.parent, outdir}, model=model, where=outdir,
                title="構成 (video.md) を書きます",
            )
        except AgentError as exc:
            return _err(str(exc))
    return 0


# --- plan -------------------------------------------------------------
def cmd_plan(args) -> int:
    from .spec import build_request, parse

    spec_path = Path(args.spec)
    if not spec_path.exists():
        return _err(f"{spec_path} がありません (`gmp init {spec_path}` で雛形を作れます)")

    from . import settings

    spec = parse(spec_path)
    try:
        # 3 層を解決して依頼文に焼き込む。plan.json が設定ファイル無しで
        # 再現できる状態にしておくのが Pass1 の責任
        resolved = settings.load(spec=spec_path, video=spec.raw)
    except settings.SettingsError as exc:
        return _err(str(exc))
    for warning in resolved.warnings:
        print(f"  ! {warning}")

    plan_path = Path(args.plan_out) if args.plan_out else spec_path.parent / "plan.json"
    request = build_request(spec, resolved, plan_dir=plan_path.parent)

    project_file = resolved.sources.get(settings.PROJECT)
    if project_file:
        print(f"  プロジェクトの既定: {project_file}")
    # **支援収録は url を要らない** (ブラウザを開かず、人が操作した相手を撮る)。
    # ここで window / package を見ないと、撮れる 1 本に毎回この警告が出る
    from .plan import assisted_target

    if not resolved.get("app.url") and not assisted_target(resolved.section("app")):
        print("  ! app.url がどこにも設定されていません"
              f" ({settings.PROJECT_FILE} か video.md に書いてください)")

    # **雛形の見本値のまま呼ぶと、AI は「本物を指してくれ」と訊いて終わる。**
    # --run では答える人がいないので、AI を 1 回焼いてから気づくことになる
    from .spec import unfilled

    stale = unfilled(resolved)
    if len(stale) >= 2:
        print(f"  ! 構成が雛形の既定のままです: {' / '.join(stale)}"
              f"\n    {spec_path} を直してから呼んでください"
              " (収録対象が決まっていないと台本は書けません)")

    # 依頼文は生成物なので出力側に置く。プロジェクトには video.md と
    # plan.json しか残らないので .gitignore が要らない。
    outdir = paths.resolve_outdir(
        spec_path,
        project=resolved.get("project"),
        app_cwd=resolved.rebase_path("app.cwd", spec_path.parent),
    )
    out = Path(args.out) if args.out else outdir / "PLAN_REQUEST.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(request, encoding="utf-8")
    print(f"作成: {out}")

    # claude を動かすのは対象プロジェクト。app.cwd を書いたファイルからの
    # 相対として解いた実体を渡す
    relative = resolved.rebase_path("app.cwd", Path.cwd())
    work = (Path.cwd() / relative).resolve() if relative else spec_path.parent.resolve()

    if getattr(args, "open", False):
        # **訊かれたら人が答えられる。** 収録対象やセレクタは、そのプロジェクトを
        # 見ないと決まらないことが多い
        from .agent import AgentError, open_session

        try:
            open_session(
                f"@{out} の指示に従って {plan_path} に plan.json を作ってください。"
                "分からないことは訊いてください。",
                work, allow={out.parent, plan_path.parent},
                model=args.model or resolved.get("agent.model"), where=out.parent,
                title="台本 (plan.json) を作ります",
            )
        except AgentError as exc:
            return _err(str(exc))
        print(f"\n出来たら: gmp build {plan_path} --voice")
        return 0

    if not args.run:
        print("\n次にやること -- 対象プロジェクトを開いた Claude Code に、この依頼文を渡す:")
        print(f'  claude "@{out} の指示に従って plan.json を作って"')
        print(f"\n訊かれても答えられるように開くなら: gmp plan {spec_path} --open")
        print(f"自動でやらせるなら: gmp plan {spec_path} --run")
        return 0

    from .agent import AgentError, run

    try:
        run(
            out, plan_path, work,
            model=args.model or resolved.get("agent.model"),
            permission_mode=args.permission_mode or resolved.get("agent.permission_mode"),
            timeout=args.timeout,
        )
    except AgentError as exc:
        return _err(str(exc))

    from .plan import PlanError, load

    try:
        plan = load(plan_path)
    except PlanError as exc:
        return _err(f"作られた plan.json が読めません: {exc}")

    print(f"\n作成: {plan_path}")
    print(f"  {len(plan.scenes)} シーン / {len(plan.beats)} ビート  {plan.title}")
    for scene in plan.scenes:
        print(f"    {scene.id}  ({len(scene.beats)} beats)  {scene.title}")
    _report_length(plan, resolved)
    print(f"\n次: gmp build {plan_path}")
    return 0


def _report_length(plan, resolved, outdir=None) -> None:
    """見積り尺を出し、目標を超えていたら言う.

    「90秒で」と依頼文に書いても守られない。機械側で数えて言わないと
    series.target_seconds は飾りになる。
    """
    from .plan import estimate

    seconds, measured = estimate(
        plan, outdir,
        reading_cps=resolved.get("subtitle.reading_cps"),
        pad=resolved.get("subtitle.pad"),
    )
    how = "音声の実尺" if measured else "字幕と hold からの見積り"
    print(f"  尺 {seconds:5.1f} 秒  ({how}。操作にかかる時間は含みません)")

    target = resolved.get("series.target_seconds")
    if not target:
        return
    limit = target * (1 + (resolved.get("series.tolerance") or 0.0))
    if seconds > limit:
        over = seconds - target
        print(f"  ! 目標の {target:.0f} 秒を {over:.0f} 秒超えています"
              f" (許容 {limit:.0f} 秒)。ビートを削るか説明を分けてください")


# --- voice ------------------------------------------------------------
def cmd_voice(args) -> int:
    from .plan import PlanError, load
    from .tts import TTSError, synthesize, write_back

    try:
        plan, outdir = _load_plan(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))
    if args.out:
        outdir = Path(args.out)

    # CLI 指定は plan.json の voice より優先する (口調の差し替え用)
    for key in ("speaker", "style", "speed", "url"):
        value = getattr(args, key, None)
        if value is not None:
            setattr(plan.voice, key, value)

    print(f"合成: {plan.title}  -> {outdir / 'voice'}")
    try:
        synthesize(plan, outdir, force=args.force)
    except TTSError as exc:
        return _err(str(exc))

    target = write_back(plan)
    print(f"\n書き戻し: {target}")

    # ここで初めて本当の尺が分かる (音声の尺がビートの尺そのものなので)。
    # 目標尺 (series.target_seconds) を読むのは**警告を出すためだけ**。
    # ここで読んだ値を合成や収録の挙動に使ってはいけない
    from . import settings

    try:
        resolved = settings.load(spec=Path(args.plan))
        _report_length(plan, resolved, outdir)
    except settings.SettingsError:
        pass   # 尺の報告に失敗しても合成は終わっている

    print(f"次: gmp record {args.plan}")
    return 0


def cmd_kana(args) -> int:
    """各ビートがどう読まれるかを、合成せずに確認する.

    TTS は文脈の薄い単語を誤読する (「語」→カタリ など)。録り終えてから
    気づくと撮り直しになるので、原稿を書いた直後にこれで見る。
    """
    from .plan import PlanError
    from .tts import TTSError, _engine
    from .tts.voicevox import VoiceVoxError

    try:
        plan, _ = _load_plan(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))

    try:
        engine = _engine(plan.voice)
        speaker_id = engine.resolve_speaker()
        pushed = engine.push_dict(plan.voice.dict or {})
        try:
            lines = []
            for scene, beat in plan.beats:
                text = (beat.say or "").strip()
                if not text:
                    continue
                lines.append(f"{scene.id}: {text}\n    {engine.kana(text, speaker_id)}")
        finally:
            engine.pop_dict(pushed)
    except (TTSError, VoiceVoxError) as exc:
        return _err(str(exc))

    body = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"書き出し: {args.out}")
    else:
        print(body)
    return 0


def cmd_voices(args) -> int:
    """利用可能な話者を並べる."""
    from .plan import Voice
    from .tts.voicevox import VoiceVox, VoiceVoxError

    engine = VoiceVox(Voice(url=args.url))   # url 未指定なら設定から解決される
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
    from .plan import PlanError

    try:
        plan, outdir = _load_plan(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))
    if args.out:
        outdir = Path(args.out)

    # **支援収録の 1 本はブラウザを開かない。** 人が撮った素材を並べる
    # (`gmp shoot` で貯めたもの)。出すものは自動収録と同じ raw + timing なので、
    # このあとの `gmp render` は区別しない
    # **Android で actions が書いてあるなら、機械が操作して撮る。**
    # 人が撮ると、途中で状態が変わったまま撮り足して「同じ画面のはずの 2 枚で
    # 表示が食い違う」ことが起きる (実際に起きた)。通しで撮れば無くなる
    if plan.app.package and any(b.actions for _, b in plan.beats):
        from .android import DriveError
        from .ffmpeg import FFmpegError
        from .record_android import record as drive

        print(f"自動収録 (Android): {plan.title}  ({len(plan.beats)} beats -> {outdir})")
        try:
            result = drive(plan, outdir, verbose=args.verbose,
                           serial=getattr(args, "serial", "") or "")
        except (DriveError, FFmpegError, ValueError) as exc:
            return _err(str(exc))
        print(f"\n  video   {result.video}  ({result.duration:.2f}s)")
        print(f"  timing  {result.timing}")
        return 0

    if plan.app.assisted:
        from .assemble import assemble
        from .ffmpeg import FFmpegError

        print(f"組み立て: {plan.title}  ({len(plan.beats)} beats -> {outdir})")
        try:
            result = assemble(plan, outdir)
        except (FFmpegError, ValueError) as exc:
            return _err(str(exc))
    else:
        from .record import record

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

    # **通ったことは中身が合っている証明にはならない。** 光らせ損ねや選択の
    # ずれは収録を止めないので、ここで数えて言わないと、流れていくログを目で
    # 追っていた人にしか届かない
    if result.warnings:
        print(f"\n  ! 警告 {len(result.warnings)} 件 (timing.json の warnings に残ります)")
        for warning in result.warnings:
            where = warning.get("where")
            print(f"      {where + ': ' if where else ''}{warning['message']}")
        if args.strict:
            return _err("--strict: 警告があるので失敗にします")

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

    # 見た目と画質は機械の設定 (この機械に入っているフォントを指すため)。
    # 引数があればそれが勝つ
    from .settings import machine_value

    try:
        result = render(
            timing,
            out=args.out,
            font=args.font or machine_value("render.font"),
            crf=args.crf if args.crf is not None else machine_value("render.crf"),
            preset=args.preset or machine_value("render.preset"),
            burn_subtitles=not args.no_subtitles,
            with_audio=not args.no_audio,
            credit=not args.no_credit,
        )
    except (FFmpegError, FileNotFoundError) as exc:
        return _err(str(exc))

    print(f"  subs    {result.subtitles}")
    print(f"  audio   {result.audio_tracks} track(s)")
    print(f"\n完成: {result.video}")
    return 0


# --- build ------------------------------------------------------------
def cmd_build(args) -> int:
    from .plan import PlanError

    try:
        _, outdir = _load_plan(args.plan)
    except (PlanError, FileNotFoundError) as exc:
        return _err(str(exc))
    if args.out:
        outdir = Path(args.out)

    if args.voice:
        rc = cmd_voice(args)
        if rc != 0:
            return rc
        print()
    rc = cmd_record(args)
    if rc != 0:
        return rc

    args.timing = outdir / "timing.json"
    args.out = None  # render の --out は成果物ファイル名なので流用しない
    return cmd_render(args)


# --- check ------------------------------------------------------------
def cmd_check(args) -> int:
    """全部の台本を撮り直して、まだアプリに当たっているかを見る.

    既定は**本物の収録** (render も AI も要らないが、絵は撮る)。成果物は
    いつもの出力先に出るので、CI で回すなら `GHOSTMOVIEPLAY_HOME` を
    捨ててよい場所に向けること。尺は動画の長さの合計とほぼ同じかかる。

    `--dry` は撮らずに読むだけ。速いが、分かるのは**撮らなくても分かること**
    (機械依存の焼き込み・長すぎる字幕) に限られる。
    """
    from . import check as checker
    from .record import record

    root = Path(args.dir)
    plans = checker.find_plans(root)
    if not plans:
        return _err(f"{root} の下に plan.json がありません")

    if args.list:
        for path in plans:
            print(path)
        return 0

    def record_one(plan, path):
        outdir = paths.resolve_outdir(path, project=plan.project, app_cwd=plan.app.cwd)
        return record(plan, outdir, headless=True, verbose=args.verbose)

    if args.dry:
        # 撮らずに分かるぶんだけ。**撮ればこれも一緒に出る**ので、CI では
        # 速いほうを先に回して、赤ならそこで止めるのが安い
        print(f"確認: {len(plans)} 本の台本を読みます (撮りません)")
    else:
        print(f"確認: {len(plans)} 本の台本を撮り直します (動画の尺ぶんかかります)")

    report = checker.Report()
    for i, path in enumerate(plans, start=1):
        print(f"\n[{i}/{len(plans)}] {path}")
        result = checker.check_one(path, None if args.dry else record_one)
        report.results.append(result)
        length = f"   {result.seconds:.1f} 秒" if result.seconds else ""
        # 環境の警告はここまでに何行も流れている。**赤ではないと言うだけでなく
        # 件数を添える** —— 流れた行と判定が結び付かないと、通ったのか
        # 見逃したのか読めない
        env = f"   (環境の警告 {len(result.ignored)} 件)" if result.ignored else ""
        print(f"  {checker.MARK[result.state]:<2} {result.detail}{env}{length}")

    print("\n" + report.summary())
    # **赤はもう一度まとめて出す。** 収録は 1 本ずつ長いので、上に流れた
    # 警告は CI のログでは遠すぎる
    for result in report.red:
        print(f"\n  {checker.MARK[result.state]} {result.plan}")
        print(f"      {result.detail}")
        for warning in result.stale:
            where = warning.get("where")
            print(f"      {where + ': ' if where else ''}{warning['message']}")
    return 1 if report.red else 0


# --- demo -------------------------------------------------------------
def cmd_demo(args) -> int:
    """使い捨ての試し場を作って、収録から画面まで通す.

    **目で見て確かめるための道。** テストが緑でも画面の手触りは分からないが、
    本物 (docs/video/intro) で試すと紹介動画の素材に差分が出るし、100 秒の
    収録を待つことになる。捨てられる場所に 10 秒の 1 本を作る。

    叩くのは[使い方]と同じコマンド。**手順が腐ればここで落ちる。**
    """
    import tempfile

    from . import demo

    root = Path(args.dir) if args.dir else Path(tempfile.gettempdir()) / "gmp-demo"
    print(f"試し場: {root}")
    try:
        spec = demo.build(root)
    except (OSError, ValueError) as exc:
        return _err(f"試し場を作れません: {exc}")
    plan = spec.parent / "plan.json"

    if args.build_only:
        print(f"\n次: gmp ui {spec} --run")
        return 0

    # **手順書と同じコマンドを、同じ名前で叩く** (中で関数を呼ぶと、手順が
    # 腐っていても気づけない)
    print(f"\n$ gmp record {plan}")
    rc = main(["record", str(plan)])
    if rc != 0:
        return rc

    _, outdir = _load_plan(plan)
    print(f"\n$ gmp render {outdir / 'timing.json'}")
    rc = main(["render", str(outdir / "timing.json")])
    if rc != 0:
        return rc

    if args.no_open:
        print(f"\n次: gmp ui {spec} --run")
        return 0

    print(f"\n$ gmp ui {spec} --run")
    print("   表の「台本」の行をダブルクリックすると、文と間を直す画面が開きます")
    return main(["ui", str(spec), "--run"])


# --- パーサ -----------------------------------------------------------
def _add_record_opts(p) -> None:
    p.add_argument("--out", help="出力ディレクトリ (既定: plan.json の隣の out/)")
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して収録する")
    # **シリアルは plan.json に無い** (機械ごとに違うので焼かない)。
    # 繋がっているのが 1 台なら要らない
    p.add_argument("--serial", default="", help="Android で撮る端末 (2 台以上繋いでいるとき)")
    p.add_argument(
        "--subtitle-mode", choices=["burn", "dom", "both"], default="burn",
        help="burn=ffmpegで焼く(既定) / dom=ページに描く / both",
    )
    p.add_argument(
        "--sync-offset", type=float, default=None,
        help="字幕タイミングの手動補正(秒)。既定は自動推定",
    )
    p.add_argument(
        "--strict", action="store_true",
        help="止めない失敗 (光らせ損ね・選択のずれ・音声の欠落) があれば非0で終わる",
    )


def _add_voice_opts(p) -> None:
    p.add_argument("--speaker", help="話者名 または 話者ID (plan.json の voice より優先)")
    p.add_argument("--style", help="話者のスタイル (ノーマル / あまあま など)")
    p.add_argument("--speed", type=float, help="話速")
    p.add_argument("--url", help="VOICEVOX ENGINE の URL")
    p.add_argument("--force", action="store_true", help="変更が無くても合成しなおす")


def _add_render_opts(p) -> None:
    # 既定は機械の設定 (render.font / render.crf / render.preset)。
    # ここで default を入れると設定より引数が常に勝ってしまうので入れない
    p.add_argument("--font", help="字幕フォント (既定: 設定の render.font)")
    p.add_argument("--crf", type=int, help="x264 CRF (小さいほど高画質)")
    p.add_argument("--preset", help="x264 preset")
    p.add_argument("--no-subtitles", action="store_true", help="字幕を焼かない")
    p.add_argument("--no-audio", action="store_true", help="音声を乗せない")
    p.add_argument(
        "--no-credit", action="store_true",
        help="クレジット表記を焼かない (別途表示する場合のみ)",
    )


def _lenient_output() -> None:
    """コンソールに無い文字で落ちないようにする.

    Windows の既定コンソールは cp932 で、`—` や `…` が encode できない。
    表示が崩れるのは我慢できるが、それで途中で死ぬのは困る。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _lenient_output()
    parser = argparse.ArgumentParser(
        prog="gmp",
        description="GhostMoviePlay -- AI が実演して解説する動画を作る",
    )
    parser.add_argument("--version", action="version", version=f"gmp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="ffmpeg / playwright の状態を見る")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("where", help="生成物の置き場所を見る")
    p.add_argument("plan", nargs="?", help="plan.json (渡すとその動画の出力先を出す)")
    p.set_defaults(func=cmd_where)

    p = sub.add_parser("config", help="効いている設定と由来を見る / グローバル設定を変える")
    p.add_argument("spec", nargs="?", help="video.md (渡すとその動画の解決結果を出す)")
    p.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="グローバル設定を書く (例: --set voice.speaker=ずんだもん)")
    p.add_argument("--unset", action="append", metavar="KEY", help="グローバル設定を消す")
    p.add_argument("--set-home", metavar="DIR", help="出力ルートを設定する (--set home= と同じ)")
    p.add_argument("--unset-home", action="store_true", help="出力ルートの設定を消す")
    p.add_argument("--init-project", nargs="?", const="", metavar="DIR",
                   help=f"プロジェクトの既定 {PROJECT_FILE} の雛形を置く (既定: カレント)")
    p.add_argument("--force", action="store_true", help="--init-project で上書きする")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("ui", help="画面を開く (設定 / 撮る)")
    p.add_argument("spec", nargs="?", help="video.md (渡すとその動画を選んだ状態で開く)")
    p.add_argument("--run", action="store_true", help="「撮る」面から開く")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("shoot", help="支援収録: 人が操作したウィンドウを撮ってビートに貯める")
    p.add_argument("plan", nargs="?", default="plan.json",
                   help="plan.json (無ければ骨から作る)。フォルダや video.md でもよい")
    p.set_defaults(func=cmd_shoot)

    p = sub.add_parser("init", help="動画 1 本ぶんのフォルダと video.md を作る")
    p.add_argument("--open", action="store_true",
                   help="対話の claude を開いて構成を書かせる")
    p.add_argument("path", nargs="?", default="video.md",
                   help="ディレクトリ、または video.md のパス")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("plan", help="video.md から Pass1 の依頼文を書き出す / 実行する")
    p.add_argument("spec", nargs="?", default="video.md")
    p.add_argument("--out", help="依頼文の書き出し先 (既定: PLAN_REQUEST.md)")
    p.add_argument("--run", action="store_true",
                   help="claude を -p で回して plan.json まで作る (訊かれても答えられない)")
    p.add_argument("--open", action="store_true",
                   help="対話の claude を開いて台本を作らせる (訊かれたら答えられる)")
    p.add_argument("--plan-out", help="plan.json の書き出し先")
    p.add_argument("--model", help="claude に渡すモデル (既定: 設定の agent.model)")
    p.add_argument("--permission-mode",
                   help="claude に渡す権限モード (既定: 設定の agent.permission_mode"
                        f" = {DEFAULT_PERMISSION_MODE})")
    p.add_argument("--timeout", type=float, help="claude の制限時間(秒)")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("voice", help="ビートの say を音声化して plan.json に書き戻す")
    p.add_argument("plan")
    # --out は _add_voice_opts に入れない。build は record 側からも --out を
    # 足すので、両方に入れると argparse が衝突する
    p.add_argument("--out", help="出力ディレクトリ (既定: gmp where の場所)")
    _add_voice_opts(p)
    p.set_defaults(func=cmd_voice)

    p = sub.add_parser("kana", help="各ビートの読みを確認する (合成しない)")
    p.add_argument("plan")
    p.add_argument("--out", help="ファイルに書き出す (コンソールの文字化け回避)")
    p.set_defaults(func=cmd_kana)

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

    p = sub.add_parser(
        "demo", help="使い捨ての試し場を作って、収録から画面まで通す (手で確かめる)",
    )
    p.add_argument("dir", nargs="?", default=None,
                   help="試し場を作る場所 (既定: 一時フォルダの gmp-demo)")
    p.add_argument("--build-only", action="store_true",
                   help="組み立てるだけ (撮らない)")
    p.add_argument("--no-open", action="store_true",
                   help="画面を開かない (収録と仕上げまで)")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser(
        "check", help="全部の台本を撮り直して、まだアプリに当たっているか見る",
    )
    p.add_argument("dir", nargs="?", default=".", help="探す場所 (既定: カレント)")
    p.add_argument("--list", action="store_true",
                   help="見つかった plan.json を並べるだけ (撮らない)")
    p.add_argument("--dry", action="store_true",
                   help="撮らずに、読むだけで分かる欠陥を見る (速い)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="ビートごとの進行も出す")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return _err("中断しました")


if __name__ == "__main__":
    raise SystemExit(main())
