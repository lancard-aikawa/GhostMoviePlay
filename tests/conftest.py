import pytest


@pytest.fixture(autouse=True)
def isolate_output_home(tmp_path_factory, monkeypatch):
    """テストが実ユーザの Videos フォルダを汚さないようにする.

    出力先は環境変数 > 設定ファイル > プラットフォーム既定 の順で決まるので、
    最優先の環境変数を一時ディレクトリに固定しておけばどのテストからも漏れない。
    """
    home = tmp_path_factory.mktemp("gmp-home")
    monkeypatch.setenv("GHOSTMOVIEPLAY_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def tk_root():
    """Tk の root はセッションに 1 つだけ作る.

    1 プロセスで Tk() を作り直すと、たまに init.tcl を読めずに落ちる。
    テストごとに作ると「画面が無い」で不安定に飛ぶので、root は使い回して
    テストごとには Toplevel を作る。**ファイルごとに持たせてもいけない**
    (先に作ったほうが勝ち、あとのファイルが丸ごと skip になる)。
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        # 理由を書かないと、本当の不具合を「画面が無い」で握り潰してしまう
        pytest.skip(f"ウィンドウを作れない: {exc}")
    root.withdraw()
    yield root
    root.destroy()
