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
