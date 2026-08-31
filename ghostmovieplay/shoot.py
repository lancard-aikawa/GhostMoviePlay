"""支援収録の plan.json 操作 (画面を作らずに決まる部分).

**自動操作が届かない相手を、人が操作して撮る道。** ログインの要る業務アプリ、
canvas、OAuth —— `gmp record` が原理的に届かないところは、人が手を動かすしかない。
そのとき画面がやるのは**ショットを貯めて、どのビートのものかを覚えておくこと**だけ。

台本の構造はそのまま使う (`docs/ideas/desktop.md`):

    シーン = plan.json の scenes[]      (人が「セクション」と呼ぶまとまり)
    ビート = plan.json の beats[]       (人が「ステップ」と呼ぶ 1 単位)
    1 ビート = ショット 1 つ + コメント 1 つ

**3 階層目を作らない。** 「1 ステップに画像を何枚も」を階層で表すと plan.json が
2 階層で足りなくなり、`voice` / `render` / `check` が全部それを知る羽目になる。
何枚も撮りたいときは**撮るたびにビートが増える**ことで満たす —— 1 画像 1 コメントは
そのほうが素直に守れる (同じ画像を 2 つのビートが指してもよい。**複製は作らない**)。

**生の JSON に当てる。** `plan.load()` の dataclass から書き戻すと、AI が書いた
キーの並びとこちらが知らない項目が消える (`plan.patch` と同じ理由)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plan import PLAN_VERSION

SHOT_DIR = "shots"
STILL_SUFFIX = ".png"
CLIP_SUFFIX = ".mp4"


class ShootError(RuntimeError):
    pass


@dataclass(frozen=True)
class Row:
    """一覧に出す 1 ビート."""

    scene_index: int
    beat_index: int
    scene_id: str
    scene_title: str
    say: str
    subtitle: str
    do: str
    shot: str | None
    audio: str | None

    @property
    def address(self) -> str:
        return f"{self.scene_id}#{self.beat_index}"

    @property
    def kind(self) -> str:
        """ショットの種別: "" / "静止画" / "動画"."""
        if not self.shot:
            return ""
        return "動画" if self.shot.lower().endswith(CLIP_SUFFIX) else "静止画"


def skeleton(title: str, window: str, width: int, height: int,
             fps: int = 30, project: str | None = None) -> dict[str, Any]:
    """支援収録の plan.json の骨.

    **収録対象を嘘で埋めない** (`gmp init` の雛形と同じ規則)。ウィンドウのタイトルだけは
    人が選んだ実物なので値として書く。say は空のまま —— そこは Claude の領分で、
    空なら「まだ書いていない」と見分けがつく。
    """
    doc: dict[str, Any] = {
        "version": PLAN_VERSION,
        "meta": {"title": title or "untitled"},
        "app": {"window": window},
        "video": {"width": width, "height": height, "fps": fps},
        "scenes": [{"id": "scene1", "title": "", "beats": [{"say": ""}]}],
    }
    if project:
        doc["meta"]["project"] = project
    return doc


class Doc:
    """plan.json を生の辞書のまま持ち回す編集用の入れ物.

    **保存前に他所で変わっていないかを見る。** このウィンドウが構造ごと書き戻すので、
    Claude が同じファイルの say を書いている最中に上書きすると、書かれた文が
    黙って消える。`stale()` が真なら呼び側が訊いてから保存する。
    """

    def __init__(self, path: Path, raw: dict[str, Any], mtime: float | None):
        self.path = Path(path)
        self.raw = raw
        self.mtime = mtime
        self.dirty = False

    # --- 出し入れ ----------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> Doc:
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ShootError(f"読めません: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ShootError(f"JSON として読めません: {exc}") from exc
        if not isinstance(raw, dict):
            raise ShootError("plan.json の中身が辞書ではありません")
        raw.setdefault("scenes", [])
        return cls(path, raw, _mtime(path))

    @classmethod
    def create(cls, path: str | Path, raw: dict[str, Any]) -> Doc:
        doc = cls(Path(path), raw, None)
        doc.dirty = True
        return doc

    def stale(self) -> bool:
        """読み込んだあとに他所で書き換わったか."""
        now = _mtime(self.path)
        if now is None or self.mtime is None:
            return False
        return now > self.mtime + 1e-6

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 読んだときと同じ書式で書き戻す (indent=2 + 末尾改行)
        self.path.write_text(
            json.dumps(self.raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        self.mtime = _mtime(self.path)
        self.dirty = False
        return self.path

    # --- 読み ---------------------------------------------------------
    @property
    def scenes(self) -> list[dict[str, Any]]:
        scenes = self.raw.get("scenes")
        if not isinstance(scenes, list):
            scenes = []
            self.raw["scenes"] = scenes
        return scenes

    def rows(self) -> list[Row]:
        out: list[Row] = []
        for si, scene in enumerate(self.scenes):
            beats = scene.get("beats")
            if not isinstance(beats, list):
                beats = []
                scene["beats"] = beats
            for bi, beat in enumerate(beats):
                out.append(Row(
                    scene_index=si, beat_index=bi,
                    scene_id=str(scene.get("id") or f"scene{si + 1}"),
                    scene_title=str(scene.get("title") or ""),
                    say=str(beat.get("say") or ""),
                    subtitle=str(beat.get("subtitle") or ""),
                    do=str(beat.get("do") or ""),
                    shot=beat.get("shot"), audio=beat.get("audio"),
                ))
        return out

    def beat(self, scene_index: int, beat_index: int) -> dict[str, Any] | None:
        try:
            return self.scenes[scene_index]["beats"][beat_index]
        except (IndexError, KeyError, TypeError):
            return None

    @property
    def window(self) -> str:
        app = self.raw.get("app")
        return str(app.get("window") or "") if isinstance(app, dict) else ""

    @property
    def package(self) -> str:
        app = self.raw.get("app")
        return str(app.get("package") or "") if isinstance(app, dict) else ""

    @property
    def target(self) -> str:
        """撮る相手 (ウィンドウのタイトル か Android のパッケージ).

        **`plan.App.assisted` と同じ組み合わせ。** 空のまま保存すると
        「設定済みに見える嘘」が残るので、呼び側はここで止める。
        """
        return self.window or self.package

    @property
    def size(self) -> tuple[int, int]:
        video = self.raw.get("video") or {}
        return int(video.get("width", 1280)), int(video.get("height", 720))

    # --- 書き ---------------------------------------------------------
    def set_window(self, title: str) -> None:
        self.raw.setdefault("app", {})["window"] = title
        self.dirty = True

    def set_size(self, width: int, height: int) -> None:
        video = self.raw.setdefault("video", {})
        video["width"], video["height"] = int(width), int(height)
        self.dirty = True

    def add_scene(self, title: str = "") -> int:
        """末尾にシーンを 1 つ足して、その添字を返す. ビートを 1 つ持たせる."""
        used = {str(s.get("id")) for s in self.scenes}
        number = len(self.scenes) + 1
        while f"scene{number}" in used:
            number += 1
        self.scenes.append({"id": f"scene{number}", "title": title,
                            "beats": [{"say": ""}]})
        self.dirty = True
        return len(self.scenes) - 1

    def add_beat(self, scene_index: int, after: int | None = None) -> int:
        """ビートを 1 つ足して、その添字を返す."""
        try:
            beats = self.scenes[scene_index].setdefault("beats", [])
        except IndexError as exc:
            raise ShootError("そのシーンがありません") from exc
        at = len(beats) if after is None else max(0, min(len(beats), after + 1))
        beats.insert(at, {"say": ""})
        self.dirty = True
        return at

    def remove_beat(self, scene_index: int, beat_index: int) -> bool:
        """ビートを消す. **最後の 1 つは消さない** (load が空の beats を拒む)."""
        try:
            beats = self.scenes[scene_index]["beats"]
        except (IndexError, KeyError, TypeError):
            return False
        if len(beats) <= 1:
            return False
        del beats[beat_index]
        self.dirty = True
        return True

    def remove_scene(self, scene_index: int) -> bool:
        """シーンを消す. **最後の 1 つは消さない**."""
        if len(self.scenes) <= 1 or not 0 <= scene_index < len(self.scenes):
            return False
        del self.scenes[scene_index]
        self.dirty = True
        return True

    def set_shot(self, scene_index: int, beat_index: int, relative: str | None) -> None:
        """ショットを差し替える (None なら外す).

        **ファイルは消さない。** 撮り直しの効かないショットなので、参照を外すのと
        現物を消すのは別の操作にしておく。
        """
        beat = self.beat(scene_index, beat_index)
        if beat is None:
            raise ShootError("そのビートがありません")
        if relative:
            beat["shot"] = relative
        else:
            beat.pop("shot", None)
        self.dirty = True

    def set_text(self, scene_index: int, beat_index: int,
                 say: str | None = None, subtitle: str | None = None,
                 do: str | None = None) -> list[str]:
        """コメント (say) と字幕を書き換える. 戻り値は直した項目.

        **原稿を直したらそのビートの音声を落とす** (`plan._apply` と同じ規則) ——
        残すと、直した原稿に古い読み上げが乗ったまま組み立てられる。
        """
        beat = self.beat(scene_index, beat_index)
        if beat is None:
            raise ShootError("そのビートがありません")
        done: list[str] = []
        if say is not None and say != (beat.get("say") or ""):
            beat["say"] = say
            beat.pop("audio", None)
            done.append("say")
        if subtitle is not None:
            if subtitle:
                if subtitle != beat.get("subtitle"):
                    beat["subtitle"] = subtitle
                    done.append("subtitle")
            elif beat.pop("subtitle", None) is not None:
                done.append("subtitle")
        # **`do` は絵にも音にも触らない**ので、直しても音声は落とさない
        if do is not None:
            if do:
                if do != beat.get("do"):
                    beat["do"] = do
                    done.append("do")
            elif beat.pop("do", None) is not None:
                done.append("do")
        if done:
            self.dirty = True
        return done

    def set_scene_title(self, scene_index: int, title: str) -> None:
        try:
            self.scenes[scene_index]["title"] = title
        except IndexError as exc:
            raise ShootError("そのシーンがありません") from exc
        self.dirty = True


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def next_shot_path(outdir: Path, scene_id: str, clip: bool = False) -> tuple[Path, str]:
    """次に使うショットのファイル名. 戻り値は (絶対パス, 出力ディレクトリからの相対).

    **通し番号にする。** ビートの添字を名前にすると、あいだにビートを挿した
    とたんに名前と中身がずれる (ショットは移動しないので)。どのビートのものかは
    plan.json が覚えている。
    """
    directory = Path(outdir) / SHOT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    suffix = CLIP_SUFFIX if clip else STILL_SUFFIX
    # **拡張子を無視して数える。** 見ないと 0001-intro.png と 0001-intro.mp4 が
    # 別のショットなのに同じ番号を持つ (人が探すときに取り違える)
    used = {p.stem for p in directory.glob("*")}
    serial = 1
    while f"{serial:04d}-{scene_id}" in used:
        serial += 1
    name = f"{serial:04d}-{scene_id}{suffix}"
    return directory / name, f"{SHOT_DIR}/{name}"


def progress(rows: list[Row]) -> tuple[int, int]:
    """(ショットのあるビート, 全ビート)."""
    return sum(1 for r in rows if r.shot), len(rows)
