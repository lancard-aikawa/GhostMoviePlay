r"""撮影用の使い捨てフォルダを用意する / 片付ける (`app.setup` / `app.teardown`).

**実ファイルは絶対に使わない。** 中身の無いダミーを、それらしい名前で置くだけ。
「パスワードを付けたのにファイル名が丸見え」を見せる動画なので、**画面に映る
名前は機密っぽく見える必要がある**が、映って困るものであってはいけない。

置き場所は **`GHOSTMOVIEPLAY_STAGE`（`C:\gmp`）の下**。収録が渡してくる撮影用の
使い捨て置き場で、**自分で名前を決めない**。深いところに置かないのは、
**7-Zip がタイトルバーとアドレスバーの 2 か所にパスを出す**から —— 動画の
上半分がパスで埋まるし、`%USERPROFILE%` の下だと**ユーザー名が公開動画に
写り込む**（実際に 1 回撮り直した）。

## 撮り直しのための `--archives`

台本の後半は「**出来た書庫を開く**」ところを撮る。ふつうに撮るなら人が幕 1 で
作るのでそれでよいが、**そのビートだけ撮り直したいとき**に前の操作を全部やり直す
のは重い。`--archives` は書庫が出来上がった状態まで進める。

**起動オプションを足す道は採らない。** 「このビートではこのファイルを開いた状態で
起動する」を `app.start` に持たせると、**自動操作を裏口から戻す**ことになる
(支援収録は人が操作するのが前提で、書庫を開くのはダブルクリック 1 回)。
用意するのは状態だけで、開くのは人。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 収録から渡ってくる置き場所。**手で走らせても同じ所に作る**ように、
# 同じ規則 (ドライブ直下の gmp) を fallback に書いておく。
# 7-Zip はタイトルバーとアドレスバーの 2 か所にパスを出すので、深いところや
# %USERPROFILE% の下だと動画の上半分がパスで埋まり、**ユーザー名まで写り込む**
STAGE = Path(os.environ.get("GHOSTMOVIEPLAY_STAGE")
             or os.environ.get("SystemDrive", "C:") + "/gmp")
FOLDER = STAGE / "sample"

# 中身は 1 行だけ。**サイズが揃っていると一覧が読みやすい**
FILES = (
    "給与明細_2026-07.pdf",
    "人事評価シート.xlsx",
    "取引先リスト.csv",
    "契約書_ドラフト.docx",
)
BODY = "これは GhostMoviePlay の撮影用ダミーです。中身はありません。\n"

# 書庫の名前は **7-Zip が勝手に付けるもの**に合わせてある (フォルダ名 + 拡張子)。
# 形式を変えると拡張子も変わるので、幕 1 の zip と幕 3 の 7z はぶつからない
PASSWORD = "1234"
ZIP = f"{FOLDER.name}.zip"
SEVEN = f"{FOLDER.name}.7z"


def seven_zip() -> Path:
    exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe"
    if not exe.is_file():
        raise SystemExit(f"7-Zip が見つかりません: {exe}\n  winget install 7zip.7zip")
    return exe


def build() -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        (FOLDER / name).write_text(BODY, encoding="utf-8")
    return FOLDER


def archives() -> list[str]:
    """幕 1 と幕 3 が作るはずの書庫を、先に作っておく.

    **失敗のほうも AES-256 で作る。** 「弱い暗号を使ったのが悪い」に見えると
    教訓がずれる —— 強い暗号でもファイル名は隠れない、が要点。
    """
    exe = seven_zip()
    sources = [f"*{Path(name).suffix}" for name in FILES]
    made: list[str] = []
    for name, args in ((ZIP, ["-tzip", "-mem=AES256"]),
                       (SEVEN, ["-t7z", "-mhe=on"])):
        (FOLDER / name).unlink(missing_ok=True)
        done = subprocess.run(
            [str(exe), "a", *args, f"-p{PASSWORD}", name, *sources],
            cwd=str(FOLDER), capture_output=True)
        if done.returncode != 0 or not (FOLDER / name).is_file():
            raise SystemExit(f"{name} を作れません (7z exit {done.returncode})")
        made.append(name)
    return made


def clean() -> None:
    """**撮影中に作った書庫ごと消す。** 人が手で撮るので、何が増えたかは
    こちらから分からない。フォルダごと落とすのがいちばん確実。
    """
    shutil.rmtree(FOLDER, ignore_errors=True)


if __name__ == "__main__":
    flags = sys.argv[1:]
    if "--clean" in flags:
        clean()
        print(f"片付けました: {FOLDER}")
    else:
        build()
        note = ""
        if "--archives" in flags:
            note = "  + " + " / ".join(archives()) + f"  (パスワード {PASSWORD})"
        print(f"用意しました: {FOLDER}  ({len(FILES)} ファイル){note}")
