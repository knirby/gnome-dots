"""Translucent header bars for GTK 4 apps, as a block in the user's gtk.css."""

from .. import blocks, ui
from ..paths import CONFIG_HOME
from .base import Module

TARGET = CONFIG_HOME / "gtk-4.0" / "gtk.css"


class GtkCss(Module):
    name = "gtk"
    title = "GTK 4 header bars"
    summary = "translucent header bars, added to ~/.config/gtk-4.0/gtk.css"

    def plan(self, ctx):
        return [f"add a marked block to {TARGET} (the rest of the file is kept)"]

    def apply(self, ctx):
        blocks.set_block(TARGET, ctx.config_text("gtk/gtk-4.0.css"), "css")
        ctx.state.add_unique("edited_files", str(TARGET))
        ui.ok("Header bar style added")

    def remove(self, ctx):
        if blocks.remove_block(TARGET, "css"):
            ui.ok(f"Removed the block from {TARGET}")
