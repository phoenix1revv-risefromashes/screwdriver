"""Test the public inspect command and report creation."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from screwdriver.cli import main
from screwdriver.models import (
    CPUInfo,
    DeviceNode,
    Finding,
    FindingSeverity,
    HostIdentity,
    MemoryInfo,
    NetworkInfo,
    NetworkInterface,
    OperatingSystemInfo,
    PlatformInfo,
    PowerInfo,
    SystemSnapshot,
    USBDevice,
)


def _snapshot() -> SystemSnapshot:
    return SystemSnapshot(
        identity=HostIdentity(
            hostname="test-robot",
            username="phoenix",
            effective_username="phoenix",
            uid=1000,
            gid=1000,
            groups=[
                "dialout",
                "video",
            ],
            login_shell="/bin/bash",
            machine_id="1234567890abcdef",
        ),
        operating_system=OperatingSystemInfo(
            distribution="Test Linux 1.0",
            kernel="6.8.0-test",
            kernel_build="#1 test",
            architecture="aarch64",
            boot_mode="UEFI",
            init_system="systemd",
            package_manager="apt",
            timezone="UTC",
            boot_time=datetime(
                2026,
                8,
                9,
                tzinfo=UTC,
            ),
            uptime_seconds=3600,
            process_count=100,
        ),
        platform=PlatformInfo(
            family="generic-linux",
        ),
        cpu=CPUInfo(
            model="Test CPU",
            vendor="Test Vendor",
            sockets=1,
            physical_cores=4,
            logical_cpus=8,
            online_cpus=8,
            current_frequency_mhz=2000,
            minimum_frequency_mhz=500,
            maximum_frequency_mhz=2500,
            usage_percent=10,
            load_average=(
                0.1,
                0.2,
                0.3,
            ),
            governor="schedutil",
        ),
        memory=MemoryInfo(
            total_bytes=8 * 1024**3,
            used_bytes=2 * 1024**3,
            available_bytes=6 * 1024**3,
            usage_percent=25,
            shared_bytes=0,
            swap_total_bytes=0,
            swap_used_bytes=0,
            swap_free_bytes=0,
            swap_usage_percent=0,
        ),
        storage_devices=[],
        gpus=[],
        thermal_sensors=[],
        power=PowerInfo(
            source="external",
            battery_present=False,
        ),
        network=NetworkInfo(
            interfaces=[
                NetworkInterface(
                    name="eth0",
                    interface_type="ethernet",
                    ipv4_addresses=[
                        "192.168.10.25/24",
                    ],
                    mac_address="00:11:22:33:44:55",
                    state="up",
                    is_default_route=True,
                )
            ],
            default_interface="eth0",
            default_gateway="192.168.10.1",
            internet_route_available=True,
        ),
        usb_devices=[
            USBDevice(
                sysfs_name="1-3",
                vendor_id="046d",
                product_id="094c",
                manufacturer="Logitech",
                product_name="Brio 100",
                bus_number=1,
                device_number=4,
                drivers=["uvcvideo"],
                device_nodes=[
                    DeviceNode(
                        path="/dev/video0",
                        node_type="character",
                        permissions="crw-rw----",
                        owner="root",
                        group="video",
                        readable=True,
                        writable=True,
                    )
                ],
            )
        ],
        findings=[
            Finding(
                code="HOST_RESOURCES_HEALTHY",
                severity=FindingSeverity.INFO,
                summary=("No host-resource warnings were detected."),
            )
        ],
    )


def test_inspect_defaults_to_local_and_writes_all_reports(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with patch(
        "screwdriver.cli.collect_host",
        return_value=_snapshot(),
    ):
        assert (
            main(
                [
                    "inspect",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out

    assert "Inspection mode: local" in output
    assert "Hostname:           test-robot" in output
    assert "Model:              Test CPU" in output
    assert "IPv4:             192.168.10.25/24" in output
    assert "IPv6:              excluded by output preference" in output
    assert "USB device 1: Logitech Brio 100" in output
    assert "USB ID:           046d:094c" in output
    assert "Kernel drivers:   uvcvideo" in output
    assert "Current access: read-write" in output
    assert "analyze" not in output

    assert (tmp_path / "snapshot.json").is_file()
    assert (tmp_path / "report.txt").is_file()
    assert (tmp_path / "report.html").is_file()
    assert (tmp_path / "inspection.log").is_file()


def test_agentic_mode_is_honest_about_current_scope(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with patch(
        "screwdriver.cli.collect_host",
        return_value=_snapshot(),
    ):
        assert (
            main(
                [
                    "inspect",
                    "--agentic",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out

    assert "Inspection mode: agentic" in output
    assert "agent reasoning not implemented yet" in output


def test_focus_requires_agentic_mode() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "inspect",
                "--local",
                "--focus",
                "camera",
            ]
        )

    assert error.value.code == 2


def test_analyze_command_was_removed() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "analyze",
                "snapshot.json",
            ]
        )

    assert error.value.code == 2
