"""GNOME Shell extensions: install or update them, switch them on, and switch
off the ones that conflict."""

from .. import ui
from ..gnome import dconf
from ..gnome import extensions as ext
from .base import Module


def github_ref(e: dict, shell_major: int) -> str | None:
    """The pinned commit, else the head of the first listed branch, whose
    metadata.json supports this GNOME Shell; None when none does."""
    for ref in [e["commit"]] if e.get("commit") else e.get("branches", ["main"]):
        sha = ref if e.get("commit") else ext.github_head(e["repo"], ref)
        if sha and ext.supports(ext.github_metadata(e["repo"], sha), shell_major):
            return sha
    return None


class Extensions(Module):
    name = "extensions"
    title = "GNOME Shell extensions"
    summary = "ArcMenu, Blur my Shell, Dash to Dock, Astra Monitor and the rest"
    needs_dconf = True
    needs_network = True

    def _status(self, ctx) -> list[dict]:
        if "_extensions" in ctx.vars:
            return ctx.vars["_extensions"]
        rows = []
        for e in ctx.extensions:
            uuid = e["uuid"]
            row = {"entry": e, "uuid": uuid, "name": e["name"], "have": ext.installed_version(uuid),
                   "user_copy": ext.user_dir(uuid).exists()}
            if e["source"] == "ego":
                info = ext.ego_info(uuid, ctx.shell_major)
                row["info"] = info
                row["want"] = info.get("version") if info else None
                user_meta = ext.metadata(uuid) if row["user_copy"] else None
                current = user_meta.get("version") if user_meta else None
                if e.get("pin_version") and current == e["pin_version"]:
                    # pinned: the metadata says 9999, the state knows what's really there
                    current = ctx.state["extensions"].get(uuid, {}).get("version")
                # Copies an older version unpacked lost their file modes;
                # reinstall those once.
                record = ctx.state["extensions"].get(uuid, {})
                stale = record and not record.get("preexisting") and not record.get("modes")
                row["action"] = ("unavailable" if not info else
                                 "ok" if row["user_copy"] and current == row["want"] and not stale else
                                 "update" if row["user_copy"] else "install")
            else:
                head = github_ref(e, ctx.shell_major)
                row["want"] = head
                known = ctx.state["extensions"].get(uuid, {}).get("version")
                row["action"] = ("unavailable" if not head else
                                 "ok" if row["user_copy"] and known == head else
                                 "update" if row["user_copy"] else "install")
            rows.append(row)
        ctx.vars["_extensions"] = rows
        return rows

    def plan(self, ctx):
        lines = []
        for r in self._status(ctx):
            want = r["want"]
            label = want[:8] if isinstance(want, str) else f"v{want}"
            lines.append({
                "install": f"{r['name']}: install {label}",
                "update": f"{r['name']}: update to {label}",
                "ok": f"{r['name']}: up to date",
                "unavailable": f"{r['name']}: no build for GNOME {ctx.shell_major}, skipped",
            }[r["action"]])
        present = [u for u in ctx.conflicts if ext.find(u) or u in ext.enabled()]
        if present:
            lines.append("disable conflicting: " + ", ".join(present))
        return lines

    def apply(self, ctx, force_reinstall: bool = False):
        installed = []
        for r in self._status(ctx):
            uuid, e = r["uuid"], r["entry"]
            record = ctx.state["extensions"].setdefault(
                uuid, {"source": e["source"], "preexisting": r["user_copy"]})
            if r["action"] == "unavailable":
                ui.warn(f"{r['name']}: nothing published for GNOME {ctx.shell_major}; skipped")
                continue
            if r["action"] == "ok" and not force_reinstall:
                ui.ok(f"{r['name']} is up to date")
                installed.append(uuid)
                continue
            try:
                if e["source"] == "ego":
                    record["version"] = ext.install_from_ego(uuid, ctx.shell_major, r["info"])
                    record["modes"] = True
                else:
                    ext.install_from_github(uuid, e["repo"], r["want"], e.get("build"), e.get("artifact"))
                    record["version"] = r["want"]
                if e.get("pin_version"):
                    ext.pin_version(uuid, e["pin_version"])
            except Exception as err:
                ui.error(f"{r['name']}: {err}")
                ctx.failures.append(f"extension {r['name']}")
                continue
            installed.append(uuid)
            ui.ok(f"{r['name']} {'updated' if r['action'] == 'update' else 'installed'}")
        conflicts = [u for u in ctx.conflicts if ext.find(u) or u in ext.enabled()]
        ext.set_enabled(installed, conflicts)
        if conflicts:
            ui.ok("Disabled conflicting: " + ", ".join(conflicts))
        ui.ok(f"{len(installed)} extensions enabled from the next login")
        ctx.vars.pop("_extensions", None)

    def remove(self, ctx):
        ours = [u for u, rec in ctx.state["extensions"].items() if not rec.get("preexisting")]
        ext.set_enabled([], ours)
        # Drop them from disabled-extensions too, so no stale entries remain.
        dconf.write("/org/gnome/shell/disabled-extensions", [u for u in ext.disabled() if u not in ours])
        for uuid in ours:
            ext.remove_user_copy(uuid)
            ctx.state["extensions"].pop(uuid, None)
        if ours:
            ui.ok(f"Removed {len(ours)} extensions")
