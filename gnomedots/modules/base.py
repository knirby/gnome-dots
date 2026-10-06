"""The shape every setup step shares."""

from ..context import Context


class Module:
    name = ""
    title = ""
    summary = ""
    needs_dconf = False      # writes settings, so needs dconf and a session bus
    needs_network = False

    def plan(self, ctx: Context) -> list[str]:
        """What apply() would change, one line per item, for the confirmation."""
        return []

    def apply(self, ctx: Context) -> None:
        raise NotImplementedError

    def remove(self, ctx: Context) -> None:
        """Undo apply() during uninstall. Settings are undone by the backup restore."""
