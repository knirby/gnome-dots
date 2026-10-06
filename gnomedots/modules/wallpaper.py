"""Today's Bing picture as the wallpaper right away. The Wallpaper Slideshow
extension keeps downloading and cycling them after the next login."""

import urllib.parse

from .. import ui, util
from ..gnome import dconf
from .base import Module

BING = "https://www.bing.com"


def resolution(ctx) -> str:
    return "UHD" if ctx.hardware["widest_display"] > 1920 else "1920x1200"


def file_name(urlbase: str, res: str) -> str:
    # The name Wallpaper Slideshow gives the same picture, so it isn't fetched twice.
    pretty = urlbase.rsplit("/", 1)[-1].replace("th?id=OHR.", "").split("_")[0]
    return f"{pretty}-{res}.jpg"


class Wallpaper(Module):
    name = "wallpaper"
    title = "Bing wallpaper"
    summary = "today's Bing picture now; the slideshow extension keeps them coming"
    needs_dconf = True
    needs_network = True

    def plan(self, ctx):
        market = ctx.themes_config["wallpaper"]["market"]
        return [f"Bing picture of the day ({market}, {resolution(ctx)}) into {ctx.wallpaper_dir()}"]

    def apply(self, ctx):
        folder = ctx.wallpaper_dir()
        market = ctx.themes_config["wallpaper"]["market"]
        res = resolution(ctx)
        ui.action(f"mkdir {folder}")
        if not ui.dry_run:
            folder.mkdir(parents=True, exist_ok=True)
        try:
            query = urllib.parse.urlencode({"format": "js", "idx": 0, "n": 1, "mkt": market})
            image = util.http_json(f"{BING}/HPImageArchive.aspx?{query}", timeout=20)["images"][0]
            target = folder / file_name(image["urlbase"], res)
            if not target.exists():
                ui.action(f"download {image['urlbase']}_{res}.jpg")
                if not ui.dry_run:
                    util.download(f"{BING}{image['urlbase']}_{res}.jpg", target)
        except Exception as e:
            ui.warn(f"Could not fetch today's Bing picture ({e}); the slideshow will after login.")
            return
        ctx.vars["WALLPAPER_PATH"] = str(target)
        uri = target.as_uri()
        for key, value in (("picture-uri", uri), ("picture-uri-dark", uri),
                           ("picture-options", "zoom"), ("color-shading-type", "solid"),
                           ("primary-color", "#ff7800"), ("secondary-color", "#000000")):
            dconf.write(f"/org/gnome/desktop/background/{key}", value)
        ctx.state.add_unique("dconf_sections", "/org/gnome/desktop/background/")
        ui.ok(f"Wallpaper set to {target.name}")
