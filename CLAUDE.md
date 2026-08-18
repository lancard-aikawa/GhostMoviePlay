# CLAUDE.md

使い方は [README.md](README.md)、詳細は `docs/` にある（[設定](docs/settings.md) /
[音声](docs/voice.md) / [plan.json](docs/plan.md) / [実装メモ](docs/internals.md)）。
ここには **それらを読んでも分からないこと**（設計の前提、壊しやすい不変条件、
実測して初めて分かった落とし穴）だけを書く。

## コマンド

```powershell
uv sync
uv run playwright install chromium
uv run gmp doctor                      # ffmpeg / chromium の確認
uv run pytest                          # 全テスト
uv run pytest -m "not slow"            # 実プロセスを起動するテストを除く
uv run gmp build examples/demo/plan.json --voice   # 通しで1本
```

音声を扱うときは VOICEVOX ENGINE が要る。GUI を開かずに済ませるなら:

```powershell
Start-Process "$env:LOCALAPPDATA\Programs\VOICEVOX\vv-engine\run.exe" -ArgumentList "--host","127.0.0.1","--port","50021" -WindowStyle Hidden
```

## 設計の前提

### Pass2 と Pass3 に AI を入れない

このツールの全体は **AI を使う段を 1 つに閉じ込める**ことで成り立っている。

```
Pass1  gmp plan     AI あり   ソースを読んで演目を設計する
Pass2  gmp record   AI なし   plan.json を決定論的にリプレイして録画
Pass3  gmp render   AI なし   字幕・音声を乗せる
```

record や render に「賢い判断」を足したくなったら、**それは plan.json に書くべき情報**。
ここに AI を入れると、撮り直しのたびに絵が変わり、口調の差し替えに再収録が要り、
コストが読めなくなる。3 段に分けた意味が全部消える。

### 設定は Pass1 で plan.json に焼き切る

設定は 3 層（`config.toml` / `<project>/gmp.toml` / `video.md`）ある。
`settings.py` の各項目には**行き先 (`bake`)** が宣言されていて、これが
上の「Pass2/3 に AI を入れない」と同じ不変条件を守っている。

- `plan` —— 解決した値は **`gmp plan` の時点で plan.json に入れる**。
  `record` / `render` / `voice` が設定ファイルを読んではいけない。読むと、
  同じ plan.json が機械ごとに違う動画を出す。AI ではなく設定ファイル経由で
  3 段構成が破れるので、見た目より気づきにくい
- `brief` —— `PLAN_REQUEST.md` に載るだけ（口調・題材・尺・字幕の上限）。
  plan.json には残らない
- `runtime` —— 機械依存で、**絵と音を変えない**値だけ（接続先・フォント・画質）。
  これだけが実行時に設定ファイルを読んでよい。`layers` が `(MACHINE,)` に
  限られていることをテストで固定している

同じ理由で、**グローバル設定に「プロジェクト固有の事実」を置けないようにしてある**
（`app.url`、`determinism.seed` など）。書くと警告して無視する。許すと、同じ
機械で 2 本目のプロジェクトを撮った瞬間に嘘になる。

**Pass2/3 から設定を読む入口は `settings.machine_value()` 1 つだけ。**
`bake="runtime"` 以外を渡すと例外を投げる。声の既定のように「機械にも書けるが
plan.json に焼かれる」値もここからは取れない（取れると、plan.json に書いてある
声と違う声で喋る経路ができる）。`voice.url` と `render.font/crf/preset` が
これを通っている唯一の利用者。

`voice.url` は plan.json に**書き戻さない**（`tts.MACHINE_KEYS`）。機械ごとに
違う値なので、焼くと別のマシンで繋がらない接続先が残る。`--url` は一時指定。

出力ルートの解決だけは `paths.output_home()` に実装が残っている（`settings` が
`paths` を使う関係で、逆向きの依存を作りたくないため）。二重実装なので
`tests/test_settings.py` の `test_home_agrees_with_paths_output_home` で
両者が同じ答えを出すことを固定している。

### 設定画面が書いてよいファイル

**編集する層は画面で 1 回だけ選ぶ。行ごとに選ばせない。** 行ごとの書込先に
していたころ、既定を「その値の由来」にしていたので、グローバル設定から来ている値を
このプロジェクトだけ直したつもりで**全プロジェクトの既定を書き換えていた**。
あわせて、入力欄に出すのは**編集中の層が自分で持っている値だけ**にしてある
（解決後の値を出すと、グローバル設定を編集しているのにプロジェクトの値が見え、
それを直すと既定へ焼く。逆向きの同じ事故）。

`gmp ui` が書くのは **`config.toml` と `gmp.toml` だけ**。`video.md` は
フロントマターの下に本文（補足の散文）を持つので、GUI から書き戻すと人の
書いた文章とコメントを壊す。1本ぶんは「効いている値」の表示に留め、
video.md 由来の行には「この1本が上書き中」を出して、直しても効かないことを
先に言う（書ける先が無い行は編集できないようにしてある）。

