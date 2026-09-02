# 展示に出した 1 本を差し替える

[README](../README.md) — 撮り直した動画を
[GhostMoviePlay Gallery](https://lancard-aikawa.github.io/GhostMoviePlayGallery/)
に反映する手順。

**撮るのはこちら、展示は向こう。** mp4 は
[`lancard-aikawa/GhostMoviePlayGallery`](https://github.com/lancard-aikawa/GhostMoviePlayGallery)
にしか置かない（このリポジトリの `.gitignore` が `*.mp4` を外しているのはそのため）。
だから**撮り直しはこちらで終わらない** —— 差し替えるまで、展示は古い画のまま
黙って配られる。あちらは撮り直したことに気づけないので、**気づけるのはここだけ**。

**前提**: Gallery を隣に clone してあること（`build.py` が `git archive` で素材を
束ねるので、無いとそこで止まる）。

```
C:\Repos\mywork\
  ├─ GhostMoviePlay\            ← 撮る (ここ)
  └─ GhostMoviePlayGallery\     ← 展示する
```

## 手順

```bash
# 1. こちらで撮り直して、mp4 まで出す
uv run gmp build docs/video/<名前>/plan.json --voice     # 自動収録の 1 本
uv run gmp where docs/video/<名前>/plan.json             # 出来た場所を確かめる

# 2. mp4 を持っていく (名前は videos.py の slug に揃える)
cp "<出力先>/output.mp4" ../GhostMoviePlayGallery/videos/<slug>.mp4

# 3. カードの文面が嘘になっていないか見る (下記) → videos.py を直す

# 4. 作り直す (HTML と設定の zip とサムネが出る)
cd ../GhostMoviePlayGallery && python build.py

# 5. 出来たものごとコミットして push
git add videos/<slug>.mp4 videos/<slug>.jpg index.html v/ bundles/
git commit -m "<名前> を撮り直したものに差し替える"
git push
```

**`index.html` と `v/*.html` を手で直さない。** `build.py` が上書きする。直すのは
`videos.py`（中身）か `style.css`（見た目）。

**push を忘れると、ページだけ古いまま残る。** GitHub 側にビルドは無く、配信されるのは
コミットしたファイルそのもの。

## カードが嘘になるところ

mp4 を置き換えただけでは足りない。**`videos.py` の文面は撮り方を説明している**ので、
撮り方が変わったらそこも変わる。

| 直すもの | いつ嘘になるか |
| --- | --- |
| `repro` | **撮り方が変わったとき。** 「支援収録で人が操作して撮っています」のままだと、機械が撮るようになった 1 本で読む人が `gmp shoot` を開いてしまう |
| `bundle_note` | 束をどこに置けば動くかが変わったとき（`app.cwd` の指す先を変えた、仕込みの置き場所を変えた） |
| `target` | 収録対象が変わったとき（アプリ、URL、仕込みが作るもの） |
| `lede` | **中身が変わったとき。** 画が変わったのに説明が前のままだと、観る人が「別のものを見せられている」と感じる |
| `poster_at` | 尺が変わって、その秒がサムネにふさわしくなくなったとき |
| `bundle.path` | **素材のフォルダを動かしたとき。** `git archive` のパスなので、変えると build がそこで止まる（黙って古い zip を配らないための作り） |

**素材 (`video.md` / `plan.json`) を動かしたら、必ず `bundle.path` も直す。**
CLAUDE.md の「変更時に一緒に直すもの」にも同じ行がある。

## 出来たサムネを目で見る

`build.py` が抜く `videos/<slug>.jpg` は、**動画そのものの 1 枚**。ここを見ると
収録の失敗が拾える —— 実際、7-Zip の差し替えでサムネを見て、**書庫の中身が
4 行あるのに 2 行しか描かれていない画**を撮っていたことが分かった
（一覧は「読めるようになった」あとから描かれる）。

**2 回撮って byte 一致することでは気づけない。** 同じところで同じように欠けるので、
繰り返し撮れていることの確認をすり抜ける。差し替えのたびに 1 枚だけでも目で見る。

## 向こうに任せること

1 本を**新しく**足す手順、`.gitignore` と Git LFS の罠、履歴の作り直し、
GitHub Pages の設定は
[Gallery の README](https://github.com/lancard-aikawa/GhostMoviePlayGallery#readme)
にある。ここに書き写さない（写すと片方だけ古くなる）。

## いま差し替えが要るもの

- **`assist-7zip`** —— 2026-09-02 に自動収録へ切り替えて撮り直した。mp4 の
  差し替えに加えて、**`repro` と `bundle_note` が「人が操作して撮る」のまま**なので
  直す（`uv run gmp record docs/video/assist-7zip/plan.json` で撮れるようになった）
