"""Header bar styling for GTK apps, as blocks in the user's gtk.css files.

GTK 4 gets translucent header bars. GTK 3 gets round, padded window buttons,
which is also what Chromium, Electron and libdecor windows draw on Wayland.
"""

from .. import blocks, ui
from ..paths import CONFIG_HOME
from .base import Module

# (config file, user file)
FILES = (
    ("gtk/gtk-4.0.css", CONFIG_HOME / "gtk-4.0" / "gtk.css"),
    ("gtk/gtk-3.0.css", CONFIG_HOME / "gtk-3.0" / "gtk.css"),
)
TARGETS = tuple(target for _, target in FILES)


class GtkCss(Module):
    name = "gtk"
    title = "GTK header bars"
    summary = "translucent GTK 4 header bars and round window buttons, added to the gtk.css files"

    def plan(self, ctx):
        return [f"add a marked block to {target} (the rest of the file is kept)" for target in TARGETS]

    def apply(self, ctx):
        for source, target in FILES:
            blocks.set_block(target, ctx.config_text(source), "css")
            ctx.state.add_unique("edited_files", str(target))
        ui.ok("Header bar and window button styles added")

    def remove(self, ctx):
        for target in TARGETS:
            if blocks.remove_block(target, "css"):
                ui.ok(f"Removed the block from {target}")
