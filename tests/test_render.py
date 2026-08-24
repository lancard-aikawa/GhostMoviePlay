"""Pass3 が ffmpeg に渡すもの.

render.py はほぼ全部が「引数の組み立て」なので、ffmpeg を起こさずに
組み上がったコマンドを見れば中身は検査できる。**順番と相対パスに
不変条件がある**ところなので、ここが空だと黙って壊れる。
"""

import json

import pytest

from ghostmovieplay import ffmpeg, render


@pytest.fixture
def outdir(tmp_path):
    """収録が済んだ状態の出力ディレクトリ."""
    (tmp_path / "raw.webm").write_bytes(b"")
    voice = tmp_path / "voice"
    voice.mkdir()
    for name in ("000.wav", "001.wav"):
        (voice / name).write_bytes(b"")
    timing = {
        "title": "テスト動画",
        "credit": "VOICEVOX:ずんだもん",
        "video": {"width": 1280, "height": 720, "fps": 30},
        "source_video": "raw.webm",
        "duration": 12.0,
        "beats": [
            # timing.json の audio は**絶対パス** (timing は出力先、plan は
            # プロジェクトにあって階層が違うため)
            {"caption": "ひとつめ", "start": 1.0, "end": 3.0,
             "audio": str(voice / "000.wav")},
            {"caption": "ふたつめ", "start": 3.0, "end": 6.0,
             "audio": str(voice / "001.wav")},
        ],
    }
    (tmp_path / "timing.json").write_text(json.dumps(timing, ensure_ascii=False),
                                          encoding="utf-8")
    return tmp_path


@pytest.fixture
def spy(monkeypatch):
    """ffmpeg を起こさずに、渡された引数と作業ディレクトリを捕まえる."""
    seen = {}

    def fake_run(args, cwd=None, quiet=True):
        seen["args"] = list(args)
        seen["cwd"] = cwd

    monkeypatch.setattr(ffmpeg, "run", fake_run)
    return seen


def filters(seen) -> str:
    """-vf か -filter_complex の中身 (音声の有無で入れ物が変わる)."""
    args = seen["args"]
    for flag in ("-vf", "-filter_complex"):
        if flag in args:
            return args[args.index(flag) + 1]
    raise AssertionError(f"フィルタが無い: {args}")


# --- 順番 -------------------------------------------------------------
def test_the_video_is_made_cfr_before_subtitles_are_burned(outdir, spy):
    """**この順番は入れ替えられない。**

    Playwright の webm はフレーム間隔が可変なので、先に fps=N を通さないと
    字幕がズレる。
    """
    render.render(outdir / "timing.json")

    chain = filters(spy)
    assert "fps=30" in chain
    assert chain.index("fps=30") < chain.index("subtitles=")


# --- パス -------------------------------------------------------------
def test_subtitles_are_passed_as_a_relative_name(outdir, spy):
    """字幕フィルタに Windows の絶対パス (C:\\... のコロン) を渡すと壊れる.

    outdir を cwd にして相対名で渡すことで避けている。**絶対パスに
    変えないこと。**
    """
    render.render(outdir / "timing.json")

    assert "subtitles=subs.ass" in filters(spy)
    assert spy["cwd"] == outdir


def test_a_missing_recording_is_reported_not_handed_to_ffmpeg(outdir, spy):
    (outdir / "raw.webm").unlink()
    with pytest.raises(FileNotFoundError):
        render.render(outdir / "timing.json")
    assert not spy


# --- 音声 -------------------------------------------------------------
def test_each_beat_is_delayed_to_its_own_start(outdir, spy):
    result = render.render(outdir / "timing.json")

    chain = filters(spy)
    assert "adelay=1000|1000" in chain      # 1.0 秒のビート
    assert "adelay=3000|3000" in chain
    assert "amix=inputs=2" in chain
    # 音声が動画より短いと最後のフレームで切れるので詰める
    assert "apad" in chain
    assert "-shortest" in spy["args"]
    assert result.audio_tracks == 2


def test_a_wav_that_is_not_there_is_skipped(outdir, spy):
    (outdir / "voice" / "001.wav").unlink()
    result = render.render(outdir / "timing.json")

    chain = filters(spy)
    assert result.audio_tracks == 1
    assert "adelay=1000|1000" in chain
    assert "adelay=3000|3000" not in chain   # 消えたほうは入力にしない


def test_without_audio_the_video_track_is_silent(outdir, spy):
    render.render(outdir / "timing.json", with_audio=False)

    assert "-an" in spy["args"]
    assert "adelay" not in filters(spy)


# --- クレジット -------------------------------------------------------
def test_audio_brings_the_credit_with_it(outdir, spy):
    """**音声を乗せたらクレジットも焼く。** 落とせる経路を作らない."""
    result = render.render(outdir / "timing.json")
    assert "VOICEVOX" in result.subtitles.read_text(encoding="utf-8")


def test_no_audio_means_no_credit(outdir, spy):
    result = render.render(outdir / "timing.json", with_audio=False)
    assert "VOICEVOX" not in result.subtitles.read_text(encoding="utf-8")


# --- 字幕を焼かない ---------------------------------------------------
def test_subtitles_can_be_left_off_but_the_cfr_pass_stays(outdir, spy):
    render.render(outdir / "timing.json", burn_subtitles=False)

    chain = filters(spy)
    assert "subtitles=" not in chain
    assert "fps=30" in chain
