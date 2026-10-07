"""Where things live: XDG base directories, the installed copy and its state."""

import os
import shlex
import subprocess
from pathlib import Path

from . import APP_NAME

HOME = Path.home()


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var, "")
    return Path(value) if os.path.isabs(value) else HOME / default


DATA_HOME = _xdg("XDG_DATA_HOME", ".local/share")
CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config")
STATE_HOME = _xdg("XDG_STATE_HOME", ".local/state")
CACHE_HOME = _xdg("XDG_CACHE_HOME", ".cache")

BIN_DIR = HOME / ".local" / "bin"
LAUNCHER = BIN_DIR / APP_NAME

# The installed copy of this repository, so the clone can be deleted.
APP_DIR = DATA_HOME / APP_NAME
STATE_DIR = STATE_HOME / APP_NAME
STATE_FILE = STATE_DIR / "state.json"
BACKUP_DIR = STATE_DIR / "backups"
LOG_FILE = STATE_DIR / "last-run.log"
CACHE_DIR = CACHE_HOME / APP_NAME

EXTENSIONS_DIR = DATA_HOME / "gnome-shell" / "extensions"
ICONS_DIR = DATA_HOME / "icons"

# The tree this code runs from: a fresh clone or APP_DIR.
SOURCE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = SOURCE_ROOT / "config"
ASSETS_DIR = SOURCE_ROOT / "assets"


def data_dirs() -> list[Path]:
    """XDG_DATA_HOME followed by XDG_DATA_DIRS, as the session sees them."""
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    out = [DATA_HOME]
    for d in dirs.split(":"):
        if d and Path(d) not in out:
            out.append(Path(d))
    return out


def user_dir(name: str) -> Path | None:
    """An xdg-user-dirs folder (PICTURES, TEMPLATES, ...), honouring its
    translations, or None when it isn't set (or is set to the home folder,
    which is how xdg-user-dirs disables one)."""
    try:
        out = subprocess.run(["xdg-user-dir", name], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if out and Path(out) != HOME:
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    dirs_file = CONFIG_HOME / "user-dirs.dirs"
    try:
        for line in dirs_file.read_text().splitlines():
            if line.startswith(f"XDG_{name}_DIR="):
                value = shlex.split(line.split("=", 1)[1])[0]
                value = value.replace("$HOME", str(HOME))
                if Path(value) != HOME:
                    return Path(value)
    except (OSError, IndexError, ValueError):
        pass
    return None


def pictures_dir() -> Path:
    """The user's Pictures folder."""
    return user_dir("PICTURES") or HOME / "Pictures"
