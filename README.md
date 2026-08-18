# GhostMoviePlay

AI がアプリやゲームを実際に操作し、**失敗例とその理由、そして正解ルートまでを字幕付きで解説する動画**を生成するパイプライン。

Web で表示できるものなら何でも対象になる（ゲーム、業務アプリ、社内ツールのデモ）。
AI にプロジェクトフォルダを読ませるため、UI の外側から観察するのではなく
**仕様を理解した上で「狙って失敗し」「なぜ悪手なのかを説明できる」** のが特徴。

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

```bash
uv sync
uv run playwright install chromium
uv run gmp doctor            # ffmpeg / chromium の確認

cd <対象プロジェクト>
uv run gmp init docs/video/getting-started            # 1本ぶんのフォルダを掘る
#   docs/video/getting-started/video.md を編集（対象URL・口調・シーン構成）
uv run gmp plan  docs/video/getting-started/video.md --run    # 台本を作らせる
uv run gmp kana  docs/video/getting-started/plan.json         # 読みを確認する
uv run gmp build docs/video/getting-started/plan.json --voice # → output.mp4
```

成果物の場所は `gmp where <plan.json>` で分かる（プロジェクトの外に出る）。

`--run` を付けなければ依頼文 (`PLAN_REQUEST.md`) を書き出すだけで止まる。
対話しながら台本を詰めたいときは、それを対象プロジェクトの Claude Code に渡す方が早い:

```bash
uv run gmp plan video.md
claude "@PLAN_REQUEST.md の指示に従って plan.json を作って"
```

各段を個別に回すとき:

```bash
uv run gmp where  plan.json    # 生成物がどこに出るか確認
uv run gmp voice  plan.json    # → <出力先>/voice/*.wav
uv run gmp record plan.json    # → <出力先>/raw.webm, timing.json
uv run gmp render <出力先>/timing.json    # → output.mp4
```

### 音声を付ける

