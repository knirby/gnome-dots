"""Which distribution this is and which package manager serves GNOME.

Support is a whitelist of distribution families. A distribution counts when
its os-release ID (or one of its ID_LIKE parents) is in a family and that
family's package manager is present. An unknown distribution that still has
one of these package managers is "untested": the installer asks before using
it.

On Bedrock Linux the package manager that matters is the one of the stratum
providing gnome-shell, so packages land where GNOME can see them; every
package command is wrapped in `strat <stratum>`.
"""

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .. import util

# family -> (package manager binary, os-release IDs)
FAMILIES: dict[str, tuple[str, frozenset[str]]] = {
    "apt": ("apt-get", frozenset({
        "debian", "ubuntu", "linuxmint", "pop", "elementary", "zorin", "kali",
        "raspbian", "neon", "pureos", "devuan", "mx", "deepin", "tuxedo",
    })),
    "dnf": ("dnf", frozenset({
        "fedora", "rhel", "centos", "rocky", "almalinux", "nobara", "ultramarine",
    })),
    "pacman": ("pacman", frozenset({
        "arch", "endeavouros", "manjaro", "cachyos", "garuda", "artix", "arcolinux",
    })),
    "portage": ("emerge", frozenset({"gentoo", "funtoo", "calculate"})),
    "xbps": ("xbps-install", frozenset({"void"})),
}

FAMILY_NAMES = {
    "apt": "Debian/Ubuntu (apt)",
    "dnf": "Fedora/RHEL (dnf)",
    "pacman": "Arch (pacman)",
    "portage": "Gentoo (emerge)",
    "xbps": "Void (xbps)",
}


@dataclass
class Distro:
    id: str = "linux"
    id_like: list[str] = field(default_factory=list)
    name: str = "Linux"
    pretty: str = "Linux"
    version_id: str = ""
    family: str | None = None      # whitelisted family, if any
    guessed: str | None = None     # family of a package manager found on an unknown distro
    bedrock: bool = False
    stratum: str | None = None     # Bedrock stratum providing gnome-shell
    root: Path = Path("/")         # where that stratum's files are seen from here
    ostree: bool = False           # image-based (Silverblue, Kinoite...): no dnf installs

    @property
    def supported(self) -> bool:
        return self.family is not None

    @property
    def strat_prefix(self) -> list[str]:
        return ["strat", self.stratum] if self.bedrock and self.stratum else []

    def describe(self) -> str:
        text = self.pretty
        if self.bedrock:
            text = f"Bedrock Linux, GNOME from the {self.stratum or '?'} stratum ({self.pretty})"
        if self.ostree:
            text += ", image-based"
        return text


def parse_os_release(path: Path) -> dict[str, str]:
    values = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                try:
                    values[key.strip()] = shlex.split(value)[0] if value.strip() else ""
                except ValueError:
                    values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return values


def _root_has(root: Path, binary: str) -> bool:
    if root == Path("/"):
        return util.which(binary) is not None
    return any((root / d / binary).exists() for d in ("usr/bin", "bin", "usr/sbin", "sbin"))


def detect() -> Distro:
    root = Path("/")
    d = Distro()
    if Path("/bedrock/etc/bedrock-release").exists():
        d.bedrock = True
        out = util.output(["brl", "which", "gnome-shell"]) or ""
        d.stratum = out.strip().splitlines()[0] if out.strip() else None
        if d.stratum:
            candidate = Path("/bedrock/strata") / d.stratum
            if candidate.is_dir():
                root = candidate
    d.root = root

    # Bedrock rewrites a hijacked stratum's /etc/os-release; the vendor's copy
    # in /usr/lib keeps the real name.
    order = ["usr/lib/os-release", "etc/os-release"] if d.bedrock else ["etc/os-release", "usr/lib/os-release"]
    rel = next((r for r in (parse_os_release(root / f) for f in order) if r), {})
    d.id = rel.get("ID", "linux").lower()
    d.id_like = rel.get("ID_LIKE", "").lower().split()
    d.name = rel.get("NAME", "Linux")
    d.pretty = rel.get("PRETTY_NAME", d.name)
    d.version_id = rel.get("VERSION_ID", "")
    d.ostree = Path("/run/ostree-booted").exists()

    for ident in [d.id, *d.id_like]:
        for family, (binary, ids) in FAMILIES.items():
            if ident in ids and _root_has(root, binary):
                d.family = family
                return d
    for family, (binary, _) in FAMILIES.items():
        if _root_has(root, binary):
            d.guessed = family
            break
    return d
