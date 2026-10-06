#!/usr/bin/env python3
"""Set up GNOME the knirby way: python3 install.py [--yes] [--dry-run] [--skip MODULE ...]

Run it from a terminal inside your GNOME session, as your normal user. After
the first run, the `knirby-gnomedots` command does the rest (update, status,
uninstall); `python3 install.py --help` lists everything.
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("knirby-gnomedots needs Python 3.11 or newer")

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gnomedots.cli import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv = ["install", *argv]
    sys.exit(main(argv))
