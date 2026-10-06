"""Icon and cursor themes, downloaded from upstream when the distribution
doesn't package them."""

import tarfile
from pathlib import Path, PurePosixPath

from .. import ui, util
from ..paths import CACHE_DIR, HOME, ICONS_DIR, data_dirs
from .base import Module


def icon_dirs() -> list[Path]:
    return [HOME / ".icons", *(d / "icons" for d in data_dirs())]


def theme_present(name: str) -> bool:
    return any((d / name / "index.theme").is_file() for d in icon_dirs())


def _extract(archive: Path, prefix: str, folders: list[str]) -> list[str]:
    pp = PurePosixPath(prefix).parts if prefix else ()
    done = set()
    with tarfile.open(archive) as tf:
        members = []
        for m in tf.getmembers():
            parts = PurePosixPath(m.name).parts
            # Archives either hold the theme folders at the top or under a
            # single versioned folder (repo-1.2.3/usr/share/icons/...).
            for start in (0, 1):
                head = parts[start:start + len(pp)]
                rest = parts[start + len(pp):]
                if head == pp and rest and rest[0] in folders:
                    m.name = str(PurePosixPath(*rest))
                    members.append(m)
                    done.add(rest[0])
                    break
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        for folder in done:
            util.remove_tree(ICONS_DIR / folder)
        try:
            tf.extractall(ICONS_DIR, members=members, filter="data")
        except TypeError:  # Python without extraction filters
            tf.extractall(ICONS_DIR, members=members)
    return sorted(done)


class Themes(Module):
    name = "themes"
    title = "Icon and cursor themes"
    summary = "Mint-Y-Grey icons and the Bibata Modern Ice cursor"
    needs_network = True

    def plan(self, ctx):
        lines = []
        for t in ctx.themes_config["theme"]:
            if theme_present(t["name"]):
                lines.append(f"{t['name']}: already installed")
            else:
                lines.append(f"{t['name']}: from the distribution, else downloaded ({t['size']})")
        return lines

    def apply(self, ctx):
        for t in ctx.themes_config["theme"]:
            name = t["name"]
            if theme_present(name):
                ui.ok(f"{name} is installed")
                continue
            ui.step(f"Downloading {name} ({t['size']})")
            ui.action(f"download {t['url']} into {ICONS_DIR}")
            if ui.dry_run:
                continue
            archive = CACHE_DIR / Path(t["url"]).name
            try:
                util.download(t["url"], archive, timeout=600)
                got = _extract(archive, t.get("prefix", ""), t["folders"])
            finally:
                archive.unlink(missing_ok=True)
            missing = set(t["folders"]) - set(got)
            if missing:
                raise RuntimeError(f"{name}: the download lacked {', '.join(sorted(missing))}")
            for folder in got:
                ctx.state["themes"][folder] = str(ICONS_DIR / folder)
                if util.which("gtk-update-icon-cache"):
                    util.run(["gtk-update-icon-cache", "-qf", str(ICONS_DIR / folder)])
            ui.ok(f"{name} installed in {ICONS_DIR}")

    def remove(self, ctx):
        for folder, path in list(ctx.state["themes"].items()):
            p = Path(path)
            if p.parent == ICONS_DIR:
                util.remove_tree(p)
            ctx.state["themes"].pop(folder, None)
