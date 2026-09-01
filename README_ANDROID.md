# Android アプリを撮る

[README](README.md) — Android のアプリを撮るときの手引き。**撮り方は 2 つある。**

| | 誰が操作するか | いつ使うか |
| --- | --- | --- |
| **支援収録** | 人（`gmp shoot` の画面） | 自動操作が届かない・セレクタが取れない |
| **自動収録** | 機械（`gmp record`） | ビートに `actions` を書けるとき。**撮り直しが安い** |

どちらも出るものは同じ `shots/*.png` で、`gmp render` は区別しない。
**まず自動収録を試して、届かないところだけ人が撮る**のが順当。

**`do` と `say` の書き方、1 ビート = ショット 1 つ、撮り直しの考え方、組み立て**は
Windows と同じなので [README_WINAPP.md](README_WINAPP.md) を読むこと。
ここには **Android で違うところだけ**を書く。

## まず、本当にこれが要るか

**モバイル Web なら要らない。** ブラウザで開くものは `app.url` を書けば
`gmp record` が自動で撮る。`video` を 390x844 にすれば縦画面になるし、
**撮り直しが無料**のまま済む。ネイティブアプリでないと出せないもの
（ネイティブの UI、端末の権限ダイアログ、オフライン動作）を撮るときだけ、
こちらを使う。

**自動操作は入っている**（下記）。ただし相手のアプリがアクセシビリティに
何も出していないと届かないので、そこは人が撮ることになる。

## Windows と違うところ

| | Windows | Android |
| --- | --- | --- |
| 撮る範囲 | ウィンドウ 1 つ | **画面全体しか撮れない** |
| 一過性の UI（メニュー・シェード） | 静止画では閉じてしまう | **開いたまま撮れる** |
| 静止画と録画の矩形 | 14x8 px ずれる | **一致する** |
| 静止画 1 枚 | 数十 ms | **約 1 秒** |
| 撮る相手を選ぶ | ウィンドウ（ダイアログは別） | 端末（画面は 1 つ） |

**いちばん効くのは 1 行目。** Windows は「撮る本人が見ていないものは入らない」が
保てるが、**Android は範囲を狭められない**。何もしないと、通知・時計・電波・
Wi-Fi の SSID・キャリア名がそのまま動画に入る（実測で全部入った）。
下の `起動` がこれを消す。

## 用意するもの

- **adb**（Android SDK Platform-Tools）を PATH に。`uv run gmp doctor` で確認できる
- 端末の**開発者オプション → USB デバッグ**を有効にして USB で繋ぐ。
  繋いだあと端末に出る「このコンピュータを許可しますか」に OK

`adb devices` に `device` と出ていれば準備完了。`unauthorized` なら端末側の許可が
まだで、`offline` なら繋ぎ直す（撮る画面はどちらも一覧に出さない）。

## 設定

`gmp.toml`（プロジェクト共通）か `video.md`（この 1 本）に書く。

```toml
[app]
# **これを埋めると「人が操作して撮る」1 本になる。** url は要らない
package = 'com.example.app'

# **撮る前に人が満たしておくこと。** 撮る画面のいちばん上に出る。
# 手順 (beat.do) ではないので、ここに書く
precondition = 'デモ用アカウントでログイン済みであること'

# 撮る画面の「起動」でアプリを開く。**activity 名を書かない** ——
# monkey なら改名されても当たる
start = 'adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1'

# 写り込みを消す。起動で走り、閉じるときに teardown が走る
setup = '''adb shell settings put global sysui_demo_allowed 1 && adb shell am broadcast -a com.android.systemui.demo -e command enter && adb shell am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0900 && adb shell am broadcast -a com.android.systemui.demo -e command battery -e level 100 -e plugged false && adb shell am broadcast -a com.android.systemui.demo -e command network -e wifi hide -e mobile hide && adb shell am broadcast -a com.android.systemui.demo -e command notifications -e visible false'''
teardown = '''adb shell am broadcast -a com.android.systemui.demo -e command exit && adb shell settings put global sysui_demo_allowed 0'''

# 撮る端末の実寸。縦画面
[video]
width = 720
height = 1604
```

**端末のシリアルは書かない。** 機械ごとに違う値なので、焼くと別の端末で繋がらない
（`voice.url` と同じ理由）。どの端末で撮るかは撮る画面で選ぶ。

**`adb shell pm clear` を仕込みに書かない。** アプリのデータごとログインが消えるので、
`precondition` に「ログイン済み」と書いた 1 本では仕込みが前提を自分で壊す。

設定の詳しい話は [docs/settings.md](docs/settings.md)、
plan.json の書き方は [docs/plan.md](docs/plan.md)。

## 進め方（人が撮る場合）

### 1. 撮る画面を開く

```powershell
uv run gmp shoot docs/video/xxx/plan.json
```

撮る面（`gmp ui`）の `ショット` の行をダブルクリックしても開く。
いちばん上に `撮る前に：` の帯が出ていたら、**先にそれを満たしてから**始める。

### 2. 「起動」を押す

