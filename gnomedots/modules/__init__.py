"""The setup steps, in the order they run.

Wallpaper runs before settings (the lock screen template needs the picture's
path), and the logo and system monitor run after settings, which resets the
extensions' settings folders.
"""

from .command import Command
from .extensions import Extensions
from .gtk import GtkCss
from .keybindings import Keybindings
from .menulogo import MenuLogo
from .packages import Packages
from .settings import Input, Settings
from .sysmon import SystemMonitor
from .themes import Themes
from .wallpaper import Wallpaper

ALL = [Packages(), Themes(), Extensions(), Wallpaper(), Settings(), Input(),
       Keybindings(), MenuLogo(), SystemMonitor(), GtkCss(), Command()]
BY_NAME = {m.name: m for m in ALL}
