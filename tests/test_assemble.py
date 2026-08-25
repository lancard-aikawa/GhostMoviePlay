"""支援収録の Pass2 が ffmpeg に渡すものと、書き出す timing.json.

`render` は timing.json と `source_video` だけを見て動くので、**自動収録と
同じ形を出せているか**がここの検査すべて。形が崩れると、字幕もクレジットも
黙って落ちる。
"""

from __future__ import annotations

import json

import pytest

from ghostmovieplay import assemble as mod
from ghostmovieplay.plan import AUDIO_TAIL, Beat, Plan, Scene, Video


@pytest.fixture
def spy(monkeypatch):
    """ffmpeg を起こさずに、渡された引数と作業ディレクトリを捕まえる."""
    calls: list[tuple[list[str], object]] = []

    def fake_run(args, cwd=None, quiet=True):
        calls.append((list(args), cwd))
        # concat の出力だけは実体を作る (呼び側が存在を見る)
        out = args[-1]
        if str(out).endswith((".mp4", ".png")):
            from pathlib import Path

            path = Path(cwd) / out if cwd else Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")

    monkeypatch.setattr(mod.ffmpeg, "run", fake_run)
    monkeypatch.setattr(mod.ffmpeg, "probe_duration", lambda path: None)
    monkeypatch.setattr(mod, "_size_of", lambda path: None)
    return calls


def make_plan(beats, **video):
    return Plan(
        title="テスト動画",
        video=Video(width=800, height=600, fps=30, leader=0.0, trailer=0.0, **video),
        scenes=[Scene(id="intro", title="はじめ", beats=beats)],
    )


def shot(outdir, name="0001-intro.png"):
    path = outdir / "shots" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return f"shots/{name}"


def timing_of(outdir):
    return json.loads((outdir / "timing.json").read_text(encoding="utf-8"))


def filters(calls):
    """呼び出しごとの -vf の中身."""
    out = []
    for args, _cwd in calls:
        if "-vf" in args:
            out.append(args[args.index("-vf") + 1])
    return out


