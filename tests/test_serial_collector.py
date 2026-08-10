"""Test passive serial/TTY discovery with a simulated sysfs tree."""

from pathlib import Path
from unittest.mock import patch

from screwdriver.collectors.serial import collect_serial_devices
from screwdriver.models import DeviceNode
from screwdriver.safety import (
    InspectionMode,
    SafetyPolicy,
)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        value,
        encoding="utf-8",
    )


def test_collect_usb_serial_identity_driver_stable_path_and_access(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys/class/tty"
    usb_device = tmp_path / "sys/devices/platform/usb1/1-2"
    tty_device = usb_device / "1-2:1.0/ttyUSB0"
    driver = tmp_path / "sys/bus/usb-serial/drivers/cp210x"
    dev_root = tmp_path / "dev"

    tty_device.mkdir(parents=True)
    driver.mkdir(parents=True)
    sysfs_root.mkdir(parents=True)
    dev_root.mkdir(parents=True)

    (sysfs_root / "ttyUSB0").mkdir()
    (sysfs_root / "ttyUSB0/device").symlink_to(tty_device)
    (tty_device / "driver").symlink_to(driver)

    _write(
        usb_device / "idVendor",
        "10c4\n",
    )
    _write(
        usb_device / "idProduct",
        "ea60\n",
    )
    _write(
        usb_device / "manufacturer",
        "Silicon Labs\n",
    )
    _write(
        usb_device / "product",
        "CP2102N USB to UART Bridge\n",
    )
    _write(
        usb_device / "serial",
        "bridge-123\n",
    )

    node_path = dev_root / "ttyUSB0"
    node_path.touch()

    stable_path = dev_root / "serial/by-id/usb-Silicon_Labs_CP2102N-bridge-123"
    stable_path.parent.mkdir(parents=True)
    stable_path.symlink_to(Path("../../ttyUSB0"))

    node = DeviceNode(
        path=str(node_path),
        node_type="character",
        permissions="crw-rw----",
        owner="root",
        group="dialout",
        readable=False,
        writable=False,
    )

    with patch(
        ("screwdriver.collectors.serial._describe_device_node"),
        return_value=node,
    ):
        devices = collect_serial_devices(
            sysfs_root,
            dev_root,
        )

    assert len(devices) == 1

    device = devices[0]

    assert device.port == str(node_path)
    assert device.transport == "usb-serial"
    assert device.driver == "cp210x"
    assert device.usb_id == "10c4:ea60"
    assert device.display_name == "Silicon Labs CP2102N USB to UART Bridge"
    assert device.stable_id_path == str(stable_path)
    assert device.device_node is node
    assert device.device_node.access == "denied"


def test_collector_ignores_virtual_ttys_and_never_opens_ports(
    tmp_path: Path,
) -> None:
    sysfs_root = tmp_path / "sys/class/tty"

    (sysfs_root / "tty0").mkdir(parents=True)
    (sysfs_root / "pts0").mkdir()

    with patch(
        "builtins.open",
        side_effect=AssertionError("port opened"),
    ):
        assert (
            collect_serial_devices(
                sysfs_root,
                tmp_path / "dev",
            )
            == []
        )


def test_policy_rejects_collection_when_passive_reads_are_not_authorized(
    tmp_path: Path,
) -> None:
    class RejectAllPolicy(SafetyPolicy):
        def require(
            self,
            request: object,
        ) -> None:
            raise PermissionError("blocked for test")

    policy = RejectAllPolicy(mode=InspectionMode.PASSIVE)

    try:
        collect_serial_devices(
            tmp_path,
            tmp_path,
            policy,
        )
    except PermissionError as error:
        assert str(error) == "blocked for test"
    else:
        raise AssertionError("collector did not enforce its safety policy")
