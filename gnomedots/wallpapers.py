"""The Bing wallpaper folder: fetching, trimming, cleaning, and the hourly job.

Wallpaper Slideshow downloads Bing pictures on a 12-hour timer that runs on
the monotonic clock: suspend stops it and every login restarts it, so on a
machine that sleeps a lot whole days are skipped. Here an hourly job (a
systemd user timer, which catches up after suspend, or a login process where
systemd isn't the user's service manager) fetches the latest pictures under
the same file names the extension uses, makes a new day's picture the
wallpaper straight away, and trims the oldest pictures once the folder grows
past its size limit. The slideshow watches the folder, so it picks up both.
"""

import os
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path

from . import APP_NAME, ui, util
from .gnome import dconf, gvariant
from .paths import CONFIG_HOME, LAUNCHER, STATE_DIR, pictures_dir

BING = "https://www.bing.com"
AZ = "/org/gnome/shell/extensions/azwallpaper/"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
UNIT = f"{APP_NAME}-wallpapers"
SYSTEMD_DIR = CONFIG_HOME / "systemd" / "user"
AUTOSTART = CONFIG_HOME / "autostart" / f"{UNIT}.desktop"
LAST_SHOWN = STATE_DIR / "wallpaper-of-the-day"

SERVICE_TEXT = f"""[Unit]
Description=Fetch the newest Bing wallpaper and trim old ones

[Service]
Type=oneshot
ExecStart={LAUNCHER} wallpapers sync --quiet
"""

TIMER_TEXT = """[Unit]
Description=Check for a new Bing wallpaper every hour

[Timer]
OnStartupSec=1min
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
"""

AUTOSTART_TEXT = f"""[Desktop Entry]
Type=Application
Name=Bing wallpaper updates
Comment=Fetches the newest Bing wallpaper every hour ({APP_NAME})
Exec={LAUNCHER} wallpapers sync --quiet --watch
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def file_name(urlbase: str, res: str) -> str:
    # The name Wallpaper Slideshow gives the same picture, so neither fetches it twice.
    pretty = urlbase.rsplit("/", 1)[-1].replace("th?id=OHR.", "").split("_")[0]
    return f"{pretty}-{res}.jpg"


class Settings:
    """The extension's own settings win, so changes made in its preferences stick."""

    def __init__(self, config: dict, resolution: str | None = None):
        self.folder = Path(gvariant.load_str(dconf.read(AZ + "bing-download-directory"))
                           or pictures_dir() / config["folder"])
        self.market = gvariant.load_str(dconf.read(AZ + "bing-wallpaper-market")) or config["market"]
        self.resolution = (gvariant.load_str(dconf.read(AZ + "bing-wallpaper-resolution"))
                           or resolution or "1920x1200")
        self.limit = int(config.get("keep_mb", 200)) * 1024 * 1024


def images(folder: Path) -> list[Path]:
    """Pictures in the folder, oldest first."""
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and not p.name.startswith(".")]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def current_wallpaper() -> Path | None:
    uri = gvariant.load_str(dconf.read("/org/gnome/desktop/background/picture-uri-dark")) or \
        gvariant.load_str(dconf.read("/org/gnome/desktop/background/picture-uri"))
    if not uri or not uri.startswith("file://"):
        return None
    return Path(urllib.parse.unquote(urllib.parse.urlparse(uri).path))


def set_wallpaper(path: Path) -> None:
    uri = path.as_uri()
    dconf.write("/org/gnome/desktop/background/picture-uri", uri)
    dconf.write("/org/gnome/desktop/background/picture-uri-dark", uri)


FALLBACK_RESOLUTION = "1920x1080"   # the one size Bing publishes for every picture


