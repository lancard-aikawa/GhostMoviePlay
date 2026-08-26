"""撮影用の使い捨てフォルダを用意する / 片付ける (`app.setup` / `app.teardown`).

**実ファイルは絶対に使わない。** 中身の無いダミーを、それらしい名前で置くだけ。
「パスワードを付けたのにファイル名が丸見え」を見せる動画なので、**画面に映る
名前は機密っぽく見える必要がある**が、映って困るものであってはいけない。

置き場所を `~/gmp-sample` にしているのは、**7-Zip がタイトルバーとアドレスバーの
2 か所にパスを出す**から。深いところに置くと、動画の上半分がパスで埋まる。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

FOLDER = Path.home() / "gmp-sample"

# 中身は 1 行だけ。**サイズが揃っていると一覧が読みやすい**
FILES = (
    "給与明細_2026-07.pdf",
    "人事評価シート.xlsx",
    "取引先リスト.csv",
    "契約書_ドラフト.docx",
)
BODY = "これは GhostMoviePlay の撮影用ダミーです。中身はありません。\n"


def build() -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        (FOLDER / name).write_text(BODY, encoding="utf-8")
    return FOLDER


def clean() -> None:
    """**撮影中に作った書庫ごと消す。** 人が手で撮るので、何が増えたかは
    こちらから分からない。フォルダごと落とすのがいちばん確実。
    """
    shutil.rmtree(FOLDER, ignore_errors=True)


if __name__ == "__main__":
    if "--clean" in sys.argv[1:]:
        clean()
        print(f"片付けました: {FOLDER}")
    else:
        print(f"用意しました: {build()}  ({len(FILES)} ファイル)")
