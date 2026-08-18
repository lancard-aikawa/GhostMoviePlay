"""`python -m ghostmovieplay` を `gmp` と同じにする.

画面 (ui_run) から段を叩くときは PATH の `gmp` ではなくこちらを使う。
PATH の実体は venv の外の別バージョンかもしれず、画面と中身がずれる。
"""

import sys

from .cli import main

sys.exit(main())
