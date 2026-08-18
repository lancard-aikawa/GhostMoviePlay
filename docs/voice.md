# 音声

[README](../README.md) — ナレーションを付けるとき。声の既定をどこに置くかは
[設定](settings.md)。

## VOICEVOX を入れる

[VOICEVOX](https://voicevox.hiroshiba.jp/) が要る。入れ方と ENGINE の起こし方は
[環境の用意](setup.md#voicevox-engine-を起動しておく)。ナレーション用途
（短文を数十本、しかも再合成はキャッシュされる）なら CPU 版で十分。

ENGINE が起動した状態で:

```bash
uv run gmp voices                          # 話者一覧
uv run gmp voice plan.json --speaker ずんだもん --style あまあま
uv run gmp build plan.json --voice         # voice + record + render
```

ENGINE の接続先は**グローバル設定**（`gmp config --set engine.voicevox.url=...`）で、
plan.json には書かない。書くと別のマシンで繋がらない接続先が残る
（`--url` は一時的な指定として扱い、`gmp voice` は plan.json に書き戻さない）。

## 合成

`voice` は plan.json の `voice` 設定を見て `say` を合成し、各ビートに
`audio` を書き戻す。**合成した音声の尺がそのままビートの尺になる**ので、
喋り終わる前に次の場面へ飛ぶことがない（`hold` は下限として働く）。

原稿も声の設定も変わっていないビートは再合成しない（`voice/manifest.json`
でハッシュ照合）。口調だけ変えたいときは `--speaker` を変えて `voice` →
`record` を回し直せばよく、`--force` で全部合成しなおせる。

## 読みの指定

TTS は文脈の薄い単語を誤読する。「語」は単独だと **カタリ** と読まれる
（「用語」「物語」は正しい）。ルビは振れないので、読みを設定に書く:

```toml
# <project>/gmp.toml —— 用語は動画をまたいで共通なのでここに置く
[voice.dict]
'語' = 'ゴ'
'冪等' = { pronunciation = 'ベキトウ', accent = 0 }
```

TOML の裸のキーは ASCII だけなので、日本語の表記は必ずクォートする。
plan.json に直接書くこともできる（`"voice": { "dict": { "語": "ゴ" } }`）。

合成の前だけエンジンのユーザー辞書へ入れ、終わったら消す（失敗しても消す）。
利用者が自分で登録済みの表記は触らない。複合語は長い一致が優先されるので、
「語」を足しても「物語」「用語」の読みは変わらない。

**録る前に読みを見る。**

```bash
uv run gmp kana plan.json --out kana.txt
```

全ビートの読みが出る。撮り終えてから誤読に気づくと撮り直しになるので、
原稿を書いた直後にこれを通す。`--out` はコンソールの文字化け回避。

## クレジット表記

VOICEVOX は生成音声を使った作品にキャラクター名を含むクレジットを求める。
`gmp voice` が話者名から `voice.credit` を自動で埋め、`gmp render` が音声を
乗せるときだけ右上に焼き込む（`--no-credit` で抑制）。
**正確な表記は音声ライブラリごとの利用規約で確認すること。** plan.json の
`voice.credit` を手で書けばそちらが優先される。
