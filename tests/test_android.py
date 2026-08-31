"""Android の駆動のうち、端末を繋がずに決まる部分.

実機が要る部分 (実際に押す) はここでは見ない。**セレクタの解釈**と
**ダンプの読み方**は端末に依らないので、ここで固定しておく。
"""

from __future__ import annotations

import pytest

from ghostmovieplay.android import (
    DriveError, Driver, Node, matches, parse, point_at,
)

# 実機 (moto g05 / a-lamo) から取ったダンプの形。**Flutter は text ではなく
# content-desc にラベルを載せる** —— 実測で 35 ノード中 text は 0 件だった
DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" bounds="[0,0][720,1604]" />
  <node index="1" class="android.widget.Button" content-desc="戻る"
        resource-id="" bounds="[14,84][84,154]" />
  <node index="2" class="android.view.View" content-desc="９月の全体連絡"
        bounds="[24,180][696,218]" />
  <node index="3" class="android.widget.Button" content-desc="コメントする"
        resource-id="com.lancard.a_lamo:id/send_comment" bounds="[440,960][680,1014]" />
  <node index="4" class="android.view.View" content-desc="発信者: &#10;東京６等"
        bounds="[24,320][284,348]" />
  <node index="5" class="android.view.View" text="ふつうの text" bounds="[0,0][0,0]" />
</hierarchy>"""


def nodes():
    return parse(DUMP)


# --- ダンプを読む -------------------------------------------------------
def test_nodes_are_read_without_an_xml_parser():
    """**XML パーサを持ち込まない** (defusedxml を足すほどの相手ではない)."""
    assert len(nodes()) == 5      # 6 個のうち、矩形の潰れた 1 個だけ落ちる


def test_a_flat_rectangle_is_dropped():
    """幅も高さも無いものは押せないので落とす."""
    assert not any(n.text == "ふつうの text" for n in nodes())


def test_escapes_are_undone():
    """`&#10;` のような実体参照が残ると、desc の一致が取れない."""
    hit = next(n for n in nodes() if n.desc.startswith("発信者"))
    assert "\n" in hit.desc and "&#10;" not in hit.desc


def test_the_centre_is_where_it_gets_tapped():
    hit = next(n for n in nodes() if n.desc == "戻る")
    assert hit.center == (49, 119)


def test_a_class_name_is_not_a_label():
    """見つからないときの案内が `android.view.View` の羅列になると役に立たない."""
    assert Node("android.view.View", "", "", "", 0, 0, 10, 10).label == ""


# --- セレクタ -----------------------------------------------------------
def test_desc_matches_exactly():
    hit = next(n for n in nodes() if n.desc == "戻る")
    assert matches(hit, "desc=戻る")
    assert not matches(hit, "desc=戻")


def test_desc_star_matches_a_part():
    hit = next(n for n in nodes() if n.desc.startswith("９月"))
    assert matches(hit, "desc*=全体連絡")


def test_id_matches_the_tail():
    """resource-id はパッケージ名つきで来るので、`:id/` の後ろで見る."""
    hit = next(n for n in nodes() if n.desc == "コメントする")
    assert matches(hit, "id=send_comment")


def test_a_selector_without_a_prefix_is_refused():
    """**推測しない。** 当たらなかったのか誤爆したのかが区別できなくなる."""
    with pytest.raises(DriveError, match="接頭辞"):
        matches(nodes()[0], "送信")


def test_an_unknown_prefix_is_refused():
    with pytest.raises(DriveError, match="知らないセレクタ"):
        matches(nodes()[0], "css=#send")


# --- 座標で直に指す -----------------------------------------------------
def test_a_point_is_kept_as_a_ratio():
    """**画素で焼かない。** 焼くと同じ台本が別の端末で違うところを押す."""
    assert point_at("at=0.5,0.5", 720, 1604) == (360, 802)


def test_other_selectors_are_not_points():
    assert point_at("desc=戻る", 720, 1604) is None


def test_a_point_outside_the_screen_is_refused():
    with pytest.raises(DriveError, match="0〜1"):
        point_at("at=1.5,0.5", 720, 1604)


def test_a_point_that_is_not_two_numbers_is_refused():
    with pytest.raises(DriveError, match="2 つの数"):
        point_at("at=まんなか", 720, 1604)


# --- 端末に触らずに Driver を試す ----------------------------------------
def driver(monkeypatch, dump=DUMP):
    d = Driver("SERIAL", (720, 1604))
    monkeypatch.setattr(d, "refresh", lambda: setattr(d, "_nodes", parse(dump)) or d._nodes)
    return d


def test_a_missing_target_says_what_was_on_screen(monkeypatch):
    """**何が見えていたかを出す。** 出さないと直しようがない."""
    d = driver(monkeypatch)
    with pytest.raises(DriveError) as exc:
        d.point("desc=ありえない")
    assert "戻る" in str(exc.value) and "コメントする" in str(exc.value)


def test_a_point_needs_no_dump(monkeypatch):
    """座標はツリーを読まずに使える (ダンプは 1 回 2.6 秒かかる)."""
    d = Driver("SERIAL", (720, 1604))
    monkeypatch.setattr(d, "refresh", lambda: pytest.fail("読んではいけない"))
    assert d.point("at=0.25,0.5") == (180, 802)


def test_the_command_line_targets_one_device():
    d = Driver("ZY32", (720, 1604))
    assert d.argv("shell", "input", "tap") == ["adb", "-s", "ZY32", "shell", "input", "tap"]
