"""Terminal output, prompts and the run log.

Everything printed also goes to the log file without colours, so a failed run
can be read back with `knirby-gnomedots status --log`.
"""

import os
import sys
from pathlib import Path

_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
_log = None

assume_yes = False
dry_run = False
verbose = False


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color else text


def open_log(path: Path) -> None:
    global _log
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _log = open(path, "w", encoding="utf-8")
    except OSError:
        _log = None


def log(text: str) -> None:
    if _log:
        _log.write(text + "\n")
        _log.flush()


def _out(prefix: str, colored: str, text: str, stream=None) -> None:
    print(f"{colored} {text}" if colored else text, file=stream or sys.stdout)
    log(f"{prefix} {text}" if prefix else text)


def header(text: str) -> None:
    print()
    _out("==", _c("1;35", "::"), _c("1", text))


def step(text: str) -> None:
    _out("->", _c("1;34", "->"), text)


def ok(text: str) -> None:
    _out("ok", _c("1;32", " ✓"), text)


def info(text: str) -> None:
    _out("  ", "  ", text)


def detail(text: str) -> None:
    if verbose:
        _out("..", _c("2", "  ·"), _c("2", text))
    else:
        log(f".. {text}")


def warn(text: str) -> None:
    _out("!!", _c("1;33", " !"), text, sys.stderr)


def error(text: str) -> None:
    _out("EE", _c("1;31", " ✗"), text, sys.stderr)


def action(text: str) -> None:
    """A change about to happen; in dry-run mode it is only announced."""
    if dry_run:
        _out("dry", _c("2;36", "  [dry-run]"), text)
    else:
        detail(text)


def confirm(question: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    if assume_yes:
        log(f"?? {question} {hint} -> yes (--yes)")
        return True
    if not sys.stdin.isatty():
        log(f"?? {question} {hint} -> {'yes' if default else 'no'} (no terminal)")
        return default
    while True:
        try:
            reply = input(f"{_c('1;36', ' ?')} {question} {hint} ").strip().lower()
        except EOFError:
            reply = ""
        if not reply:
            result = default
        elif reply in ("y", "yes"):
            result = True
        elif reply in ("n", "no"):
            result = False
        else:
            continue
        log(f"?? {question} {hint} -> {'yes' if result else 'no'}")
        return result


def choose(question: str, options: list[tuple[str, str]], default: str) -> str:
    """Ask for one of several single-letter options: [(key, label), ...]."""
    if assume_yes or not sys.stdin.isatty():
        log(f"?? {question} -> {default} (default)")
        return default
    labels = "  ".join(f"[{k.upper() if k == default else k}] {label}" for k, label in options)
    keys = {k for k, _ in options}
    while True:
        try:
            reply = input(f"{_c('1;36', ' ?')} {question}\n    {labels}: ").strip().lower()
        except EOFError:
            reply = ""
        reply = reply[:1] or default
        if reply in keys:
            log(f"?? {question} -> {reply}")
            return reply


def confirm_backup(question: str, default: bool = True) -> bool | None:
    """Ask before a change to the settings, offering to back them up first.
    True: go ahead with a backup, False: go ahead without one, None: cancel.
    The default is the backup when default is True, cancelling otherwise;
    --yes always takes the backup."""
    if assume_yes:
        log(f"?? {question} -> yes, with a backup (--yes)")
        return True
    reply = choose(question, [("y", "yes, back up my settings first"),
                              ("s", "yes, skip the backup"),
                              ("c", "cancel")], "y" if default else "c")
    return {"y": True, "s": False}.get(reply)


def bullet_list(items, indent: str = "    ") -> None:
    for item in items:
        _out("  ", "", f"{indent}• {item}")
