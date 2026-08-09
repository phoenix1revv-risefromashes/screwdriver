"""Test passive USB discovery with a simulated sysfs tree."""

from pathlib import Path
from unittest.mock import patch

from screwdriver.collectors.usb import collect_usb_devices
from screwdriver.models import DeviceNode


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_collect_usb_device_identity_drivers_and_nodes(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys/bus/usb/devices"
    real_device = tmp_path / "sys/devices/platform/usb1/1-3"
    real_interface = real_device / "1-3:1.0"
    driver_root = tmp_path / "sys/bus/usb/drivers"

    real_device.mkdir(parents=True)
    real_interface.mkdir()
    (driver_root / "usb").mkdir(parents=True)
    (driver_root / "uvcvideo").mkdir()
    sysfs_root.mkdir(parents=True)

    (sysfs_root / "1-3").symlink_to(real_device)
    (sysfs_root / "1-3:1.0").symlink_to(real_interface)
    (real_device / "driver").symlink_to(driver_root / "usb")
    (real_interface / "driver").symlink_to(driver_root / "uvcvideo")

    _write(real_device / "idVendor", "046D\n")
    _write(real_device / "idProduct", "094C\n")
    _write(real_device / "manufacturer", "Logitech\n")
    _write(real_device / "product", "Brio 100\n")
    _write(real_device / "serial", "camera-serial\n")
    _write(real_device / "busnum", "1\n")
    _write(real_device / "devnum", "4\n")
    _write(real_device / "version", "2.10\n")
    _write(real_device / "speed", "480\n")
    _write(real_device / "bDeviceClass", "ef\n")
    _write(
        real_interface / "video4linux/video0/dev",
        "81:0\n",
    )

    node = DeviceNode(
        path="/dev/video0",
        node_type="character",
        permissions="crw-rw----",
        owner="root",
        group="video",
        readable=True,
        writable=True,
    )

    with (
        patch(
            "screwdriver.collectors.usb._build_device_node_index",
            return_value={(81, 0): [Path("/dev/video0")]},
        ),
        patch(
            "screwdriver.collectors.usb._describe_device_node",
            return_value=node,
        ),
    ):
        devices = collect_usb_devices(
            sysfs_root,
            tmp_path / "dev",
        )

    assert len(devices) == 1

    device = devices[0]

    assert device.usb_id == "046d:094c"
    assert device.display_name == "Logitech Brio 100"
    assert device.bus_number == 1
    assert device.device_number == 4
    assert device.speed_mbps == 480
    assert device.device_class_name == "miscellaneous"
    assert device.drivers == ["usb", "uvcvideo"]
    assert device.device_nodes == [node]
    assert device.device_nodes[0].access == "read-write"


def test_collect_usb_devices_ignores_malformed_records(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys/bus/usb/devices"
    malformed = sysfs_root / "1-9"
    malformed.mkdir(parents=True)

    _write(malformed / "idVendor", "not-a-vendor")
    _write(malformed / "idProduct", "0001")

    assert (
        collect_usb_devices(
            sysfs_root,
            tmp_path / "dev",
        )
        == []
    )


def test_collect_usb_devices_handles_missing_sysfs(
    tmp_path: Path,
) -> None:
    assert (
        collect_usb_devices(
            tmp_path / "missing",
            tmp_path / "dev",
        )
        == []
    )


def test_hub_does_not_inherit_child_device_nodes(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys/bus/usb/devices"
    real_hub = tmp_path / "sys/devices/platform/usb1/1-1"
    child_device = real_hub / "1-1.2"
    child_interface = child_device / "1-1.2:1.0"

    child_interface.mkdir(parents=True)
    sysfs_root.mkdir(parents=True)

    (sysfs_root / "1-1").symlink_to(real_hub)
    (sysfs_root / "1-1.2").symlink_to(child_device)
    (sysfs_root / "1-1.2:1.0").symlink_to(child_interface)

    _write(real_hub / "idVendor", "1234\n")
    _write(real_hub / "idProduct", "0001\n")
    _write(real_hub / "product", "USB Hub\n")

    _write(child_device / "idVendor", "10c4\n")
    _write(child_device / "idProduct", "ea60\n")
    _write(
        child_device / "product",
        "CP2102N USB to UART Bridge\n",
    )
    _write(
        child_interface / "ttyUSB0/dev",
        "188:0\n",
    )

    node = DeviceNode(
        path="/dev/ttyUSB0",
        node_type="character",
        permissions="crw-rw----",
        owner="root",
        group="dialout",
        readable=True,
        writable=True,
    )

    with (
        patch(
            "screwdriver.collectors.usb._build_device_node_index",
            return_value={(188, 0): [Path("/dev/ttyUSB0")]},
        ),
        patch(
            "screwdriver.collectors.usb._describe_device_node",
            return_value=node,
        ),
    ):
        devices = collect_usb_devices(
            sysfs_root,
            tmp_path / "dev",
        )

    hub = next(device for device in devices if device.sysfs_name == "1-1")
    child = next(device for device in devices if device.sysfs_name == "1-1.2")

    assert hub.device_nodes == []
    assert child.device_nodes == [node]