[VOICEVOX](https://voicevox.hiroshiba.jp/) が要る。Windows なら:

```powershell
winget install HiroshibaKazuyuki.VOICEVOX.CPU
```

ナレーション用途（短文を数十本、しかも再合成はキャッシュされる）なら CPU 版で十分。
GUI を開いておけば ENGINE も一緒に立つ。GUI なしで回したいときは同梱の
`vv-engine\run.exe` を直接叩けばよい。

起動した状態で:

```bash
uv run gmp voices                          # 話者一覧
uv run gmp voice plan.json --speaker ずんだもん --style あまあま
uv run gmp build plan.json --voice         # voice + record + render
```

ENGINE の接続先は**機械の設定**（`gmp config --set engine.voicevox.url=...`）で、
plan.json には書きません。書くと別のマシンで繋がらない接続先が残るためです
（`--url` は一時的な指定として扱い、`gmp voice` は plan.json に書き戻しません）。

`voice` は plan.json の `voice` 設定を見て `say` を合成し、各ビートに
`audio` を書き戻す。**合成した音声の尺がそのままビートの尺になる**ので、
喋り終わる前に次の場面へ飛ぶことがない（`hold` は下限として働く）。

原稿も声の設定も変わっていないビートは再合成しない（`voice/manifest.json`
でハッシュ照合）。口調だけ変えたいときは `--speaker` を変えて `voice` →
`record` を回し直せばよく、`--force` で全部合成しなおせる。

**読みの指定。** TTS は文脈の薄い単語を誤読する。「語」は単独だと **カタリ** と
読まれる（「用語」「物語」は正しい）。ルビは振れないので、読みを plan.json に書く:

```jsonc
"voice": {
  "dict": {
    "語": "ゴ",
    "冪等": { "pronunciation": "ベキトウ", "accent": 0 }
  }
}
```

合成の前だけエンジンのユーザー辞書へ入れ、終わったら消す（失敗しても消す）。
利用者が自分で登録済みの表記は触らない。複合語は長い一致が優先されるので、
「語」を足しても「物語」「用語」の読みは変わらない。

**録る前に読みを見る。**

```bash
uv run gmp kana plan.json --out kana.txt
```

全ビートの読みが出る。撮り終えてから誤読に気づくと撮り直しになるので、
原稿を書いた直後にこれを通す。`--out` はコンソールの文字化け回避。

**クレジット表記。** VOICEVOX は生成音声を使った作品にキャラクター名を含む
クレジットを求める。`gmp voice` が話者名から `voice.credit` を自動で埋め、
`gmp render` が音声を乗せるときだけ右上に焼き込む（`--no-credit` で抑制）。
**正確な表記は音声ライブラリごとの利用規約で確認すること。** plan.json の
`voice.credit` を手で書けばそちらが優先される。

## 設定

設定は 3 層ある。**下に行くほど強い。**

| 層 | ファイル | 置くもの |
|---|---|---|
| 機械 | `config.toml`（`gmp config --set`） | 出力ルート、VOICEVOX の接続先、フォント、画質、**声と口調の既定** |
| プロジェクト | `<project>/gmp.toml`（**git に入れる**） | 対象URL・起動コマンド、声と口調、読み辞書、題材と本数、seed |
| 1本 | `video.md` のフロントマター | その動画だけの上書き |

```bash
uv run gmp config --init-project .        # <project>/gmp.toml の雛形を置く
uv run gmp config                         # いま効いている値と、その由来を全部出す
uv run gmp config docs/video/intro/video.md   # その1本まで含めた解決結果
uv run gmp config --set voice.speaker=ずんだもん --set render.crf=18
```

`gmp config` は各項目の値と**どの層から来たか**を並べる。3 層あるので、
これが見えないと必ず迷子になる。`*` が付いている行が「誰かが決めた値」。

**`config.toml` に置けるのは「機械が変われば変わる値」と「好みの既定」だけ。**
アプリの URL や起動コマンド、`seed` のようなプロジェクト固有の事実は置けず、
書いても警告して無視される（同じ機械で 2 つ目のプロジェクトを撮った瞬間に嘘になる）。
綴りを間違えたキーも黙って消えずに警告が出る。

**読み辞書 (`voice.dict`) はプロジェクトに置く。** 用語の読みは動画をまたいで
共通なので、1本ずつ持つと「1本目で直した読みが2本目で戻る」を必ず踏む。
これだけは層をまたいで**マージ**される（他の項目は上書き）。

解決した値の行き先は 3 通りある。`gmp config` の見出しがそれ:

| | 行き先 |
|---|---|
| `plan` | plan.json に焼かれる。Pass2/3 が読む |
| `brief` | `PLAN_REQUEST.md` に載るだけ。plan.json には残らない（口調・題材・尺） |
| `runtime` | この機械でだけ効く。plan.json には入らない（接続先・フォント・画質） |

**`plan` の値は Pass1 の時点で plan.json に焼き切る。** `record` / `render` が
設定ファイルを読むと、同じ plan.json が機械ごとに違う動画を出すようになる。
`gmp plan` が書く依頼文には「**そのまま使う値**」として解決済みの JSON が
入っていて、AI はそれを写すだけ。だから **plan.json は設定ファイル無しでも
そのまま撮り直せる**（別のマシンに持って行っても同じ動画になる）。

`app.cwd` のような相対パスは、**それを書いたファイルからの相対**として解釈して
plan.json の位置に直してから渡す。`gmp.toml` の `cwd = '.'` はプロジェクトルート、
`video.md` の `cwd = '.'` は動画のフォルダで、別の場所を指す。

`gmp.toml` を作ったあとの `gmp init` は、**共通の値を video.md に書き写しません**
（書き写すと 1本ぶんが常にプロジェクトを上書きしてしまう）。何を継承しているかは
コメントで見えるので、変えたい行だけコメントを外します。

### 尺の見積り

`gmp plan --run` と `gmp voice` が通しの尺を出します。目標
（`series.target_seconds`）を許容幅（`series.tolerance`）より超えていたら警告します。
依頼文に「90 秒で」と書いても守られないので、機械側で数えて言うようにしてあります。

```
  尺  103.4 秒  (音声の実尺。操作にかかる時間は含みません)
  ! 目標の 90 秒を 13 秒超えています (許容 112 秒)。ビートを削るか説明を分けてください
```

`gmp voice` の後は**音声の実尺**で数えます（音声の尺がそのままビートの尺なので
これが正確）。合成前は字幕の文字数と `hold` からの見積りになります。どちらも
**操作にかかる時間は含みません**ので、足りない側にズレます。

## ファイルの置き場所

**ソースと生成物を完全に分ける。** プロジェクトの git には `video.md` と
`plan.json`（と `gmp.toml`）しか入らないので、**プロジェクト側に .gitignore が要らない**。

```
プロジェクト（git 管理）
<project>/gmp.toml   プロジェクト共通の既定（対象URL・声・口調・題材・読み辞書）
<project>/docs/video/getting-started/
  ├─ video.md      手で書く指示。gmp.toml を上書きする
  └─ plan.json     AI が書いた台本。手で直す資産。AI コストはここだけ

ユーザフォルダ（git 外）
~/Videos (Win) | ~/Movies (Mac) /GhostMoviePlay/<project>/<video>/
  ├─ PLAN_REQUEST.md
  ├─ voice/*.wav
  ├─ raw.webm / timing.json / subs.ass
  └─ output.mp4
```

`plan.json` はセレクタとアプリの挙動に依存していて**腐る**。だから対象プロジェクトの
git に置き、UI の変更と同じ diff に乗るようにする。ツール側に集めると必ず放置される。

置き場所は上から順に決まる:

1. `--out DIR`
2. 環境変数 `GHOSTMOVIEPLAY_HOME`
3. 設定ファイル（`gmp config --set-home DIR`）
4. プラットフォーム既定

```bash
uv run gmp where                        # 解決結果を見る
uv run gmp config --set-home D:/videos  # 出力ルートを変える
```

将来 GUI を付けるときは 3 を書き換えるだけで済むようにしてある。

**Win/Mac で名前が一致する動画フォルダは存在しない** — Windows は `Videos`、
macOS は `Movies`。Linux は XDG。プラットフォームごとに解決している。
Windows は Known Folder が OneDrive などにリダイレクトされていることがあるため
レジストリを引く。`Documents` を使わないのは、リダイレクト先が OneDrive のことが多く、
数百MB になる `raw.webm` がクラウド同期に乗ってしまうため。

## サンプル

```bash
uv run gmp build examples/demo/plan.json --voice
```

「タイル取りゲーム」（数字を取ると両隣が取れなくなる）で、
*大きい数から取る* という典型的な悪手を実演 → 何を失ったか解説 → 満点ルート、
という 3 幕構成の動画が出る。plan.json を手で書いた例でもある。

### 実プロジェクトの例

[GlossPop](https://github.com/lancard-aikawa/GlossPop) の
`docs/video/gloss-scope/` が 1 本目。**登録する語が短すぎると本文がリンクだらけになる**
という、ソースを読まないと狙って作れない失敗を扱っている（日本語には語境界が無いので
自動リンクが部分文字列で照合される、という設計から来る）。

そこでは収録用に `serve.py` を置き、使い捨てのデータルートでアプリを起動している。
**実データを触らず、撮り直すたびに同じ初期状態から始められる**ようにするため。
状態を持つアプリを撮るときはこの形が要る。

## コマンド

| | |
|---|---|
| `gmp doctor` | ffmpeg / playwright の状態確認 |
| `gmp where [plan.json]` | 生成物の置き場所を見る |
| `gmp config [video.md]` | 効いている設定と由来を見る |
| `gmp config --set KEY=VALUE` | この機械の設定を書く（`--set-home DIR` も可） |
| `gmp config --init-project [DIR]` | `<project>/gmp.toml` の雛形を置く |
| `gmp init <dir>` | 1本ぶんのフォルダと `video.md` を作る |
| `gmp plan [spec]` | video.md → 依頼文。`--run` で claude を起動し plan.json まで |
| `gmp kana <plan.json>` | 各ビートの読みを確認する（合成しない） |
| `gmp voice <plan.json>` | `say` を音声化 → `voice/*.wav` |
| `gmp voices` | VOICEVOX の話者一覧 |
| `gmp record <plan.json>` | 収録 → `raw.webm` + `timing.json` |
| `gmp render [timing.json]` | 字幕・音声を乗せて `output.mp4` |
| `gmp build <plan.json>` | (voice +) record + render |

主なオプション: `--headed`（ブラウザを見ながら収録）、`--sync-offset`（字幕タイミング補正）、
`--speaker` / `--style` / `--speed`、`--font`、`--crf`、`--no-subtitles`、`--no-audio`、`--no-credit`。
`--font` / `--crf` / `--preset` / `--url` / `--model` / `--permission-mode` を省略すると
機械の設定（`render.*` / `engine.voicevox.url` / `agent.*`）が使われる。

## plan.json

```jsonc
{
  "version": 1,
  "meta":  { "title": "...", "lang": "ja", "project": "MyApp" },
  "app":   { "url": "...", "ready": "#tile-0",
             "start": "npm run dev", "cwd": ".", "start_timeout": 60 },
  "video": { "width": 1280, "height": 720, "fps": 30, "leader": 2.5, "trailer": 1.2 },
  "voice": { "engine": "voicevox", "speaker": "ずんだもん", "style": "ノーマル", "speed": 1.0 },
  "determinism": { "seed": 12345, "time": "2026-01-01T09:00:00" },
  "scenes": [{
    "id": "fail-greedy",
    "beats": [{
      "say": "ナレーション原稿",
      "subtitle": "字幕（省略時は say）",
      "hold": 2.4,                 // 操作後の最低保持秒。読み切れる長さにする
      "audio": "voice/0.wav",      // あればこの尺が優先される
      "actions": [
        { "type": "click", "selector": "#tile-1" },
        { "type": "highlight", "selector": "#result", "duration": 2.4 }
      ]
    }]
  }]
}
```

action: `goto` `click` `dblclick` `hover` `type` `press` `select` `scroll_to`
`select_text` `highlight` `wait_for` `sleep` `eval`

**ビートが動画の最小単位**で、1 ビート = 1 字幕。字幕はビート開始から終了まで出る。
解説だけしたいビートは `actions` を空にして `hold` だけ置く。

## 実装メモ

**疑似カーソル。** クリック位置へ 420ms かけてカーソルを滑らせ、波紋を出してから
実際にクリックする。これが無いと「クリックが虚空から発生する」動画になり、
何が起きたのか視聴者に伝わらない。`add_init_script` で仕込むのでページ遷移後も復活する。

**録画開始の遅れ。** Playwright の録画は `new_page()` から始まる建前だが、実測すると
最初のフレームが載るのは **1.8〜2.1 秒後**。2 つ手当てしている。

- `video.leader` は「ページ生成から最初のビートまでの最小待ち時間」(既定 2.5 秒)。
  ここが遅れより短いと**冒頭のビートが動画に入らない**。推定した遅れが leader を
  超えたら警告を出す。
- 字幕・音声の時刻は、収録後に `実測経過時間 − webm の尺` で遅れを推定して差し引く。
  合わない環境では `--sync-offset` で手動補正できる。

**テキスト選択。** `select_text` は本物のマウスドラッグでなぞる。実装で 3 つ踏んだ。

- 座標を測ってからドラッグするまでにページがスクロールすると別の文字列を掴む
  （読書位置の復元など）。選択結果を毎回照合し、食い違ったら測り直す
- `<a>` は既定で draggable なので、リンクの上で押すとリンクのドラッグが始まる。
  なぞる間だけ切る
- **Chromium はリンクの上で押し始めたドラッグではテキスト選択を開始しない。**
  手前の平文から掴み、離したあとに範囲を狙いどおりへ確定して、選択ツールバーの類に
  `mouseup` を一度知らせる

**ハイライトは自動で送る。** 画面外を光らせても見えないので、`highlight` は
対象を表示範囲に入れてから光らせる（`"scroll": false` で切れる）。

**音声の尺がビートの尺を決める。** 逆順（先に尺を決めてから合成）にすると必ず尻切れになるので、
`gmp voice` → `gmp record` の順は入れ替えられない。

**開発サーバの起動。** `app.start` があれば `gmp record` が起動し、`app.url` が応答するまで
待ってから収録に入る。終わればプロセスツリーごと畳む（Windows は `taskkill /T`。
npm 経由だと子プロセスが残るため）。**すでに応答している場合は起動しない**ので、
自分で `npm run dev` を回したまま `gmp record` を叩いても二重起動しない。

**再現性。** `determinism` で 2 つのブレを潰せる。同じ plan.json から 2 回収録して、
同時刻のフレームが**バイト単位で一致**することを確認済み。

- `seed` — `Math.random` を mulberry32 に差し替える。`crypto.getRandomValues` や
  サーバ側の乱数までは面倒を見ない。
- `time` — `page.clock` で開始時刻を固定し、その後は実時間どおりに進める。
  `install` しただけだと時計が止まって `setTimeout` も凍るので `resume` まで打つ。
  タイムゾーンを書かないとローカル時刻として解釈される
  （JST 環境で `09:00:00` を指定すると `toISOString()` は `00:00:00Z` を返す）。

**CFR 化。** Playwright が吐く webm はフレーム間隔が可変。`fps=N` を通してから
字幕を焼かないとズレる。render は必ずこの順で 1 パスにまとめている。

**字幕は焼き込み。** DOM に描くとアプリの z-index と衝突し、多言語化もできない。
`timing.json` → ASS → ffmpeg の順。DOM 字幕は確認用に `--subtitle-mode dom` で使える。

**Pass1 の起動。** `gmp plan --run` は対象プロジェクトを作業ディレクトリにして
`claude -p` を起動する。video.md と plan.json はプロジェクトの外にあることが多いので
`--add-dir` でその場所を渡す。npm 経由でインストールされた `claude.cmd` シムは
Windows の `CreateProcess` から直接起動できないため、`cmd /c` を噛ませている。

## 開発

設計の前提・壊しやすい不変条件・実測値は [CLAUDE.md](CLAUDE.md) にある。

```bash
uv run pytest                 # 全テスト
uv run pytest -m "not slow"   # 実プロセスを起動するものを除く
```

## 未実装

- VOICEVOX 以外の TTS エンジン（`ghostmovieplay/tts/` に足せば `voice.engine` で選べる）
- BGM・効果音、シーン間のトランジション
- canvas / WebGL アプリ向けの状態取得ヘルパ
- 収録前後のフック（アプリの状態を仕込む・後片付けする）。いまは `app.start` に
  起動スクリプトを噛ませて代用している（GlossPop の `serve.py` がその例）
