"""Keyboard shortcuts, plus Super+T for whichever terminal is installed."""

from .. import APP_NAME, ui, util
from ..gnome import dconf, gvariant
from .base import Module
from .settings import load_templates

MEDIA_KEYS = "/org/gnome/settings-daemon/plugins/media-keys/"
CUSTOM = MEDIA_KEYS + "custom-keybindings/"
TERMINAL_PATH = f"{CUSTOM}{APP_NAME}-terminal/"
TERMINAL_KEY = "<Super>t"


def custom_paths() -> list[str]:
    out = util.output(["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys",
                       "custom-keybindings"])
    return gvariant.load_strv(out if out is not None else dconf.read(MEDIA_KEYS + "custom-keybindings"))


class Keybindings(Module):
    name = "keybindings"
    title = "Keyboard shortcuts"
    summary = "window, workspace and launcher shortcuts; Super+T opens the terminal"
    needs_dconf = True

    def plan(self, ctx):
        return [
            "Super+X close, Super+Up/Down maximise/minimise, Super+Left/Right workspaces",
            "Super+1-4 workspaces, Super+E files, Super+S search, Super+D desktop, Super+A apps",
            "Shift+Super+S screenshot, Ctrl+Super+Space next layout, Super+, settings",
            "Super+T terminal, Super+M menu, Super+V clipboard, Super+Space launcher",
        ]

    def apply(self, ctx):
        load_templates(ctx, ["keybindings.ini"])
        terminal = ctx.terminal
        if not terminal:
            ui.warn("No terminal found, so Super+T is left unset.")
            return
        paths = custom_paths()
        for p in paths:
            if p != TERMINAL_PATH and gvariant.load_str(dconf.read(p + "binding")) == TERMINAL_KEY:
                ui.info(f"Super+T is already a custom shortcut ({p}); keeping it.")
                break
        else:
            dconf.write(TERMINAL_PATH + "name", "Terminal")
            dconf.write(TERMINAL_PATH + "command", terminal["cmd"])
            dconf.write(TERMINAL_PATH + "binding", TERMINAL_KEY)
            if TERMINAL_PATH not in paths:
                dconf.write(MEDIA_KEYS + "custom-keybindings", [*paths, TERMINAL_PATH])
            ctx.state.add_unique("dconf_trees", TERMINAL_PATH)
        ui.ok("Shortcuts applied")

    def remove(self, ctx):
        paths = custom_paths()
        if TERMINAL_PATH in paths:
            dconf.write(MEDIA_KEYS + "custom-keybindings", [p for p in paths if p != TERMINAL_PATH])
        dconf.reset_tree(TERMINAL_PATH)
