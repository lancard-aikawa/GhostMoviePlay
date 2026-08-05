"""app.start で指定された開発サーバを起動し、収録が終わったら畳む.

すでにそのURLが応答していれば何もしない (自分で起動して回している最中に
gmp record を叩くのが普通なので、二重起動しない方が嬉しい)。

Windows では npm/uv 経由で起動すると子プロセスがぶら下がるため、
taskkill /T でプロセスツリーごと落とす。
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


def _kill_tree(proc: subprocess.Popen) -> None:
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
        _kill_tree(proc)
