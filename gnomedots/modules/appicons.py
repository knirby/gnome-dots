"""Launcher icons that match Mint-Y-Grey: Files shows the grey folder and the
terminal Mint-Y's terminal, instead of the apps' own icons, which Mint-Y
doesn't theme.

Each app's system desktop file is copied to ~/.local/share/applications with
only its Icon= line changed and a marker key added, so everything else
(actions, MIME types, D-Bus activation) stays as the package ships it, and
`update` recopies it when the package changes. A launcher you already
customised yourself is left alone.

Desktop Icons NG refuses to start properly ("Gnome Files is not registered as
a File Manager") unless org.gnome.Nautilus.desktop handles inode/directory.
A copy shadows the system file, so the user MIME cache is rebuilt and Files
is made the folder handler again, as it is on a stock system.
"""

from pathlib import Path

from .. import APP_NAME, ui, util
from ..gnome import apps
from ..paths import DATA_HOME
from .base import Module

APPS_DIR = DATA_HOME / "applications"
MARK = f"X-{APP_NAME}-original-icon"
FOLDERS = "inode/directory"


def system_entry(desktop_id: str) -> Path | None:
    """The desktop file the session would use if there were no copy here."""
    for d in apps.app_dirs():
        if d != APPS_DIR and (d / desktop_id).is_file():
            return d / desktop_id
    return None


def ours(path: Path) -> bool:
    return f"\n{MARK}=" in "\n" + (util.read(path) or "")


def with_icon(text: str, icon: str) -> str:
    """The desktop file with its main Icon= set to icon (translated icons
    dropped, the original kept under MARK)."""
    out, section = [], None
    for line in text.splitlines():
        if line.startswith("["):
            section = line.strip()
        key = line.split("=", 1)[0].strip()
        if section == "[Desktop Entry]":
            if key == "Icon":
                out += [f"Icon={icon}", f"{MARK}={line.split('=', 1)[1].strip()}"]
                continue
            if key.startswith("Icon[") or key == MARK:
                continue
        out.append(line)
    return "\n".join(out) + "\n"


def handles_folders(text: str) -> bool:
    return any(line.startswith("MimeType=") and FOLDERS in line.split("=", 1)[1].split(";")
               for line in text.splitlines())


def refresh(file_manager: str | None) -> None:
    if util.which("update-desktop-database"):
        util.run(["update-desktop-database", "-q", str(APPS_DIR)], mutate=True)
    if file_manager:
        util.run(["gio", "mime", FOLDERS, file_manager], mutate=True)


class AppIcons(Module):
    name = "app-icons"
    title = "Launcher icons"
    summary = "Files and the terminal use Mint-Y-Grey icons (launcher copies in ~/.local/share/applications)"

    def _wanted(self, ctx) -> list[tuple[str, str, Path]]:
        """(desktop id, icon, system file) for each installed app to restyle."""
        rows = []
        for desktop_id, icon in ctx.apps_config.get("icons", {}).items():
            src = system_entry(desktop_id)
            if src:
                rows.append((desktop_id, icon, src))
        return rows

    def plan(self, ctx):
        lines = []
        for desktop_id, icon, _ in self._wanted(ctx):
            target = APPS_DIR / desktop_id
            if target.exists() and not ours(target):
                lines.append(f"{desktop_id}: you changed it yourself, kept")
            else:
                lines.append(f"{desktop_id}: icon {icon}")
        return lines or ["none of the apps are installed"]

    def apply(self, ctx):
        file_manager, changed = None, False
        for desktop_id, icon, src in self._wanted(ctx):
            target = APPS_DIR / desktop_id
            if target.exists() and not ours(target):
                ui.info(f"{desktop_id}: keeping your own launcher")
                continue
            text = with_icon(src.read_text(encoding="utf-8"), icon)
            if handles_folders(text):
                file_manager = desktop_id
            if util.read(target) != text.strip():
                util.write_text(target, text)
                changed = True
        if changed or file_manager:
            refresh(file_manager)
        ui.ok("Launcher icons set")

    def remove(self, ctx):
        removed = False
        for p in APPS_DIR.glob("*.desktop"):
            if ours(p):
                util.remove_tree(p)
                removed = True
        if removed:
            refresh(None)
