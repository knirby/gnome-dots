"""The running GNOME session: shell version, session bus, logging out."""

import os
import re
from pathlib import Path

from .. import ui, util


def shell_version() -> tuple[int, int] | None:
    out = util.output(["gnome-shell", "--version"]) or ""
    m = re.search(r"(\d+)(?:\.(\d+))?", out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def has_session_bus() -> bool:
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    return Path(f"/run/user/{os.getuid()}/bus").exists()


def in_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("DESKTOP_SESSION", "")
    return "gnome" in desktop.lower()


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "unknown")


def logout() -> bool:
    if util.which("gnome-session-quit"):
        return util.run(["gnome-session-quit", "--logout", "--no-prompt"], mutate=True).returncode == 0
    return False


def reboot() -> bool:
    # GNOME's own dialog first: it lets apps object to unsaved work.
    for cmd in (["gnome-session-quit", "--reboot"], ["systemctl", "reboot"], ["loginctl", "reboot"]):
        if util.which(cmd[0]) and util.run(cmd, mutate=True).returncode == 0:
            return True
    ui.warn("Could not reboot from here; reboot from the system menu.")
    return False


def offer_restart(reason: str = "GNOME loads new extensions at login") -> None:
    if ui.dry_run:
        return
    ui.header("Restart to apply")
    ui.info(f"{reason}, so log out and back in (or reboot) to see everything.")
    choice = ui.choose("What now?", [("l", "log out now"), ("r", "reboot now"), ("n", "later")], "n")
    if choice == "l":
        ui.info("Logging out...")
        if not logout():
            ui.warn("Could not log out from here; use the system menu.")
    elif choice == "r":
        reboot()
    else:
        ui.info("Remember to log out and back in before judging the result.")
