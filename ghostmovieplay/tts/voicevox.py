"""VOICEVOX ENGINE クライアント.

ローカルで動く VOICEVOX ENGINE の HTTP API を叩く。
依存を増やしたくないので urllib を直接使っている (相手は localhost)。

  POST /audio_query?text=...&speaker=N  -> 合成クエリ(JSON)
  POST /synthesis?speaker=N   body=query -> wav
  GET  /speakers                         -> 話者一覧
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..plan import Voice

# よく使う話者のローマ字別名。engine の一覧に無ければこれで引き直す
ALIASES = {
    "zundamon": "ずんだもん",
    "metan": "四国めたん",
    "tsumugi": "春日部つむぎ",
    "ritsu": "波音リツ",
    "hau": "雨晴はう",
    "takehiro": "玄野武宏",
    "kotarou": "白上虎太郎",
    "ryuusei": "青山龍星",
    "himari": "冥鳴ひまり",
    "sora": "九州そら",
    "mochiko": "もち子さん",
    "kenzaki": "剣崎雌雄",
}

DEFAULT_SPEAKER = "ずんだもん"


class VoiceVoxError(RuntimeError):
    pass


class VoiceVox:
    def __init__(self, voice: Voice):
        self.voice = voice
        self.base = voice.url.rstrip("/")

    # --- HTTP --------------------------------------------------------
    def _request(self, path: str, params: dict[str, Any], body: bytes | None = None,
                 method: str = "POST") -> bytes:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Content-Type": "application/json"} if body else {}
        req = urllib.request.Request(url, data=body if body is not None else (b"" if method == "POST" else None),
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return res.read()
        except urllib.error.URLError as exc:
            raise VoiceVoxError(
                f"VOICEVOX ENGINE に繋がりません ({self.base}): {exc}\n"
                "  VOICEVOX を起動するか、engine を単体で立ち上げてください。\n"
                "  plan.json の voice.url で接続先を変えられます。"
            ) from exc

    # --- 話者 --------------------------------------------------------
    def speakers(self) -> list[dict[str, Any]]:
        return json.loads(self._request("/speakers", {}, method="GET"))

    def resolve_speaker(self) -> int:
        """voice.speaker / voice.style から話者IDを決める."""
        want = self.voice.speaker
        if isinstance(want, int):
            return want
        if isinstance(want, str) and want.isdigit():
            return int(want)

        name = ALIASES.get(str(want or "").lower(), want) or DEFAULT_SPEAKER
        style_want = self.voice.style

        speakers = self.speakers()
        for sp in speakers:
            if sp.get("name") != name:
                continue
            styles = sp.get("styles") or []
            if style_want:
                for st in styles:
                    if st.get("name") == style_want:
                        return int(st["id"])
                available = ", ".join(st.get("name", "") for st in styles)
                raise VoiceVoxError(
                    f"話者 {name!r} にスタイル {style_want!r} がありません (あるのは: {available})"
                )
            if styles:
                return int(styles[0]["id"])

        known = ", ".join(sorted({sp.get("name", "") for sp in speakers}))
        raise VoiceVoxError(f"話者 {name!r} が見つかりません\n  利用可能: {known}")

    # --- 合成 --------------------------------------------------------
    def synthesize(self, text: str, speaker_id: int) -> bytes:
        query = json.loads(self._request("/audio_query", {"text": text, "speaker": speaker_id}))

        v = self.voice
        query["speedScale"] = v.speed
        query["pitchScale"] = v.pitch
        query["intonationScale"] = v.intonation
        query["volumeScale"] = v.volume
        query["prePhonemeLength"] = v.pre
        query["postPhonemeLength"] = v.post

        return self._request(
            "/synthesis",
            {"speaker": speaker_id},
            body=json.dumps(query, ensure_ascii=False).encode("utf-8"),
        )
