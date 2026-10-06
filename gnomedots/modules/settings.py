"""The desktop configuration itself: dconf templates for GNOME, its apps and
every extension, filled in with this machine's values."""

from .. import ui
from ..gnome import apps, dconf
from ..gnome import extensions as ext
from .base import Module
from .wallpaper import resolution

SEPARATOR = {"name": "Separator", "icon": "list-remove-symbolic", "id": "ArcMenu_Separator"}


def template_values(ctx) -> dict:
    """Values for the @NAME@ placeholders. None leaves that key untouched."""
    cfg = ctx.apps_config
    terminal = ctx.terminal
    software = ctx.software
    shortcuts = []
    for item in cfg.get("arcmenu_shortcuts", []):
        if item == "separator":
            shortcuts.append(SEPARATOR)
            continue
        app = {"@terminal": terminal["desktop"] if terminal else None,
               "@extensions": ctx.extensions_app}.get(item, item)
        if app and apps.installed(app):
            shortcuts.append({"id": app})
    pinned = [{"id": a} for a in (apps.first_installed(slot) for slot in cfg.get("arcmenu_pinned", [])) if a]

    def version(uuid):
        v = ext.installed_version(uuid)
        return v if isinstance(v, int) else None

    values = {
        "TERMINAL_CMD": terminal["cmd"] if terminal else None,
        "SOFTWARE_CMD": software["cmd"] if software else None,
        "EXTENSIONS_APP": ctx.extensions_app,
        "BING_DIR": str(ctx.wallpaper_dir()),
        "BING_RESOLUTION": resolution(ctx),
        "WALLPAPER_PATH": None,
        "ARCMENU_SHORTCUTS": shortcuts or None,
        "ARCMENU_PINNED": pinned or None,
        "ARCMENU_VERSION": version("arcmenu@arcmenu.com"),
        "AZWALLPAPER_VERSION": version("azwallpaper@azwallpaper.gitlab.com"),
    }
    values.update({k: v for k, v in ctx.vars.items() if k.isupper()})
    return values


def load_templates(ctx, files: list[str], tree: str | None = None) -> bool:
    """Render and load templates. With tree, that dconf folder is reset first
    so the result is exactly the template, not a mix with old values."""
    values = template_values(ctx)
    ok = True
    for name in files:
        text = dconf.render(ctx.config_text(f"dconf/{name}"), values)
        if tree:
            dconf.reset_tree(tree)
            ctx.state.add_unique("dconf_trees", tree)
        else:
            ctx.state.add_unique("dconf_sections", *dconf.sections(text).keys())
        ok = dconf.load(text) and ok
    return ok


class Settings(Module):
    name = "settings"
    title = "Desktop and extension settings"
    summary = "theme, fonts, top bar, dock, blur, window corners, app preferences"
    needs_dconf = True

    def plan(self, ctx):
        t = ctx.terminal
        return [
            "dark Adwaita, accent colour picked from the wallpaper, Mint-Y-Grey icons, Bibata cursor, Noto Sans + Fira Code",
            "top bar: ArcMenu, Astra Monitor, media, clock on the right; dock at the bottom",
            "blur everywhere, rounded corners, 2 fixed workspaces",
            f"terminal: {t['cmd'] if t else 'none found'}",
            "every managed extension's settings are reset to this configuration",
        ]

    def apply(self, ctx):
        failed = []
        if not load_templates(ctx, ["desktop.ini", "apps.ini"]):
            failed.append("desktop")
        for e in ctx.extensions:
            if e.get("settings") and not load_templates(ctx, [f"extensions/{e['settings']}"], e["dconf"]):
                failed.append(e["name"])
        favorites = [a for a in (apps.first_installed(slot) for slot in ctx.apps_config["favorites"]) if a]
        if favorites:
            dconf.write("/org/gnome/shell/favorite-apps", favorites)
            ctx.state.add_unique("dconf_sections", "/org/gnome/shell/")
        if failed:
            ctx.failures.append("settings: " + ", ".join(failed))
            ui.warn("Some settings did not load: " + ", ".join(failed))
        else:
            ui.ok("Desktop and extension settings applied")


class Input(Module):
    name = "input"
    title = "Mouse and keyboard feel"
    summary = "flat mouse acceleration and speed, num lock on (layouts untouched)"
    needs_dconf = True

    def plan(self, ctx):
        return ["mouse: flat acceleration, speed -0.34; num lock on at login"]

    def apply(self, ctx):
        if load_templates(ctx, ["input.ini"]):
            ui.ok("Mouse and keyboard settings applied")
