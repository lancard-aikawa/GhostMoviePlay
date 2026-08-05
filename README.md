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

uv run gmp init video.md     # 指示ファイルの雛形
#   video.md を編集（対象URL・口調・シーン構成）
uv run gmp plan video.md     # → PLAN_REQUEST.md を書き出す
#   対象プロジェクトを開いた Claude Code に PLAN_REQUEST.md を渡す → plan.json
uv run gmp build plan.json   # 収録 + 書き出し → out/output.mp4
```

各段を個別に回すとき:

```bash
uv run gmp voice  plan.json          # → voice/*.wav (plan.json に書き戻し)
uv run gmp record plan.json          # → out/raw.webm, out/timing.json
uv run gmp render out/timing.json    # → out/output.mp4
```

### 音声を付ける

[VOICEVOX](https://voicevox.hiroshiba.jp/) を起動した状態で:

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
| `gmp init [path]` | `video.md` の雛形を作る |
| `gmp plan [spec]` | video.md → Pass1 依頼文 (`PLAN_REQUEST.md`) |
| `gmp voice <plan.json>` | `say` を音声化 → `voice/*.wav` |
| `gmp voices` | VOICEVOX の話者一覧 |
| `gmp record <plan.json>` | 収録 → `raw.webm` + `timing.json` |
| `gmp render [timing.json]` | 字幕・音声を乗せて `output.mp4` |
| `gmp build <plan.json>` | (voice +) record + render |

主なオプション: `--headed`（ブラウザを見ながら収録）、`--sync-offset`（字幕タイミング補正）、
`--speaker` / `--style` / `--speed`、`--font`、`--crf`、`--no-subtitles`、`--no-audio`。

## plan.json

```jsonc
{
  "version": 1,
  "meta":  { "title": "...", "lang": "ja" },
  "app":   { "url": "...", "ready": "#tile-0" },
  "video": { "width": 1280, "height": 720, "fps": 30, "leader": 2.5, "trailer": 1.5 },
  "voice": { "engine": "voicevox", "speaker": "ずんだもん", "style": "ノーマル", "speed": 1.0 },
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

**CFR 化。** Playwright が吐く webm はフレーム間隔が可変。`fps=N` を通してから
字幕を焼かないとズレる。render は必ずこの順で 1 パスにまとめている。

**字幕は焼き込み。** DOM に描くとアプリの z-index と衝突し、多言語化もできない。
`timing.json` → ASS → ffmpeg の順。DOM 字幕は確認用に `--subtitle-mode dom` で使える。

## 未実装

- `gmp plan` の Claude CLI 直接呼び出し（現状は依頼文を書き出すところまで）
- `app.start` によるサーバ自動起動
- 乱数・時刻の固定（`page.clock`）
- VOICEVOX 以外の TTS エンジン（`ghostmovieplay/tts/` に足せば `voice.engine` で選べる）
