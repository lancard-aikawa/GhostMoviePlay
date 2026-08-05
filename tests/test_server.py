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
