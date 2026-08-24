"""Passively inventory Linux hardware buses without exercising attached devices."""

from __future__ import annotations

from pathlib import Path

from screwdriver.models import Component, ComponentStatus

_PCI_ROOT = Path("/sys/bus/pci/devices")
_I2C_ROOT = Path("/sys/bus/i2c/devices")
_SPI_ROOT = Path("/sys/bus/spi/devices")
_GPIO_ROOT = Path("/sys/class/gpio")
_DEV_ROOT = Path("/dev")


def collect_hardware_bus_inventory(
    *,
    pci_root: Path = _PCI_ROOT,
    i2c_root: Path = _I2C_ROOT,
    spi_root: Path = _SPI_ROOT,
    gpio_root: Path = _GPIO_ROOT,
    dev_root: Path = _DEV_ROOT,
) -> list[Component]:
    """Collect registered PCI, I2C, SPI, and GPIO hardware from sysfs metadata."""

    return [
        *_collect_pci(pci_root),
        *_collect_i2c(i2c_root, dev_root),
        *_collect_spi(spi_root, dev_root),
        *_collect_gpio(gpio_root, dev_root),
    ]


def _collect_pci(root: Path) -> list[Component]:
    items: list[Component] = []
    for entry in _entries(root):
        vendor = _read_text(entry / "vendor")
        device = _read_text(entry / "device")
        class_code = _read_text(entry / "class")
        driver = _driver_name(entry)
        items.append(
            Component(
                category="hardware interface",
                name=entry.name,
                status=ComponentStatus.OK,
                details={
                    "kind": _pci_type(class_code),
                    "bus": "PCI / PCIe",
                    "channel": entry.name,
                    "vendor_id": vendor,
                    "device_id": device,
                    "class": class_code,
                    "driver": driver,
                    "state": "PRESENT",
                    "source": "Linux PCI/sysfs",
                },
            )
        )
    return items


def _collect_i2c(root: Path, dev_root: Path) -> list[Component]:
    items: list[Component] = []
    for entry in _entries(root):
        name = _read_text(entry / "name") or entry.name
        is_adapter = entry.name.startswith("i2c-")
        channel = str(dev_root / entry.name) if is_adapter else entry.name
        items.append(
            Component(
                category="hardware interface",
                name=name,
                status=ComponentStatus.OK,
                details={
                    "kind": "System" if is_adapter else _infer_type(name),
                    "bus": "I²C",
                    "channel": channel,
                    "driver": _driver_name(entry),
                    "state": "PRESENT",
                    "source": "Linux I2C/sysfs",
                },
            )
        )
    return items


def _collect_spi(root: Path, dev_root: Path) -> list[Component]:
    items: list[Component] = []
    for entry in _entries(root):
        modalias = _read_text(entry / "modalias")
        driver = _driver_name(entry)
        device_node = dev_root / entry.name
        if not device_node.exists() and entry.name.startswith("spi"):
            device_node = dev_root / f"spidev{entry.name.removeprefix('spi')}"
        channel = str(device_node) if device_node.exists() else entry.name
        items.append(
            Component(
                category="hardware interface",
                name=modalias or entry.name,
                status=ComponentStatus.OK,
                details={
                    "kind": _infer_type(f"{modalias or ''} {driver or ''}"),
                    "bus": "SPI",
                    "channel": channel,
                    "driver": driver,
                    "state": "PRESENT",
                    "source": "Linux SPI/sysfs",
                },
            )
        )
    return items


def _collect_gpio(root: Path, dev_root: Path) -> list[Component]:
    items: list[Component] = []
    for entry in _entries(root):
        if not entry.name.startswith("gpiochip"):
            continue
        label = _read_text(entry / "label") or entry.name
        node = dev_root / entry.name
        items.append(
            Component(
                category="hardware interface",
                name=label,
                status=ComponentStatus.OK,
                details={
                    "kind": "System",
                    "bus": "GPIO",
                    "channel": str(node) if node.exists() else entry.name,
                    "driver": _driver_name(entry),
                    "state": "PRESENT",
                    "source": "Linux GPIO/sysfs",
                    "lines": _read_text(entry / "ngpio"),
                },
            )
        )
    return items


def _pci_type(class_code: str | None) -> str:
    value = (class_code or "").lower().removeprefix("0x")
    if value.startswith("03"):
        return "Display"
    if value.startswith("02"):
        return "System"
    if value.startswith("01"):
        return "System"
    if value.startswith("04"):
        return "System"
    return "System"


def _infer_type(text: str) -> str:
    lowered = text.lower()
    for tokens, kind in (
        (("camera",), "Camera"),
        (("touch",), "Touch Input"),
        (("microphone", "mic"), "Microphone"),
        (("lidar",), "LiDAR"),
        (("imu", "inertial"), "IMU"),
        (("gps", "gnss"), "GPS"),
        (("motor", "servo", "gripper", "actuator"), "Actuator"),
        (("sensor", "adc", "temperature", "pressure"), "Sensor"),
    ):
        if any(token in lowered for token in tokens):
            return kind
    return "System"


def _entries(root: Path) -> list[Path]:
    try:
        return sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []


def _driver_name(path: Path) -> str | None:
    for candidate in (path, path / "device"):
        try:
            return (candidate / "driver").resolve(strict=True).name
        except (OSError, RuntimeError):
            continue
    return None


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8", errors="replace").strip().strip("\x00")
    except OSError:
        return None
    return value or None