`gmp.toml` への保存は `settings.patch_toml()` を通す。**変更した行だけを
当ててコメントと並び順を保つ。** `dump()` で書き直すと、なぜその値なのかを
書いたコメントが消える（雛形が配っている説明ごと消える）。

画面の判断のうち Tk が要らないものは `ui.py` のモジュール関数にしてある
（`TABS` / `settable` / `visible` / `plan_writes` / `parse_dict_text`）。
ウィンドウを作らずにテストできるので、`tests/test_ui.py` は CI で走る。

**同じ行に置けるのは書ける層 (`layers`) が同じ設定だけ。** 行はまとめて出し分けるので、
層の違うものを並べると片方が宙に浮く（`series.count` はプロジェクトにしか置けないので、
`target_seconds` と同じ行にできない）。`tests/test_ui.py` が見ている。

**下の帯は本体より先に pack する。** タブの中身は `side=LEFT` で cavity を取るので、
試聴バーを後から pack すると右側の残りから幅を持っていき、**本体が半分の幅になって
行の右端の項目が消える**（実際に消した）。フッターのボタン行と同じ罠が 1 段深い
ところにもある。

**`bind_all("<MouseWheel>")` は後から呼んだものが勝つ。** タブごとに canvas が
あるので、出しっぱなしにすると**最後に作ったタブしかスクロールしない**。
`<Enter>` / `<Leave>` でポインタが乗っている間だけ束縛する。

**その層に書けない入力欄は出さない。** `gmp.toml` が無い状態の `app.url` も、
グローバル設定を編集しているときの `app.url` も、埋めた先が無い。例外は `ui.visible()` の
`pinned` —— **UI では触れない層**（video.md / 環境変数）で決まっている値だけは、
直せなくても読み取り専用で見せる。機械とプロジェクトは切り替えれば触れるので入れない。

**Tk の root はテストで作り直さない。** 1 プロセスで `Tk()` を繰り返すと、たまに
`init.tcl` を読めずに落ちて「画面が無い環境」として飛ぶ。セッションで 1 つ作り、
テストごとには `Toplevel` を作る。skip の理由には例外の中身を書く
（書かないと本当の不具合を握り潰す）。

### 見積り尺と実測の余白を別々に書かない

`plan.AUDIO_TAIL` は「音声を鳴らし終えてから次のビートへ行くまでの余白」で、
`record` が実際に使う値と `estimate()` が数える値の**両方がこれを見る**。
片方に数値を直書きすると、見積りと実測が理由もなくズレる。

### 順番を入れ替えられないもの

| | なぜ |
| --- | --- |
| `voice` → `record` | **音声の尺がビートの尺を決める**。先に尺を決めてから合成すると必ず尻切れになる |
| CFR 化 → 字幕焼き込み | Playwright の webm はフレーム間隔が可変。先に `fps=N` を通さないと字幕がズレる |
| 決定論化 → `goto` | `page.clock` と seed の init script はナビゲーションより前にしか仕込めない |
| 選択の確定 → `mouseup` の通知 | 選択ツールバーの類は `mouseup` を見て出る。範囲を確定してから知らせる |

## 壊しやすい不変条件

### `beat.audio` は出力ディレクトリからの相対パス

plan.json の隣ではない。plan.json は**プロジェクトの git に入る**が wav は生成物で
ユーザフォルダ側に出るので、plan.json の隣にすると解決できない。相対のままなのは
マシンをまたいでも plan.json が壊れないようにするため。

一方 **`timing.json` の `audio` は絶対パス**。timing.json は出力ディレクトリに、
plan.json はプロジェクトにあって階層が違うので、相対で持つと render が見失う。
（これは実際に踏んだ。TTS を実装するまで露見しなかった。）

### 相対パスは「それを書いたファイル」からの相対

設定は 3 層あるので、`app.cwd = '.'` の意味が層ごとに違う。`gmp.toml` の `.` は
プロジェクトルート、`video.md` の `.` は動画のフォルダ。**解決した値をそのまま
使ってはいけない。** `settings.Resolved.rebase_path()` に使う側の基準を渡して
書き直す（`gmp plan` は plan.json の置き場所を基準にする）。

`Origin.source` にどのファイルが書いたかを覚えてあるのはこのためで、由来の
追跡は表示のためだけの機能ではない。

なお **TOML の裸のキーは ASCII だけ**。`voice.dict` に日本語の表記を書くときは
`'語' = 'ゴ'` とクォートする（`settings.dump` は自動でクォートする）。

### 音声を乗せたらクレジットも焼く

VOICEVOX は生成音声を使った作品にキャラクター名を含むクレジットを求める。
`render` は `with_audio` のときだけクレジットを焼く、という関係で担保している。
**音声だけ乗せてクレジットを落とせる経路を作らないこと。**
`--no-credit` は「別の場所に自分で表示する」人のための逃げ道で、既定ではない。

### 再合成のフィンガープリント

`voice/manifest.json` は「原稿 + 声の設定」のハッシュで再合成を省く。

- **音に影響するものは必ず入れる** —— `dict`（読み）を入れ忘れると、読みを直しても
  古い wav が使われて直らない
