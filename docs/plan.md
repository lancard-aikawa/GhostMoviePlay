# plan.json

[README](../README.md) — AI が書いた台本を手で直すとき。
AI に渡す仕様は `ghostmovieplay/spec.py` の `PLAN_SCHEMA_DOC` が正で、
ここはそれを人が読む形にしたもの。

```jsonc
{
  "version": 1,
  "meta":  { "title": "...", "lang": "ja", "project": "MyApp" },
  "app":   { "url": "...", "ready": "#tile-0",
             "start": "npm run dev", "cwd": ".", "start_timeout": 60,
             "setup": "python seed.py", "teardown": "python seed.py --clean" },
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

`app` `video` `voice` `determinism` は[設定](settings.md)から解決された値が
焼き込まれる。plan.json はそれ単体で撮り直せる（設定ファイルは要らない）。

`app.setup` / `app.teardown` は収録の前後に走らせるコマンド（`app.cwd` で実行）。
**仕込みは `app.start` より前**に走るので、仕込んだデータを開発サーバが読める。
仕込みが落ちたら収録しない（荒れていないデータを撮っても意味が無い）。後片付けが
落ちても収録は失敗にしないが、`timing.json` の警告には残る（消し損ねた使い捨て
データが次の収録に残るため）。

## 尺の見積り

`gmp plan --run` と `gmp voice` が通しの尺を出す。目標（`series.target_seconds`）を
許容幅（`series.tolerance`）より超えていたら警告する。依頼文に「90 秒で」と書いても
守られないので、機械側で数えて言うようにしてある。

```
  尺  103.4 秒  (音声の実尺。操作にかかる時間は含みません)
  ! 目標の 90 秒を 13 秒超えています (許容 112 秒)。ビートを削るか説明を分けてください
```

`gmp voice` の後は**音声の実尺**で数える（音声の尺がそのままビートの尺なので
これが正確）。合成前は字幕の文字数と `hold` からの見積りになる。どちらも
**操作にかかる時間は含まない**ので、足りない側にズレる。

### ズレの大きさ（実測 21 本）

業務アプリの説明動画 21 本を撮ったときの実測。**実長は見積りの 1.8〜2.6 倍**になった。

| 内容 | 見積り | 実長 | 比 |
| --- | --- | --- | --- |
| 解説中心（画面を止めて喋る） | 39.1s | 100.2s | 2.6 |
| 入力と遷移が多い | 94.4s | 167.4s | 1.8 |
| 数字の読み上げ | 90.8s | 223.9s | 2.5 |

倍率が一定でないので、**見積りから実長を割り出すことはできない**。1 本に収まるか
どうかは撮ってから決めるしかない —— 実際、3 本が 3 分半を超えたので撮ってから
2 本ずつに割った。**割ると合計は伸びる**（前置きと締めが 2 組要る）が、1 本あたりが
3 分を切って見返しやすくなる。

## 状態を持つアプリを撮る

撮り直すたびに同じ初期状態から始められないと、plan.json のリプレイが意味を持たない。
[GlossPop](https://github.com/lancard-aikawa/GlossPop) の `docs/video/gloss-scope/`
では収録用に `serve.py` を置き、`app.start` からそれを起動して**使い捨てのデータルート**で
アプリを立てている。実データを触らずに済み、何度撮っても同じ画面から始まる。

仕込みと配信が分けられるなら `app.setup` / `app.teardown` に置くほうが素直
（`app.start` は起動だけになる）。仕込みは `start` より前に走る。

その 1 本は「**登録する語が短すぎると本文がリンクだらけになる**」という、ソースを
読まないと狙って作れない失敗を扱っている（日本語には語境界が無いので自動リンクが
部分文字列で照合される、という設計から来る）。
