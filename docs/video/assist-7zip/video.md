---
# この1本ぶんの指示。共通の既定は gmp.toml にある:
#   C:\Repos\mywork\GhostMoviePlay\gmp.toml
# いま効いている値と由来: gmp config docs/video/assist-7zip/video.md
title: パスワード付き zip はファイル名を隠さない

app:
  # **支援収録の 1 本。** 7-Zip は UI Automation に Pane しか出さないので、
  # 自動操作が原理的に届かない (docs/ideas/desktop.md)。人が操作して撮る
  window: gmp-sample
  # 空文字はプロジェクトの値を打ち消す。ブラウザを開かないので URL は要らない
  url: ''
  ready: ''
  cwd: '.'
  setup: python make_sample.py
  teardown: python make_sample.py --clean
  # 引用符で始まると cmd が前後のクォートを剥がして壊れるので call を頭に置く。
  # ドライブ名を書かない (git に入る plan.json に機械依存の値を焼かないため)
  start: call "%ProgramFiles%\7-Zip\7zFM.exe" "%USERPROFILE%\gmp-sample"

determinism:
  # 人が撮るので決定論は成り立たない。焼いても嘘になるだけなので落とす
  seed: ''
  time: ''

voice:
  # この1本にしか出ない読み。プロジェクトの辞書に足される (voice.dict は合成される)
  dict:
    zip: ジップ
    '7z': セブンゼット
    '7-Zip': セブンジップ
    AES: エーイーエス

scenes:
  - id: leak
    goal: 機密っぽい 4 ファイルを AES-256 のパスワード付き zip にしたのに、開くと名前が全部読めることを見せる
  - id: why
    goal: zip はファイル名の一覧を暗号化しない仕様で、暗号の強さとは無関係だと説明する
  - id: fix
    goal: 7z に変えると現れる「ファイル名を暗号化」を使い、開いた瞬間にパスワードを訊かれることを見せる
---

## 補足

- **撮る相手は 2 つの窓にまたがる。** 本体は `7zFM.exe`（タイトルは現在の
  フォルダのパス）、圧縮ダイアログは **`7zG.exe` の別窓**（タイトルは `圧縮`）。
  撮る画面の一覧から選び直して撮る。`app.window` は本体のほうを指している。
- **ダミーは `app.setup` が `~/gmp-sample` に作る。** 実ファイルは使わない。
  撮り終わったら `終了` で片付く（撮影中に作った書庫ごと消える）。
- **失敗のほうも AES-256 で作る。** 「弱い暗号を使ったのが悪い」に見えると
  教訓がずれる。強い暗号でも隠れないことが要点。
- パスワードは `1234` のような短いもので構わない。**ダイアログの
  「パスワードを表示」は入れておく**（画面に何を打ったか残らないと伝わらない）。
- 最後は「隠せるかどうかを決めるのは暗号の強さではなく書庫形式」で締める。
