"""Android のキャプチャのうち、端末を繋がずに決まる部分.

実機が要る部分 (実際に撮る・録る) はここでは見ない。**面が capture.py と
揃っていること**は見る —— ずれると撮る画面がどちらか片方でしか動かなくなる。
"""

from __future__ import annotations

import struct

import pytest

from ghostmovieplay import capture, capture_android as android


def raw(width=4, height=3, fmt=1, header=16, pad=0):
    """screencap が返すもの (ヘッダ + 生画素)."""
    head = struct.pack("<IIII", width, height, fmt, 0)[:header]
    return head + b"\x7f" * (width * height * 4 + pad)


# --- 面 ---------------------------------------------------------------
def test_the_surface_matches_capture():
    """撮る画面が使う名前が両方にある (片方だけだと backend を差し替えられない)."""
    for name in ("CaptureError", "Recording", "duration", "even",
                 "find", "foreground", "shot", "supported", "windows"):
        assert hasattr(capture, name), name
        assert hasattr(android, name), name


def test_the_device_looks_like_a_window():
    """Device は Window と同じ属性名を持つ (撮る画面が同じコードで扱える)."""
    device = android.Device("SERIAL", "moto g05", "Android 15", 720, 1604)
    for name in ("handle", "title", "process", "width", "height", "label"):
        assert hasattr(device, name), name
    assert "moto g05" in device.label and "720x1604" in device.label


def test_the_error_type_is_shared():
    """例外が同じ型 (撮る画面の except が両方を捕まえる)."""
    assert android.CaptureError is capture.CaptureError


# --- adb のコマンドライン ------------------------------------------------
def test_a_serial_narrows_to_one_device():
    assert android._argv("shell", "true", serial="ZY32") == \
        ["adb", "-s", "ZY32", "shell", "true"]


def test_no_serial_leaves_adb_to_choose():
    assert android._argv("devices") == ["adb", "devices"]


# --- screencap の生データ ------------------------------------------------
def test_a_modern_header_is_16_bytes():
    """Android 9 以降は 幅・高さ・format・colorspace の 16 バイト."""
    width, height, pix_fmt, pixels = android._decode(raw())
    assert (width, height, pix_fmt) == (4, 3, "rgba")
    assert len(pixels) == 4 * 3 * 4


def test_an_older_header_is_12_bytes():
    """古い端末は colorspace が無い. **長さで見分ける**."""
    width, height, pix_fmt, pixels = android._decode(raw(header=12))
    assert (width, height, pix_fmt) == (4, 3, "rgba")
    assert len(pixels) == 4 * 3 * 4


def test_rgbx_is_read_without_alpha():
    """アルファを持たない形式は rgb0 で渡す (rgba だと透明になりうる)."""
    assert android._decode(raw(fmt=2))[2] == "rgb0"


def test_an_unknown_pixel_format_is_refused():
    """知らない形式を rgba のつもりで渡すと、色の壊れた画が黙って出来る."""
    with pytest.raises(android.CaptureError, match="画素形式"):
        android._decode(raw(fmt=99))


def test_a_truncated_capture_is_refused():
    """長さが合わなければ諦める (途中まで読めた画を出さない)."""
    with pytest.raises(android.CaptureError, match="長さ"):
        android._decode(raw(pad=7))


def test_an_empty_capture_is_refused():
    with pytest.raises(android.CaptureError):
        android._decode(b"")


# --- 端末を見つける ------------------------------------------------------
def fake_adb(monkeypatch, devices):
    """`_text` を差し替える. devices は "行" の並び."""
    def text(*args, serial=""):
        if args == ("devices",):
            return "List of devices attached\n" + "\n".join(devices)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 720x1604"
        if args[:2] == ("shell", "getprop"):
            return "moto g05" if args[2].endswith("model") else "15"
        return ""
    monkeypatch.setattr(android, "_text", text)
    monkeypatch.setattr(android, "supported", lambda: True)


def test_only_usable_devices_are_listed(monkeypatch):
    """`unauthorized` と `offline` は出さない —— 選ばせると必ず撮れない."""
    fake_adb(monkeypatch, ["AAA\tdevice", "BBB\tunauthorized", "CCC\toffline"])
    assert [d.handle for d in android.windows()] == ["AAA"]


def test_nothing_is_listed_without_adb(monkeypatch):
    monkeypatch.setattr(android, "supported", lambda: False)
    assert android.windows() == []


def test_find_matches_serial_or_model(monkeypatch):
    fake_adb(monkeypatch, ["ZY32MBLT69\tdevice"])
    assert android.find("ZY32").handle == "ZY32MBLT69"
    assert android.find("moto").handle == "ZY32MBLT69"
    assert android.find("ありえない名前") is None
    assert android.find("") is None


# --- 画面の大きさ --------------------------------------------------------
def test_the_override_size_wins(monkeypatch):
    """`wm size` を変えてある端末では、実際に映るのは Override のほう."""
    monkeypatch.setattr(android, "_text",
                        lambda *a, **k: "Physical size: 1080x2400\nOverride size: 720x1600")
    assert android._screen_size("X") == (720, 1600)


def test_a_missing_size_is_refused(monkeypatch):
    monkeypatch.setattr(android, "_text", lambda *a, **k: "")
    with pytest.raises(android.CaptureError, match="大きさ"):
        android._screen_size("X")


# --- 前面のウィンドウ ----------------------------------------------------
def test_there_is_no_foreground_window():
    """Android には「直前に触っていたウィンドウ」が無い.

    撮る画面は「空なら選び直さない」ので、ここが空であることで素通りする。
    """
    assert android.foreground() == ""
