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

from ..plan import Voice  # noqa: F401  (型注釈で使う)

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
        self.resolved_name: str | None = None  # クレジット表記に使う

    # --- HTTP --------------------------------------------------------
    def _request(self, path: str, params: dict[str, Any], body: bytes | None = None,
                 method: str = "POST") -> bytes:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Content-Type": "application/json"} if body else {}
        payload = body if body is not None else (b"" if method == "POST" else None)
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
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
        """voice.speaker / voice.style から話者IDを決める.

        あわせてクレジット表記用に話者名を控える。
        """
        want = self.voice.speaker
        speakers = self.speakers()

        # ID 直指定。一覧に無くても指定は尊重するが、名前は引けるなら引く
        if isinstance(want, int) or (isinstance(want, str) and want.isdigit()):
            sid = int(want)
            for sp in speakers:
                if any(int(st["id"]) == sid for st in sp.get("styles", [])):
                    self.resolved_name = sp.get("name")
                    break
            return sid

        name = ALIASES.get(str(want or "").lower(), want) or DEFAULT_SPEAKER
        style_want = self.voice.style

        for sp in speakers:
            if sp.get("name") != name:
                continue
            styles = sp.get("styles") or []
            if style_want:
                for st in styles:
                    if st.get("name") == style_want:
                        self.resolved_name = name
                        return int(st["id"])
                available = ", ".join(st.get("name", "") for st in styles)
                raise VoiceVoxError(
                    f"話者 {name!r} にスタイル {style_want!r} がありません (あるのは: {available})"
                )
            if styles:
                self.resolved_name = name
                return int(styles[0]["id"])

        known = ", ".join(sorted({sp.get("name", "") for sp in speakers}))
        raise VoiceVoxError(f"話者 {name!r} が見つかりません\n  利用可能: {known}")

    def credit(self) -> str:
        """作品に載せるクレジット表記.

        VOICEVOX は生成音声を使った作品にキャラクター名を含むクレジットを求める。
        正確な表記は音声ライブラリごとの利用規約で確認すること。
        """
        return f"VOICEVOX:{self.resolved_name}" if self.resolved_name else "VOICEVOX"

    # --- 読み --------------------------------------------------------
    def kana(self, text: str, speaker_id: int) -> str:
        """その文がどう読まれるかを返す (合成せずに確認できる)."""
        query = json.loads(self._request("/audio_query", {"text": text, "speaker": speaker_id}))
        return query.get("kana", "")

    def push_dict(self, entries: dict[str, Any]) -> list[str]:
        """読みをユーザー辞書へ一時的に入れる。戻り値は消すための uuid.

        既に同じ表記が入っていれば触らない (利用者が自分で登録したものを
        消さないため)。複合語は長い一致が優先されるので、"語" を足しても
        "物語" や "用語" の読みは変わらない。
        """
        if not entries:
            return []

        existing = {w.get("surface") for w in self.user_dict().values()}
        added: list[str] = []
        for surface, spec in entries.items():
            if surface in existing:
                continue
            if isinstance(spec, str):
                spec = {"pronunciation": spec}
            params = {
                "surface": surface,
                "pronunciation": spec["pronunciation"],
                "accent_type": int(spec.get("accent", 0)),
                "word_type": spec.get("type", "COMMON_NOUN"),
                "priority": int(spec.get("priority", 5)),
            }
            try:
                added.append(json.loads(self._request("/user_dict_word", params)))
            except VoiceVoxError as exc:
                raise VoiceVoxError(f"読みの登録に失敗しました ({surface}): {exc}") from exc
        return added

    def pop_dict(self, uuids: list[str]) -> None:
        """push_dict で入れたぶんだけ消す."""
        for uuid in uuids:
            try:
                self._request(f"/user_dict_word/{uuid}", {}, method="DELETE")
            except VoiceVoxError:
                pass  # 消せなくても合成そのものは終わっている

    def user_dict(self) -> dict[str, Any]:
        return json.loads(self._request("/user_dict", {}, method="GET"))

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
