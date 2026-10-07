"""The GNOME Rounded Blur library: without it, Blur my Shell's dynamic blur
(panel, dock, popups) has square corners.

No distribution packages it except through the AUR and a Fedora COPR, and it
must match the running Mutter exactly, so it's built from a pinned commit
against this machine's libmutter and installed to /usr, as the upstream guide
does. A copy that's already there (a package, a manual build) is used as is.
The build is redone by `update` when GNOME's major version changes.
"""

import io
import re
import tarfile
import tempfile
from pathlib import Path

from .. import ui, util
from ..paths import CACHE_DIR
from ..system import privilege
from .base import Module

TYPELIB = "girepository-1.0/Blur-1.0.typelib"
LIBDIRS = ["usr/lib64", "usr/lib", "usr/lib/*-linux-gnu", "usr/local/lib64", "usr/local/lib",
           "usr/local/lib/*-linux-gnu"]


def installed(root: Path) -> list[Path]:
    return [p for d in LIBDIRS for p in root.glob(f"{d}/{TYPELIB}")]


def retarget(meson_build: str, shell_major: int, mutter_api: int) -> str:
    """Point the build at this machine's libmutter instead of the one the
    commit names (the upstream install script makes the same edits)."""
    text = re.sub(r"mutter_api_version = '\d+'", f"mutter_api_version = '{mutter_api}'", meson_build)
    text = re.sub(r"mutter_req = '>= [\d.]+'", f"mutter_req = '>= {shell_major}.0'", text)
    return re.sub(r"dependency\('libmutter-\d+'\)", "dependency('libmutter-' + mutter_api_version)", text)


class RoundedBlur(Module):
    name = "rounded-blur"
    title = "Rounded corners for Blur my Shell"
    summary = "the GNOME Rounded Blur library, built for this GNOME, so blur has rounded corners"
    needs_network = True

    def needs_root(self, ctx) -> bool:
        return self._status(ctx) in ("build", "rebuild")

    def wants_packages(self, ctx) -> bool:
        return self.needs_root(ctx)   # build tools only when building

    def _status(self, ctx) -> str:
        """ok, rebuild, build or unsupported."""
        if ctx.shell_major > 50:
            return "unsupported"
        record = ctx.state.get("rounded_blur")
        if record:
            return "ok" if record.get("shell") == ctx.shell_major else "rebuild"
        return "ok" if installed(ctx.distro.root) else "build"

    def plan(self, ctx):
        cfg = ctx.toml("extensions.toml")["rounded-blur"]
        return [{
            "ok": "already installed",
            "rebuild": f"rebuild for GNOME {ctx.shell_major} (libmutter-{ctx.mutter_api}), needs root",
            "build": f"build {cfg['repo']} at {cfg['commit'][:8]} for libmutter-{ctx.mutter_api} "
                     "and install it to /usr, needs root",
            "unsupported": f"no build for GNOME {ctx.shell_major} yet, skipped; blur keeps square corners",
        }[self._status(ctx)]]

    def apply(self, ctx):
        status = self._status(ctx)
        if status == "ok":
            ui.ok("GNOME Rounded Blur is installed")
            return
        if status == "unsupported":
            ui.warn(f"GNOME Rounded Blur has no build for GNOME {ctx.shell_major} yet; blur keeps square corners")
            return
        root = self._root(ctx)
        if root is None:
            raise RuntimeError("installing it needs sudo, doas or run0")
        cfg = ctx.toml("extensions.toml")["rounded-blur"]
        strat = ctx.distro.strat_prefix
        ui.step(f"Building GNOME Rounded Blur for libmutter-{ctx.mutter_api}")
        ui.action(f"build {cfg['repo']} at {cfg['commit'][:8]} and install it to /usr")
        if ui.dry_run:
            return
        if status == "rebuild":
            self.remove(ctx)
        data = util.http_get(f"https://codeload.github.com/{cfg['repo']}/tar.gz/{cfg['commit']}", timeout=120)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Root writes the install log into the build folder; cleaning up
        # around that is fine.
        with tempfile.TemporaryDirectory(dir=CACHE_DIR, prefix="rounded-blur-", ignore_cleanup_errors=True) as tmp:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                try:
                    tf.extractall(tmp, filter="data")
                except TypeError:  # Python without extraction filters
                    tf.extractall(tmp)
            src = next(p for p in Path(tmp).iterdir() if p.is_dir())
            meson_build = src / "meson.build"
            meson_build.write_text(retarget(meson_build.read_text(), ctx.shell_major, ctx.mutter_api))
            build = src / "build"
            for cmd in (["meson", "setup", str(build), str(src), "--prefix=/usr", "--buildtype=release"],
                        ["meson", "compile", "-C", str(build)]):
                util.run([*strat, *cmd], env={"LC_ALL": "C"}, timeout=600, check=True)
            util.run([*root, "meson", "install", "-C", str(build), "--no-rebuild", "--quiet"],
                     capture=False, timeout=300, check=True)
            files = [line for line in (build / "meson-logs" / "install-log.txt").read_text().splitlines()
                     if line.startswith("/")]
        util.run([*root, "ldconfig"])
        ctx.state["rounded_blur"] = {"shell": ctx.shell_major, "commit": cfg["commit"], "files": files}
        ui.ok("GNOME Rounded Blur installed; Blur my Shell uses it from the next login")

    def remove(self, ctx):
        """Remove only what this tool's own build installed."""
        record = ctx.state.get("rounded_blur")
        if not record:
            return
        root = self._root(ctx)
        if root is None:
            ui.warn("Can't get root to remove GNOME Rounded Blur: " + " ".join(record["files"]))
            return
        util.run([*root, "rm", "-f", *record["files"]], mutate=True)
        util.run([*root, "ldconfig"], mutate=True)
        if not ui.dry_run:
            ctx.state.data.pop("rounded_blur", None)

    @staticmethod
    def _root(ctx) -> list[str] | None:
        pre = privilege.prefix()
        return None if pre is None else pre + ctx.distro.strat_prefix
