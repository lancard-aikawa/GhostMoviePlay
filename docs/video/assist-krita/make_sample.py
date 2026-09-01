r"""撮影用の使い捨てキャンバスを用意する / 片付ける (`app.setup` / `app.teardown`).

**実ファイルは開かない。** 人の描きかけの絵を開くと、レイヤー名にも履歴にも
タイトルバーにもその人の作業が出る。ここで作るのは**四角が 2 つ並んだだけの
白いキャンバス**で、映って困るものは 1 つも入っていない。

`app.start` がこのファイルを引数で開くのは、**ウェルカム画面を出さないため**でも
ある。Krita は引数なしで起動すると**最近使ったドキュメントをサムネイル付きで
並べる** —— 撮る本人の作業中のファイル名が、動画の 1 枚目に丸ごと載る。

置き場所は **`GHOSTMOVIEPLAY_STAGE`（`C:\gmp`）の下**。収録が渡してくる撮影用の
使い捨て置き場で、**自分で名前を決めない** —— 各自がドライブ直下に 1 本ずつ
作っていたころ、撮り終わったあと何が誰のものか分からなくなった。深いところや
`%USERPROFILE%` の下に置かないのは、Krita はタイトルバーにファイル名しか
出さないとはいえ、「最近使ったファイル」やダイアログで**フルパスが見える**ため
（`%USERPROFILE%` だと**ユーザー名が写り込む**）。

## 画像を作るのに何も足さない

PNG は zlib と struct だけで書ける (`_png`)。静止画 1 枚のために Pillow を
入れる理由が無いのは `capture.py` と同じ (あちらは生の BGRA を ffmpeg に渡す)。

## 撮り直しのための `--painted`

台本の後半 (幕 2・幕 3) は「**左の図形が塗り終わっていて、選択範囲がまだ
残っている**」ところから始まる。そこだけ撮り直すたびに幕 1 の塗りをやり直すのは
重いので、`--painted` は**塗り終わった状態のキャンバス**を置く。

**選択範囲までは作れない** —— あれは Krita の中にしかなく、ファイルには残らない。
`--painted` で起動したあとも、選択のドラッグ (Ctrl+R) は人がやり直す。

**塗りの縁は人がドラッグした矩形で決まる**ので、`--painted` の黒い四角と幕 1 で
実際に撮ったショットは厳密には一致しない。**幕 1 のショットと混ぜて使うとき
だけ**注意する (幕 1 ごと撮り直すなら関係ない)。
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
import zlib
from pathlib import Path

# 収録から渡ってくる置き場所。**手で走らせても同じ所に作る**ように、
# 同じ規則 (ドライブ直下の gmp) を fallback に書いておく
STAGE = Path(os.environ.get("GHOSTMOVIEPLAY_STAGE")
             or os.environ.get("SystemDrive", "C:") + "/gmp")
FOLDER = STAGE / "canvas"
CANVAS = FOLDER / "sketch.png"

WIDTH, HEIGHT = 1280, 720
WHITE = (255, 255, 255)
LINE = (154, 160, 166)          # 図形の輪郭。塗る前の下描きに見える薄さ
INK = (0, 0, 0)                 # Krita の既定のブラシ色 (黒) に合わせる
EDGE = 4                        # 輪郭の太さ

# 左は「塗る図形」、右は「そのあと描こうとして描けない場所」。
# **2 つ離して置く** —— 選択範囲が左に残ったまま右へ筆を運ぶ動画なので、
# 点線と筆先が同時に映って、離れていることがそのまま絵になる
LEFT = (160, 200, 480, 520)
RIGHT = (800, 200, 1120, 520)
# 人は図形をすっぽり囲うようにドラッグするので、塗りは図形より少し大きい
MARGIN = 24


def _png(path: Path, width: int, height: int, rows: list[bytearray]) -> Path:
    """RGB 8bit の PNG を書く (フィルタなし)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\0" + bytes(row) for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))
    return path


def _fill(rows: list[bytearray], box: tuple[int, int, int, int],
          color: tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = box
    for y in range(max(0, y0), min(HEIGHT, y1)):
        row = rows[y]
        for x in range(max(0, x0), min(WIDTH, x1)):
            row[x * 3:x * 3 + 3] = bytes(color)


def build(painted: bool = False) -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    rows = [bytearray(bytes(WHITE) * WIDTH) for _ in range(HEIGHT)]

    if painted:
        x0, y0, x1, y1 = LEFT
        _fill(rows, (x0 - MARGIN, y0 - MARGIN, x1 + MARGIN, y1 + MARGIN), INK)

    for box in (LEFT, RIGHT):
        x0, y0, x1, y1 = box
        if painted and box == LEFT:
            continue                       # 塗り潰したので輪郭は見えない
        _fill(rows, (x0, y0, x1, y0 + EDGE), LINE)
        _fill(rows, (x0, y1 - EDGE, x1, y1), LINE)
        _fill(rows, (x0, y0, x0 + EDGE, y1), LINE)
        _fill(rows, (x1 - EDGE, y0, x1, y1), LINE)

    return _png(CANVAS, WIDTH, HEIGHT, rows)


def clean() -> None:
    """**フォルダごと落とす。** 人が手で撮るので、撮影中に別名で保存されたものが
    あってもこちらからは分からない。
    """
    shutil.rmtree(FOLDER, ignore_errors=True)


if __name__ == "__main__":
    flags = sys.argv[1:]
    if "--clean" in flags:
        clean()
        print(f"片付けました: {FOLDER}")
    else:
        painted = "--painted" in flags
        build(painted)
        state = "左の図形は塗り終わった状態" if painted else "白いキャンバス"
        print(f"用意しました: {CANVAS}  ({state})")
