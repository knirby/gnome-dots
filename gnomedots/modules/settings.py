"""The desktop configuration itself: dconf templates for GNOME, its apps and
every extension, filled in with this machine's values."""

from .. import ui, util
from ..gnome import apps, dconf, gvariant
from ..gnome import extensions as ext
from .base import Module
from .wallpaper import resolution

FAVORITES = "/org/gnome/shell/favorite-apps"


def current_favorites() -> list[str]:
    """The dock favourites as GNOME shows them now, its defaults included
    when they were never changed."""
    text = dconf.read(FAVORITES)
    if text is None:
        text = util.output(["gsettings", "get", "org.gnome.shell", "favorite-apps"])
    return gvariant.load_strv(text)


def template_values(ctx) -> dict:
    """Values for the @NAME@ placeholders. None leaves that key untouched."""
    terminal = ctx.terminal
    software = ctx.software

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
            "top bar: logo menu and the app's menus, media, clock in the centre, Astra Monitor; dock at the bottom",
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
        # The dock keeps what you already pinned and missing favourites go after
        # it, each only once: one you unpin later stays unpinned.
        current = current_favorites()
        added = ctx.state["favorites_added"]
        missing = []
        for slot in ctx.apps_config["favorites"]:
            app = apps.first_installed(slot)
            if app and app not in added and not any(a in current for a in slot):
                missing.append(app)
        ctx.state.add_unique("favorites_added", *missing)
        if missing:
            dconf.write(FAVORITES, current + missing)
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
