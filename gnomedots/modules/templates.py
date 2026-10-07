"""File templates for Files' New Document menu (right-click > New Document),
which is empty on a fresh install: text, Markdown, office documents, and a
Code submenu of scripts and config files.

They go into the xdg-user-dirs Templates folder. Files lists that folder only
when it's set to something other than the home folder, so where it isn't set
it becomes ~/Templates. The hash of every file written is kept, so update
refreshes only templates still as shipped, uninstall removes only those, a
template you deleted stays deleted and one you already had is never touched.
Office templates are added only when an app opens that type.
"""

import hashlib
from pathlib import Path

from .. import ui, util
from ..paths import CONFIG_DIR, CONFIG_HOME, HOME, user_dir
from .base import Module

SOURCE = CONFIG_DIR / "templates"
OFFICE = {
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str | None:
    try:
        return digest(path.read_bytes())
    except OSError:
        return None


def has_handler(mime: str) -> bool:
    out = util.output(["gio", "mime", mime], timeout=10) or ""
    return "Default application" in out or "Registered applications:" in out


def target_dir() -> tuple[Path, bool]:
    """The Templates folder and whether it still has to be registered."""
    found = user_dir("TEMPLATES")
    return (found, False) if found else (HOME / "Templates", True)


def register(folder: Path) -> None:
    """Point xdg-user-dirs' TEMPLATES at folder."""
    if util.which("xdg-user-dirs-update"):
        util.run(["xdg-user-dirs-update", "--set", "TEMPLATES", str(folder)], mutate=True)
        return
    # GLib reads user-dirs.dirs itself, so the file alone is enough.
    dirs_file = CONFIG_HOME / "user-dirs.dirs"
    lines = [line for line in (util.read(dirs_file) or "").splitlines()
             if not line.startswith("XDG_TEMPLATES_DIR=")]
    lines.append(f'XDG_TEMPLATES_DIR="$HOME/{folder.relative_to(HOME)}"')
    util.write_text(dirs_file, "\n".join(lines) + "\n", 0o644)


class Templates(Module):
    name = "templates"
    title = "File templates"
    summary = "text, office and code files for Files' New Document menu, in ~/Templates"

    def _sources(self) -> list[tuple[str, Path]]:
        """(path relative to the Templates folder, source file) for each
        template whose type something on this machine opens."""
        rows = []
        for src in sorted(SOURCE.rglob("*")):
            if not src.is_file():
                continue
            mime = OFFICE.get(src.suffix)
            if mime and not has_handler(mime):
                continue
            rows.append((src.relative_to(SOURCE).as_posix(), src))
        return rows

    def _sort(self, ctx, folder: Path) -> tuple[list[str], list[str], list[str]]:
        """Templates to add, to refresh, and ones that are yours and kept."""
        add, refresh, kept = [], [], []
        written = ctx.state["templates"]
        for rel, src in self._sources():
            target = folder / rel
            ours = written.get(rel)
            current = file_digest(target)
            if current is None:
                if not ours:              # removed by you: stays removed
                    add.append(rel)
            elif ours and current == ours:
                if current != digest(src.read_bytes()):
                    refresh.append(rel)
            else:
                kept.append(rel)
        return add, refresh, kept

    def plan(self, ctx):
        folder, unset = target_dir()
        add, refresh, kept = self._sort(ctx, folder)
        lines = []
        if unset:
            lines.append(f"make {folder} the Templates folder (none is set, so New Document is hidden)")
        if add:
            lines.append(f"add {len(add)} templates to {folder}: " + ", ".join(Path(r).stem for r in add))
        if refresh:
            lines.append("update " + ", ".join(Path(r).stem for r in refresh))
        if kept:
            lines.append("keep your own " + ", ".join(Path(r).name for r in kept))
        return lines or [f"templates in {folder} are up to date"]

    def apply(self, ctx):
        folder, unset = target_dir()
        if unset:
            register(folder)
        add, refresh, kept = self._sort(ctx, folder)
        sources = dict(self._sources())
        for rel in add + refresh:
            data = sources[rel].read_bytes()
            mode = 0o755 if data.startswith(b"#!") else 0o644
            util.write_bytes(folder / rel, data, mode)
            ctx.state["templates"][rel] = digest(data)
        for rel in kept:
            ui.info(f"{rel}: keeping your own")
        ui.ok(f"{len(add)} templates added, {len(refresh)} updated" if add or refresh
              else "Templates up to date")

    def remove(self, ctx):
        folder, _ = target_dir()
        written = ctx.state["templates"]
        for rel, ours in list(written.items()):
            target = folder / rel
            if file_digest(target) == ours:
                util.remove_tree(target)
            written.pop(rel)
        # Subfolders it made (Code), once nothing of yours is in them.
        for sub in sorted({p for p in SOURCE.rglob("*") if p.is_dir()}, reverse=True):
            d = folder / sub.relative_to(SOURCE)
            if d.is_dir() and not any(d.iterdir()) and not ui.dry_run:
                d.rmdir()
