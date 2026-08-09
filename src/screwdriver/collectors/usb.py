"""Passively discover USB devices, drivers, and associated device nodes."""

from __future__ import annotations

import grp
import os
import pwd
import re
import stat
from collections.abc import Iterable
from pathlib import Path

from screwdriver.models import DeviceNode, USBDevice

_SYSFS_USB_ROOT = Path("/sys/bus/usb/devices")
_DEV_ROOT = Path("/dev")
_USB_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{4}$")
_USB_CLASS_NAMES = {
    "00": "defined at interface level",
    "01": "audio",
    "02": "communications",
    "03": "human interface device",
    "05": "physical",
    "06": "imaging",
    "07": "printer",
    "08": "mass storage",
    "09": "hub",
    "0a": "CDC data",
    "0b": "smart card",
    "0d": "content security",
    "0e": "video",
    "0f": "personal healthcare",
    "10": "audio/video",
    "11": "billboard",
    "dc": "diagnostic",
    "e0": "wireless controller",
    "ef": "miscellaneous",
    "fe": "application specific",
    "ff": "vendor specific",
}


def collect_usb_devices(
    sysfs_root: Path = _SYSFS_USB_ROOT,
    dev_root: Path = _DEV_ROOT,
) -> list[USBDevice]:
    """Return USB devices visible through sysfs without changing device state."""

    try:
        entries = list(sysfs_root.iterdir())
    except OSError:
        return []

    node_index = _build_device_node_index(dev_root)
    devices: list[USBDevice] = []

    for entry in entries:
        vendor_id = _read_usb_id(entry / "idVendor")
        product_id = _read_usb_id(entry / "idProduct")

        if vendor_id is None or product_id is None:
            continue

        interfaces = _find_interfaces(sysfs_root, entry.name)
        driver_names = _collect_driver_names(entry, interfaces)
        device_nodes = _collect_device_nodes(
            entry,
            interfaces,
            node_index,
        )
        class_code = _read_usb_class(entry / "bDeviceClass")

        devices.append(
            USBDevice(
                sysfs_name=entry.name,
                vendor_id=vendor_id,
                product_id=product_id,
                manufacturer=_read_text(entry / "manufacturer"),
                product_name=_read_text(entry / "product"),
                serial_number=_read_text(entry / "serial"),
                bus_number=_read_int(entry / "busnum"),
                device_number=_read_int(entry / "devnum"),
                usb_version=_read_text(entry / "version"),
                speed_mbps=_read_float(entry / "speed"),
                device_class=class_code,
                device_class_name=_USB_CLASS_NAMES.get(class_code or ""),
                drivers=driver_names,
                device_nodes=device_nodes,
            )
        )

    return sorted(
        devices,
        key=lambda device: (
            device.bus_number is None,
            device.bus_number or 0,
            device.device_number is None,
            device.device_number or 0,
            device.sysfs_name,
        ),
    )


def _find_interfaces(
    sysfs_root: Path,
    device_name: str,
) -> list[Path]:
    try:
        return sorted(sysfs_root.glob(f"{device_name}:*"))
    except OSError:
        return []


def _collect_driver_names(
    device: Path,
    interfaces: Iterable[Path],
) -> list[str]:
    names: set[str] = set()

    for path in (device, *interfaces):
        try:
            driver = (path / "driver").resolve(strict=True)
        except OSError:
            continue

        names.add(driver.name)

    return sorted(names)


def _collect_device_nodes(
    device: Path,
    interfaces: Iterable[Path],
    node_index: dict[tuple[int, int], list[Path]],
) -> list[DeviceNode]:
    major_minor_pairs: set[tuple[int, int]] = set()

    try:
        resolved_device = device.resolve(strict=True)
    except OSError:
        resolved_device = None

    if resolved_device is not None:
        pair = _parse_major_minor(_read_text(resolved_device / "dev"))

        if pair is not None:
            major_minor_pairs.add(pair)

    for interface in interfaces:
        try:
            resolved_interface = interface.resolve(strict=True)
        except OSError:
            continue

        try:
            dev_files = resolved_interface.rglob("dev")

            for dev_file in dev_files:
                pair = _parse_major_minor(_read_text(dev_file))

                if pair is not None:
                    major_minor_pairs.add(pair)
        except OSError:
            continue

    nodes: list[DeviceNode] = []
    seen_paths: set[Path] = set()

    for pair in sorted(major_minor_pairs):
        for path in node_index.get(pair, []):
            if path in seen_paths:
                continue

            seen_paths.add(path)
            node = _describe_device_node(path)

            if node is not None:
                nodes.append(node)

    return sorted(nodes, key=lambda node: node.path)


def _build_device_node_index(
    dev_root: Path,
) -> dict[tuple[int, int], list[Path]]:
    index: dict[tuple[int, int], list[Path]] = {}

    try:
        walker = os.walk(dev_root, followlinks=False)

        for directory, _, filenames in walker:
            for filename in filenames:
                path = Path(directory) / filename

                try:
                    metadata = path.stat()
                except OSError:
                    continue

                if not (stat.S_ISCHR(metadata.st_mode) or stat.S_ISBLK(metadata.st_mode)):
                    continue

                pair = (
                    os.major(metadata.st_rdev),
                    os.minor(metadata.st_rdev),
                )
                index.setdefault(pair, []).append(path)
    except OSError:
        return {}

    return index


def _describe_device_node(path: Path) -> DeviceNode | None:
    try:
        metadata = path.stat()
    except OSError:
        return None

    node_type = "character" if stat.S_ISCHR(metadata.st_mode) else "block"

    return DeviceNode(
        path=str(path),
        node_type=node_type,
        permissions=stat.filemode(metadata.st_mode),
        owner=_username_for_uid(metadata.st_uid),
        group=_group_for_gid(metadata.st_gid),
        readable=os.access(path, os.R_OK),
        writable=os.access(path, os.W_OK),
    )


def _read_usb_id(path: Path) -> str | None:
    value = _read_text(path)

    if value is None:
        return None

    if _USB_ID_PATTERN.fullmatch(value) is None:
        return None

    return value.lower()


def _read_usb_class(path: Path) -> str | None:
    value = _read_text(path)

    if value is None:
        return None

    if re.fullmatch(r"[0-9a-fA-F]{2}", value) is None:
        return None

    return value.lower()


def _read_text(path: Path) -> str | None:
    try:
        value = (
            path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            .strip()
            .strip("\x00")
        )
    except OSError:
        return None

    return value or None


def _read_int(path: Path) -> int | None:
    value = _read_text(path)

    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _read_float(path: Path) -> float | None:
    value = _read_text(path)

    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def _parse_major_minor(
    value: str | None,
) -> tuple[int, int] | None:
    if value is None:
        return None

    try:
        major_text, minor_text = value.split(
            ":",
            maxsplit=1,
        )
        return int(major_text), int(minor_text)
    except (TypeError, ValueError):
        return None


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
