"""Passively discover connected display units from the Linux DRM subsystem."""

from __future__ import annotations

from pathlib import Path

from screwdriver.models import Component, ComponentStatus

_DRM_ROOT = Path("/sys/class/drm")


def collect_display_units(drm_root: Path = _DRM_ROOT) -> list[Component]:
    """Return physically connected DRM display connectors without changing display state."""

    try:
        entries = sorted(drm_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []

    displays: list[Component] = []
    for entry in entries:
        status = _read_text(entry / "status")
        if status is None or status.lower() != "connected":
            continue

        connector = _connector_name(entry.name)
        modes = _read_lines(entry / "modes")
        enabled = _read_text(entry / "enabled")
        edid = _read_bytes(entry / "edid")
        identity = _parse_edid_identity(edid) if edid else {}
        driver = _find_driver(entry)
        display_name = identity.get("monitor_name") or connector

        details: dict[str, str | int | float | bool | None] = {
            "kind": "Display",
            "source": "Linux DRM/sysfs",
            "bus": "DRM",
            "connector": connector,
            "state": "CONNECTED",
            "enabled": enabled.upper() if enabled else None,
            "resolution": modes[0] if modes else None,
            "modes": ", ".join(modes) if modes else None,
            "driver": driver,
            "manufacturer": identity.get("manufacturer"),
            "product_code": identity.get("product_code"),
            "serial_number": identity.get("serial_number"),
            "edid_name": identity.get("monitor_name"),
            "sysfs_path": str(entry),
        }
        displays.append(
            Component(
                category="display",
                name=display_name,
                status=ComponentStatus.OK,
                details=details,
            )
        )

    return displays


def _connector_name(sysfs_name: str) -> str:
    """Strip the DRM card prefix while preserving connector numbering."""

    if "-" not in sysfs_name:
        return sysfs_name
    return sysfs_name.split("-", 1)[1]


def _find_driver(connector: Path) -> str | None:
    for candidate in (connector, *connector.parents):
        device = candidate / "device"
        try:
            device_path = device.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        for node in (device_path, *device_path.parents):
            try:
                return (node / "driver").resolve(strict=True).name
            except (OSError, RuntimeError):
                continue
    return None


def _parse_edid_identity(edid: bytes) -> dict[str, str]:
    """Extract stable human-readable identity fields from a standard EDID block."""

    if len(edid) < 128 or edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return {}

    manufacturer_word = int.from_bytes(edid[8:10], "big")
    letters = [chr(((manufacturer_word >> shift) & 0x1F) + 64) for shift in (10, 5, 0)]
    manufacturer = "".join(letters) if all("A" <= letter <= "Z" for letter in letters) else ""
    product_code = f"0x{int.from_bytes(edid[10:12], 'little'):04x}"
    serial_value = int.from_bytes(edid[12:16], "little")
    result = {
        "manufacturer": manufacturer,
        "product_code": product_code,
    }
    if serial_value:
        result["serial_number"] = str(serial_value)

    for offset in range(54, min(len(edid), 126), 18):
        descriptor = edid[offset : offset + 18]
        if len(descriptor) < 18 or descriptor[:5] != b"\x00\x00\x00\xfc\x00":
            continue
        name = descriptor[5:18].decode("ascii", errors="ignore").strip(" \x00\n\r")
        if name:
            result["monitor_name"] = name
            break
    return result


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8", errors="replace").strip().strip("\x00")
    except OSError:
        return None
    return value or None


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    except OSError:
        return []


def _read_bytes(path: Path) -> bytes | None:
    try:
        value = path.read_bytes()
    except OSError:
        return None
    return value or None
