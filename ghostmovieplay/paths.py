"""生成物の置き場所を決める.

方針: **ソースと成果物を完全に分ける**。
  プロジェクトの git には video.md と plan.json だけが入り、
  生成物 (voice/ raw.webm timing.json subs.ass output.mp4) は
  ユーザフォルダ側の 1 か所にまとまる。プロジェクト側に .gitignore が要らない。

置き場所の決まり方 (上から優先):
  1. --out で明示
  2. 環境変数 GHOSTMOVIEPLAY_HOME
  3. 設定ファイル config.toml の home
  4. プラットフォーム既定の動画フォルダ / GhostMoviePlay

出力ルートは「機械が決める設定」なので、プロジェクトの gmp.toml には置けない
(settings.py の layers で弾いている)。設定全体の層と由来の追跡は settings.py。
ここが持っているのは置き場所の解決と、設定ファイルの読み書きだけ。

Win/Mac で名前が一致する動画フォルダは存在しない (Windows=Videos, macOS=Movies)
ので、プラットフォームごとに解決する。Windows は Known Folder が
OneDrive などへリダイレクトされていることがあるため、レジストリを引く。
Documents を使わないのは、リダイレクト先が OneDrive のことが多く、
数百MB になる raw.webm がクラウド同期に乗ってしまうため。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

APP_DIR_NAME = "GhostMoviePlay"
ENV_HOME = "GHOSTMOVIEPLAY_HOME"
CONFIG_NAME = "config.toml"

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str, fallback: str = "video") -> str:
    """フォルダ名に使えない文字を落とす."""
    cleaned = _INVALID.sub("-", str(name)).strip(" .")
    return cleaned or fallback


# --- プラットフォーム既定 ---------------------------------------------
def user_videos_dir() -> Path:
    """OS ごとの動画フォルダ. Windows=Videos / macOS=Movies / Linux=XDG."""
    if sys.platform == "win32":
        # リダイレクトされている可能性があるのでレジストリを引く
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                raw, _ = winreg.QueryValueEx(k, "My Video")
            resolved = Path(os.path.expandvars(raw))
            if resolved.parent.exists():
                return resolved
        except (OSError, ImportError):
            pass
        return Path.home() / "Videos"

    if sys.platform == "darwin":
        return Path.home() / "Movies"  # macOS は Videos ではない

    try:
        out = subprocess.run(
            ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            resolved = Path(out.stdout.strip())
            if resolved != Path.home():
                return resolved
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Videos"


# --- 設定ファイル -----------------------------------------------------
def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_DIR_NAME / CONFIG_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME / CONFIG_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_DIR_NAME.lower() / CONFIG_NAME


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    import tomllib

    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def save_config(config: dict) -> Path:
    """機械の設定を書く. 区画つき (ネストした) 設定も書ける.

    書式は settings.dump が持っている (スキーマの順に並べ、説明を添える)。
    ここで import するのは settings が paths を使うため (循環を避ける)。
    """
    from .settings import dump

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump(config, header="GhostMoviePlay — グローバル設定 (この機械。gmp config で編集)"),
        encoding="utf-8",
    )
    return path


# --- 出力先 -----------------------------------------------------------
def output_home() -> Path:
    """生成物のルート."""
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    configured = load_config().get("home")
    if configured:
        return Path(str(configured)).expanduser()
    return user_videos_dir() / APP_DIR_NAME


def home_source() -> str:
    """output_home がどこ由来か (gmp where 用)."""
    if os.environ.get(ENV_HOME):
        return f"環境変数 {ENV_HOME}"
    if load_config().get("home"):
        return f"設定ファイル {config_path()}"
    return "プラットフォーム既定"


def project_name(project: str | None, source: Path, app_cwd: str | None = None) -> str:
    """<project> 部分を決める.

    meta.project があればそれ。無ければ app.cwd の実体ディレクトリ名、
    それも無ければ plan.json / video.md の 2 階層上の名前を使う。
    """
    if project:
        return sanitize(project)
    if app_cwd:
        resolved = Path(app_cwd)
        if not resolved.is_absolute():
            resolved = (source.parent / resolved).resolve()
        if resolved.name:
            return sanitize(resolved.name)
    parent = source.parent.parent
    return sanitize(parent.name, fallback="misc")


def resolve_outdir(
    source: Path,
    project: str | None = None,
    app_cwd: str | None = None,
    explicit: str | Path | None = None,
) -> Path:
    """source (plan.json か video.md) に対する生成物の置き場所.

    <home>/<project>/<video>/ という形。<video> は source のあるフォルダ名。
    """
    if explicit:
        return Path(explicit).expanduser()
    source = Path(source)
    video = sanitize(source.parent.name, fallback=sanitize(source.stem))
    return output_home() / project_name(project, source, app_cwd) / video
