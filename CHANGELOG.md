# 変更履歴

**使う人から見えるものだけ**を新しい順に。コマンド・設定・`plan.json` の書式・
画面・出来上がるファイルが変わったときに書く。内部の作り直しや資料の手入れは
載せない（それは `git log` の担当）。

ここが引き受けるのは **「もう撮ってある 1 本に手当てが要るか」** —— README と
CLAUDE.md は *いま何が真か* しか書かないので、**前のやり方で作ったものが
どうなるか**を言える場所が他に無い。

**目玉だけ出して、残りは畳んである。** ただし **⚠（手当てが要るもの）は畳まない**
—— 閉じた `<details>` の中は Ctrl+F に引っかからないので、畳むと *`app.setup` を
書き換える必要がある* を探しに来た人に何も当たらなくなる。

版はまだ切っていない（`0.1.0` のまま、tag も無い）ので、見出しは日付。

---

## 2026-09-01 — 素材を対象の外へ / 使い捨て置き場が `C:\gmp` に

- **`video.md` / `plan.json` を、撮る対象のプロジェクトの外に置ける。**
  グローバル設定の `projects` に **プロジェクト名で** 対象の場所を登録すると、
  収録がそこで走る。他人のリポジトリを汚さずに撮れる。
  **`app.cwd` を書いてある台本はこれまで通り**（書いてあるほうが強い）
- ⚠ **仕込み (`app.setup`) が使う使い捨ての置き場を `C:\gmp\<名前>` に統一した。**
  **ドライブ直下に掘っていた古い `app.setup` は書き換えが要る。**
  浅いところに置くのは変わらない（撮る相手がパスを画面に出すので、
  `%USERPROFILE%` の下だと公開する動画にユーザー名が映る）

<details>
<summary>そのほか 3 件（Android の日本語入力、収録の扱いの統一、<code>render</code> の案内）</summary>

- **Android で日本語が打てる**（ADBKeyboard 経由）。`input text` は非 ASCII を
  黙って落とすので、**打てていない画が撮れていた**。端末に ADBKeyboard が
  入っていないまま日本語を書いた台本は、撮る前に落ちる
- **Android の自動収録が web と同じ扱いになった。** `gmp record` が撮るのに
  `gmp check` が「撮り直せません」と数えていたズレが消えた
- `gmp render` に `plan.json` を渡すと、**渡すべき `timing.json` の場所を教える**
  （前は `raw.webm がありません` としか出ず、渡すものが違うことに気づけなかった）

</details>

## 2026-08-31 — Android アプリを自動で操作して撮れる

- **`app.package` を書くと Android を撮る。** 画面を読んで押すドライバが入り、
  `actions` を書けば実機で通しで撮れる（人が操作する道もそのまま）。
  手引きは [README_ANDROID.md](README_ANDROID.md)
- ⚠ **撮る価値の前提を「失敗」から「分からなくて離れてしまうこと」に置き直した。**
  依頼文 (`PLAN_REQUEST.md`) と `gmp.toml` の雛形（口調・題材）が変わるので、
  **これ以降に作らせる台本は題材の選び方が変わる**。既に撮った 1 本はそのままで
  よいが、作り直すと違うものが出る

<details>
<summary>そのほか 4 件（<code>goal</code>、<code>app.precondition</code>、縦画面の字幕、読み辞書の限界）</summary>

- **シーンに達成条件 `goal` を足した**（`contains` / `absent`）。撮った画面が
  狙いどおりかを Pass2 が見て、外れていれば警告に残る。**台本が別の画面を
  指したまま 47 秒間まちがった絵を撮っても、以前は何も出なかった**
- **撮る前に人が満たしておくことを `app.precondition` に書ける。** 撮る画面に出る
- 縦画面で字幕が画面からはみ出すのを直した（文字の大きさを短いほうの辺で決める）
- ラテン文字の語は読み辞書では直せないと分かった。製品名は `say` にカタカナで書く

</details>

## 2026-08-26 〜 08-27 — 支援収録（人が操作して撮る）

- **`gmp shoot`。** 自動操作が届かない相手を人が操作して撮り、ビートにショットを
  貯める。`gmp record` がそれを並べて 1 本にするので、**`render` は 1 行も
  変わらない** —— 字幕も音声も自動収録と同じように乗る。段は 5 つのまま
