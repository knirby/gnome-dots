"""Point the top bar system monitor at this machine's own sensors, GPU and
disk, detected silently (see hardware.py)."""

from .. import ui
from ..gnome import dconf
from .base import Module

ASTRA = "/org/gnome/shell/extensions/astra-monitor/"


def _label(sensor: str | None) -> str:
    if not sensor:
        return "none"
    import json
    path = json.loads(sensor)["path"]
    return f"{path[0].split('-{$')[0]} {path[1]}"


class SystemMonitor(Module):
    name = "sysmon"
    title = "System monitor hardware"
    summary = "CPU temperature, fan, GPU and disk for Astra Monitor, auto-detected"
    needs_dconf = True

    def plan(self, ctx):
        hw = ctx.hardware
        return [f"CPU temperature: {_label(hw['cpu_temperature'])}; "
                f"second sensor: {_label(hw['secondary_sensor'])} ({hw['secondary_kind']})"]

    def apply(self, ctx):
        hw = ctx.hardware
        first, second = hw["cpu_temperature"], hw["secondary_sensor"]
        if not first:
            first, second = second, None
        values = {
            "sensors-header-show": bool(first),
            "sensors-header-sensor1": first or '""',
            "sensors-header-sensor1-show": bool(first),
            "sensors-header-sensor2": second or '""',
            "sensors-header-sensor2-show": bool(second),
            "gpu-main": hw["gpu"] or '""',
            "storage-main": hw["root_disk"] or "[default]",
        }
        for key, value in values.items():
            dconf.write(ASTRA + key, value)
        ui.ok("System monitor set up for this hardware")
        ui.detail(f"cpu={first} second={second} gpu={hw['gpu']} disk={hw['root_disk']}")
