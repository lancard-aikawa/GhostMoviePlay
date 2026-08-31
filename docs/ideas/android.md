# Android アプリを撮る

[アイデア](README.md) — 収録対象を Web から Android ネイティブアプリへ広げる案。

**撮る側は入った。** 人が操作して撮る道は動いていて、手引きは
[README_ANDROID.md](../../README_ANDROID.md)。ここに残っているのは
**自動操作（Pass2 の差し替え）の見積り**と、そのときに効いてくる実測。
書いたら測り直すこと。

結論から言うと**難しくない**。差し替えが要るのは実質 **Pass2 だけ**で、
`plan.json` / `timing.json` という境界がすでに切ってあるおかげで
Pass1 と Pass3 はほぼそのまま使える。

## 段ごとの影響

| 段 | Android で | 手間 |
| --- | --- | --- |
| `plan` (Pass1) | Kotlin / Compose を読ませる。selector が CSS → resource-id / content-desc / text | 小（SKILL.md の書き換え） |
| `voice` | **そのまま** | なし |
| `record` (Pass2) | Playwright → Appium (UiAutomator2)、`record_video` → scrcpy | **中〜大** |
| `render` (Pass3) | **そのまま**（縦画面の字幕は入った） | なし |

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

## 実測 (2026-08-31 / moto g05 / Android 15 / 720x1604 / USB 接続)

**撮る側だけ実機で測った。** 数字は 1 台ぶんなので、機種と接続で動く。
録画は端末側 (`screenrecord`) とホスト側 (`scrcpy 4.1`) の両方。

| 測ったもの | 実測 |
| --- | --- |
| 静止画 `adb exec-out screencap -p` | **1241 ms / 枚**（端末側で PNG に圧縮する） |
| 静止画 生 + ホストで PNG 化 | **1015 ms / 枚**（転送 831 ms + ffmpeg 約 180 ms） |
| 録画開始の遅れ `screenrecord` | **0.2〜0.3 秒**（別々の 2 回で 295 / 318 ms、および約 200 ms） |
| 録画開始の遅れ `scrcpy` | **0.93 秒 と 1.89 秒**（連続 2 回。**1 秒ばらつく**） |
| 静止画と録画の矩形 | **720x1604 で完全一致**（screencap / screenrecord / scrcpy の 3 つとも） |
| `uiautomator dump` | **2.6 秒 / 回**（52 ノード、うち resource-id つき 32） |
| adb の往復 (`adb shell true`) | 81〜100 ms |

**測り方。** 「実測経過 − 尺」は下記の VFR の性質があるので使えない。録画中に
**既知の時刻で 3 回画面を変え**（通知シェードの開閉）、動きの始まったフレームの
PTS と引き算する。3 つが揃えば一意に決まる。1 回だけだと偶発的な画面の動きと
区別がつかなかった（実際につかなかった）。

**遅れは `screenrecord` なら Web より一桁小さい。** Playwright の `new_page()` は
1.8〜2.1 秒だが、`screenrecord` は 0.3 秒で始まる。

**ところが scrcpy は遅くて、しかも実行ごとにばらつく。** 同じコマンドの連続 2 回で
0.93 秒と 1.89 秒。**この 1 秒は `video.leader` を大きくしても埋まらない** ——
leader は「最初のビートを遅らせる」だけで、**ホストの時刻と動画の時刻のずれ**は
残るので、字幕と音が毎テイク違う量ずれる。

**だから遅れを定数として持たない。収録のたびに測る。** 録画を始めたら
**同期マーカーを 1 つ打って**（画面を既知の時刻で 1 回変える）、その PTS で
時刻を合わせる。上の測り方をそのまま収録に使うということ。こうすると遅れの
分散が効かなくなるので、**`screenrecord` と scrcpy のどちらを選んでも成立する**。

**人が撮る側では、遅れは「録れていない頭の 1 秒」として出る。** 支援収録は人が
`撮影開始` を押してすぐ操作を始めるので、**scrcpy だと最初の 1 秒が入らない**。
scrcpy は `INFO: Recording started to mp4 file:` を、`screenrecord --verbose` は
`Configuring recorder for ...` を標準出力に出すので、**その行を見てから画面の
ボタンを有効にする**のが素直（待たせる時間を人に見せられる）。

