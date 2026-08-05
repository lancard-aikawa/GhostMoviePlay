"""TTS: ビートの say を音声に変換する.

音声の尺がビートの尺を決めるので、合成は record より前に走らせる:

    gmp voice plan.json   -> voice/*.wav を作り plan.json に audio を書き戻す
    gmp record plan.json  -> その尺だけビートを保持する
    gmp render            -> adelay で並べて mix する

同じ原稿・同じ声の設定なら再合成しない (voice/manifest.json でハッシュ照合)。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ..plan import Plan, Voice


class TTSError(RuntimeError):
    pass


def _engine(voice: Voice):
    if voice.engine == "voicevox":
        from .voicevox import VoiceVox

        return VoiceVox(voice)
    raise TTSError(f"未知の TTS エンジン: {voice.engine!r} (使えるのは: voicevox)")


def _fingerprint(text: str, voice: Voice, speaker_id: int) -> str:
    payload = json.dumps(
        {"text": text, "speaker": speaker_id, **asdict(voice)},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def synthesize(plan: Plan, force: bool = False, verbose: bool = True) -> list[Path]:
    """plan の全ビートを音声化し、beat.audio に相対パスを入れる.

    戻り値は生成/再利用された wav のパス (say が空のビートは None を挟まず飛ばす)。
    """
    base = plan.source.parent if plan.source else Path.cwd()
    voice_dir = base / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = voice_dir / "manifest.json"
    manifest: dict[str, str] = {}
    if manifest_path.exists() and not force:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    engine = _engine(plan.voice)
    speaker_id = engine.resolve_speaker()
    if verbose:
        print(f"  engine  {plan.voice.engine} speaker={speaker_id} speed={plan.voice.speed}")

    written: list[Path] = []
    made = reused = 0

    for gi, (scene, beat) in enumerate(plan.beats):
        text = (beat.say or "").strip()
        if not text:
            beat.audio = None
            continue

        name = f"{gi:03d}_{scene.id}.wav"
        path = voice_dir / name
        finger = _fingerprint(text, plan.voice, speaker_id)

        if not force and path.exists() and manifest.get(name) == finger:
            reused += 1
        else:
            path.write_bytes(engine.synthesize(text, speaker_id))
            manifest[name] = finger
            made += 1
            if verbose:
                print(f"    {name}  {text[:34]}")

        beat.audio = f"voice/{name}"
        written.append(path)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if verbose:
        print(f"  合成 {made} / 再利用 {reused}  -> {voice_dir}")
    return written


def write_back(plan: Plan, path: Path | None = None) -> Path:
    """beat.audio を書き戻した plan.json を保存する."""
    target = Path(path) if path else plan.source
    if target is None:
        raise TTSError("書き戻し先の plan.json がわかりません")

    raw = json.loads(Path(plan.source).read_text(encoding="utf-8"))
    flat = [b for s in raw.get("scenes", []) for b in s.get("beats", [])]
    for beat_raw, (_, beat) in zip(flat, plan.beats):
        if beat.audio:
            beat_raw["audio"] = beat.audio
        else:
            beat_raw.pop("audio", None)
    raw["voice"] = {k: v for k, v in asdict(plan.voice).items() if v is not None}

    Path(target).write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Path(target)