**必ず押す。** 仕込みが走って写り込みが消え、アプリが開く。実測では、これで
`12:08 + 通知アイコン 6 個 + VoLTE + Wi-Fi + 電波 + 電池` が `9:00 + 電池` だけになった。

押さずに撮ると**通知も SSID もそのまま動画に入る**。閉じるときに元へ戻る
（`片付ける` を押し忘れても戻る）。

### 3. 上から順に撮る

表の行を選んで `画像を撮る`。`do` に「どの画面か：やること」の形で書いてあるので、
その画面にしてから撮る。

- **1 枚に約 1 秒かかる。** 転送が支配的なので、待つのは正常
- **メニューやシェードを開いたまま撮れる。** ホスト側から撮るので、端末の
  フォーカスは動かない
- 撮ると次のビートへ進む（`撮ったら次のビートへ` のチェック）

### 4. 動きを見せたいところは録画する

`録画を撮る` → 操作 → `録画を止める`。

- **画面が変わらない間はフレームが出ない**（`screenrecord` は VFR）。
  静止した画面を 6 秒撮ると mp4 の尺は 0.8 秒になるが、**撮った実時間まで
  最後のフレームで埋める**ので、置いた「間」は消えない
- 録画は端末側に一度書いてから手元へ持ってくる。`録画を止める` に 1 秒ほどかかる

### 5. 保存して残りを回す

`保存` → 撮る面に戻って `声をつける` → `収録する` → `仕上げる`。
**支援収録では `声をつける` が先**（画が先にあるので、音の尺に画を合わせる）。

## 機械に操作させて撮る（自動収録）

ビートに `actions` を書くと、`gmp record` が**人の代わりに操作して撮ります**。
出るものは人が撮ったときと同じ `shots/*.png` なので、そこから先は同じです。

```jsonc
"actions": [
  { "type": "click", "selector": "desc=投稿" },
  { "type": "wait_for", "selector": "desc=作成", "seconds": 10 },
  { "type": "type", "selector": "id=post_title_field", "text": "Q3-2026" }
]
```

**セレクタは接頭辞を必ず書く**（推測させると、当たらなかったのか誤爆したのかが
区別できない）。

| | 意味 |
| --- | --- |
| `desc=送信` | `content-desc` が完全一致。**Flutter はここにラベルを載せる** |
| `desc*=送信` | `content-desc` に含む |
| `id=post_title_field` | `resource-id` の `:id/` から後ろ |
| `text=送信` | `text` が完全一致（**Flutter では当たらない**） |
| `at=0.5,0.75` | 画面の割合で直に指す。ツリーに出ない相手の最後の手 |

使えるのは `click` / `type` / `press` / `wait_for` / `sleep` / `scroll_to` だけで、
**それ以外は撮る前に落とします**。とくに `highlight` は使えません（疑似カーソルも
枠も DOM に注入した JS なので、他人のアプリの上には出せない）。

### 必ず踏むもの

**`app.setup` に `am force-stop` を書く。** 書かないと、**前回どこで終わったかを
引き継いだまま**始まります（`作成` の画面を開いたまま放置していて、最初のビートが
15 秒待って落ちた）。**`pm clear` は使わない** —— ログインごと消えるので、
`precondition` の「ログイン済みであること」を仕込みが自分で壊します。

```toml
setup = 'adb shell am force-stop com.example.app'
```

**日本語を打つには ADBKeyboard を入れる。** `input text` は非 ASCII を**黙って
落とします** —— コマンドは成功して、入力欄が空のまま残ります（実測。ローマ字を
書いても IME が変換してしまい、`zentai renraku` が「全体れんらく」になった。
**変換は IME の学習状態で変わる**ので決定論になりません）。ADBKeyboard を入れて
既定の IME にすれば、`type` がそのまま日本語を打てます（broadcast で渡すので
IME の変換を通りません）。入れていない端末で日本語を書くと、**撮る前に落ちます**。

```powershell
# 1. 入れる (Play Protect が古い targetSdk を弾くので、検証を一時的に切る)
adb shell settings put global verifier_verify_adb_installs 0
adb install -r --bypass-low-target-sdk-block ADBKeyboard.apk
adb shell settings delete global verifier_verify_adb_installs   # 必ず戻す
adb shell ime enable com.android.adbkeyboard/.AdbIME
```

既定に据えるのと戻すのは **`app.setup` / `app.teardown`** に書きます（撮る前後に
走らせるものはそこ、という決まりのまま）。戻し先は端末ごとに違うので、
`adb shell settings get secure default_input_method` で先に控えておくこと。

```toml
setup = 'adb shell ime set com.android.adbkeyboard/.AdbIME && adb shell am force-stop com.example.app'
teardown = 'adb shell ime set com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME'
```

**打ったら `press KEYCODE_BACK` で閉じる。** ADBKeyboard は画面の下端に
`ADB Keyboard {ON}` の帯を出すので、そのまま撮ると**動画に写ります**。
BACK は帯だけを閉じ、開いているダイアログは残ります（実測）。

