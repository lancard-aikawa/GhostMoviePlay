"""timing.json から ASS 字幕を生成する.

焼き込みを ffmpeg 側でやるのは、口調や言語を変えたときに再収録せず
render だけやり直せるようにするため。
"""

from __future__ import annotations

from pathlib import Path

# 行送りを許可したい位置 (この直後で折り返す)
BREAK_AFTER = "、。！？!?,."
DEFAULT_FONT = "Yu Gothic UI"


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def wrap(text: str, limit: int) -> str:
    """日本語字幕向けの素朴な折り返し。既存の改行は尊重する."""
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            line += ch
            if len(line) >= limit and ch in BREAK_AFTER:
                out.append(line)
                line = ""
            elif len(line) >= limit + 6:
                out.append(line)
                line = ""
        if line:
            out.append(line)
    return "\\N".join(out)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def build_ass(
    timing: dict,
    font: str = DEFAULT_FONT,
    max_chars: int = 26,
    credit: bool = True,
) -> str:
    v = timing.get("video", {})
    width = int(v.get("width", 1280))
    height = int(v.get("height", 720))
    size = max(20, round(height * 0.061))
    margin_v = round(height * 0.055)
    margin_h = round(width * 0.06)
    credit_size = max(12, round(height * 0.028))

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,3.2,1.4,2,{margin_h},{margin_h},{margin_v},1
Style: Credit,{font},{credit_size},&H30FFFFFF,&H000000FF,&H60101010,&H00000000,0,0,0,0,100,100,0,0,1,2,0,9,{credit_size},{credit_size},{credit_size},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []

    # クレジットは右上に出しっぱなし。字幕(下部中央)とはぶつからない
    credit_text = (timing.get("credit") or "").strip()
    if credit and credit_text:
        duration = float(timing.get("duration") or 0.0)
        if duration > 0:
            lines.append(
                f"Dialogue: 0,{_ts(0)},{_ts(duration)},Credit,,0,0,0,,{_escape(credit_text)}"
            )
    for beat in timing.get("beats", []):
        caption = (beat.get("caption") or "").strip()
        if not caption:
            continue
        start = float(beat.get("start", 0.0))
        end = float(beat.get("end", start + 1.5))
        if end - start < 0.4:
            end = start + 0.4
        text = wrap(_escape(caption), max_chars)
        lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}"
        )

    return head + "\n".join(lines) + "\n"


def write_ass(
    timing: dict,
    path: str | Path,
    font: str = DEFAULT_FONT,
    max_chars: int = 26,
    credit: bool = True,
) -> Path:
    path = Path(path)
    path.write_text(
        build_ass(timing, font=font, max_chars=max_chars, credit=credit),
        encoding="utf-8",
    )
    return path
