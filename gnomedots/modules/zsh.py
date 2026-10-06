"""Optional zsh profile: Oh My Zsh with git, sudo, autosuggestions and syntax
highlighting, knirby's prompt, and zsh as the login shell.

Only runs when asked for (--with zsh, or yes at the install prompt). An
existing ~/.zshrc or ~/.zsh_prompt is kept as *.pre-knirby-gnomedots and put
back on uninstall.
"""

import os
import pwd
from pathlib import Path

from .. import APP_NAME, ui, util
from ..paths import HOME
from .base import Module

OMZ = HOME / ".oh-my-zsh"
OMZ_REPO = "https://github.com/ohmyzsh/ohmyzsh.git"
PLUGINS = {
    "zsh-autosuggestions": "https://github.com/zsh-users/zsh-autosuggestions.git",
    "zsh-syntax-highlighting": "https://github.com/zsh-users/zsh-syntax-highlighting.git",
}
FILES = {".zshrc": "zsh/zshrc", ".zsh_prompt": "zsh/zsh_prompt"}
MARK = "knirby-gnomedots zsh profile"
SUFFIX = f".pre-{APP_NAME}"


def _ours(path: Path, template: str) -> bool:
    text = util.read(path, "")
    return MARK in text or text == template.strip()


def login_shell() -> str:
    return pwd.getpwuid(os.getuid()).pw_shell


class Zsh(Module):
    name = "zsh"
    title = "zsh profile (addon)"
    summary = "optional: Oh My Zsh, autosuggestions, syntax highlighting, knirby's prompt"
    default = False
    needs_network = True

    def plan(self, ctx):
        lines = ["Oh My Zsh with git, sudo, zsh-autosuggestions and zsh-syntax-highlighting",
                 "prompt: (exit status) /path (git branch) $, time on the right"]
        for name in FILES:
            if (HOME / name).exists() and not _ours(HOME / name, ctx.config_text(FILES[name])):
                lines.append(f"your ~/{name} is kept as ~/{name}{SUFFIX}")
        if not login_shell().endswith("/zsh"):
            lines.append("offer to make zsh your login shell")
        return lines

    def apply(self, ctx):
        zsh = util.which("zsh")
        if not zsh and not ui.dry_run:
            raise RuntimeError("zsh isn't installed (the packages module installs it)")
        if not util.which("git") and not ui.dry_run:
            raise RuntimeError("git isn't installed (the packages module installs it)")
        record = ctx.state.data.setdefault("zsh", {})

        if not (OMZ / "oh-my-zsh.sh").is_file():
            util.run(["git", "clone", "--depth=1", OMZ_REPO, str(OMZ)], mutate=True, check=True)
            record["installed_omz"] = True
            ui.ok("Oh My Zsh installed")
        custom = Path(os.environ.get("ZSH_CUSTOM") or OMZ / "custom") / "plugins"
        for plugin, repo in PLUGINS.items():
            if not (custom / plugin).is_dir():
                util.run(["git", "clone", "--depth=1", repo, str(custom / plugin)], mutate=True, check=True)
                record.setdefault("plugins", []).append(str(custom / plugin))
                ui.ok(f"{plugin} installed")

        for name, template_path in FILES.items():
            target = HOME / name
            template = ctx.config_text(template_path)
            backup = HOME / f"{name}{SUFFIX}"
            if target.exists() and not _ours(target, template) and not backup.exists():
                ui.action(f"keep {target} as {backup}")
                if not ui.dry_run:
                    target.rename(backup)
                record.setdefault("backups", []).append(name)
            util.write_text(target, template)
        ui.ok("zsh profile written")

        if zsh and not login_shell().endswith("/zsh"):
            if ui.confirm("Make zsh your login shell?", True):
                record.setdefault("previous_shell", login_shell())
                if util.which("chsh"):
                    ok = util.run(["chsh", "-s", zsh], mutate=True, capture=False).returncode == 0
                else:
                    ok = util.run(["sudo", "usermod", "-s", zsh, pwd.getpwuid(os.getuid()).pw_name],
                                  mutate=True, capture=False).returncode == 0
                if ok:
                    ui.ok("zsh is your login shell from the next login")
                else:
                    ui.warn(f"Couldn't change the login shell; run: chsh -s {zsh}")

    def remove(self, ctx):
        record = ctx.state.get("zsh")
        if not record:
            return
        for name in FILES:
            target, backup = HOME / name, HOME / f"{name}{SUFFIX}"
            if backup.exists():
                ui.action(f"restore {backup} to {target}")
                if not ui.dry_run:
                    backup.replace(target)
            elif _ours(target, ctx.config_text(FILES[name])):
                util.remove_tree(target)
        for plugin in record.get("plugins", []):
            util.remove_tree(Path(plugin))
        if record.get("installed_omz"):
            util.remove_tree(OMZ)
        previous = record.get("previous_shell")
        if previous and login_shell().endswith("/zsh") and Path(previous).exists():
            if ui.confirm(f"Switch your login shell back to {previous}?", True):
                util.run(["chsh", "-s", previous] if util.which("chsh") else
                         ["sudo", "usermod", "-s", previous, pwd.getpwuid(os.getuid()).pw_name],
                         mutate=True, capture=False)
        ctx.state.data.pop("zsh", None)
        ui.ok("zsh profile removed")
