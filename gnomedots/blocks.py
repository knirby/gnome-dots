"""Marked blocks inside files the user owns (shell rc files, gtk.css).

The tool never rewrites such a file wholesale: it adds one block between
marker lines, replaces only that block on later runs and removes only that
block on uninstall.
"""

import re
from pathlib import Path

from . import APP_NAME, util

STYLES = {
    "hash": ("# >>> {} >>>", "# <<< {} <<<"),
    "css": ("/* >>> {} >>> */", "/* <<< {} <<< */"),
}


def _markers(style: str) -> tuple[str, str]:
    begin, end = STYLES[style]
    return begin.format(APP_NAME), end.format(APP_NAME)


def _pattern(style: str) -> re.Pattern:
    begin, end = _markers(style)
    return re.compile(r"\n?" + re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.S)


def has_block(path: Path, style: str) -> bool:
    try:
        return _markers(style)[0] in path.read_text()
    except OSError:
        return False


def set_block(path: Path, body: str, style: str) -> None:
    begin, end = _markers(style)
    block = f"{begin}\n{body.rstrip()}\n{end}\n"
    try:
        text = path.read_text()
    except FileNotFoundError:
        text = ""
    if begin in text:
        new = _pattern(style).sub("\n" + block, text, count=1)
    else:
        new = text + ("" if not text or text.endswith("\n") else "\n") + ("\n" if text else "") + block
    if new != text:
        util.write_text(path, new)


def remove_block(path: Path, style: str) -> bool:
    try:
        text = path.read_text()
    except OSError:
        return False
    if _markers(style)[0] not in text:
        return False
    new = _pattern(style).sub("\n", text, count=1)
    new = new.strip("\n") + "\n" if new.strip() else ""
    util.write_text(path, new)
    return True
