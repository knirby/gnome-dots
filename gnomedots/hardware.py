"""Silent hardware detection for the top bar system monitor.

Astra Monitor names things its own way, so this module reads sysfs and
produces exactly the identifiers it stores in its settings:

- a sensor is {"service": "hwmon", "path": [device, sensor, "input"]}, where
  device is the hwmon chip name plus "-{$address}" when the chip sits on a bus
  (Astra's own naming) and sensor is the channel label, or "temp1" when the
  chip gives none;
- the GPU is its PCI address split as Astra splits it, with vendor and device;
- the disk is the lsblk ID of the partition mounted at /.

Nothing here prints or asks: whatever can't be found is left to Astra's own
defaults.
"""

import glob
import json
import re
from pathlib import Path

from . import util

HWMON = Path("/sys/class/hwmon")

# hwmon driver -> CPU temperature channels, best first. None = first channel.
CPU_CHIPS = [
    ("coretemp", ["Package id 0", "Package id 1", "Core 0"]),
    ("k10temp", ["Tctl", "Tdie", "Tccd1"]),
    ("zenpower", ["Tdie", "Tctl"]),
    ("cpu_thermal", [None]),
    ("cpu-thermal", [None]),
    ("soc_thermal", [None]),
    ("thinkpad", ["CPU", None]),
    ("acpitz", [None]),
]
GPU_TEMP_CHIPS = [("amdgpu", ["edge", "junction", None]), ("nouveau", [None]),
                  ("i915", [None]), ("xe", [None])]
DISK_TEMP_CHIPS = [("nvme", ["Composite", None]), ("drivetemp", [None])]


def _int(path) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def _astra_device(h: Path) -> str | None:
    name = util.read(h / "name")
    if not name:
        return None
    address = util.read(h / "device" / "address")
    if address:
        address = re.sub(r"^0+:", "", address)
        address = re.sub(r"\.[0-9]*$", "", address)
        return f"{name}-{{${address.replace(':', '')}}}"
    device = util.read(h / "device" / "device")
    if device:
        return f"{name}-{{${device.removeprefix('0x')}}}"
    return name


def _channels(h: Path, kind: str) -> list[tuple[int, str, int]]:
    """[(index, astra sensor name, value)] for temp or fan inputs with a reading."""
    out = []
    for f in glob.glob(str(h / f"{kind}*_input")):
        m = re.match(rf"{kind}(\d+)_input$", Path(f).name)
        value = _int(f)
        if not m or value is None:
            continue
        idx = int(m.group(1))
        label = util.read(h / f"{kind}{idx}_label")
        out.append((idx, label or f"{kind}{idx}", value))
    return sorted(out)


def _chips() -> list[tuple[str, Path]]:
    chips = []
    for h in sorted(HWMON.glob("hwmon*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        name = util.read(h / "name")
        if name:
            chips.append((name, h))
    return chips


def _sensor(device: str, channel: str) -> str:
    return json.dumps({"service": "hwmon", "path": [device, channel, "input"]}, separators=(",", ":"))


def _pick_temp(table) -> str | None:
    chips = _chips()
    for chip, wanted in table:
        for name, h in chips:
            if name != chip:
                continue
            channels = [c for c in _channels(h, "temp") if c[2] > 0]
            for want in wanted:
                for _, label, _ in channels:
                    if want is None or label == want:
                        return _sensor(_astra_device(h), label)
    return None


def cpu_temperature() -> str | None:
    return _pick_temp(CPU_CHIPS)


def fan() -> str | None:
    """A spinning fan, preferring one labelled as the CPU fan."""
    found = []
    for order, (name, h) in enumerate(_chips()):
        for idx, label, rpm in _channels(h, "fan"):
            if rpm > 0:
                found.append(("cpu" not in label.lower(), order, idx, h, label))
    if not found:
        return None
    _, _, _, h, label = min(found, key=lambda f: f[:3])
    return _sensor(_astra_device(h), label)


def secondary_sensor() -> tuple[str | None, str]:
    """The second top bar sensor: a fan's RPM, else a GPU or disk temperature."""
    s = fan()
    if s:
        return s, "fan"
    s = _pick_temp(GPU_TEMP_CHIPS)
    if s:
        return s, "gpu"
    s = _pick_temp(DISK_TEMP_CHIPS)
    return s, ("disk" if s else "none")


def gpu() -> str | None:
    """Astra's main GPU: NVIDIA first, then the boot GPU, then any display device."""
    gpus = []
    for dev in Path("/sys/bus/pci/devices").glob("*"):
        cls = util.read(dev / "class", "")
        if not cls.startswith("0x03"):
            continue
        vendor = util.read(dev / "vendor", "").removeprefix("0x")
        device = util.read(dev / "device", "").removeprefix("0x")
        m = re.match(r"^([0-9a-f]{4}:[0-9a-f]{2}):([0-9a-f]{2})\.([0-9a-f])$", dev.name)
        if not (m and vendor and device):
            continue
        rank = 0 if vendor == "10de" else 1 if util.read(dev / "boot_vga") == "1" else 2
        gpus.append((rank, dev.name, {"domain": m.group(1), "bus": m.group(2), "slot": m.group(3),
                                      "vendorId": vendor, "productId": device}))
    if not gpus:
        return None
    return json.dumps(min(gpus, key=lambda g: g[:2])[2], separators=(",", ":"))


def root_disk() -> str | None:
    out = util.output(["lsblk", "-J", "-o", "ID,MOUNTPOINTS"])
    if not out:
        return None
    try:
        devices = json.loads(out).get("blockdevices", [])
    except ValueError:
        return None

    def walk(nodes):
        for node in nodes:
            if node.get("children"):
                hit = walk(node["children"])
                if hit:
                    return hit
            elif "/" in (node.get("mountpoints") or []) and node.get("id"):
                return node["id"]
        return None

    return walk(devices)


def widest_display() -> int:
    """Width in pixels of the widest connected display, 0 if unknown."""
    widest = 0
    for status in glob.glob("/sys/class/drm/card*-*/status"):
        if util.read(status) != "connected":
            continue
        modes = util.read(Path(status).with_name("modes"), "")
        for mode in modes.splitlines():
            m = re.match(r"(\d+)x(\d+)", mode)
            if m:
                widest = max(widest, int(m.group(1)))
    return widest


def summary() -> dict:
    second, kind = secondary_sensor()
    return {
        "cpu_temperature": cpu_temperature(),
        "secondary_sensor": second,
        "secondary_kind": kind,
        "gpu": gpu(),
        "root_disk": root_disk(),
        "widest_display": widest_display(),
    }