def _fetch_one(s: Settings, urlbase: str) -> tuple[Path, bool]:
    """(path, newly downloaded) for one picture, at the chosen resolution or,
    where Bing doesn't publish that size (it 404s), at 1920x1080."""
    sizes = [s.resolution] + ([FALLBACK_RESOLUTION] if s.resolution != FALLBACK_RESOLUTION else [])
    for res in sizes:
        target = s.folder / file_name(urlbase, res)
        if target.exists():
            return target, False
    last = None
    for res in sizes:
        target = s.folder / file_name(urlbase, res)
        ui.action(f"download {target.name}")
        if ui.dry_run:
            return target, True
        try:
            body = util.http_get(f"{BING}{urlbase}_{res}.jpg", timeout=120)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                continue
            raise
        fd, tmp = tempfile.mkstemp(dir=s.folder, prefix=".", suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
        return target, True
    raise last or LookupError("no size available")


def fetch(s: Settings, count: int = 8) -> tuple[list[Path], Path | None]:
    """Download the latest pictures that aren't there yet.

    Returns (new files, today's picture). Files are written under a hidden
    temporary name and renamed, so the slideshow never sees half a picture.
    """
    query = urllib.parse.urlencode({"format": "js", "idx": 0, "n": count, "mbl": 1,
                                    "mkt": "" if s.market == "Automatic" else s.market})
    data = util.http_json(f"{BING}/HPImageArchive.aspx?{query}", timeout=30)
    if not ui.dry_run:
        s.folder.mkdir(parents=True, exist_ok=True)
    new, today = [], None
    for i, image in enumerate(data.get("images", [])):
        try:
            path, fresh = _fetch_one(s, image["urlbase"])
        except Exception as e:  # one missing picture never stops the rest
            ui.log(f"wallpaper {image.get('urlbase')}: {e}")
            continue
        if i == 0:
            today = path
        if fresh:
            new.append(path)
    return new, today


def prune(s: Settings, keep: set[Path] = frozenset()) -> list[Path]:
    """Delete the oldest pictures until the folder is under its limit."""
    files = images(s.folder)
    total = sum(p.stat().st_size for p in files)
    removed = []
    for p in files:
        if total <= s.limit:
            break
        if p in keep:
            continue
        total -= p.stat().st_size
        util.remove_tree(p)
        removed.append(p)
    return removed


def sync(s: Settings) -> dict:
    new, today = fetch(s)
    current = current_wallpaper()
    switched = False
    # Show each day's picture once when it first appears, whoever downloaded
    # it; the slideshow carries on from there.
    if today and today.exists() and util.read(LAST_SHOWN) != today.name:
        set_wallpaper(today)
        current, switched = today, True
        util.write_text(LAST_SHOWN, today.name + "\n")
    removed = prune(s, keep={p for p in (current, today) if p})
    return {"new": new, "today": today, "switched": switched, "removed": removed}


def clean(s: Settings, keep_current: bool = True) -> list[Path]:
    current = current_wallpaper() if keep_current else None
    removed = []
    for p in images(s.folder):
        if p != current:
            util.remove_tree(p)
            removed.append(p)
    return removed


def size(folder: Path) -> int:
    return sum(p.stat().st_size for p in images(folder))


# -- the hourly job --------------------------------------------------------

def systemd_user() -> bool:
    return util.which("systemctl") is not None and \
        util.run(["systemctl", "--user", "show-environment"], timeout=10).returncode == 0


def install_schedule() -> str:
    if systemd_user():
        util.write_text(SYSTEMD_DIR / f"{UNIT}.service", SERVICE_TEXT)
        util.write_text(SYSTEMD_DIR / f"{UNIT}.timer", TIMER_TEXT)
        util.run(["systemctl", "--user", "daemon-reload"], mutate=True)
        util.run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"], mutate=True)
        util.remove_tree(AUTOSTART)
        return "an hourly systemd timer"
    util.write_text(AUTOSTART, AUTOSTART_TEXT)
    return "an hourly check that starts at login"


def remove_schedule() -> None:
    if util.which("systemctl"):
        util.run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"], mutate=True)
    for p in (SYSTEMD_DIR / f"{UNIT}.service", SYSTEMD_DIR / f"{UNIT}.timer", AUTOSTART):
        util.remove_tree(p)
    if util.which("systemctl"):
        util.run(["systemctl", "--user", "daemon-reload"], mutate=True)


def watch(s: Settings, every: int = 3600) -> None:
    """For sessions without systemd: sync now, then every hour of wall-clock
    time. Short naps keep it on schedule across suspend."""
    last = 0.0
    while True:
        if time.time() - last >= every:
            try:
                sync(s)
            except Exception as e:  # offline, Bing hiccup: try again next hour
                ui.log(f"wallpaper sync failed: {e}")
            last = time.time()
        time.sleep(300)
