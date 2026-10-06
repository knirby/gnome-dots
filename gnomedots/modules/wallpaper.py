"""Bing wallpapers: today's picture right away, a new one every day after,
old ones trimmed once the folder passes its size limit (see wallpapers.py)."""

from .. import ui, wallpapers
from ..gnome import dconf
from .base import Module


def resolution(ctx) -> str:
    return "UHD" if ctx.hardware["widest_display"] > 1920 else "1920x1200"


class Wallpaper(Module):
    name = "wallpaper"
    title = "Bing wallpaper"
    summary = "today's Bing picture now, a new one daily, old ones kept up to 200 MB"
    needs_dconf = True
    needs_network = True

    def _settings(self, ctx) -> wallpapers.Settings:
        s = wallpapers.Settings(ctx.themes_config["wallpaper"], resolution(ctx))
        # The template sets the extension's folder and resolution; on a first
        # install those keys aren't written yet, so use this run's values.
        s.folder = ctx.wallpaper_dir()
        s.resolution = resolution(ctx)
        s.market = ctx.themes_config["wallpaper"]["market"]
        return s

    def plan(self, ctx):
        s = self._settings(ctx)
        return [f"Bing picture of the day ({s.market}, {s.resolution}) into {s.folder}",
                f"checked hourly, also after suspend; oldest pictures go past {s.limit // 2**20} MB"]

    def apply(self, ctx):
        s = self._settings(ctx)
        try:
            result = wallpapers.sync(s)
        except Exception as e:
            ui.warn(f"Could not fetch Bing pictures now ({e}); the hourly check will.")
        else:
            today = result["today"]
            if today and (today.exists() or ui.dry_run):
                ctx.vars["WALLPAPER_PATH"] = str(today)
                for key, value in (("picture-options", "zoom"), ("color-shading-type", "solid"),
                                   ("primary-color", "#ff7800"), ("secondary-color", "#000000")):
                    dconf.write(f"/org/gnome/desktop/background/{key}", value)
                ctx.state.add_unique("dconf_sections", "/org/gnome/desktop/background/")
                ui.ok(f"Wallpaper set to {today.name}")
        how = wallpapers.install_schedule()
        ui.ok(f"New pictures arrive through {how}")

    def remove(self, ctx):
        wallpapers.remove_schedule()
