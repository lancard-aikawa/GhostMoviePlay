# 環境の用意

[README](../README.md) — **いちばん最初に読む**。ここが全部終われば
`gmp doctor` が「準備完了」を出す。声の設定は [音声](voice.md)、
出力先は [設定](settings.md)。

Windows 11 での手順。他の OS でも動くが、実測値と `winget` の行は Windows のもの。

## 何が要るか

| | 無いと止まるもの | 入れ方 |
|---|---|---|
| **uv** (Python 3.11+) | 全部 | `winget install astral-sh.uv` |
| **ffmpeg / ffprobe** | `gmp render`（字幕・音声を乗せる段） | `winget install Gyan.FFmpeg` |
| **Chromium** (playwright) | `gmp record`（収録） | `uv run playwright install chromium` |
| **VOICEVOX** | `gmp voice`（ナレーション） | `winget install HiroshibaKazuyuki.VOICEVOX.CPU` |
| **Claude Code** | `gmp plan --run` と画面の「台本を作る」 | [claude.com/claude-code](https://claude.com/claude-code) |
| **adb** (platform-tools) | Android の[支援収録](plan.md#自動操作が届かない相手を撮る支援収録) | [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) を PATH に |

下 3 つは**要るときだけ**でよい。音声なしの動画（字幕だけ）は VOICEVOX なしで
撮れるし、台本を手で書く・対話の claude に書かせるなら `claude` コマンドは要らない
（`gmp plan` は依頼文 `PLAN_REQUEST.md` を書き出すだけの使い方ができる）。
`adb` は Android のアプリを撮る 1 本にしか要らない（Windows のアプリを撮るなら
`app.window` の道で、こちらは何も足さなくていい）。

## 通しの手順

```powershell
winget install astral-sh.uv
winget install Gyan.FFmpeg
winget install HiroshibaKazuyuki.VOICEVOX.CPU   # ナレーションを付けるなら

git clone https://github.com/lancard-aikawa/GhostMoviePlay
cd GhostMoviePlay
uv sync
uv run playwright install chromium
uv run gmp doctor
```

`winget` で入れた直後は PATH が更新されていないので、**PowerShell を開き直してから**
`gmp doctor` を叩く（`ffmpeg` が入っているのに NG と言われたらこれ）。

`gmp doctor` はインストール済みかどうかではなく**実際に動くか**を見る。chromium は
起動して閉じるところまでやるので、`uv sync` だけで `playwright install` を忘れている
ケースを拾える。

## VOICEVOX ENGINE を起動しておく

`gmp voice` が喋らせるのは GUI ではなく、同梱の **ENGINE**（`127.0.0.1:50021` の
HTTP サーバ）。GUI を開けば ENGINE も一緒に立つが、収録のたびに開くのは邪魔なので
直接起こしてよい:

```powershell
Start-Process "$env:LOCALAPPDATA\Programs\VOICEVOX\vv-engine\run.exe" -ArgumentList "--host","127.0.0.1","--port","50021" -WindowStyle Hidden
```

繋がっているかは話者一覧が出るかで分かる:

```powershell
uv run gmp voices
```

接続先を変えているなら `gmp config --set engine.voicevox.url=...`（**グローバル設定**。
機械ごとに違う値なので plan.json には焼かない → [音声](voice.md#合成)）。

CPU 版で足りる。ナレーションは短文が数十本で、しかも同じ原稿は再合成されない
（[音声](voice.md)のフィンガープリント）。

## 確認できたら

README の[使い方](../README.md#使い方)へ。まず動くところを見たいなら、この
リポジトリに入っているサンプルを 1 本撮ってしまうのが早い:

```powershell
uv run gmp build examples/demo/plan.json --voice
```

出来上がりの置き場所は `uv run gmp where examples/demo/plan.json` で分かる
（生成物はプロジェクトの外、既定では `~/Videos/GhostMoviePlay/` の下に出る）。
