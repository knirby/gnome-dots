"""knirby-gnomedots: one command from a stock GNOME desktop to knirby's setup."""

__version__ = "1.1.0"

APP_NAME = "knirby-gnomedots"
REPO = "knirby/gnome-dots"
BRANCH = "main"

# GNOME Shell majors the configuration is built and tested for. Newer majors
# and older ones down to MIN_SHELL run with a warning (extensions without a
# build for them are skipped); anything older is refused unless --force.
SUPPORTED_SHELL = (50,)
MIN_SHELL = 46
MIN_PYTHON = (3, 11)
