"""Getting root for package installs, and only for them."""

import os

from .. import util

_TOOLS = ("sudo", "doas", "run0", "pkexec")


def prefix() -> list[str] | None:
    """The command prefix that runs a command as root, or None if there is none."""
    if os.geteuid() == 0:
        return []
    for tool in _TOOLS:
        if util.which(tool):
            return [tool]
    return None


def warm_up(pre: list[str]) -> bool:
    """Ask for the password once, up front, rather than mid-install; False
    when root can't be had."""
    if not pre:
        return True
    cmd = ["sudo", "-v"] if pre == ["sudo"] else [*pre, "true"]
    return util.run(cmd, capture=False).returncode == 0