- ⚠ **音声の尺が画を伸ばす（支援収録だけ）。** 画が先にあるので、足りなければ
  最後のフレームで埋める。**縮めはしない** —— 8 秒かけた操作を 3 秒の原稿に
  合わせて切ると、操作の途中で切れる

<details>
<summary>そのほか 3 件（<code>app.window</code> / <code>do</code> / <code>shot</code>、手引きとサンプル 2 本、配った zip の受け取り方）</summary>

- **`app.window`**（撮る相手のウィンドウタイトル）、ビートの **`do`**（撮る人への
  やること。動画には出ない）と **`shot`**（撮った 1 枚 / 1 本）
- 手引き [README_WINAPP.md](README_WINAPP.md)、サンプル 2 本
  （[7-Zip](docs/video/assist-7zip/) 69 秒 / [Krita](docs/video/assist-krita/) 96 秒）
- Gallery の zip を受け取った側の手引き [README_BUNDLE.md](README_BUNDLE.md)

</details>

## 2026-08-25 — 腐っていないかを見る道と、観てから直す道

- **`gmp check`** —— 全部の台本を撮り直して、まだアプリに当たっているかを見る。
  `--dry` は撮らずに読むだけ（[docs/check.md](docs/check.md)）
- **台本エディタ** —— 観てから `say` / `subtitle` / `hold` だけを画面で直せる。
  どこからやり直せば反映されるかも画面が言う（字幕だけなら仕上げ直すだけ）

<details>
<summary>そのほか 3 件（止めない失敗、<code>app.setup</code> / <code>app.teardown</code>、<code>gmp demo</code>）</summary>

- **止めない失敗を `timing.json` の `warnings` に残す。** `gmp record --strict` で
  非 0 終了。撮る面にも出る。**`gmp record` が通ったことは中身が合っている証明に
  ならない**、が出発点
- **収録の前後に走らせる `app.setup` / `app.teardown`。** 仕込みは `start` より前、
  後片付けはアプリを畳んでから
- **`gmp demo`** —— 使い捨ての試し場を組み立てて、収録から画面まで通す

</details>

## 2026-08-18 〜 08-19 — 設定が 3 層になり、画面が付いた

- ⚠ **設定は `config.toml`（グローバル）/ `gmp.toml`（プロジェクト）/ `video.md`
  （この動画）の 3 層。解決した値は `gmp plan` の時点で `plan.json` に焼かれる。**
  `record` / `render` / `voice` は設定ファイルを読まない（読むと、同じ台本が機械
  ごとに違う動画を出す）。**設定を変えても、既に出来ている台本には効かない** ——
  効かせるには `gmp plan` からやり直す
- **`gmp ui`** —— 設定面と、`--run` の撮る面（どこまで出来たか・各段のボタン・
  実行ログ・完成した動画の再生）

<details>
<summary>そのほか 2 件（<code>highlight</code> の警告、紹介動画）</summary>

- `highlight` が相手を見つけられないときに警告を出す
- このツール自身の紹介動画 (`docs/video/intro`)

</details>

## 2026-08-17 — 出力先がプロジェクトの外へ / 声まわりが揃った

- ⚠ **生成物をユーザフォルダへ集約した。** `raw.webm` / `voice/*.wav` /
  `output.mp4` はプロジェクトの中に出なくなった。場所は
  `gmp where <plan.json>` で分かる（`home` で変えられる）。
  **`plan.json` は git に入るが、生成物は入らない**という切り分け
- **音声を乗せたらクレジットを自動で焼く**（VOICEVOX の規約）。
  `--no-credit` は「別の場所に自分で表示する」人のための逃げ道で、既定ではない

<details>
<summary>そのほか 2 件（読みの指定、<code>select_text</code>）</summary>

- **読みの指定 `voice.dict` と `gmp kana`。** 辞書に足したことと読みが変わったことは
  別なので、足したら `gmp kana` で見る
- `select_text` アクションと、ハイライトの自動スクロール

</details>

## 2026-08-05 — 最初のもの

- 3 段（`gmp plan` / `gmp record` / `gmp render`）と `gmp voice`。
  AI を使う段は Pass1 の 1 つだけ

<details>
<summary>そのほか 2 件（開発サーバ、決定論）</summary>

- 収録の間だけ開発サーバを起こす（`app.start`）
- 乱数と時刻の固定（`determinism.seed` / `determinism.time`）

</details>