- **音に影響しないものは入れない** —— `credit` と `url` は `NON_AUDIO_KEYS` で外して
  ある。入れると、クレジットを書き換えただけで全部再合成される

### テストは実ユーザの Videos フォルダに書いてはいけない

出力先は環境変数 > 設定ファイル > 既定 の順で決まる。`tests/conftest.py` が
最優先の環境変数を一時ディレクトリに固定している。**この autouse fixture を外すと、
CLI を通るテストが実際に `~/Videos/GhostMoviePlay/` を汚す**（実際に汚した）。

### ffmpeg は出力ディレクトリを cwd にして起動する

字幕フィルタに Windows の絶対パス（`C:\...` のコロン）を渡すと壊れる。
`cwd=outdir` にして `subtitles=subs.ass` と相対名で渡すことで回避している。
**絶対パスに変えないこと。**

## 実測して分かったこと

数字は Windows 11 / Chromium での実測。環境が変われば動くが、性質は変わらない。

- **録画は `new_page()` の 1.8〜2.1 秒後から始まる。** `video.leader` はこれを吸収する
  ための「ページ生成から最初のビートまでの最小待ち時間」。短いと**冒頭のビートが
  動画に入らない**。推定した遅れが leader を超えたら警告が出る
- **Chromium はリンクの上で押し始めたドラッグではテキスト選択を開始しない。**
  実際の操作でも同じ。`select_text` は手前の平文から掴む
- **`<a>` は既定で draggable。** リンクの上で押すとテキスト選択ではなくリンクの
  ドラッグが始まる。なぞる間だけ切っている
- **座標を測ってからドラッグするまでにページがスクロールすることがある**
  （読書位置の復元など）。選択結果を毎回照合して測り直す
- **TTS は文脈の薄い単語を誤読する。** 「語」は単独だと カタリ。ルビは振れないので
  `voice.dict` で読みを渡す。複合語（用語・物語）は長い一致が優先されるので巻き添えにならない
- **`page.clock.install()` だけだと時計が止まる。** `setTimeout` も凍ってアプリが
  動かなくなるので `resume()` まで打つ

## 変更時に一緒に直すもの

| 変えたもの | 一緒に直す |
| --- | --- |
| action を足した | `plan.ACTION_SPECS`（必須キー）、`record.Recorder.do()` の分岐、`skills/ghostplay/SKILL.md` の action 表、`docs/plan.md` の action 一覧、`tests/test_plan.py` |
| plan.json のスキーマ | `plan.py` の dataclass と `load()`、`spec.PLAN_SCHEMA_DOC`（**AI に渡す仕様はここが正**）、SKILL.md、`docs/plan.md` |
| 出力先の決まり方 | `paths.py`、`docs/settings.md` の「ファイルの置き場所」、`gmp where` の表示、`tests/test_paths.py` |
| 設定項目を足した | `settings.SCHEMA`（**`layers` と `bake` を必ず埋める**）、`ui.TABS` と `ui.LABELS`（漏れは `tests/test_ui.py` が検出する）、雛形を配るなら `settings.PROJECT_TEMPLATE`、`docs/settings.md`、`tests/test_settings.py`。値を実際に使う側（`spec.build_request` / 実行時の解決）も一緒に繋ぐ |
| 設定の層を足した | `settings.ORDER` と `LAYER_LABEL`、`resolve()` の layers 組み立て、`gmp config` のヘッダ表示、`docs/settings.md` の 3 層の表 |
| voice の設定項目 | `plan.Voice`、`tts/voicevox.py`、**音に影響するなら `NON_AUDIO_KEYS` に入れない**、機械ごとに違う値なら `MACHINE_KEYS` に入れる、`settings.SCHEMA` の `voice.*`、`tests/test_reading.py` |
| TTS エンジンを足した | `tts/__init__.py` の `_engine()`、`resolve_speaker` / `synthesize` / `credit` / `push_dict` / `pop_dict` を実装（`hasattr` で見ているので辞書系は任意） |
| 字幕の見た目 | `subtitles.py` の Style 行。**クレジットは別スタイル**（右上・小さめ）で、字幕（下部中央）とぶつからない配置を保つ |
| CLI のサブコマンド | `cli.py` の `main()`、README のコマンド表 |

## サンプルと実例

- `docs/video/intro/` —— **このツール自身の紹介動画**（約 100 秒）。収録対象は
  `site/index.html` という説明ページで、`app.start` の簡易サーバ越しに開く。
  `gmp.toml` がこのリポジトリのプロジェクト設定になっている。**設定・読み辞書・
  尺の見積りを実際に通す唯一の場所**なので、それらを変えたらここを撮り直す
- `examples/demo/` —— 手で書いた plan.json。タイル取りゲームで
  「大きい数から取ると損をする」を実演する 3 幕構成
- `C:\Repos\mywork\GlossPop\docs\video\gloss-scope\` —— 実プロジェクトの 1 本目。
  収録用に使い捨てのデータルートを立てる `serve.py` を置く形の例
