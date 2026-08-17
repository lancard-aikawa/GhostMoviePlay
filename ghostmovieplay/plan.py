"""plan.json のスキーマ定義・読み込み・検証.

plan.json は Pass1 (AI) の成果物であり Pass2 (収録) の入力。
人間が手で読んで直せることを最優先に、素直な構造にしてある。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLAN_VERSION = 1

# actions[].type で使える操作と、必須キー
ACTION_SPECS: dict[str, tuple[str, ...]] = {
    "goto": ("url",),
    "click": ("selector",),
    "dblclick": ("selector",),
    "hover": ("selector",),
    "type": ("selector", "text"),
    "press": ("key",),
    "select": ("selector", "value"),
    "scroll_to": ("selector",),
    "select_text": ("text",),
    "highlight": ("selector",),
    "wait_for": (),  # selector か seconds のどちらか
    "sleep": ("seconds",),
    "eval": ("expr",),
}


class PlanError(ValueError):
    """plan.json が壊れている."""


@dataclass
class Beat:
    """1 ビート = 1 字幕 + それに紐づく操作列.

    動画の最小単位。字幕はビートの開始から終了まで出しっぱなしになる。
    """

    say: str = ""
    subtitle: str | None = None  # 省略時は say をそのまま字幕に使う
    hold: float = 0.0  # 操作が終わったあとの最低保持秒数
    actions: list[dict[str, Any]] = field(default_factory=list)
    audio: str | None = None  # TTS wav への相対パス (Pass2 で尺の決定に使う)

    @property
    def caption(self) -> str:
        return self.subtitle if self.subtitle is not None else self.say


@dataclass
class Scene:
    id: str
    title: str = ""
    beats: list[Beat] = field(default_factory=list)


@dataclass
class Video:
    width: int = 1280
    height: int = 720
    fps: int = 30
    # ページ生成から最初のビートまでの最小待ち時間。
    # Chromium の録画は最初のフレームが載るまで 1-2 秒かかることがあり、
    # ここが短いと冒頭のビートが動画に入らない。実測 skew より大きく取る。
    leader: float = 2.5
    trailer: float = 1.2  # 末尾の余白


@dataclass
class App:
    url: str = ""
    ready: str | None = None  # ここが見えるまで待ってから収録開始
    start: str | None = None  # 開発サーバの起動コマンド。既に応答していれば起動しない
    cwd: str | None = None  # start の実行ディレクトリ (plan.json からの相対)
    start_timeout: float = 60.0


@dataclass
class Voice:
    """TTS の設定。gmp voice がこれを見て合成する."""

    engine: str = "voicevox"
    speaker: str | int | None = None  # 名前 ("ずんだもん"/"zundamon") か話者ID
    style: str | None = None  # "ノーマル" "あまあま" など
    url: str = "http://127.0.0.1:50021"
    speed: float = 1.0
    pitch: float = 0.0
    intonation: float = 1.0
    volume: float = 1.0
    pre: float = 0.1  # 発話前の無音(秒)
    post: float = 0.1
    # 作品に焼くクレジット表記。gmp voice が話者から自動で埋める。
    # 手で書けばそれが優先される (正確な表記は音声ライブラリの利用規約に従うこと)
    credit: str | None = None


@dataclass
class Determinism:
    """リプレイのブレを潰す設定. 詳細は determinism.py."""

    seed: int | None = None  # Math.random の固定
    time: str | None = None  # 開始時刻の固定 ("2026-01-01T09:00:00")


@dataclass
class Plan:
    title: str = "untitled"
    lang: str = "ja"
    project: str | None = None  # 生成物の置き場所 <home>/<project>/ に使う
    app: App = field(default_factory=App)
    video: Video = field(default_factory=Video)
    voice: Voice = field(default_factory=Voice)
    determinism: Determinism = field(default_factory=Determinism)
    scenes: list[Scene] = field(default_factory=list)
    source: Path | None = None

    @property
    def beats(self) -> list[tuple[Scene, Beat]]:
        return [(s, b) for s in self.scenes for b in s.beats]


def _validate_action(action: dict[str, Any], where: str) -> None:
    kind = action.get("type")
    if kind not in ACTION_SPECS:
        known = ", ".join(sorted(ACTION_SPECS))
        raise PlanError(f"{where}: 未知の action type {kind!r} (使えるのは: {known})")
    for key in ACTION_SPECS[kind]:
        if key not in action:
            raise PlanError(f"{where}: action {kind!r} に必須キー {key!r} がありません")
    if kind == "wait_for" and not (action.get("selector") or action.get("seconds")):
        raise PlanError(f"{where}: wait_for には selector か seconds のどちらかが必要です")


def load(path: str | Path) -> Plan:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path}: JSON として読めません: {exc}") from exc

    version = raw.get("version", PLAN_VERSION)
    if version != PLAN_VERSION:
        raise PlanError(f"{path}: version {version} は未対応 (このgmpは {PLAN_VERSION})")

    meta = raw.get("meta", {})
    plan = Plan(
        title=meta.get("title", path.stem),
        lang=meta.get("lang", "ja"),
        project=meta.get("project"),
        app=App(**{k: v for k, v in raw.get("app", {}).items() if k in App.__annotations__}),
        video=Video(**{k: v for k, v in raw.get("video", {}).items() if k in Video.__annotations__}),
        voice=Voice(**{k: v for k, v in raw.get("voice", {}).items() if k in Voice.__annotations__}),
        determinism=Determinism(**{
            k: v for k, v in raw.get("determinism", {}).items()
            if k in Determinism.__annotations__
        }),
        source=path,
    )

    scenes = raw.get("scenes")
    if not scenes:
        raise PlanError(f"{path}: scenes が空です")

    for si, sraw in enumerate(scenes):
        scene = Scene(id=sraw.get("id", f"scene{si}"), title=sraw.get("title", ""))
        beats = sraw.get("beats") or []
        if not beats:
            raise PlanError(f"{path}: scene {scene.id!r} に beats がありません")
        for bi, braw in enumerate(beats):
            beat = Beat(
                say=braw.get("say", ""),
                subtitle=braw.get("subtitle"),
                hold=float(braw.get("hold", 0.0)),
                actions=list(braw.get("actions") or []),
                audio=braw.get("audio"),
            )
            for ai, action in enumerate(beat.actions):
                _validate_action(action, f"{scene.id}.beats[{bi}].actions[{ai}]")
            scene.beats.append(beat)
        plan.scenes.append(scene)

    if not plan.app.url:
        raise PlanError(f"{path}: app.url が必要です")
    return plan
