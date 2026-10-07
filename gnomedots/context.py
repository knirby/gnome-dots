"""Everything a module needs to know about this run and this machine."""

import tomllib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import hardware, paths
from .gnome import apps
from .state import State
from .system import distro as distro_mod
from .system import privilege, session
from .system.packages import Backend, backend_for


@dataclass
class Options:
    assume_yes: bool = False
    dry_run: bool = False
    force: bool = False
    skip: set[str] = field(default_factory=set)
    only: set[str] = field(default_factory=set)
    with_: set[str] = field(default_factory=set)   # opt-in addons to include


class Context:
    def __init__(self, options: Options, state: State | None = None):
        self.options = options
        self.state = state or State.load()
        self.vars: dict = {}
        self.failures: list[str] = []
        self.allow_untested_pm = False
        self.selected: set[str] = set()   # modules taking part in this run

    # -- configuration files ---------------------------------------------

    def toml(self, name: str) -> dict:
        with open(paths.CONFIG_DIR / name, "rb") as f:
            return tomllib.load(f)

    def config_text(self, relative: str) -> str:
        return (paths.CONFIG_DIR / relative).read_text()

    @cached_property
    def extensions(self) -> list[dict]:
        return self.toml("extensions.toml")["extension"]

    @cached_property
    def conflicts(self) -> list[str]:
        return self.toml("extensions.toml").get("conflicts", {}).get("uuids", [])

    @cached_property
    def apps_config(self) -> dict:
        return self.toml("apps.toml")

    @cached_property
    def themes_config(self) -> dict:
        return self.toml("themes.toml")

    @cached_property
    def packages_config(self) -> dict:
        return self.toml("packages.toml")

    # -- the machine -----------------------------------------------------

    @cached_property
    def distro(self) -> distro_mod.Distro:
        return distro_mod.detect()

    @cached_property
    def shell_version(self) -> tuple[int, int] | None:
        return session.shell_version()

    @property
    def shell_major(self) -> int:
        return self.shell_version[0] if self.shell_version else 0

    @property
    def mutter_api(self) -> int:
        """libmutter's API number: 16 for GNOME 48, 18 for GNOME 50."""
        return self.shell_major - 32

    @cached_property
    def backend(self) -> Backend | None:
        family = self.distro.family or (self.distro.guessed if self.allow_untested_pm else None)
        if not family or self.distro.ostree:
            return None
        root = privilege.prefix()
        if root is None:
            return None
        return backend_for(self.distro, root, family)

    @cached_property
    def hardware(self) -> dict:
        return hardware.summary()

    # -- resolved apps ---------------------------------------------------

    @cached_property
    def terminal(self) -> dict | None:
        return apps.resolve(self.apps_config.get("terminal", []))

    @cached_property
    def software(self) -> dict | None:
        return apps.resolve(self.apps_config.get("software", []))

    @cached_property
    def extensions_app(self) -> str | None:
        hit = apps.resolve(self.apps_config.get("extensions", []))
        return hit["desktop"] if hit else None

    def refresh_apps(self) -> None:
        """Forget resolved apps (after packages were installed)."""
        for name in ("terminal", "software", "extensions_app"):
            self.__dict__.pop(name, None)

    def wants(self, module, default: bool = True) -> bool:
        if self.options.only:
            return module in self.options.only
        if module in self.options.skip:
            return False
        return default or module in self.options.with_

    def wallpaper_dir(self) -> Path:
        return paths.pictures_dir() / self.themes_config["wallpaper"]["folder"]
