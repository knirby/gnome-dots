"""Reading, writing, backing up and restoring the dconf database.

Settings ship as dconf keyfiles (what `dconf dump` prints). A value written as
@NAME@ is a placeholder, filled in at apply time from machine-specific values
(the home folder, the detected terminal, sensors...) and rendered as GVariant.

Extension settings need no installed schema this way, so they can be written
before GNOME has ever loaded the extension.
"""

import re
import time
from pathlib import Path

from .. import ui, util
from ..paths import BACKUP_DIR
from . import gvariant

PLACEHOLDER = re.compile(r"^(\s*[A-Za-z0-9_-]+\s*=\s*)@([A-Z0-9_]+)@\s*$")


class TemplateError(KeyError):
    pass


def available() -> bool:
    return util.which("dconf") is not None


def render(text: str, values: dict) -> str:
    out = []
    for line in text.splitlines():
        m = PLACEHOLDER.match(line)
        if m:
            name = m.group(2)
            if name not in values:
                raise TemplateError(f"no value for @{name}@")
            value = values[name]
            if value is None:
                continue  # placeholder with nothing detected: leave the key alone
            line = m.group(1) + gvariant.dump(value)
        out.append(line)
    return "\n".join(out) + "\n"


def sections(text: str) -> dict[str, str]:
    """Split a keyfile into {"/dir/path/": "body"}."""
    result: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("[") and line.rstrip().endswith("]"):
            current = "/" + line.strip()[1:-1].strip("/") + "/"
            result.setdefault(current, [])
        elif current is not None and line.strip() and not line.lstrip().startswith("#"):
            result[current].append(line)
    return {k: "\n".join(v) for k, v in result.items()}


def keyfile(parts: dict[str, str]) -> str:
    return "\n\n".join(f"[{path.strip('/')}]\n{body}" for path, body in parts.items() if body) + "\n"


def load(text: str, root: str = "/") -> bool:
    proc = util.run(["dconf", "load", root], mutate=True, input=text)
    if proc.returncode != 0:
        ui.error(f"dconf load {root} failed: {(proc.stderr or '').strip()}")
    return proc.returncode == 0


def read(key: str) -> str | None:
    out = util.output(["dconf", "read", key])
    return out.strip() if out and out.strip() else None


def write(key: str, value, raw: bool = False) -> bool:
    """Write one key; raw=True passes value through as GVariant text."""
    text = value if raw else gvariant.dump(value)
    return util.run(["dconf", "write", key, text], mutate=True).returncode == 0


def reset_tree(path: str) -> None:
    util.run(["dconf", "reset", "-f", path], mutate=True)


def reset_shallow(path: str) -> None:
    """Reset the keys directly in path, leaving its subdirectories alone."""
    for entry in (util.output(["dconf", "list", path]) or "").split():
        if not entry.endswith("/"):
            util.run(["dconf", "reset", path + entry], mutate=True)


# -- backups ---------------------------------------------------------------

def backup(label: str = "manual") -> Path | None:
    """Dump the whole database to a timestamped backup folder; None if dconf
    can't read it."""
    name = time.strftime("%Y%m%d-%H%M%S") + f"-{label}"
    folder = BACKUP_DIR / name
    text = util.output(["dconf", "dump", "/"])
    if text is None:
        ui.error("dconf couldn't read the settings database")
        return None
    ui.action(f"back up dconf to {folder}")
    if ui.dry_run:
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dconf.ini").write_text(text)
    return folder


def list_backups() -> list[Path]:
    if not BACKUP_DIR.is_dir():
        return []
    return sorted(p for p in BACKUP_DIR.iterdir() if (p / "dconf.ini").is_file())


def restore(folder: Path, shallow_dirs: list[str], trees: list[str]) -> bool:
    """Put back the managed parts of a backup.

    Only the dirs this tool writes are touched: each is reset and refilled from
    the backup, so keys the tool added disappear and the old values return.
    Settings of anything else on the system are left as they are now.
    """
    saved = sections((folder / "dconf.ini").read_text())
    for tree in trees:
        reset_tree(tree)
    for d in shallow_dirs:
        reset_shallow(d)
    wanted = {}
    for path, body in saved.items():
        if path in shallow_dirs or any(path.startswith(t) for t in trees):
            wanted[path] = body
    return load(keyfile(wanted)) if wanted else True
