# GhostMoviePlay

AI がアプリやゲームを実際に操作し、**失敗例とその理由、そして正解ルートまでを字幕付きで解説する動画**を生成するパイプライン。

Web で表示できるものなら何でも対象になる（ゲーム、業務アプリ、社内ツールのデモ）。
AI にプロジェクトフォルダを読ませるため、UI の外側から観察するのではなく
**仕様を理解した上で「狙って失敗し」「なぜ悪手なのかを説明できる」** のが特徴。

**動作を見るなら、Claude Code にプロジェクトフォルダを指定して「動画にして」と
言ってみるのが早い。** 何を撮るかを決めるのはそこなので、下の設定を読む前に
一度投げてみるとよい（頼み方は [Claude に頼む](#claude-に頼む)）。

## 設計 — AI と収録を分ける

素朴に「AI が 1 手ずつ操作しながら録画」すると、API 往復のたびに無音の数十秒が
入って観るに耐えない動画になる。そこで3段に分ける。

```
Pass1  gmp plan     AI あり   ソースを読む → 演目を設計 → plan.json
       gmp voice    AI なし   say を VOICEVOX で音声化 (尺がビートの尺を決める)
Pass2  gmp record   AI なし   plan.json を決定論的にリプレイして録画
Pass3  gmp render   AI なし   字幕焼き込み・音声 mix → mp4
```

この分離によって:

- **口調・言語を変えても再収録が要らない。** 原稿だけ差し替えて render し直す。
- **plan.json は人間が読んで直せる。** AI の作った失敗例が的外れなら手で直せばよい。
- **AI コストは Pass1 の 1 回だけ。** 撮り直しは無料。

## 使い方

前提ソフト（ffmpeg・Chromium・VOICEVOX）の入れ方は[環境の用意](docs/setup.md)。

```bash
uv sync
uv run playwright install chromium
uv run gmp doctor            # ffmpeg / chromium の確認

cd <対象プロジェクト>
uv run gmp config --init-project .                    # 共通の既定 (gmp.toml) を置く
uv run gmp ui                                         # 画面で埋める (対象URL・声・口調・題材)
uv run gmp init docs/video/getting-started            # 1本ぶんのフォルダを掘る
#   docs/video/getting-started/video.md を編集（タイトルとシーン構成）
uv run gmp plan  docs/video/getting-started/video.md --open   # 台本を作らせる
uv run gmp kana  docs/video/getting-started/plan.json         # 読みを確認する
uv run gmp build docs/video/getting-started/plan.json --voice # → output.mp4
```

画面から回してもよい。`gmp ui --run` の「撮る」面に、いまどこまで出来ているか
（台本・音声・収録・完成）と、各段のボタン・実行ログ・完成した動画の再生が並ぶ。

`gmp.toml` に置いた対象URL・声・口調・題材は、以降の全部に効く。画面を使わず
`gmp.toml` を直に書いてもよく、いま何が効いているかは `gmp config` で見られる
（[設定](docs/settings.md)）。成果物はプロジェクトの外に出る。場所は
`gmp where <plan.json>` で分かる。

`--run` を付けなければ依頼文 (`PLAN_REQUEST.md`) を書き出すだけで止まる。
対話しながら台本を詰めたいときは、それを対象プロジェクトの Claude Code に渡す方が早い:

```bash
uv run gmp plan video.md
claude "@PLAN_REQUEST.md の指示に従って plan.json を作って"
```

各段を個別に回すとき:

```bash
uv run gmp voice  plan.json    # → <出力先>/voice/*.wav
uv run gmp record plan.json    # → <出力先>/raw.webm, timing.json
uv run gmp render <出力先>/timing.json    # → output.mp4
```

## サンプル

出来上がりを先に見るなら **[GhostMoviePlay Gallery](https://lancard-aikawa.github.io/GhostMoviePlayGallery/)** —— このツールで出力した動画を、
尺・収録対象・素材へのリンク・**それを再現するコマンド**を添えて並べてある。
手元で撮るなら:

```bash
uv run gmp build examples/demo/plan.json --voice
```

「タイル取りゲーム」（数字を取ると両隣が取れなくなる）で、
*大きい数から取る* という典型的な悪手を実演 → 何を失ったか解説 → 満点ルート、
という 3 幕構成の動画が出る（約 75 秒）。plan.json を手で書いた例でもある。
収録の間だけ簡易サーバを立てるので、clone した場所がどこでもそのまま動く。

**画面ごと手で確かめたいなら**、使い捨ての試し場を作る:

```bash
uv run gmp demo          # 10 秒の 1 本を撮って、そのまま「撮る」面が開く
```

一時フォルダに収録対象・設定・構成・台本を組み立て、[使い方](#使い方)と同じ
コマンド（`record` → `render` → `ui`）を順に叩く。台本づくり（Pass1）だけは
AI を焼かずに済ませるため、用意した plan.json を置く。**捨ててよい場所なので、
台本を書き換えても何も壊れない。**

**このリポジトリ自身の紹介動画**も同じ仕組みで作っている:

```bash
uv run gmp build docs/video/intro/plan.json --voice   # 約 100 秒
```

収録対象は `docs/video/intro/site/index.html`（説明ページ）で、`app.start` の
簡易サーバ越しに開く。設定は `gmp.toml`（このプロジェクトの既定）から来る。

## 呼び名

画面・ドキュメント・コミットで同じ言葉を使う。

| 呼び名 | 実体 | 中身 |
|---|---|---|
| プロジェクト | `gmp.toml` のあるフォルダ | 撮る対象のアプリ |
| 動画 | `video.md` のあるフォルダ | 1 本ぶんの入れ物 |
| **構成** | `video.md` | タイトル、シーンと狙い、上書き設定、補足の散文。**人が書く** |
| 依頼文 | `PLAN_REQUEST.md` | Pass1 に渡す指示 |
| **台本** | `plan.json` | セリフ（`say`）、字幕、ト書き（`actions`）、尺。**AI が書き、人が直せる** |
| 音声 | `voice/*.wav` | `say` を読み上げたもの |
| 素材 | `raw.webm` | 収録した無音の映像 |
| 収録 | `timing.json` | ビートの実測時刻 |
| 字幕 | `subs.ass` | |
| 完成 | `output.mp4` | |

セリフとト書きが入っているのは `plan.json` だけなので、**台本は `plan.json`**。
`video.md` が持っているのはシーンと狙いなので **構成**。

**`1本` は数え方としてしか使わない**（「動画が 1 本もありません」「動画 1 本ぶんの
フォルダ」）。物の名前に使うと、`台本を作る` の隣の `1本を作る` が台本の数のことに
読めるし、選ぶ欄の見出しにすると何を選ぶのか言えていない（画像を選ぶ欄に
「この一枚」と出ているのと同じ）。

設定の層は `グローバル` / `プロジェクト` / `この動画`（`gmp config` の由来欄と同じ語）。

## Claude に頼む

**この 3 つが決まらないと台本は書けない** —— 収録する URL、起動コマンド、
起動し終わったと分かるセレクタ。どれもそのプロジェクトを読まないと決まらないので、
人が調べて書くより **Claude Code に読ませるほうが早い**。シーン構成も同じ。

対象プロジェクトを開いた Claude Code に、そのまま貼る:

### 1本まるごと

```
GhostMoviePlay で、このプロジェクトの実演解説動画を 1 本作って。
gmp init で構成 (video.md) を作り、収録対象は自分でソースを読んで埋めて。
台本は skills/ghostplay/SKILL.md に従って書いて。
出来たら gmp build <plan.json> --voice まで通して、尺と警告を報告して。
```

### 構成 (video.md) だけ

```
docs/video/<名前>/video.md を書いて。
このプロジェクトの url / start / ready をソースから調べて埋めて、
scenes は「失敗例 → 何が悪かったか → 正解ルート」の 3 幕で goal を書いて。
セリフや操作手順 (plan.json) はまだ書かないで。
```

### 台本 (plan.json) だけ

```
@<出力先>/PLAN_REQUEST.md の指示に従って plan.json を作って。
書いたら gmp record <plan.json> が通るところまで確認して。
```

依頼文の場所は `gmp plan <video.md>` が出す（`gmp where <video.md>` でも分かる）。

### 撮り直し・手直し

```
plan.json の尺が目標を超えているので、say を削って 90 秒に収めて。
絵は変えないで、ビートは減らさずに文だけ短くして。
```

```
「<語>」の読みが違う。gmp kana <plan.json> で確認して、
gmp.toml の voice.dict に読みを足して。
```

`gmp` のサブコマンドがそのまま Claude への語彙になる（[コマンド](#コマンド)）。
**録画と書き出しは決定論的**なので、Claude に何度やり直させても絵は変わらない。

### 画面 (`gmp ui`) との使い分け

| | |
|---|---|
| Claude に頼む | **何を撮るか**を決めるところ全部（収録対象、シーン構成、台本、読み、尺の詰め） |
| 画面を使う | **どこまで出来たか**を見る、収録と書き出しを回す（数分かかるので進捗と中止が要る）、出来た動画を再生する、構成を読んで直す、**観てから台本の文と間を直す** |

画面の `台本を作る` と `claude に書かせる` は、上の指示を Claude Code に渡して
対話で開くだけのもの。**画面から入っても、決めているのは Claude**。

## コマンド

| | |
|---|---|
| `gmp doctor` | ffmpeg / playwright の状態確認 |
| `gmp where [plan.json]` | 生成物の置き場所を見る |
| `gmp ui [video.md]` | 画面を開く（設定 / 撮る）。`--run` で「撮る」面から |
| `gmp config [video.md]` | 効いている設定と由来を見る |
| `gmp config --set KEY=VALUE` | グローバル設定を書く（`--set-home DIR` も可） |
| `gmp config --init-project [DIR]` | `<project>/gmp.toml` の雛形を置く |
| `gmp init <dir>` | 動画 1 本ぶんのフォルダと `video.md` を作る |
| `gmp init <dir> --open` | 構成を対話の claude に書かせる（収録対象とシーン構成） |
| `gmp plan [spec]` | video.md → 依頼文。`--open` で対話の claude、`--run` で `-p` |
| `gmp kana <plan.json>` | 各ビートの読みを確認する（合成しない） |
| `gmp voice <plan.json>` | `say` を音声化 → `voice/*.wav` |
| `gmp voices` | VOICEVOX の話者一覧 |
| `gmp record <plan.json>` | 収録 → `raw.webm` + `timing.json`（止めない失敗は `warnings` に残る） |
| `gmp render [timing.json]` | 字幕・音声を乗せて `output.mp4` |
| `gmp build <plan.json>` | (voice +) record + render |
| `gmp check [DIR]` | 全部の台本を撮り直して、まだアプリに当たっているか見る（`--dry` で読むだけ） |
| `gmp demo [DIR]` | 使い捨ての試し場を作り、収録から画面まで通す（手で確かめる） |

主なオプション: `--headed`（ブラウザを見ながら収録）、`--strict`（止めない失敗が
あれば非0で終わる）、`--sync-offset`（字幕タイミング補正）、
`--speaker` / `--style` / `--speed`、`--no-subtitles`、`--no-audio`、`--no-credit`。
`--font` / `--crf` / `--preset` / `--url` / `--model` / `--permission-mode` を省略すると
グローバル設定（`render.*` / `engine.voicevox.url` / `agent.*`）が使われる。

## ドキュメント

| | |
|---|---|
| [docs/setup.md](docs/setup.md) | 前提ソフトの入れ方、VOICEVOX ENGINE の起動 |
| [docs/settings.md](docs/settings.md) | 設定の 3 層、`gmp ui`、生成物の置き場所 |
| [docs/voice.md](docs/voice.md) | VOICEVOX、読みの指定、クレジット表記 |
| [docs/plan.md](docs/plan.md) | plan.json の書式、action 一覧、尺の見積り |
| [docs/check.md](docs/check.md) | 台本が古くなっていないかを CI で見る (`gmp check`) |
| [docs/governance.md](docs/governance.md) | 運用そのものを題材にする撮り方（統治・習慣・荒れたデータの仕込み） |
| [docs/internals.md](docs/internals.md) | 実装メモ（なぜこの実装なのか） |
| [CLAUDE.md](CLAUDE.md) | 設計の前提、壊しやすい不変条件、実測値 |

## 開発

```bash
uv run pytest                 # 全テスト
uv run pytest -m "not slow"   # 実プロセスを起動するものを除く
```

## 未実装

- VOICEVOX 以外の TTS エンジン（`ghostmovieplay/tts/` に足せば `voice.engine` で選べる）
- BGM・効果音、シーン間のトランジション
- canvas / WebGL アプリ向けの状態取得ヘルパ
- 2 本を並べて出す（良い状態と悪い状態の対比）。`gmp render` は 1 本しか扱わないので、
  いまは 2 回撮って ffmpeg を自分で叩くことになる
- CI で `gmp check` を回す（[置き方と、ここでは回していない理由](docs/check.md#ci-で回す候補このリポジトリでは回していない)）。
  **効くのは撮る対象と台本が同じリポジトリにあるとき** —— このリポジトリの収録対象は
  作って以来変わっておらず、拾うものが無い

道具の形そのものを変える案（媒体の差し替え、Android、検査への転用）は
[docs/ideas/](docs/ideas/README.md) に置いてある。
