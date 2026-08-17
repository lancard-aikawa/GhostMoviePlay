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

uv run gmp init docs/video/getting-started   # 1本ぶんのフォルダを掘る
#   video.md を編集（対象URL・口調・シーン構成）
uv run gmp plan video.md --run   # claude を起動して plan.json まで作らせる
uv run gmp build plan.json       # 収録 + 書き出し → out/output.mp4
```

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

`voice` は plan.json の `voice` 設定を見て `say` を合成し、各ビートに
`audio` を書き戻す。**合成した音声の尺がそのままビートの尺になる**ので、
喋り終わる前に次の場面へ飛ぶことがない（`hold` は下限として働く）。

原稿も声の設定も変わっていないビートは再合成しない（`voice/manifest.json`
でハッシュ照合）。口調だけ変えたいときは `--speaker` を変えて `voice` →
`record` を回し直せばよく、`--force` で全部合成しなおせる。

**クレジット表記。** VOICEVOX は生成音声を使った作品にキャラクター名を含む
クレジットを求める。`gmp voice` が話者名から `voice.credit` を自動で埋め、
`gmp render` が音声を乗せるときだけ右上に焼き込む（`--no-credit` で抑制）。
**正確な表記は音声ライブラリごとの利用規約で確認すること。** plan.json の
`voice.credit` を手で書けばそちらが優先される。

## ファイルの置き場所

**ソースと生成物を完全に分ける。** プロジェクトの git には `video.md` と
`plan.json` しか入らないので、**プロジェクト側に .gitignore が要らない**。

```
プロジェクト（git 管理）
<project>/docs/video/getting-started/
  ├─ video.md      手で書く指示
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
uv run gmp build examples/demo/plan.json
```

「タイル取りゲーム」（数字を取ると両隣が取れなくなる）で、
*大きい数から取る* という典型的な悪手を実演 → 何を失ったか解説 → 満点ルート、
という 3 幕構成の動画が出る。plan.json を手で書いた例でもある。

## コマンド

| | |
|---|---|
| `gmp doctor` | ffmpeg / playwright の状態確認 |
| `gmp where [plan.json]` | 生成物の置き場所を見る |
| `gmp config --set-home DIR` | 出力ルートを設定する |
| `gmp init <dir>` | 1本ぶんのフォルダと `video.md` を作る |
| `gmp plan [spec]` | video.md → 依頼文。`--run` で claude を起動し plan.json まで |
| `gmp voice <plan.json>` | `say` を音声化 → `voice/*.wav` |
| `gmp voices` | VOICEVOX の話者一覧 |
| `gmp record <plan.json>` | 収録 → `raw.webm` + `timing.json` |
| `gmp render [timing.json]` | 字幕・音声を乗せて `output.mp4` |
| `gmp build <plan.json>` | (voice +) record + render |

主なオプション: `--headed`（ブラウザを見ながら収録）、`--sync-offset`（字幕タイミング補正）、
`--speaker` / `--style` / `--speed`、`--font`、`--crf`、`--no-subtitles`、`--no-audio`、`--no-credit`。

## plan.json

```jsonc
{
  "version": 1,
  "meta":  { "title": "...", "lang": "ja", "project": "MyApp" },
  "app":   { "url": "...", "ready": "#tile-0",
             "start": "npm run dev", "cwd": ".", "start_timeout": 60 },
  "video": { "width": 1280, "height": 720, "fps": 30, "leader": 2.5, "trailer": 1.5 },
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
`highlight` `wait_for` `sleep` `eval`

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

## 未実装

- VOICEVOX 以外の TTS エンジン（`ghostmovieplay/tts/` に足せば `voice.engine` で選べる）
- BGM・効果音、シーン間のトランジション
- canvas / WebGL アプリ向けの状態取得ヘルパ
