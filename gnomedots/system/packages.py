"""Package manager backends behind one small interface.

Each backend answers three questions (is it installed, can the repositories
provide it, install/remove these) for one package manager. Queries run as the
user; installs and removals run through the privilege prefix. On Bedrock both
are wrapped in `strat <stratum>`.
"""

from .. import ui, util
from .distro import Distro


class Backend:
    family = ""
    name = ""

    def __init__(self, distro: Distro, root_prefix: list[str]):
        self.strat = distro.strat_prefix
        self.root = root_prefix + self.strat
        self.refreshed = False

    def q(self, *cmd: str) -> int:
        return util.run([*self.strat, *cmd], timeout=180).returncode

    def is_installed(self, pkg: str) -> bool:
        raise NotImplementedError

    def is_available(self, pkg: str) -> bool:
        raise NotImplementedError

    def available(self, pkgs: list[str]) -> set[str]:
        """The subset of pkgs the repositories can provide."""
        return {p for p in pkgs if self.is_available(p)}

    def refresh(self) -> bool:
        """Refresh the repository index, where the package manager wants it."""
        return True

    def install(self, pkgs: list[str]) -> bool:
        raise NotImplementedError

    def remove(self, pkgs: list[str]) -> bool:
        raise NotImplementedError


class Apt(Backend):
    family, name = "apt", "apt"

    def is_installed(self, pkg):
        out = util.output([*self.strat, "dpkg-query", "-W", "-f=${Status}", pkg]) or ""
        return "install ok installed" in out

    def is_available(self, pkg):
        out = util.output([*self.strat, "apt-cache", "policy", pkg]) or ""
        for line in out.splitlines():
            if line.strip().startswith("Candidate:"):
                return "(none)" not in line
        return False

    def refresh(self):
        if self.refreshed:
            return True
        self.refreshed = True
        return util.run([*self.root, "apt-get", "update"], mutate=True, capture=False).returncode == 0

    def install(self, pkgs):
        return util.run([*self.root, "env", "DEBIAN_FRONTEND=noninteractive",
                         "apt-get", "install", "-y", *pkgs], mutate=True, capture=False).returncode == 0

    def remove(self, pkgs):
        return util.run([*self.root, "apt-get", "remove", "-y", *pkgs],
                        mutate=True, capture=False).returncode == 0


class Dnf(Backend):
    family, name = "dnf", "dnf"

    def is_installed(self, pkg):
        return self.q("rpm", "-q", "--whatprovides", pkg) == 0

    def is_available(self, pkg):
        return pkg in self.available([pkg])

    def available(self, pkgs):
        out = util.output([*self.strat, "dnf", "repoquery", "-q", "--qf", "%{name}\n", *pkgs], timeout=300)
        names = set((out or "").split())
        return {p for p in pkgs if p in names}

    def install(self, pkgs):
        return util.run([*self.root, "dnf", "install", "-y", *pkgs],
                        mutate=True, capture=False).returncode == 0

    def remove(self, pkgs):
        return util.run([*self.root, "dnf", "remove", "-y", *pkgs],
                        mutate=True, capture=False).returncode == 0


class Pacman(Backend):
    family, name = "pacman", "pacman"

    def is_installed(self, pkg):
        return self.q("pacman", "-Q", pkg) == 0

    def is_available(self, pkg):
        return self.q("pacman", "-Si", pkg) == 0

    def install(self, pkgs):
        if util.run([*self.root, "pacman", "-S", "--needed", "--noconfirm", *pkgs],
                    mutate=True, capture=False).returncode == 0:
            return True
        # A stale package database 404s on the mirrors. Arch only supports
        # syncing together with a full upgrade, so ask before doing that.
        ui.warn("pacman could not fetch the packages; the package database is probably stale.")
        if not ui.confirm("Run a full system upgrade (pacman -Syu) and install them with it?", False):
            return False
        return util.run([*self.root, "pacman", "-Syu", "--needed", "--noconfirm", *pkgs],
                        mutate=True, capture=False).returncode == 0

    def remove(self, pkgs):
        return util.run([*self.root, "pacman", "-Rns", "--noconfirm", *pkgs],
                        mutate=True, capture=False).returncode == 0


class Portage(Backend):
    family, name = "portage", "emerge"

    def is_installed(self, pkg):
        return bool((util.output([*self.strat, "portageq", "match", "/", pkg]) or "").strip())

    def is_available(self, pkg):
        return bool((util.output([*self.strat, "portageq", "best_visible", "/", pkg]) or "").strip())

    def install(self, pkgs):
        ui.info("Gentoo builds from source; this can take a while.")
        return util.run([*self.root, "emerge", "--noreplace", "--quiet-build=y", *pkgs],
                        mutate=True, capture=False).returncode == 0

    def remove(self, pkgs):
        ok = util.run([*self.root, "emerge", "--deselect", *pkgs], mutate=True, capture=False).returncode == 0
        if ok:
            ui.info("Deselected. Run `emerge --depclean` to drop them from disk.")
        return ok


class Xbps(Backend):
    family, name = "xbps", "xbps"

    def is_installed(self, pkg):
        return self.q("xbps-query", pkg) == 0

    def is_available(self, pkg):
        return self.q("xbps-query", "-R", pkg) == 0

    def install(self, pkgs):
        return util.run([*self.root, "xbps-install", "-Sy", *pkgs],
                        mutate=True, capture=False).returncode == 0

    def remove(self, pkgs):
        return util.run([*self.root, "xbps-remove", "-Ry", *pkgs],
                        mutate=True, capture=False).returncode == 0


BACKENDS = {b.family: b for b in (Apt, Dnf, Pacman, Portage, Xbps)}


def backend_for(distro: Distro, root_prefix: list[str], family: str | None = None) -> Backend | None:
    cls = BACKENDS.get(family or distro.family or "")
    return cls(distro, root_prefix) if cls else None
