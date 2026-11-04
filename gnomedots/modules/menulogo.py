"""The Global Menu's logo button needs no setup here: the extension shows this distribution's logo (its
square mark when one is installed) and, with `logo-fix-os-logo`, installs it as a user icon for GNOME
Settings -> About. This only cleans those icons up on uninstall."""

from pathlib import Path

from .. import ui
from ..paths import DATA_HOME

LIST = DATA_HOME / "gnome-global-menu" / "os-logo-files"


def remove_os_logo() -> None:
    """Delete the user icons the extension wrote for the os-release logo."""
    if not LIST.is_file():
        return
    for name in LIST.read_text().split():
        Path(name).unlink(missing_ok=True)
    LIST.unlink(missing_ok=True)
    ui.ok("Removed the square distribution logo icons")
