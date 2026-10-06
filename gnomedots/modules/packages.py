"""System packages: fonts, themes, tools the extensions use."""

from .. import ui, util
from .base import Module
from .themes import theme_present

# Commands that must exist for the rest of the setup, by required package.
REQUIRED_COMMANDS = {"dconf": "dconf", "glib-tools": "glib-compile-schemas",
                     "make": "make", "gettext": "msgfmt"}


class Packages(Module):
    name = "packages"
    title = "System packages"
    summary = "fonts, themes and helper tools from the distribution's repositories"

    def _plan(self, ctx) -> dict:
        if "_packages" in ctx.vars:
            return ctx.vars["_packages"]
        plan = {"install": [], "missing_required": [], "unpackaged": []}
        ctx.vars["_packages"] = plan
        backend = ctx.backend
        family = backend.family if backend else None
        entries = []
        for role, entry in ctx.packages_config.items():
            if entry.get("module") and entry["module"] not in ctx.selected:
                continue
            if entry.get("theme") and theme_present(entry["theme"]):
                continue
            pkg = entry.get(family) if family else None
            if not pkg:
                if entry.get("required") and not util.which(REQUIRED_COMMANDS.get(role, role)):
                    plan["missing_required"].append(role)
                else:
                    plan["unpackaged"].append(role)
                continue
            entries.append((role, entry, pkg))
        if not backend:
            return plan
        wanted = sorted({pkg for _, _, pkg in entries if not backend.is_installed(pkg)})
        can = backend.available(wanted) if wanted else set()
        seen = set()
        for role, entry, pkg in entries:
            if pkg not in wanted or pkg in seen:
                continue
            if pkg in can:
                plan["install"].append((pkg, entry.get("why", role)))
                seen.add(pkg)
            elif entry.get("required"):
                plan["missing_required"].append(role)
        return plan

    def pending(self, ctx) -> list[str]:
        """Packages apply() would install."""
        return [p for p, _ in self._plan(ctx)["install"]] if ctx.backend else []

    def plan(self, ctx):
        if not ctx.backend:
            why = "an image-based system" if ctx.distro.ostree else "no supported package manager"
            return [f"skipped: {why}; fonts and tools must already be installed"]
        plan = self._plan(ctx)
        lines = [f"{pkg} ({why})" for pkg, why in plan["install"]]
        return lines or ["everything needed is already installed"]

    def apply(self, ctx):
        backend = ctx.backend
        plan = self._plan(ctx)
        if not backend:
            missing = [c for c in REQUIRED_COMMANDS.values() if not util.which(c)]
            if missing:
                raise RuntimeError(f"missing {', '.join(missing)} and no way to install it; install it and rerun")
            ui.warn("Skipping system packages; fonts and themes come from wherever they already are.")
            return
        pkgs = [p for p, _ in plan["install"]]
        if not pkgs:
            ui.ok("Everything needed is already installed")
            return
        ui.step(f"Installing with {backend.name}: {' '.join(pkgs)}")
        backend.refresh()
        if not backend.install(pkgs):
            ui.warn("Installing them together failed; trying one at a time.")
            for p in pkgs:
                if not backend.install([p]):
                    ui.warn(f"Could not install {p}")
        if not ui.dry_run:
            added = [p for p in pkgs if backend.is_installed(p)]
            ctx.state.add_unique("packages_added", *added)
            missing = [p for p in pkgs if p not in added]
            if missing:
                ui.warn(f"Not installed: {', '.join(missing)}")
            else:
                ui.ok(f"Installed {len(added)} package(s)")
        ctx.refresh_apps()
        for role, cmd in REQUIRED_COMMANDS.items():
            if not ui.dry_run and not util.which(cmd):
                raise RuntimeError(f"`{cmd}` is still missing after installing packages")

    def remove(self, ctx):
        added = ctx.state.get("packages_added", [])
        if not added or not ctx.backend:
            return
        ui.info(f"Packages this tool installed: {' '.join(added)}")
        ui.warn("Other software may depend on them now.")
        if ui.confirm("Remove these packages too?", False):
            if ctx.backend.remove(added):
                ctx.state["packages_added"] = []
