"""The setup steps, in the order they run.

The command comes early so the hourly wallpaper job finds its launcher, and
the rounded blur library comes after packages, which install its build tools.
Wallpaper runs before settings (the lock screen template needs the picture's
path), and the logo and system monitor run after settings, which resets the
extensions' settings folders.
"""

from .appicons import AppIcons
from .command import Command
from .extensions import Extensions
from .gtk import GtkCss
from .keybindings import Keybindings
from .menulogo import MenuLogo
from .packages import Packages
from .roundedblur import RoundedBlur
from .settings import Input, Settings
from .sysmon import SystemMonitor
from .themes import Themes
from .wallpaper import Wallpaper
from .zsh import Zsh

ALL = [Packages(), Command(), Themes(), AppIcons(), Extensions(), RoundedBlur(), Wallpaper(),
       Settings(), Input(), Keybindings(), MenuLogo(), SystemMonitor(), GtkCss(), Zsh()]
BY_NAME = {m.name: m for m in ALL}
