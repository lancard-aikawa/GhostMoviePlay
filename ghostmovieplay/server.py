"""app.start で指定された開発サーバを起動し、収録が終わったら畳む.

すでにそのURLが応答していれば何もしない (自分で起動して回している最中に
gmp record を叩くのが普通なので、二重起動しない方が嬉しい)。

Windows では npm/uv 経由で起動すると子プロセスがぶら下がるため、
taskkill /T でプロセスツリーごと落とす。

収録の前後に走らせるコマンド (`app.setup` / `app.teardown`) もここが持つ。
**仕込みはサーバの起動より前**でなければならない —— 仕込んだデータを
サーバが読むので、逆順だと空のまま起動する。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from .plan import App

POLL_INTERVAL = 0.4


def is_up(url: str, timeout: float = 2.0) -> bool:
    """URL が応答するか。HTTP エラーでも「立っている」とみなす."""
    if not url.startswith(("http://", "https://")):
        return True  # file:// などは常に到達可能扱い
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # 404 でもサーバは応答している
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def kill_tree(proc: subprocess.Popen) -> None:
    """**子孫ごと**落とす. 親だけ止めると裏で走り続ける.

    収録用のサーバのほか、支援収録の画面が起こした対象アプリもここを通る
    (`ui_shoot`)。npm や uv 経由で起動すると子がぶら下がるので、
    Windows では `taskkill /T` でプロセスツリーごと落とす。
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 15)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class ServerError(RuntimeError):
    pass


class HookError(ServerError):
    """収録前の仕込みが失敗した."""


# 仕込みはデータ生成やマイグレーションを含むので、サーバの起動待ちより長く取る
HOOK_TIMEOUT = 300.0


def run_hook(command: str, cwd: Path, label: str, verbose: bool = True) -> None:
    """収録の前後に走らせる 1 コマンド.

    **落ちたら理由を持って落ちる。** 仕込みは「画面に何が映るか」を決めるので、
    黙って失敗されると*荒れていないデータ*を撮った動画が出来上がる。
    """
    if not cwd.is_dir():
        raise HookError(f"app.cwd が見つかりません: {cwd}")
    if verbose:
        print(f"  {label}: {command}  (cwd={cwd})")
    try:
        # **utf-8 で読む。** 既定 (Windows は cp932) だと、utf-8 を吐く仕込みの
        # 出力を読む裏スレッドが UnicodeDecodeError で落ちて**出力がまるごと
        # 消える** —— 失敗の理由を出したいときに限って何も残らない。
        # 画面から呼ぶときは PYTHONIOENCODING=utf-8 が子まで伝わるので必ず踏む。
        # こちらからも渡して、Python の仕込みの出し方を揃えておく
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd),
            capture_output=True, text=True, timeout=HOOK_TIMEOUT,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as exc:
        raise HookError(
            f"{label}が {HOOK_TIMEOUT:.0f} 秒で終わりません: {command}") from exc
    except OSError as exc:
        raise HookError(f"{label}を実行できません: {command} ({exc})") from exc

    if proc.returncode != 0:
        # 出力が空のときに改行だけ足さない (警告の 1 行として timing.json に
        # 入るので、末尾の空行がそのまま残る)
        tail = "\n".join(((proc.stderr or proc.stdout or "").strip().splitlines())[-10:])
        detail = f"{label}が失敗しました (exit {proc.returncode}): {command}"
        raise HookError(f"{detail}\n{tail}" if tail else detail)


@contextmanager
def prepared(app: App, base: Path, verbose: bool = True,
             problems: list[str] | None = None):
    """app.setup を先に走らせ、抜けるときに app.teardown を走らせる.

    **仕込みが落ちたら収録を止める。** 仕込めていない画面を撮っても意味が無い。
    **後片付けが落ちても止めない** —— 撮り終えたものを片付けの失敗で捨てない。
    ただし黙りもしない: `problems` に積んで、呼び側が timing.json の警告に混ぜる。
    """
    cwd = (base / app.cwd).resolve() if app.cwd else base
    if app.setup:
        run_hook(app.setup, cwd, "仕込み", verbose)
    try:
        yield
    finally:
        if app.teardown:
            try:
                run_hook(app.teardown, cwd, "後片付け", verbose)
            except HookError as exc:
                # HookError の文面が既に「後片付けが失敗しました…」なので足さない
                if problems is None:
                    print(f"    ! {exc}")
                else:
                    problems.append(str(exc))


@contextmanager
def serve(app: App, base: Path, verbose: bool = True):
    """app.start を起動して url が応答するまで待つ。抜けるときに畳む."""
    if not app.start:
        yield None
        return

    if is_up(app.url):
        if verbose:
            print(f"  サーバは起動済み: {app.url}")
        yield None
        return

    cwd = (base / app.cwd).resolve() if app.cwd else base
    if not cwd.is_dir():
        raise ServerError(f"app.cwd が見つかりません: {cwd}")

    if verbose:
        print(f"  起動: {app.start}  (cwd={cwd})")

    popen_kw: dict = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kw["start_new_session"] = True

    proc = subprocess.Popen(
        app.start, shell=True, cwd=str(cwd),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_kw,
    )

    try:
        deadline = time.monotonic() + app.start_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ServerError(
                    f"サーバが終了しました (exit {proc.returncode}): {app.start}\n"
                    f"  コマンドを cwd={cwd} で手動実行して確認してください。"
                )
            if is_up(app.url):
                if verbose:
                    print(f"  応答を確認: {app.url}")
                break
            time.sleep(POLL_INTERVAL)
        else:
            raise ServerError(
                f"{app.start_timeout:.0f} 秒待っても {app.url} が応答しません。\n"
                "  app.start_timeout を伸ばすか、app.url が正しいか確認してください。"
            )
        yield proc
    finally:
        if verbose:
            print("  サーバを終了します")
        kill_tree(proc)
