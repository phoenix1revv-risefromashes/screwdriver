"""Passively discover hardware-backed Linux serial/TTY ports."""

from __future__ import annotations

import grp
import os
import pwd
import stat
from pathlib import Path

from screwdriver.models import DeviceNode, SerialDevice
from screwdriver.safety import (
    InspectionMode,
    ProbeRequest,
    SafetyPolicy,
)

_SYSFS_TTY_ROOT = Path("/sys/class/tty")
_DEV_ROOT = Path("/dev")
_SUPPORTED_PREFIXES = (
    "ttyUSB",
    "ttyACM",
    "ttyAMA",
    "ttyTHS",
    "ttymxc",
    "ttyO",
    "ttyMSM",
    "ttyXRUSB",
    "ttyS",
    "rfcomm",
)
_PASSIVE_TTY_READ = ProbeRequest(
    name="read serial/TTY filesystem metadata",
    required_mode=InspectionMode.PASSIVE,
)


def collect_serial_devices(
    sysfs_root: Path = _SYSFS_TTY_ROOT,
    dev_root: Path = _DEV_ROOT,
    policy: SafetyPolicy | None = None,
) -> list[SerialDevice]:
    """Return serial ports without opening them or changing line state."""

    active_policy = policy or SafetyPolicy()
    active_policy.require(_PASSIVE_TTY_READ)

    try:
        entries = sorted(sysfs_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []

    stable_id_paths = _index_links(dev_root / "serial/by-id")
    physical_paths = _index_links(dev_root / "serial/by-path")
    devices: list[SerialDevice] = []

    for entry in entries:
        if not entry.name.startswith(_SUPPORTED_PREFIXES):
            continue

        device_link = entry / "device"

        try:
            hardware_path = device_link.resolve(strict=True)
        except (OSError, RuntimeError):
            continue

        node_path = dev_root / entry.name
        node = _describe_device_node(node_path)
        usb_parent = _find_usb_parent(hardware_path)

        devices.append(
            SerialDevice(
                port=str(node_path),
                sysfs_name=entry.name,
                transport=_transport(entry.name, usb_parent is not None),
                driver=_find_driver(hardware_path),
                stable_id_path=stable_id_paths.get(_resolved(node_path)),
                physical_path=physical_paths.get(_resolved(node_path)),
                usb_vendor_id=_read_text(usb_parent / "idVendor") if usb_parent else None,
                usb_product_id=_read_text(usb_parent / "idProduct") if usb_parent else None,
                manufacturer=_read_text(usb_parent / "manufacturer") if usb_parent else None,
                product_name=_read_text(usb_parent / "product") if usb_parent else None,
                serial_number=_read_text(usb_parent / "serial") if usb_parent else None,
                device_node=node,
            )
        )

    return devices


def _index_links(directory: Path) -> dict[Path, str]:
    index: dict[Path, str] = {}

    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        return index

    for entry in entries:
        if not entry.is_symlink():
            continue

        index.setdefault(_resolved(entry), str(entry))

    return index


def _find_usb_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if _read_text(candidate / "idVendor") and _read_text(candidate / "idProduct"):
            return candidate

    return None


def _find_driver(path: Path) -> str | None:
    for candidate in (path, *path.parents):
        try:
            return (candidate / "driver").resolve(strict=True).name
        except (OSError, RuntimeError):
            continue

    return None


def _transport(name: str, has_usb_parent: bool) -> str:
    if name.startswith("ttyACM"):
        return "usb-cdc-acm"
    if name.startswith(("ttyUSB", "ttyXRUSB")) or has_usb_parent:
        return "usb-serial"
    if name.startswith("rfcomm"):
        return "bluetooth-serial"
    return "onboard-uart"


def _describe_device_node(path: Path) -> DeviceNode | None:
    try:
        metadata = path.stat()
    except OSError:
        return None

    if not stat.S_ISCHR(metadata.st_mode):
        return None

    return DeviceNode(
        path=str(path),
        node_type="character",
        permissions=stat.filemode(metadata.st_mode),
        owner=_username_for_uid(metadata.st_uid),
        group=_group_for_gid(metadata.st_gid),
        readable=os.access(path, os.R_OK),
        writable=os.access(path, os.W_OK),
    )


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8", errors="replace").strip().strip("\x00")
    except OSError:
        return None

    return value or None


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return path.absolute()


def _username_for_uid(uid: int) -> str | None:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def _group_for_gid(gid: int) -> str | None:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return None
