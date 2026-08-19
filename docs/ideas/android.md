# Android アプリを撮る

[アイデア](README.md) — 収録対象を Web から Android ネイティブアプリへ広げる案の見積り。
**未実装。** 実際に書いたら測り直すこと。

結論から言うと**難しくない**。差し替えが要るのは実質 **Pass2 だけ**で、
`plan.json` / `timing.json` という境界がすでに切ってあるおかげで
Pass1 と Pass3 はほぼそのまま使える。

## 段ごとの影響

| 段 | Android で | 手間 |
| --- | --- | --- |
| `plan` (Pass1) | Kotlin / Compose を読ませる。selector が CSS → resource-id / content-desc / text | 小（SKILL.md の書き換え） |
| `voice` | **そのまま** | なし |
| `record` (Pass2) | Playwright → Appium (UiAutomator2)、`record_video` → scrcpy | **中〜大** |
| `render` (Pass3) | ほぼそのまま。縦画面向けに `subtitles.py` の配置調整 | 小 |

`Recorder.play_beat` の「音声の尺がビートの尺を決める」「実測時刻を timing.json に書く」
というロジックは丸ごと生き残る。`Recorder.do()` の分岐も Appium とほぼ 1:1 で、
`click` / `type` / `press` / `scroll_to` / `wait_for` は素直に対応する。
**`select_text` だけは Android に概念が無い**ので落ちる。

## 本当に作り直しが要るのは 1 箇所だけ

**`overlay.py`。** 疑似カーソル・波紋・ハイライト枠・黒みが全部
「DOM に `add_init_script` で注入した JS」なので、他人のアプリの View 階層に
潜り込めない Android では成立しない。

解は **収録時に描くのをやめて render 時に合成する**こと。収録中は `(時刻, 矩形)` を
イベントログに吐くだけにして、字幕を焼くのと同じ ASS レイヤに乗せる
（ASS は矩形描画と `\move` ができるので、いまの `render.py` の枠内に収まる）。

**これは Web 側にも効く。** いまのオーバーレイは DOM に依存しているので
cross-origin iframe や canvas の上には出せない。render 時合成にすればそこも撮れる。
**Android をやるかどうかに関わらず、先に切り出す価値があるのはこの部分。**

タップの波紋だけは OS が持っているので、当面それで代用できる:

```bash
adb shell settings put system show_touches 1   # タップ位置に円が出る。録画にも写る
```

## 決定論はむしろ Web より楽

いまの `determinism.py` は `Math.random` の差し替えと `page.clock` で、
自分で書いてあるとおり**サーバ側や WASM 側の乱数までは面倒を見ない**。
Android にはこれより強い手がある。

```bash
adb emu avd snapshot load clean    # エミュレータのスナップショットから毎回同じ状態で開始
adb shell pm clear <package>       # アプリデータだけ消す軽い版
adb shell settings put global sysui_demo_allowed 1   # ステータスバーの時刻・電池・電波を固定
adb shell am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0900
```

スナップショット復元はアプリ状態・時刻・データをまとめて巻き戻せるので、
GlossPop の `serve.py` が自前でやっていた「使い捨てのデータルート」が要らなくなる。

**SystemUI の demo mode は必須。** これを入れないと時計と電池残量が毎回変わるので、
[ビジュアル回帰](README.md#b-目的を差し替える--撮る道具から検査する道具へ)に使えない。

## 詰まるとしたら

- **Compose アプリの selector。** XML レイアウトなら `android:id` が全部あるので楽だが、
  Compose は既定で resource-id を持たない。アプリ側に
  `Modifier.semantics { testTagsAsResourceId = true }` を入れてもらう（実験 API）か、
  text / content-desc で当てるかの二択。**対象アプリの協力が要る**のが Web との
  一番大きな違いで、`gmp init` が収録対象を推測する `detect.py` 相当のことが
  やりにくくなる
- **収録。** `adb shell screenrecord` は上限 3 分・音声なし・VFR。
  `scrcpy --record` でホスト側に録るほうがいい。VFR は `render.py` が先頭で
  CFR 化しているのでそのまま吸収される
- **速度。** エミュレータ起動に 1 分、UiAutomator の要素検索は 1 回数百 ms。
  「撮り直しは無料」という前提は**金銭的には保たれるが、時間的には Web より一桁遅い**
- **録画開始の遅れ。** Web では `実測経過時間 − webm の尺` で推定しているが
  （[実装メモ](../internals.md)）、scrcpy 経由だと遅れが大きく分散も広い。
  `video.leader` の既定値は測り直しになる

## 近道が 2 つ

1. **モバイル Web なら今日できる。** Playwright の viewport / device emulation を
   使うだけなので、`plan.json` の `video` を 390x844 にして端末フレームを合成すれば
   実質ゼロ工数。ネイティブアプリではないが「スマホの画面で見せる」需要の大半は届く
2. **対象が Flutter なら汎用 Android より遥かに楽。** `integration_test` + `ValueKey` の
   finder が Appium より安定していて、`WidgetTester` 側で時刻も乱数も握れる
   （＝`determinism.py` が Web と同じ強さで作れる）。Flutter 製アプリを撮るのが
   目的なら、汎用 Android より先にこちらを作るほうが投資効率がいい

## やるとしたら

**「Appium ドライバ」と「render 時オーバーレイ」の 2 本**が本体。
後者から先に着手して Web 側で完成させ、前者はそのあとに足す。

新しく要るもの: `record_android.py`（`record.py` と同じ `Recorded` を返す）、
`plan.App` に `apk` / `package` / `activity`、`settings.SCHEMA` に対象の種別
（`web` / `android`）、`gmp doctor` の adb / scrcpy / Appium 確認。
`agent.py` `spec.py` `paths.py` `tts/` `subtitles.py` `ffmpeg.py` は無傷で済むはず。
