"""Finding installed applications by desktop file ID.

App IDs differ between distributions and packaging formats (Firefox is
firefox.desktop as an RPM, org.mozilla.firefox.desktop as a Flatpak), so the
configuration lists alternatives and the first one installed wins.
"""

import shlex
from pathlib import Path

from .. import util
from ..paths import HOME, data_dirs

_EXTRA = [HOME / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share"),
          Path("/var/lib/snapd/desktop")]


def app_dirs() -> list[Path]:
    dirs = []
    for base in [*data_dirs(), *_EXTRA]:
        d = base / "applications"
        if d.is_dir() and d not in dirs:
            dirs.append(d)
    return dirs


def installed(desktop_id: str) -> bool:
    # Desktop IDs map "-" to subdirectories as a fallback (kde-foo.desktop -> kde/foo.desktop).
    alt = desktop_id.replace("-", "/", 1)
    return any((d / desktop_id).is_file() or (d / alt).is_file() for d in app_dirs())


def _runnable(cmd: str | None) -> bool:
    if not cmd:
        return True
    try:
        first = shlex.split(cmd)[0]
    except (ValueError, IndexError):
        return False
    return util.which(first) is not None


def resolve(candidates: list[dict]) -> dict | None:
    """First candidate whose desktop file and command both exist."""
    for c in candidates:
        if installed(c["desktop"]) and _runnable(c.get("cmd")):
            return c
    return None


def first_installed(ids: list[str]) -> str | None:
    for i in ids:
        if installed(i):
            return i
    return None
