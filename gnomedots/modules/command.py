"""The `knirby-gnomedots` command: a copy of this repository in
~/.local/share, a launcher in ~/.local/bin and that folder on every installed
shell's PATH."""

import os
import shutil
import subprocess
from pathlib import Path

from .. import APP_NAME, blocks, ui, util
from ..paths import APP_DIR, BIN_DIR, CONFIG_HOME, HOME, LAUNCHER, SOURCE_ROOT
from .base import Module

COPY = ["gnomedots", "config", "assets", "install.py", "README.md", "LICENSE"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")

LAUNCHER_TEXT = f'''#!/usr/bin/env python3
# {APP_NAME} launcher, written by its installer. Edits are overwritten.
import sys
if sys.version_info < (3, 11):
    sys.exit("{APP_NAME} needs Python 3.11 or newer")
sys.path.insert(0, {str(APP_DIR)!r})
from gnomedots.cli import main
sys.exit(main())
'''

POSIX_PATH = '''case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac'''

FISH_PATH = '''if not contains -- $HOME/.local/bin $PATH
    set -gx PATH $HOME/.local/bin $PATH
end'''


def _zshrc() -> Path:
    zdot = os.environ.get("ZDOTDIR")
    return Path(zdot) / ".zshrc" if zdot else HOME / ".zshrc"


def shell_files() -> list[tuple[str, Path, str, str]]:
    """(shell, rc file, block, marker style) for each installed shell."""
    out = []
    if util.which("bash"):
        out.append(("bash", HOME / ".bashrc", POSIX_PATH, "hash"))
    if util.which("zsh"):
        out.append(("zsh", _zshrc(), POSIX_PATH, "hash"))
    if util.which("fish"):
        out.append(("fish", CONFIG_HOME / "fish" / "conf.d" / f"{APP_NAME}.fish", FISH_PATH, "hash"))
    return out


def _on_path(shell: str) -> bool:
    """Whether a fresh interactive shell already has ~/.local/bin on PATH."""
    flag = "-ic" if shell != "fish" else "-c"
    try:
        out = subprocess.run([shell, flag, "echo $PATH"], capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    sep = " " if shell == "fish" else ":"
    return str(BIN_DIR) in out.strip().replace(sep, "\n").splitlines()


def git_commit(root: Path) -> str | None:
    if (root / ".git").exists() and util.which("git"):
        out = util.output(["git", "-C", str(root), "rev-parse", "HEAD"])
        return out.strip() if out else None
    return None


def copy_tree(src: Path, dest: Path) -> None:
    """Replace dest with the parts of src the tool needs, via a staging folder."""
    ui.action(f"copy {src} to {dest}")
    if ui.dry_run:
        return
    staged = dest.with_name(dest.name + ".new")
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    for name in COPY:
        p = src / name
        if p.is_dir():
            shutil.copytree(p, staged / name, ignore=IGNORE)
        elif p.is_file():
            shutil.copy2(p, staged / name)
    old = dest.with_name(dest.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if dest.exists():
        dest.rename(old)
    staged.rename(dest)
    shutil.rmtree(old, ignore_errors=True)


class Command(Module):
    name = "command"
    title = f"The {APP_NAME} command"
    summary = f"{APP_NAME} update / status / uninstall, on PATH in bash, zsh and fish"

    def plan(self, ctx):
        shells = ", ".join(s for s, *_ in shell_files()) or "no shells found"
        return [f"{LAUNCHER} (shells: {shells})"]

    def apply(self, ctx):
        if SOURCE_ROOT.resolve() != APP_DIR.resolve():
            commit = git_commit(SOURCE_ROOT)
            copy_tree(SOURCE_ROOT, APP_DIR)
            if commit:
                ctx.state["commit"] = commit
        util.write_text(LAUNCHER, LAUNCHER_TEXT, mode=0o755)
        for shell, rc, body, style in shell_files():
            if blocks.has_block(rc, style) or not _on_path(shell):
                blocks.set_block(rc, body, style)
                ctx.state.add_unique("edited_files", str(rc))
                ui.detail(f"added ~/.local/bin to PATH in {rc}")
        ui.ok(f"`{APP_NAME}` installed (new terminals pick it up)")

    def remove(self, ctx):
        for _, rc, _, style in shell_files():
            if blocks.remove_block(rc, style) and rc.suffix == ".fish" and not rc.read_text().strip():
                util.remove_tree(rc)
        util.remove_tree(LAUNCHER)
        for suffix in ("", ".new", ".old"):
            util.remove_tree(APP_DIR.with_name(APP_DIR.name + suffix))