# --- render に渡す形 ---------------------------------------------------
def test_timing_has_the_shape_render_reads(tmp_path, spy):
    plan = make_plan([Beat(say="ひとこと", hold=2.0, shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)

    timing = timing_of(tmp_path)
    assert timing["source_video"] == "raw.mp4"
    assert timing["video"] == {"width": 800, "height": 600, "fps": 30}
    assert timing["sync_skew"] == 0.0
    beat = timing["beats"][0]
    assert beat["scene"] == "intro"
    assert beat["index"] == 0
    assert beat["caption"] == "ひとこと"
    assert beat["start"] == 0.0
    assert beat["end"] == pytest.approx(2.0)


def test_source_video_is_mp4_not_webm(tmp_path, spy):
    """撮る面が `source_video` を見て「再生」を出すので、名前を決め打ちしない."""
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    result = mod.assemble(plan, tmp_path, verbose=False)
    assert result.video.name == "raw.mp4"
    assert timing_of(tmp_path)["source_video"] == result.video.name


def test_credit_only_when_audio_is_used(tmp_path, spy):
    """**音声を乗せたらクレジットも焼く。** 音が無いときだけ落とす."""
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    plan.voice.credit = "VOICEVOX:ずんだもん"
    mod.assemble(plan, tmp_path, verbose=False)
    assert timing_of(tmp_path)["credit"] is None

    wav = tmp_path / "voice" / "000.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"")
    plan.scenes[0].beats[0].audio = "voice/000.wav"
    mod.assemble(plan, tmp_path, verbose=False)
    assert timing_of(tmp_path)["credit"] == "VOICEVOX:ずんだもん"


def test_audio_path_is_absolute(tmp_path, spy):
    """timing.json の audio は**絶対パス** (timing と plan で階層が違う)."""
    wav = tmp_path / "voice" / "000.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"")
    plan = make_plan([Beat(say="a", hold=1.0, audio="voice/000.wav",
                           shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    from pathlib import Path

    assert Path(timing_of(tmp_path)["beats"][0]["audio"]).is_absolute()


# --- 尺の決まり方 ------------------------------------------------------
def test_audio_length_wins_over_hold(tmp_path, spy, monkeypatch):
    monkeypatch.setattr(mod, "wav_seconds", lambda path: 4.0)
    wav = tmp_path / "voice" / "000.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"")
    plan = make_plan([Beat(say="a", hold=1.0, audio="voice/000.wav",
                           shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    assert timing_of(tmp_path)["beats"][0]["end"] == pytest.approx(4.0 + AUDIO_TAIL)


def test_clip_longer_than_audio_is_not_cut(tmp_path, spy, monkeypatch):
    """**縮めない。** 人が 8 秒かけて操作したものを 3 秒の原稿に合わせて切ると、
    操作の途中で切れる.
    """
    monkeypatch.setattr(mod.ffmpeg, "probe_duration", lambda path: 8.0)
    monkeypatch.setattr(mod, "wav_seconds", lambda path: 1.0)
    wav = tmp_path / "voice" / "000.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"")
    plan = make_plan([Beat(say="a", audio="voice/000.wav",
                           shot=shot(tmp_path, "0001-intro.mp4"))])
    mod.assemble(plan, tmp_path, verbose=False)
    assert timing_of(tmp_path)["beats"][0]["end"] == pytest.approx(8.0)


def test_short_clip_is_padded_with_the_last_frame(tmp_path, spy, monkeypatch):
    """原稿のほうが長いときは静止で埋める (**順番の不変条件がここだけ裏返る**)."""
    monkeypatch.setattr(mod.ffmpeg, "probe_duration", lambda path: 2.0)
    monkeypatch.setattr(mod, "wav_seconds", lambda path: 5.0)
    wav = tmp_path / "voice" / "000.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"")
    plan = make_plan([Beat(say="a", audio="voice/000.wav",
                           shot=shot(tmp_path, "0001-intro.mp4"))])
    mod.assemble(plan, tmp_path, verbose=False)
    padded = [f for f in filters(spy) if "tpad" in f]
    assert padded, "足りない分が静止で埋まっていない"
    assert "stop_mode=clone" in padded[0]


def test_beat_never_has_zero_length(tmp_path, spy):
    """尺 0 のセグメントは concat が受け付けない."""
    plan = make_plan([Beat(say="", shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    beat = timing_of(tmp_path)["beats"][0]
    assert beat["end"] - beat["start"] >= mod.MIN_SECONDS


# --- 止めない失敗 ------------------------------------------------------
def test_missing_shot_does_not_stop_the_build(tmp_path, spy):
    """**撮り忘れた 1 ビートのために、撮れている 20 ビートを捨てさせない。**"""
    plan = make_plan([Beat(say="撮った", hold=1.0, shot=shot(tmp_path)),
                      Beat(say="撮っていない", hold=1.0)])
    result = mod.assemble(plan, tmp_path, verbose=False)
    kinds = [w["kind"] for w in result.warnings]
    assert kinds == ["shot_missing"]
    assert result.warnings[0]["where"] == "intro#1"
    assert len(timing_of(tmp_path)["beats"]) == 2


def test_warnings_reach_timing_json(tmp_path, spy):
    """撮る面と `--strict` が見るのは timing.json のほう."""
    plan = make_plan([Beat(say="a", hold=1.0)])
    mod.assemble(plan, tmp_path, verbose=False)
    assert timing_of(tmp_path)["warnings"][0]["kind"] == "shot_missing"


def test_size_mismatch_is_a_warning_not_a_failure(tmp_path, spy, monkeypatch):
    """窓の大きさを途中で変えても組み立てはできる (黒帯で埋める). 黙らない."""
    monkeypatch.setattr(mod, "_size_of", lambda path: (640, 480))
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    result = mod.assemble(plan, tmp_path, verbose=False)
    assert [w["kind"] for w in result.warnings] == ["shot_size"]
    assert "640x480" in result.warnings[0]["message"]


def test_matching_size_is_not_reported(tmp_path, spy, monkeypatch):
    """**当たっているときに出さない** —— 件数が信用されなくなる."""
    monkeypatch.setattr(mod, "_size_of", lambda path: (800, 600))
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    assert mod.assemble(plan, tmp_path, verbose=False).warnings == []


# --- つなぎ方 ----------------------------------------------------------
def test_concat_list_uses_bare_names(tmp_path, spy, monkeypatch):
    """**リストの中の相対パスは「リストのある場所」が基準** (cwd ではない).

    ここに `assemble/` を足すと `assemble/assemble/…` を探しに行く。
    """
    # 中間ファイルは普段消える。読みたいので、この 1 件だけ残させる
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *a, **k: None)
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)

    listing = (tmp_path / mod.WORK_DIR / "concat.txt").read_text(encoding="utf-8")
    assert listing.strip(), "concat のリストが空"
    for line in listing.splitlines():
        assert line.startswith("file '"), line
        assert mod.WORK_DIR not in line


def test_concat_runs_in_the_output_directory(tmp_path, spy):
    """**cwd を出力ディレクトリにして相対名で渡す** (Windows の絶対パスの
    コロンが concat のリストでも壊れる).
    """
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    concat = [(args, cwd) for args, cwd in spy if "concat" in args]
    assert concat, "concat が呼ばれていない"
    args, cwd = concat[0]
    assert cwd == tmp_path
    assert args[-1] == "raw.mp4"


def test_work_directory_is_cleaned_up(tmp_path, spy):
    """中間ファイルを残さない (素材と同じ場所に同じ画が二重に貯まる)."""
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    assert not (tmp_path / mod.WORK_DIR).exists()


def test_leader_and_trailer_add_segments(tmp_path, spy):
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    plan.video.leader, plan.video.trailer = 2.5, 1.2
    mod.assemble(plan, tmp_path, verbose=False)
    timing = timing_of(tmp_path)
    # 冒頭の余白のぶん、最初のビートは 0 から始まらない
    assert timing["beats"][0]["start"] == pytest.approx(2.5)
    assert timing["wall_duration"] == pytest.approx(2.5 + 1.0 + 1.2)


def test_every_segment_is_normalised_to_the_video_size(tmp_path, spy):
    """大きさを揃えないと concat が繋げない."""
    plan = make_plan([Beat(say="a", hold=1.0, shot=shot(tmp_path))])
    mod.assemble(plan, tmp_path, verbose=False)
    assert all("scale=800:600" in chain for chain in filters(spy))


def test_no_beats_is_an_error(tmp_path, spy):
    plan = Plan(title="から", scenes=[])
    with pytest.raises(ValueError, match="ビート"):
        mod.assemble(plan, tmp_path, verbose=False)


def test_duplicate_beats_keep_their_own_index(tmp_path, spy):
    """**同じ内容のビートが 2 つ並んでも添字を取り違えない** ——
    say が空のビートは実際に並ぶ (撮る前は全部空).
    """
    plan = make_plan([Beat(say=""), Beat(say=""), Beat(say="")])
    mod.assemble(plan, tmp_path, verbose=False)
    assert [b["index"] for b in timing_of(tmp_path)["beats"]] == [0, 1, 2]


# --- 本物の ffmpeg を通す ----------------------------------------------
@pytest.mark.slow
def test_end_to_end_produces_a_playable_video(tmp_path):
    """**偽の ffmpeg では引数が有効かどうか分からない。** 実際に組み立てる.

    ここが通れば「素材 -> raw.mp4 -> render -> output.mp4」の鎖が繋がっている。
    """
    import shutil as sh

    from ghostmovieplay import ffmpeg as real
    from ghostmovieplay.render import render

    if not sh.which("ffmpeg") or not sh.which("ffprobe"):
        pytest.skip("ffmpeg / ffprobe が無い")

    shots = tmp_path / "shots"
    shots.mkdir()
    still = shots / "0001-intro.png"
    real.run(["-f", "lavfi", "-i", "color=c=navy:s=400x300", "-frames:v", "1",
              str(still)])
    clip = shots / "0002-intro.mp4"
    real.run(["-f", "lavfi", "-i", "color=c=green:s=400x300:r=30", "-t", "1.0",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])

    plan = make_plan([
        Beat(say="静止画のビート", hold=2.0, shot="shots/0001-intro.png"),
        # 素材 (1秒) より hold (3秒) が長い -> 最後のフレームで埋まる
        Beat(say="動画のビート", hold=3.0, shot="shots/0002-intro.mp4"),
        Beat(say="撮り忘れたビート", hold=1.0),
    ])
    plan.video.leader, plan.video.trailer = 1.0, 0.5
    # 素材と同じ大きさにしておく (ズレの検査は上の速いテストの担当)
    plan.video.width, plan.video.height = 400, 300

    result = mod.assemble(plan, tmp_path, verbose=False)
    assert result.video.is_file()
    assert [w["kind"] for w in result.warnings] == ["shot_missing"]

    # 1.0 (冒頭) + 2.0 + 3.0 + 1.0 + 0.5 (末尾) = 7.5 秒
    measured = real.probe_duration(result.video)
    assert measured == pytest.approx(7.5, abs=0.4)

    # **render が 1 行も変わらずに読めること**が支援収録の前提
    rendered = render(result.timing, burn_subtitles=True, with_audio=False)
    assert rendered.video.is_file()
    assert real.probe_duration(rendered.video) == pytest.approx(7.5, abs=0.4)
