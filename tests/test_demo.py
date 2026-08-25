"""使い捨ての試し場 (`gmp demo`).

テストが緑でも画面の手触りは分からないので、**人が見る場所**が要る。本物
(docs/video/intro) で試すと紹介動画の素材に差分が出るし 100 秒待つので、
捨てられる場所に 10 秒の 1 本を作る。

ここが見るのは「組み立てたものが本当に通るか」——**撮る前に分かることは
全部この段で赤くしておく**（撮ってから気づくと 20 秒無駄になる）。
"""

import json

import pytest

from ghostmovieplay import check, demo
from ghostmovieplay import record as record_module
from ghostmovieplay.cli import main
from ghostmovieplay.plan import load


@pytest.fixture
def built(tmp_path):
    spec = demo.build(tmp_path, port=8791, verbose=False)
    return spec


def test_everything_the_steps_need_is_there(built, tmp_path):
    """手順書の入口 (収録対象・設定・構成・台本) が揃っていること."""
    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "gmp.toml").is_file()
    assert built.name == "video.md"
    assert (built.parent / "plan.json").is_file()


def test_the_built_plan_is_clean(built):
    """**撮る前に分かる欠陥は 1 つも無いこと。**

    見本が `gmp check --dry` で赤いようでは、試し場として使えない
    (機械依存の焼き込み・長すぎる字幕)。
    """
    plan_path = built.parent / "plan.json"
    assert check.inspect(plan_path, load(plan_path)) == ()


def test_the_project_and_the_plan_agree(built, tmp_path):
    """gmp.toml の収録対象と、台本に焼いた値が食い違わないこと."""
    from ghostmovieplay import settings

    resolved = settings.load(spec=built)
    plan = load(built.parent / "plan.json")
    assert resolved.get("app.url") == plan.app.url == "http://127.0.0.1:8791/"
    assert "8791" in resolved.get("app.start")


def test_the_beats_are_short_enough_to_wait_for(built):
    """待たされる試し場は使われない (10 秒ほどで終わること)."""
    from ghostmovieplay.plan import estimate

    seconds, measured = estimate(load(built.parent / "plan.json"))
    assert not measured          # 音声はまだ無い
    assert seconds < 15


def test_every_beat_changes_the_picture(built):
    """**サムネイルが全部同じでは確かめたことにならない。**

    ビートごとに actions を持たせて、絵が変わるようにしてある。
    """
    plan = load(built.parent / "plan.json")
    for _, beat in plan.beats:
        assert beat.actions, "画の変わらないビートがある"


def test_building_again_starts_from_the_same_state(tmp_path):
    """毎回同じ初期状態から始められるのが試し場の値打ち."""
    spec = demo.build(tmp_path, port=8791, verbose=False)
    (spec.parent / "plan.json").write_text("{ こわした", encoding="utf-8")

    demo.build(tmp_path, port=8791, verbose=False)
    assert load(spec.parent / "plan.json").title == "試し撮り"


def test_the_port_is_taken_fresh(tmp_path):
    """固定ポートだと、前の試し撮りのサーバが残っていると当たる."""
    assert demo.free_port() > 0


# --- CLI --------------------------------------------------------------
def test_build_only_does_not_record(tmp_path, monkeypatch, capsys):
    def never(*a, **k):
        raise AssertionError("--build-only は撮らない")

    monkeypatch.setattr(record_module, "record", never)
    assert main(["demo", str(tmp_path), "--build-only"]) == 0
    assert "gmp ui" in capsys.readouterr().out      # 次にやることを出す


def test_the_built_project_passes_the_dry_check(tmp_path, monkeypatch):
    """組み立てたものが、そのまま `gmp check --dry` で緑になること."""
    monkeypatch.setattr(record_module, "record",
                        lambda *a, **k: pytest.fail("--dry は撮らない"))
    assert main(["demo", str(tmp_path), "--build-only"]) == 0
    assert main(["check", str(tmp_path), "--dry"]) == 0


def test_the_steps_are_the_documented_commands(tmp_path, monkeypatch, capsys):
    """**手順書と同じコマンドを叩く。** 中で関数を呼ぶと手順の腐りに気づけない."""
    from types import SimpleNamespace

    from ghostmovieplay import render as render_module
    from ghostmovieplay.record import Recorded

    def fake_record(plan, outdir, **kwargs):
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "timing.json").write_text("{}", encoding="utf-8")
        return Recorded(video=outdir / "raw.webm", timing=outdir / "timing.json",
                        duration=9.0, skew=0.0)

    monkeypatch.setattr(record_module, "record", fake_record)
    monkeypatch.setattr(render_module, "render", lambda timing, **kw: SimpleNamespace(
        video=tmp_path / "output.mp4", subtitles=None, audio_tracks=0))

    assert main(["demo", str(tmp_path), "--no-open"]) == 0
    out = capsys.readouterr().out
    assert "$ gmp record" in out
    assert "$ gmp render" in out


def test_the_demo_writes_a_plan_a_person_can_read(built):
    """台本は git に入る形と同じ書式で置く (人が読んで直せること)."""
    raw = (built.parent / "plan.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), ensure_ascii=False, indent=2) + "\n"