**画面が変わらないとフレームを出さない。scrcpy も同じ。** 静止した画面を
`screenrecord` で 10 秒撮ったら **2 フレーム**しか入っていなかった。scrcpy でも
2〜3 秒の空きがそのまま空く。CFR 化は `render.py` が先頭で吸収するので撮ったものは
使えるが、**尺から遅れを逆算する手が使えない**（上記）。

**矩形は一致する。** Windows では `PrintWindow` (`GetWindowRect`) と `gdigrab`
(DWM の矩形) が 14x8 px ずれて、静止画と録画を混ぜた Krita の 1 本で初めて出てきた。
Android は 3 つとも画面全体で、**720x1604 という 8 の倍数でない高さでも
scrcpy は丸めなかった**。この種の事故は起きない。

**静止画は生で取ってホストで PNG にするほうが速い**（1015 ms 対 1241 ms）。
`capture.py` が Windows でやっているのと同じ形で、Pillow も要らない。ただし
**ピクセル形式が違う** —— `screencap` は 16 バイトのヘッダ (幅・高さ・format・
colorspace) に続けて **RGBA_8888** を返す (`bgr0` ではなく `rgba`)。
`PrintWindow` と違って**アルファは 255 で埋まっていた**ので、全面透明の PNG に
なる罠は無い。

**それでも 1 枚 1 秒かかる。** 支援収録は 1 ビート 1 ショットなので、
撮る人は毎回 1 秒待たされる。**転送が支配的**（生で 4.6 MB / 831 ms ≈ 5.5 MB/s）
なので、速くするなら USB の側の話になる。

**写り込みは閉じられない。** 通知シェードを開いたまま撮れることを確認した
ついでに、**Wi-Fi の SSID・キャリア名・通知の中身・電池残量・時計**が 1 枚に
全部入った。Windows では「ウィンドウ単位で撮るから撮る本人が見ていないものは
入らない」で閉じている話が、**Android では画面全体しか撮れないので原理的に閉じない**。
demo mode と DND で減らせるが、**ゼロにはできない**。撮る面がそう書くしかない。

**一過性の UI は撮れる。** 通知シェードを開いたまま `screencap` が通った。
Krita でポップアップメニューが `PrintWindow` のフォーカス移動で閉じたのとは違い、
ホスト側から叩くのでデバイスのフォーカスを触らない。

## 詰まるとしたら

- **Compose アプリの selector。** XML レイアウトなら `android:id` が全部あるので楽だが、
  Compose は既定で resource-id を持たない。アプリ側に
  `Modifier.semantics { testTagsAsResourceId = true }` を入れてもらう（実験 API）か、
  text / content-desc で当てるかの二択。**対象アプリの協力が要る**のが Web との
  一番大きな違いで、`gmp init` が収録対象を推測する `detect.py` 相当のことが
  やりにくくなる
- **収録。** `adb shell screenrecord` は音声なし・VFR で、**上限は既定 180 秒
  （`--time-limit 0` で外せる）**。VFR は `render.py` が先頭で CFR 化しているので
  そのまま吸収される。**`scrcpy --record` が無条件に良いわけではない** ——
  上限は無く端末のストレージも使わないが、**遅れが 3〜6 倍大きくてばらつく**（上記）。
  同期マーカーで毎回測るなら差は消えるので、そこを作るかどうかで決まる
- **速度。** エミュレータ起動に 1 分、静止画 1 枚に 1 秒、`uiautomator dump` は
  **1 回 2.6 秒**（実測）。「撮り直しは無料」という前提は**金銭的には保たれるが、
  時間的には Web より一桁遅い**
- **録画開始の遅れ。** Web では `実測経過時間 − webm の尺` で推定しているが
  （[実装メモ](../internals.md)）、**VFR なので Android ではこの引き算が使えない**。
  両方とも実測済み（上記）。**`video.leader` を定数で持つのをやめて、
  収録ごとに同期マーカーで測る**のが結論

## 近道が 2 つ

1. **モバイル Web なら今日できる。** Playwright の viewport / device emulation を
   使うだけなので、`plan.json` の `video` を 390x844 にして端末フレームを合成すれば
   実質ゼロ工数。ネイティブアプリではないが「スマホの画面で見せる」需要の大半は届く
2. **対象が Flutter なら汎用 Android より遥かに楽。** `integration_test` + `ValueKey` の
   finder が Appium より安定していて、`WidgetTester` 側で時刻も乱数も握れる
   （＝`determinism.py` が Web と同じ強さで作れる）。Flutter 製アプリを撮るのが
   目的なら、汎用 Android より先にこちらを作るほうが投資効率がいい