**ステータスバーには IME のアイコンが残ります。** 入力欄に触れた時点で
demo mode の偽ステータスバーに ADBKeyboard のアイコンが増え、**その画面
（ダイアログ）を閉じるまで消えません** —— BACK でも、別の場所を押しても、
`demo enter` を送り直しても消えず、`exit` → `enter` が要ります（収録の途中では
掛け直せない）。素のステータスバーには出ないので、**demo mode を使う代償**です。
日本語を打つ 1 本では、そこは諦めることになります。

### 起動したあとに、もう一度ステータスバーを整える

**アプリが立ち上がるとバーにアイコンが増えます**（上記）。仕込みで整えるだけでは
間に合わないので、`app.start` の後ろに demo mode の掛け直しを足します。

```toml
start = '''adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1 && adb shell sleep 6 && adb shell am broadcast -a com.android.systemui.demo -e command exit && adb shell am broadcast -a com.android.systemui.demo -e command enter && adb shell am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0900'''
```

**通知はデモモードでは止まりません。** 隠せるのはステータスバーの中身だけで、
**ヘッズアップ通知は上から降りてきます**（送信を撮る 1 本で、自分の送った
お知らせが一覧の上に出た）。`app.setup` で DND にします。

```toml
setup = 'adb shell cmd notification set_dnd none && ...'   # teardown で set_dnd off
```

**ダンプは 1 回 2.6 秒。** 要素を探すたびに走るので、`wait_for` を並べるほど
遅くなります。待つ必要のないところには書かないこと。

**打った文字は `wait_for` で検算できます。** 入力欄はフォーカスを外すと打った
文字が `text` に出るので、`press KEYCODE_BACK` のあとに待てば、**空振りした
ビートをその場で落とせます**（撮り終わってから画を見比べるより早い）。

```jsonc
{ "type": "type", "selector": "id=post_title_field", "text": "9月の全体連絡" },
{ "type": "press", "key": "KEYCODE_BACK" },
{ "type": "wait_for", "selector": "text=9月の全体連絡", "seconds": 5 }
```

### シーンが目的を果たしたかを見る

`goal` は Android でも効きます（`says` / `selector` / `contains` / `absent`）。
**操作が全部通っても、目的を果たしたことにはならない** ——
[docs/plan.md](docs/plan.md) の達成条件と同じ書き方です。

見る場所は Android のセレクタで、**その矩形の中にある文字**を読みます。
ダンプは平坦（親子が無い）ので、Flutter のように**文字が子ノードに載る**相手でも
枠を指せば中の文字が取れます（`id=set_enquete` の枠を指して「未設定」を見る）。

```jsonc
"goal": { "says": "アンケートは付いていない", "selector": "id=set_enquete", "absent": "設定済み" }
```

### ショットの名前

自動収録のショットは **`shots/<シーン>-<番号>.png`** で、撮り直すと同じ名前を
上書きします（人が撮るほうは通し番号）。自動収録は plan.json に書き戻さないので、
番号を増やしていくと**誰も参照しないショットだけが溜まります**（実際に 4 回撮って
64 枚になり、生きているのは 16 枚だけでした）。

## つまずいたとき

**端末が一覧に出ない。** `adb devices` を見る。`unauthorized` なら端末の画面に
出ている許可ダイアログに OK。何も出ないなら USB デバッグが無効か、ケーブルが
充電専用。

**「起動」が見当たらない。** `app.start` も `app.setup` も無い 1 本には出ない。
`app.setup` だけあるときは `仕込む` という名前で出る。

**通知やアカウント名が写った。** `起動` を押していないか、アプリ自身が出している
もの（ヘッダーのユーザー名など）。前者は押し直して撮り直す。後者は**撮る前に
気づくしかない**ので、1 枚目を撮ったら一度プレビューを見ること。

**字幕が画面からはみ出す。** `video` の幅と高さが実際の端末と合っていない。
撮る画面は**まだ 1 枚も撮っていないときだけ**大きさを合わせるので、
途中で変えたときは `video.md` に実寸を書く。

**製品名が「エイ、ラモ」のように切れて聞こえる。** ラテン文字の語は読み辞書では
直せない。`say` のほうをカタカナで書く（[docs/voice.md](docs/voice.md)）。

## 覚えておくこと

- **画面全体しか撮れない。** demo mode と DND で減らせても**ゼロにはできない**ので、
  撮る端末に見られたくないものを置いたまま撮らない
- **撮る端末を人から借りたら、必ず `片付ける`（または閉じる）**。demo mode が
  入ったままになる
- **端末に置く作業ファイルは `/data/local/tmp` の下**（録画の一時ファイルと
  画面のダンプ）。撮り終わったら消しますが、中止や adb の切断で残ることはある。
  `/sdcard` に置かないのは、あそこは**ギャラリーに拾われる**ので、残った録画が
  端末の写真一覧に出てしまうため。`adb shell ls /data/local/tmp` で見えます
- **静止画 1 枚に約 1 秒、録画の開始に 0.2〜0.3 秒**。撮り直しは手作業なので、
  Windows 以上に「1 回で撮る」が効く
- 実測の数字と、自動操作をやるとしたらの見積りは
  [docs/ideas/android.md](docs/ideas/android.md) にある
