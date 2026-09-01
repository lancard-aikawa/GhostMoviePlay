import socket
import sys

import pytest

from ghostmovieplay import server
from ghostmovieplay.plan import App


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_non_http_urls_are_always_up():
    assert server.is_up("file:///C:/x/index.html")


def test_closed_port_is_down():
    assert not server.is_up(f"http://127.0.0.1:{free_port()}/", timeout=1.0)


def test_no_start_command_yields_nothing(tmp_path):
    with server.serve(App(url="file:///x"), tmp_path, verbose=False) as proc:
        assert proc is None


def test_already_running_server_is_not_launched(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_up", lambda url, timeout=2.0: True)
    app = App(url="http://127.0.0.1:1/", start="should-not-run")
    with server.serve(app, tmp_path, verbose=False) as proc:
        assert proc is None  # 起動していない


def test_missing_cwd_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_up", lambda url, timeout=2.0: False)
    app = App(url="http://127.0.0.1:1/", start="echo hi", cwd="nope")
    with pytest.raises(server.ServerError, match="app.cwd"):
        with server.serve(app, tmp_path, verbose=False):
            pass


def test_failing_command_reports_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_up", lambda url, timeout=2.0: False)
    app = App(url=f"http://127.0.0.1:{free_port()}/", start="exit 3", start_timeout=10)
    with pytest.raises(server.ServerError, match="サーバが終了しました"):
        with server.serve(app, tmp_path, verbose=False):
            pass


def test_timeout_when_url_never_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_up", lambda url, timeout=2.0: False)
    monkeypatch.setattr(server, "POLL_INTERVAL", 0.05)
    # 応答しないが終了もしないコマンド
    sleeper = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    app = App(url="http://127.0.0.1:1/", start=sleeper, start_timeout=0.5)
    with pytest.raises(server.ServerError, match="応答しません"):
        with server.serve(app, tmp_path, verbose=False):
            pass


# --- 収録の前後に走らせるもの -----------------------------------------
def touch_cmd(path) -> str:
    """そのファイルを作るだけのコマンド (走ったことが残る)."""
    return f'"{sys.executable}" -c "open(r\'{path}\', \'w\').close()"'


def test_setup_runs_before_the_server_starts(tmp_path, monkeypatch):
    """**仕込んだデータをサーバが読む。** 逆順だと空のまま起動する."""
    order = []
    mark = tmp_path / "seeded"

    monkeypatch.setattr(server, "is_up", lambda url, timeout=2.0: False)
    real_run = server.run_hook
    monkeypatch.setattr(server, "run_hook",
                        lambda *a, **k: (order.append("setup"), real_run(*a, **k))[1])

    app = App(url="file:///x", setup=touch_cmd(mark))
    with server.prepared(app, tmp_path, verbose=False):
        order.append("recording")
        assert mark.exists()      # 撮り始める前に仕込み終わっている

    assert order == ["setup", "recording"]


def test_a_failed_setup_stops_the_recording(tmp_path):
    """荒れていないデータを撮った動画が出来上がるほうが困る."""
    app = App(url="file:///x", setup="exit 3")
    with pytest.raises(server.HookError, match="仕込み"):
        with server.prepared(app, tmp_path, verbose=False):
            raise AssertionError("ここまで来てはいけない")


def test_teardown_runs_after_the_recording(tmp_path):
    mark = tmp_path / "cleaned"
    app = App(url="file:///x", teardown=touch_cmd(mark))

    with server.prepared(app, tmp_path, verbose=False):
        assert not mark.exists()
    assert mark.exists()


def test_teardown_runs_even_when_the_recording_dies(tmp_path):
    """途中で落ちても使い捨てデータは片付ける."""
    mark = tmp_path / "cleaned"
    app = App(url="file:///x", teardown=touch_cmd(mark))

    with pytest.raises(RuntimeError):
        with server.prepared(app, tmp_path, verbose=False):
            raise RuntimeError("chromium が落ちた")
    assert mark.exists()


def test_a_failed_teardown_is_reported_but_does_not_throw(tmp_path):
    """**撮り終えたものを片付けの失敗で捨てない。** ただし黙りもしない."""
    problems: list[str] = []
    app = App(url="file:///x", teardown="exit 3")

    with server.prepared(app, tmp_path, verbose=False, problems=problems):
        pass

    assert len(problems) == 1
    assert "後片付け" in problems[0]


def test_hooks_run_in_the_app_cwd(tmp_path):
    """相対パスは app.cwd から。プロジェクトのスクリプトをそのまま書ける."""
    work = tmp_path / "sub"
    work.mkdir()
    app = App(url="file:///x", cwd="sub",
              setup=f'"{sys.executable}" -c "open(\'here\', \'w\').close()"')

    with server.prepared(app, tmp_path, verbose=False):
        pass
    assert (work / "here").exists()


def test_hooks_are_told_where_to_stage(tmp_path):
    """使い捨ての置き場所はこちらから渡す (仕込みが名前を発明しない)."""
    from ghostmovieplay import paths

    app = App(
        url="file:///x",
        setup=f'"{sys.executable}" -c "'
              f"import os;open('stage','w').write(os.environ['{paths.ENV_STAGE}'])\"",
    )
    with server.prepared(app, tmp_path, verbose=False):
        pass
    assert (tmp_path / "stage").read_text() == str(paths.stage_home())


def test_the_stage_is_one_folder_under_the_drive_root():
    """深いところに置くと、撮る相手が出すパスにユーザー名が混ざる."""
    from ghostmovieplay import paths

    stage = paths.stage_home()
    assert stage.name == paths.STAGE_DIR_NAME
    assert stage.parent == stage.parent.parent      # ドライブ直下
    assert "Users" not in str(stage)


def test_a_missing_cwd_is_rejected_before_anything_runs(tmp_path):
    app = App(url="file:///x", cwd="nope", setup="echo hi")
    with pytest.raises(server.HookError, match="app.cwd"):
        with server.prepared(app, tmp_path, verbose=False):
            pass


@pytest.mark.slow
def test_launches_and_stops_a_real_server(tmp_path):
    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    port = free_port()
    app = App(
        url=f"http://127.0.0.1:{port}/index.html",
        start=f'"{sys.executable}" -m http.server {port}',
        start_timeout=30,
    )
    with server.serve(app, tmp_path, verbose=False) as proc:
        assert proc is not None
        assert server.is_up(app.url)
    assert not server.is_up(app.url, timeout=1.0)  # 抜けたら畳まれている


# --- 仕込みの出力を読む -----------------------------------------------
def test_a_hook_printing_utf8_does_not_lose_its_output(tmp_path):
    """**失敗の理由を出したいときに限って消える**のを防ぐ.

    既定 (Windows は cp932) で読むと、utf-8 を吐く仕込みの出力を読む裏スレッドが
    UnicodeDecodeError で落ちて、出力がまるごと空になる。画面から呼ぶときは
    PYTHONIOENCODING=utf-8 が子まで伝わるので必ず踏む。
    """
    script = tmp_path / "boom.py"
    script.write_text(
        "import sys\n"
        "print('仕込みが失敗しました —— 日本語とダッシュ')\n"
        "sys.exit(3)\n", encoding="utf-8")

    with pytest.raises(server.HookError) as caught:
        server.run_hook(f'python "{script.name}"', tmp_path, "仕込み", verbose=False)
    assert "日本語とダッシュ" in str(caught.value)


def test_a_hook_that_passes_says_nothing(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('用意しました')\n", encoding="utf-8")
    server.run_hook(f'python "{script.name}"', tmp_path, "仕込み", verbose=False)
