# 台本が古くなっていないか見る

[README](../README.md) — `gmp check` の話。**動画を作らずに、台本が今のアプリに
まだ当たっているかだけを確かめる。**

`gmp record` は要するに**ナレーション付きの Playwright スクリプト**なので、
落ちたということは UI が変わったということ。動画のために書いた `plan.json` を
CI で回せば、*説明が古くなったら自動で分かる*仕組みになる。**Pass1 (AI) も
Pass3 (render) も要らない。**

```powershell
uv run gmp check                 # カレント以下の plan.json を全部
uv run gmp check docs/video      # 場所を絞る
uv run gmp check --list          # 何を掃くのかだけ見る (撮らない)
uv run gmp check -v              # ビートごとの進行も出す
```

赤が 1 本でもあれば終了コードが 1 になる。

## 何を赤と数えるか

| | 何が起きた |
| --- | --- |
| `×` | `plan.json` が読めない、または**収録が落ちた**（`click` の相手が消えた等） |
| `!` | 撮れたが、`timing.json` に**台本を直すべき警告**が残った |
| `✓` | 通った |

判定は `gmp record` の警告をそのまま使う。**`gmp check` は新しい判定を持たない** ——
やっているのは束ねること（全部の `plan.json` を見つけて 1 本ずつ撮り、赤を数える）
だけなので、`gmp record --strict` を 1 本ずつ叩くのと同じものが出る。

### 赤にしない警告が 2 つある

どちらも**撮った環境の話**で、台本が古いこととは関係が無いのに CI ではほぼ必ず出る。

- `audio_missing` —— wav は生成物でプロジェクトの外に出る。clone したばかりの
  機械には無い
- `leader_short` —— 録画開始の遅れは機械の速さで決まる

**黙って捨てはしない。** 最後の行に「※ 環境の警告 N 件は赤に数えていません」を出す。
出さないと「赤が無い = 全部当たっている」が嘘になる。

**これ以外は、知らない種類でも赤にする。** 分類し忘れて素通りするより、
気づけるほうがいい（警告を足したときは [CLAUDE.md](../CLAUDE.md) の表に従って
`check.ENV_KINDS` も見直す）。

## 撮るものは本物

`gmp check` は**実際に録画する**。絵を捨てて速くする道は用意していない ——
`timing.json` だけが出来て `raw.webm` が無い状態を出力先に残すと、画面には
「収録 ✓」と出るのに `仕上げる` が落ちる。

その代わり:

- **尺は動画の長さの合計とほぼ同じかかる。** 100 秒の動画 3 本なら 5 分強
- **成果物はいつもの出力先に出る**（[設定](settings.md#ファイルの置き場所)）。
  つまり成功した `check` は撮り直しでもある。CI で回すなら
  `GHOSTMOVIEPLAY_HOME` を捨ててよい場所に向けること
- `ffmpeg` が無くても回る（尺の表示が壁時計になるだけ）

## CI の例

```yaml
# .github/workflows/check.yml
on: [push, pull_request]
jobs:
  plans-still-land:
    runs-on: ubuntu-latest
    env:
      GHOSTMOVIEPLAY_HOME: ${{ runner.temp }}/gmp
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run playwright install --with-deps chromium
      - run: uv run gmp check
```

`app.start` が CI でも動くこと（依存のインストール、ポートの空き）が前提になる。
収録用の使い捨てデータルートを立てる形（`serve.py` を `app.start` から起動する）に
してあると、そのまま通る。

## 何が分かって、何が分からないか

分かるのは **selector が指す先がまだ在るか**。`gmp record` が通ったことは
**中身が合っている証明にはならない**ので（開始 URL がダッシュボードのままの
台本が、エラーも出さずに 47 秒間まちがった画面を映した）、赤が無いことは
「説明と画面が食い違っていない」までは言わない。そこは人が観るか、
ビート単位のスクリーンショット比較（[アイデア](ideas/README.md)）の領分。
