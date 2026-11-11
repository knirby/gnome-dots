"""Optional Global Menu: the focused app's real menu bar in the top bar, plus an Apple-style logo menu.

Only runs when asked for (--with global-menu, or yes at the install prompt). The extension comes from
knirby/gnome-global-menu and is installed by that repository's own ./install, which on Fedora then asks
whether to build the patched Mutter that native Wayland menus need. The questions therefore come in
this order: this tool, the Global Menu, the patched Mutter.
"""

import sys

from .. import ui, util
from ..gnome import extensions as ext
from ..paths import CACHE_DIR
from .base import Module
from .settings import load_templates

UUID = "gnome-global-menu@felipefelix"
REPO = "https://github.com/knirby/gnome-global-menu.git"
CHECKOUT = CACHE_DIR / "gnome-global-menu"
DCONF = "/org/gnome/shell/extensions/gnome-global-menu/"


class GlobalMenu(Module):
    name = "global-menu"
    title = "Global Menu (addon)"
    summary = ("optional: the focused app's menu bar in the top bar and an Apple-style logo menu; "
               "offers the patched Mutter that native Wayland menus need")
    default = False
    needs_dconf = True
    needs_network = True

    def plan(self, ctx):
        if ctx.shell_major != 50:
            return [f"the Global Menu supports GNOME 50 only; skipped on GNOME {ctx.shell_major}"]
        lines = ["build and install the Global Menu from knirby/gnome-global-menu (needs node and npm)"]
        if ui.assume_yes or not sys.stdin.isatty():
            lines.append("not asking about the patched Mutter without a terminal or under --yes: run ./install --mutter in "
                         f"{CHECKOUT} when you want native Wayland menus")
        else:
            lines.append("its installer then asks whether to build the patched Mutter (Fedora)")
        return lines

    def apply(self, ctx):
        if ctx.shell_major != 50:
            ui.warn(f"The Global Menu supports GNOME 50 only; skipped on GNOME {ctx.shell_major}")
            return
        for tool in ("git", "node", "npm"):
            if not util.which(tool) and not ui.dry_run:
                raise RuntimeError(f"{tool} isn't installed (the packages module installs it)")
        record = ctx.state.data.setdefault("global_menu", {})
        record.setdefault("preexisting", ext.user_dir(UUID).exists())
        if (CHECKOUT / ".git").is_dir():
            util.run(["git", "-C", str(CHECKOUT), "pull", "--ff-only", "--quiet"], mutate=True, check=True)
        else:
            if not ui.dry_run:
                CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
            util.run(["git", "clone", "--depth=1", "--quiet", REPO, str(CHECKOUT)], mutate=True, check=True)
        cmd = [str(CHECKOUT / "install"), "--enable"]
        if ui.assume_yes or not sys.stdin.isatty():
            cmd.append("--no-mutter")   # replacing Mutter is only ever done on a direct yes
        # No capture: the installer's own question about the patched Mutter has to reach the terminal.
        util.run(cmd, mutate=True, check=True, capture=False)
        if not load_templates(ctx, ["extensions/global-menu.ini"], DCONF):
            ctx.failures.append("global-menu settings")
        ui.ok("Global Menu installed; it starts at your next login")

    def remove(self, ctx):
        record = ctx.state.data.pop("global_menu", None)
        if record is None or record.get("preexisting"):
            return
        installer = CHECKOUT / "install"
        if installer.is_file():
            util.run([str(installer), "--uninstall"], mutate=True, capture=False)
        else:
            ext.set_enabled([], [UUID])
            ext.remove_user_copy(UUID)
        util.remove_tree(CHECKOUT)
        ui.ok("Removed the Global Menu (a patched Mutter you built stays; ./install --uninstall --mutter "
              "in the gnome-global-menu repository puts Fedora's back)")
