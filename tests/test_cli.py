"""段のつなぎ目 (`gmp build`) と、置き場所を見せる口 (`gmp where`).

`build` は voice → record → render を順に呼ぶだけの薄い段だが、**順番と
「落ちたら次へ行かない」はここにしか無い**。どちらも壊すと、音声の無い
動画や、前回の収録から作った mp4 が黙って出てくる。
"""

import json

import pytest

from ghostmovieplay import record as record_module
from ghostmovieplay import render as render_module
from ghostmovieplay.cli import main
from ghostmovieplay.record import Recorded

PLAN = {
    "meta": {"title": "テスト動画", "project": "proj"},
    "app": {"url": "http://127.0.0.1:8000/"},
    "scenes": [{"id": "s1", "beats": [{"say": "ひとつめ"}]}],
}


@pytest.fixture
def plan_file(tmp_path):
    target = tmp_path / "plan.json"
    target.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
    return target


@pytest.fixture
def stages(monkeypatch, tmp_path):
    """voice / record / render を呼んだ順に記録する (実物は起こさない)."""
    from types import SimpleNamespace

    from ghostmovieplay import cli

    called: list[str] = []
    seen: dict = {}

    def fake_voice(args):
        called.append("voice")
        return 0

    def fake_record(plan, outdir, **kwargs):
        called.append("record")
        seen["outdir"] = outdir
        # 本物と同じく timing.json を置く (render はそれを見て段が進む)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "timing.json").write_text("{}", encoding="utf-8")
        return Recorded(video=outdir / "raw.webm", timing=outdir / "timing.json",
                        duration=10.0, skew=0.0)

    def fake_render(timing, **kwargs):
        called.append("render")
        seen["timing"] = timing
        seen["render_out"] = kwargs.get("out")
        return SimpleNamespace(video=tmp_path / "output.mp4", subtitles=None,
                               audio_tracks=0)

    monkeypatch.setattr(cli, "cmd_voice", fake_voice)
    monkeypatch.setattr(record_module, "record", fake_record)
    monkeypatch.setattr(render_module, "render", fake_render)
    return SimpleNamespace(called=called, seen=seen)


# --- 段のつなぎ目 -----------------------------------------------------
def test_build_runs_the_stages_in_the_only_order_that_works(plan_file, stages, tmp_path):
    """**音声の尺がビートの尺を決める。** 先に撮ると必ず尻切れになる."""
    out = tmp_path / "out"
    assert main(["build", str(plan_file), "--voice", "--out", str(out)]) == 0
    assert stages.called == ["voice", "record", "render"]


def test_build_without_voice_skips_only_that_stage(plan_file, stages, tmp_path):
    assert main(["build", str(plan_file), "--out", str(tmp_path / "out")]) == 0
    assert stages.called == ["record", "render"]


def test_a_failed_voice_stops_before_recording(plan_file, stages, monkeypatch, tmp_path):
    """合成が落ちたまま撮ると、尺の決まっていない動画が出来てしまう."""
    from ghostmovieplay import cli

    monkeypatch.setattr(cli, "cmd_voice", lambda args: 1)
    assert main(["build", str(plan_file), "--voice", "--out", str(tmp_path / "out")]) == 1
    assert stages.called == []


def test_strict_stops_before_the_video_is_made(plan_file, stages, monkeypatch, tmp_path):
    """--strict で赤にした収録から mp4 を作らない (通ったように見えてしまう)."""
    def warned(plan, outdir, **kwargs):
        stages.called.append("record")
        return Recorded(video=outdir / "raw.webm", timing=outdir / "timing.json",
                        duration=10.0, skew=0.0,
                        warnings=[{"kind": "highlight_missing", "where": "s1#0",
                                   "message": "光らせる相手が見つかりません"}])

    monkeypatch.setattr(record_module, "record", warned)
    assert main(["build", str(plan_file), "--out", str(tmp_path / "out"), "--strict"]) == 1
    assert stages.called == ["record"]


def test_the_out_of_build_is_a_directory_not_a_filename(plan_file, stages, tmp_path):
    """`--out` は収録の出力先。**render の --out (成果物のファイル名) に流用しない。**"""
    out = tmp_path / "somewhere"
    assert main(["build", str(plan_file), "--out", str(out)]) == 0

    assert stages.seen["outdir"] == out
    assert stages.seen["timing"] == out / "timing.json"
    assert stages.seen["render_out"] is None      # 既定の out/output.mp4 に出す


# --- 置き場所 ---------------------------------------------------------
def test_where_shows_the_same_outdir_the_stages_use(plan_file, capsys, isolate_output_home):
    """暗黙の置き場所を持つ道具なので、**どこに出るかを言える口**が要る."""
    assert main(["where", str(plan_file)]) == 0

    out = capsys.readouterr().out
    assert str(isolate_output_home / "proj") in out
    assert "output.mp4" in out


def test_where_on_a_broken_plan_says_why(tmp_path, capsys):
    broken = tmp_path / "plan.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert main(["where", str(broken)]) == 1


# --- render に渡すもの ---------------------------------------------------
def test_render_says_which_file_it_wants(plan_file, capsys):
    """**台本を渡したら timing.json を教える。**

    黙って台本の隣を探すと `raw.webm が見つかりません` としか出ず、渡すものが
    違うことに気づけない (実際に踏んだ。支援収録と Android が出すのは raw.mp4
    なので、ファイル名まで違う)。
    """
    assert main(["render", str(plan_file)]) == 1
    err = capsys.readouterr().err
    assert "timing.json" in err and "plan.json ではありません" in err
    assert "gmp record" in err or "gmp render" in err     # 次の一手を出す
