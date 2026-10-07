"""The shape every setup step shares."""

from ..context import Context


class Module:
    name = ""
    title = ""
    summary = ""
    needs_dconf = False      # writes settings, so needs dconf and a session bus
    needs_network = False
    default = True           # False: opt-in addon, only run when asked for

    def needs_root(self, ctx: Context) -> bool:
        """Whether apply() will run something as root, so the password is
        asked for once, up front."""
        return False

    def wants_packages(self, ctx: Context) -> bool:
        """Whether this run needs the packages tied to this module in
        packages.toml (`module = ...`)."""
        return True

    def plan(self, ctx: Context) -> list[str]:
        """What apply() would change, one line per item, for the confirmation."""
        return []

    def apply(self, ctx: Context) -> None:
        raise NotImplementedError

    def remove(self, ctx: Context) -> None:
        """Undo apply() during uninstall. Settings are undone by the backup restore."""