## Maestro と比べる —— 自前で書くのか、載るのか

操作の部分は、要するに [Maestro](https://maestro.dev/) の一部を自前で書く話になる。
**作ることになるのは駆動の部分だけ**で、重なりは 2 割も無い。

| Maestro が持っているもの | gmp に要るか |
| --- | --- |
| `tapOn` / `inputText` / `swipe` / `scrollUntilVisible` | **要る**。`Recorder.do()` の分岐とほぼ 1:1 |
| 暗黙の待ちとリトライ（要素が出るまで粘る） | **要る**。ここが唯一の難所 |
| `assertVisible` などのアサーション | 要らない。gmp は撮るのであってテストしない |
| YAML のフロー制御（`repeat` / `runFlow` / 条件分岐） | **要らないどころか邪魔**。それは plan.json の役目 |
| CI レポート・クラウド実行 | 要らない |
| iOS 対応 | いまは要らない。**が、自前では絶対に届かない** |
| `maestro studio`（selector を対話で選ぶ） | 要らない。selector を決めるのは Pass1 の Claude |

**丸ごと載る道は無い。Maestro が実行ループを握るから。** フローを渡すと最初から
最後まで走らせて結果を返す作りだが、`Recorder` は実行ループを手放せない ——
**音声の尺がビートの尺を決める**し、**各ビートの実測時刻を `timing.json` に書く**。
ビートごとに `maestro test` を叩けば形は作れるが、JVM の起動が毎回乗るので
「撮り直しは無料」が時間の側から崩れる。

**それでも gmp は Maestro ほどの頑丈さを要らない。** あちらが粘る作りなのは
実バックエンドに当たる CI のテストを通すため。こちらは前提が違う。

- エミュレータの**スナップショット復元**から毎回同じ状態で始められる（上記）
- `wait_for` は既に action にある。**待つ条件を書くのは Pass1** で、実行時に推測させない
- 失敗しても撮り直せばいい。赤を誰かに説明する必要がない

しかも**リトライの層は「Pass2 が賢くなる」方向**で、厚くするほど
[CLAUDE.md](../../CLAUDE.md) の「record に賢い判断を足したくなったら、それは
plan.json に書くべき情報」に正面からぶつかる。

**削られるのは要素を引くところ。** いちばん安い構成（`uiautomator dump` の XML から
resource-id / content-desc / text で引き、`bounds` の中心を `input tap`）は追加依存が
ゼロだが、**ダンプはウィンドウが idle になるまで待つ実装**なので、アニメーションが
止まらない画面（スピナー、動画、Compose の無限アニメーション）で
`ERROR: could not get idle state` に落ちる。**しかも 1 回 2.6 秒**（実測。上記）で、
それが要素ごとに乗る。**この速度では駆動に使えない。**
Maestro が金をかけているのはまさにここ（端末側に常駐ドライバを置いてダンプを介さない）。

**同じ手は自前でも取れる。** Appium の UiAutomator2 サーバは APK + HTTP なので、
**Node の Appium 本体を立てずに APK だけ入れて喋る**ことができる。ダンプより速く
idle 問題も踏まない。書くならこちら。

## やるとしたら

**支援収録が入ったので、着手の順番が変わっている。** 撮る側だけなら操作は 1 行も
要らないので、`capture.py` と同じ形の `capture_android.py` を 1 枚足せば
`gmp shoot` の画面で人が撮れる。オーバーレイは `record.py` しか使っていない ——
つまり**人が撮る 1 本にはそもそも無い**ので、
**自動操作をやると決めるまで作り直さなくていい**。

自動操作まで行くなら **「駆動」と「render 時オーバーレイ」の 2 本**が本体。
後者から先に着手して Web 側で完成させ、前者はそのあとに足す。
駆動は Appium 本体ではなく **UiAutomator2 の APK に直接乗る**（上記）。

新しく要るもの: `record_android.py`（`record.py` と同じ `Recorded` を返す）、
`plan.App` に `apk` / `package` / `activity`、`settings.SCHEMA` に対象の種別
（`web` / `android`）、`gmp doctor` の adb / scrcpy / UiAutomator2 の APK の確認。
`agent.py` `spec.py` `paths.py` `tts/` `subtitles.py` `ffmpeg.py` は無傷で済むはず。
