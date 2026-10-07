"""What this tool has done to the machine, so update and uninstall can undo it
exactly: extensions and themes it added, packages it installed, files it
edited and the backup taken before the first install."""

import json
import time

from . import __version__, ui
from .paths import STATE_FILE


class State:
    def __init__(self, data: dict | None = None):
        self.data = data or {}
        d = self.data
        d.setdefault("version", __version__)
        d.setdefault("commit", None)
        d.setdefault("installed_at", None)
        d.setdefault("updated_at", None)
        d.setdefault("initial_backup", None)
        d.setdefault("extensions", {})       # uuid -> {source, version, preexisting}
        d.setdefault("packages_added", [])   # names the tool installed itself
        d.setdefault("themes", {})           # theme name -> path it downloaded to
        d.setdefault("edited_files", [])     # files holding a marked block
        d.setdefault("templates", {})        # template path -> sha256 of what it wrote
        d.setdefault("dconf_sections", [])   # dconf dirs it wrote, shallow
        d.setdefault("dconf_trees", [])      # dconf dirs it reset and wrote, recursive
        d.setdefault("modules", [])          # modules applied at least once
        d.setdefault("config_hash", None)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def add_unique(self, key: str, *values) -> None:
        for v in values:
            if v not in self.data[key]:
                self.data[key].append(v)

    @property
    def installed(self) -> bool:
        return bool(self.data.get("installed_at"))

    @classmethod
    def load(cls) -> "State":
        try:
            return cls(json.loads(STATE_FILE.read_text()))
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        if ui.dry_run:
            return
        self.data["version"] = __version__
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        tmp.replace(STATE_FILE)

    def stamp(self, key: str) -> None:
        self.data[key] = time.strftime("%Y-%m-%dT%H:%M:%S")
