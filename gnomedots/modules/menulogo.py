"""The ArcMenu button: this distribution's logo, or Tux when there isn't one.

ArcMenu ships symbolic logos for many distributions; the one matching the
os-release ID is used if the installed ArcMenu has it. Bedrock Linux uses the
logo brl-tools installs. Everything else gets Tux.
"""

import shutil

from .. import ui
from ..gnome import dconf
from ..gnome import extensions as ext
from ..paths import ASSETS_DIR, DATA_HOME
from .base import Module

ARCMENU = "arcmenu@arcmenu.com"
KEY = "/org/gnome/shell/extensions/arcmenu/menu-button-icon"
RESOURCE = "resource:///org/gnome/shell/extensions/arcmenu/icons/scalable/actions/distro-{}-symbolic.svg"

# os-release ID -> ArcMenu logo name, where they differ.
ALIASES = {
    "kali": "kali-linux", "pop": "pop-os", "rhel": "redhat", "opensuse-leap": "opensuse",
    "opensuse-tumbleweed": "opensuse", "opensuse-slowroll": "opensuse", "raspbian": "raspbian",
}
BEDROCK_LOGOS = [
    "/usr/local/share/brl-tools/assets/bedrock-logo-mark-dark.svg",
    "/usr/local/share/pixmaps/bedrock-logo-mark-dark.svg",
]
TUX = DATA_HOME / "pixmaps" / "knirby-gnomedots-tux.svg"


def _arcmenu_logos() -> bytes:
    folder = ext.find(ARCMENU)
    if not folder:
        return b""
    data = b""
    for res in folder.glob("**/*.gresource"):
        try:
            data += res.read_bytes()
        except OSError:
            pass
    return data


def choose(ctx) -> tuple[str, str]:
    """(icon value, description)."""
    from pathlib import Path
    if ctx.distro.bedrock:
        for logo in BEDROCK_LOGOS:
            if Path(logo).is_file():
                return logo, "Bedrock Linux logo"
    logos = _arcmenu_logos()
    name = ALIASES.get(ctx.distro.id, ctx.distro.id)
    if name and f"distro-{name}-symbolic.svg".encode() in logos:
        return RESOURCE.format(name), f"{ctx.distro.name} logo"
    return str(TUX), "Tux"


class MenuLogo(Module):
    name = "menu-logo"
    title = "ArcMenu logo"
    summary = "your distribution's logo on the menu button, Tux otherwise"
    needs_dconf = True

    def plan(self, ctx):
        _, what = choose(ctx)
        return [f"menu button shows the {what}"]

    def apply(self, ctx):
        icon, what = choose(ctx)
        if icon == str(TUX):
            ui.action(f"copy Tux to {TUX}")
            if not ui.dry_run:
                TUX.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ASSETS_DIR / "tux.svg", TUX)
        dconf.write(KEY, icon)
        ui.ok(f"ArcMenu shows the {what}")

    def remove(self, ctx):
        TUX.unlink(missing_ok=True)
