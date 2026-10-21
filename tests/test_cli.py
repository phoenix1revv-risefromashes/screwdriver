"""Test the public inspect and analyze commands."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from screwdriver.cli import _open_visual_report, build_parser, main
from screwdriver.models import (
    Component,
    ComponentStatus,
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
    SerialDevice,
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
            groups=["dialout", "video"],
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
            boot_time=datetime(2026, 8, 9, tzinfo=UTC),
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
            load_average=(0.1, 0.2, 0.3),
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
                    ipv4_addresses=["192.168.10.25/24"],
                    ipv6_addresses=["fe80::211:22ff:fe33:4455/64"],
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
        serial_devices=[
            SerialDevice(
                port="/dev/ttyUSB0",
                sysfs_name="ttyUSB0",
                transport="usb-serial",
                driver="cp210x",
                stable_id_path=("/dev/serial/by-id/usb-Silicon_Labs_CP2102N_bridge-123"),
                usb_vendor_id="10c4",
                usb_product_id="ea60",
                manufacturer="Silicon Labs",
                product_name="CP2102N USB to UART Bridge",
                serial_number="bridge-123",
                hardware_verified=True,
                verification="USB parent with vendor/product identity",
                device_node=DeviceNode(
                    path="/dev/ttyUSB0",
                    node_type="character",
                    permissions="crw-rw----",
                    owner="root",
                    group="dialout",
                    readable=True,
                    writable=True,
                ),
            )
        ],
        display_inventory=[
            Component(
                category="display",
                name="ELECROW 5 inch Display",
                status=ComponentStatus.OK,
                details={
                    "kind": "Display",
                    "source": "Linux DRM/sysfs",
                    "bus": "DRM",
                    "connector": "HDMI-A-1",
                    "state": "CONNECTED",
                    "enabled": "ENABLED",
                    "resolution": "1024x600",
                    "driver": "tegra-drm",
                    "manufacturer": "ECR",
                    "product_code": "0x0500",
                },
            )
        ],
        software_stack_inventory=[
            Component(
                category="software stack",
                name="Navigation2",
                status=ComponentStatus.OK,
                details={
                    "state": "RUNNING",
                    "running": True,
                    "stack_category": "Navigation",
                    "original_category": "robotics software stack",
                },
            )
        ],
        sensor_inventory=[
            Component(
                category="sensor",
                name="camera — /camera/image_raw",
                status=ComponentStatus.OK,
                details={
                    "state": "AVAILABLE",
                    "kind": "camera",
                    "source": "ROS 2 runtime",
                    "bus": "DDS",
                    "channel": "/camera/image_raw",
                    "message_type": "sensor_msgs/msg/Image",
                    "hardware_node": "/camera_node",
                    "physical_component": "Logitech Brio 100",
                    "physical_bus": "USB",
                    "physical_channel": "/dev/video0",
                    "driver": "uvcvideo",
                    "health": "ENDPOINT_AVAILABLE_DATA_NOT_SAMPLED",
                },
            )
        ],
        actuator_inventory=[
            Component(
                category="actuator/control",
                name="mobile base drive — /cmd_vel",
                status=ComponentStatus.OK,
                details={
                    "state": "AVAILABLE",
                    "kind": "mobile base drive",
                    "source": "ROS 2 runtime",
                    "bus": "DDS",
                    "channel": "/cmd_vel",
                    "health": "COMMAND_ENDPOINT_AVAILABLE_MOTION_NOT_TESTED",
                },
            )
        ],
        ros_device_inventory=[
            Component(
                category="ROS device",
                name="camera — /camera_node",
                status=ComponentStatus.OK,
                details={
                    "device_class": "sensor / input",
                    "kind": "camera",
                    "direction": "input",
                    "source": "ROS 2 runtime",
                    "ros_node": "/camera_node",
                    "topics": "/camera/image_raw",
                    "message_types": "sensor_msgs/msg/Image",
                    "physical_component": "Logitech Brio 100",
                    "physical_bus": "USB",
                    "physical_channel": "/dev/video0",
                    "driver": "uvcvideo",
                    "state": "IN_USE_BY_ROS",
                    "confidence": "VERIFIED",
                },
            ),
            Component(
                category="ROS device",
                name="speaker / audio output — /speaker_node",
                status=ComponentStatus.OK,
                details={
                    "device_class": "audio",
                    "kind": "speaker / audio output",
                    "direction": "output",
                    "source": "ROS 2 runtime",
                    "ros_node": "/speaker_node",
                    "topics": "/audio_out",
                    "message_types": "audio_common_msgs/msg/AudioData",
                    "state": "IN_USE_BY_ROS",
                    "confidence": "VERIFIED",
                },
            ),
            Component(
                category="ROS device",
                name="display / visual output — /face_display",
                status=ComponentStatus.OK,
                details={
                    "device_class": "display / HMI",
                    "kind": "display / visual output",
                    "direction": "output",
                    "source": "ROS 2 runtime",
                    "ros_node": "/face_display",
                    "topics": "/face/image",
                    "message_types": "sensor_msgs/msg/Image",
                    "state": "IN_USE_BY_ROS",
                    "confidence": "CORRELATED",
                },
            ),
            Component(
                category="ROS device",
                name="mobile base drive — /base_controller",
                status=ComponentStatus.OK,
                details={
                    "device_class": "actuator / output",
                    "kind": "mobile base drive",
                    "direction": "output / control",
                    "source": "ROS 2 runtime",
                    "ros_node": "/base_controller",
                    "topics": "/cmd_vel",
                    "message_types": "geometry_msgs/msg/Twist",
                    "state": "IN_USE_BY_ROS",
                    "confidence": "VERIFIED",
                },
            ),
        ],
        ros_runtime_inventory=[
            Component(
                category="ROS runtime",
                name="ROS 2 graph",
                status=ComponentStatus.OK,
                details={
                    "state": "RUNNING",
                    "nodes": 4,
                    "topics": 8,
                    "services": 3,
                    "actions": 1,
                    "ros_distro": "humble",
                    "domain_id": "0",
                    "middleware": "rmw_fastrtps_cpp",
                    "discovery_mode": "daemon",
                    "environment_recovered": False,
                    "probe": "metadata only",
                },
            ),
            Component(
                category="ROS node",
                name="/camera_node",
                status=ComponentStatus.OK,
                details={
                    "state": "RUNNING",
                    "publishers": "/camera/image_raw",
                },
            ),
            Component(
                category="ROS topic",
                name="/camera/image_raw",
                status=ComponentStatus.OK,
                details={
                    "state": "AVAILABLE",
                    "type": "sensor_msgs/msg/Image",
                },
            ),
            Component(
                category="ROS service",
                name="/camera/get_parameters",
                status=ComponentStatus.OK,
                details={
                    "state": "AVAILABLE",
                    "type": "rcl_interfaces/srv/GetParameters",
                },
            ),
            Component(
                category="ROS action",
                name="/navigate_to_pose",
                status=ComponentStatus.OK,
                details={
                    "state": "AVAILABLE",
                    "type": "nav2_msgs/action/NavigateToPose",
                },
            ),
        ],
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        findings=[
            Finding(
                code="HOST_RESOURCES_HEALTHY",
                severity=FindingSeverity.INFO,
                summary="No host-resource warnings were detected.",
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
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "Inspection complete" in output
    assert "HTML report:" in output
    assert "Report link: file://" in output
    assert "Text report:" in output
    assert "Browser: disabled by --no-open" in output
    assert "HOST IDENTITY" not in output
    assert "USB device 1:" not in output

    local_runs = [path for path in (tmp_path / "local").iterdir() if path.name != "latest"]
    assert len(local_runs) == 1
    run = local_runs[0]
    assert (run / "snapshot.json").is_file()
    assert (run / "report.txt").is_file()
    assert (run / "report.html").is_file()
    assert (run / "inspection.log").is_file()
    assert (run / "report-manifest.json").is_file()
    assert (tmp_path / "local" / "latest").resolve() == run.resolve()

    snapshot_json = (run / "snapshot.json").read_text(encoding="utf-8")
    html_report = (run / "report.html").read_text(encoding="utf-8")
    text_report = (run / "report.txt").read_text(encoding="utf-8")

    assert html_report.count('<details class="main-section"') == 7
    for heading in (
        "1. CORE SYSTEM SPECS",
        "2. CONNECTIVITY",
        "3. HARDWARE INVENTORY",
        "4. ROS 2",
        "5. ROBOTICS SOFTWARE STACKS",
        "6. DIAGNOSTICS",
        "7. REPORT &amp; PROVENANCE",
    ):
        assert heading in html_report

    assert "Universal inspection of Linux-based robotic computers" in html_report
    assert "Passive inspection — no hardware was activated or modified" in html_report
    assert "HOST IDENTITY" in html_report
    assert "STORAGE DEVICES" in html_report
    assert "NETWORK INTERFACES" in html_report
    assert "fe80::211:22ff:fe33:4455/64" not in html_report
    assert "excluded by output preference" not in html_report
    assert "USB HARDWARE" in html_report
    assert "SERIAL / TTY" in html_report
    assert "DISPLAY UNITS" in html_report
    assert "ELECROW 5 inch Display" in html_report
    assert "1024x600" in html_report
    assert "ROBOTICS SOFTWARE STACKS" in html_report
    assert "ROS 2 OVERVIEW" in html_report
    assert "DIAGNOSTIC SUMMARY" in html_report
    assert "REPORTS" in html_report
    assert "PROVENANCE" in html_report
    assert "/dev/video0" in html_report
    assert "crw-rw----" in html_report
    assert "/dev/ttyUSB0" in html_report
    assert "/camera/image_raw" in html_report
    assert "color-scheme: dark" in html_report
    assert "--paper: #0a0a0a" in html_report
    assert "--ink: #f1f1f1" in html_report
    assert "<th>Type</th>" in html_report

    usb_section = html_report.split("USB HARDWARE", 1)[1].split("SERIAL / TTY", 1)[0]
    assert "<th>Health</th>" not in usb_section
    assert "<th>Confidence</th>" not in usb_section
    assert "Camera" in usb_section

    stack_section = html_report.split("5. ROBOTICS SOFTWARE STACKS", 1)[1].split(
        "6. DIAGNOSTICS", 1
    )[0]
    assert "Version / Packages" in stack_section
    assert "Operational Stage" in stack_section
    assert "<th>Installed</th>" not in stack_section
    assert "OPERATIONAL EVIDENCE" not in stack_section
    assert "<th>Configured</th>" not in stack_section
    assert "<th>Running</th>" not in stack_section

    connectivity_section = html_report.split("2. CONNECTIVITY", 1)[1].split(
        "3. HARDWARE INVENTORY", 1
    )[0]
    assert "<th>IPv6</th>" not in connectivity_section

    nodes_section = html_report.split("ROS 2 NODES", 1)[1].split("ROS 2 TOPICS", 1)[0]
    assert "<th>Publishers</th>" in nodes_section
    assert "<th>Subscribers</th>" in nodes_section
    assert "<th>Services</th>" not in nodes_section
    assert "<th>Clients</th>" not in nodes_section
    assert "<th>Action servers</th>" not in nodes_section
    assert "<th>Action clients</th>" not in nodes_section

    ros_device_section = html_report.split("ROS 2 DEVICE USAGE", 1)[1].split(
        "5. ROBOTICS SOFTWARE STACKS", 1
    )[0]
    for heading in ("ROS Node", "Physical Device", "Type", "Device Path"):
        assert f"<th>{heading}</th>" in ros_device_section
    for heading in (
        "Class",
        "Kind",
        "Direction",
        "Topics",
        "Message types",
        "Physical bus",
        "Physical channel",
        "Driver",
        "State",
        "Confidence",
    ):
        assert f"<th>{heading}</th>" not in ros_device_section
    assert "/camera_node" in ros_device_section
    assert "Logitech Brio 100" in ros_device_section

    assert "/dev/video0" in snapshot_json
    assert '"permissions": "crw-rw----"' in snapshot_json
    assert '"serial_devices"' in snapshot_json
    assert '"display_inventory"' in snapshot_json
    assert '"software_stack_inventory"' in snapshot_json
    assert '"sensor_inventory"' in snapshot_json
    assert '"actuator_inventory"' in snapshot_json
    assert '"ros_device_inventory"' in snapshot_json
    assert '"ros_runtime_inventory"' in snapshot_json
    assert '"report_timezone": "America/Los_Angeles"' in snapshot_json
    assert '"created_at": "2026-08-10T05:00:00-07:00"' in snapshot_json
    assert "Snapshot SHA-256:" in text_report
    assert "Screwdriver:      1.3.0" in text_report
    assert "software_stacks=1" in (run / "inspection.log").read_text(encoding="utf-8")
    assert "ros_devices=4" in (run / "inspection.log").read_text(encoding="utf-8")
    assert "CURRENT DEVICES IN USE BY ROS 2" in text_report
    assert "fe80::211:22ff:fe33:4455/64" in text_report
    assert "excluded by output preference" not in text_report
    assert '"hardware_bus_inventory"' in snapshot_json


def test_html_hides_generic_kernel_tty_slots_but_snapshot_keeps_them(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.serial_devices.append(
        SerialDevice(
            port="/dev/ttyS17",
            sysfs_name="ttyS17",
            transport="onboard-uart",
            driver="port",
            hardware_verified=False,
            verification="serial8250 kernel slot without confirmed UART hardware",
            device_node=DeviceNode(
                path="/dev/ttyS17",
                node_type="character",
                permissions="crw-rw----",
                owner="root",
                group="dialout",
                readable=True,
                writable=True,
            ),
        )
    )

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    capsys.readouterr()
    run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    snapshot_json = (run / "snapshot.json").read_text(encoding="utf-8")
    html_report = (run / "report.html").read_text(encoding="utf-8")

    assert "/dev/ttyS17" in snapshot_json
    assert "/dev/ttyS17" not in html_report
    assert "/dev/ttyUSB0" in html_report


def test_direct_local_session_opens_report_on_same_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")

    with (
        patch(
            "screwdriver.cli.shutil.which",
            side_effect=lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
        ),
        patch(
            "screwdriver.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(["xdg-open"], 0),
        ) as opener,
    ):
        opened, note = _open_visual_report(report, disabled=False)

    assert opened is True
    assert note == "opened locally via xdg-open"
    command = opener.call_args.args[0]
    assert command[0] == "xdg-open"
    assert command[1] == report.resolve().as_uri()


def test_ssh_session_does_not_claim_remote_browser_opened(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSH_CONNECTION", "192.0.2.1 5555 192.0.2.2 22")
    monkeypatch.setenv("SSH_TTY", "/dev/pts/4")

    with (
        patch("screwdriver.cli.collect_host", return_value=_snapshot()),
        patch("screwdriver.cli.webbrowser.open") as browser_open,
    ):
        assert main(["inspect", "--output", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    browser_open.assert_not_called()
    assert "Browser: client-side opening available via screwdriver-ssh" in output
    assert "Report link: file://" in output
    assert "Remote report link: sftp://" in output
    assert "Client auto-open command (run on the SSH client PC):" in output
    assert "screwdriver-ssh" in output
    assert "Browser: opened" not in output


def test_find_issues_prints_only_actionable_findings_and_keeps_full_reports(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.findings.extend(
        [
            Finding(
                code="SERIAL_PERMISSION_DENIED",
                severity=FindingSeverity.ERROR,
                summary="Serial controller is inaccessible.",
                evidence="/dev/ttyUSB0 is not accessible to the current user.",
                recommendation="Check dialout-group access for the serial device.",
            ),
            Finding(
                code="THERMAL_WARNING",
                severity=FindingSeverity.WARNING,
                summary="CPU temperature is elevated.",
                evidence="Peak temperature: 87 C.",
                recommendation="Check cooling and workload before continuing.",
            ),
        ]
    )

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--find-issues", "--output", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "SCREWDRIVER — FIND ISSUES" in output
    assert "2 issues found" in output
    assert "[ERROR] Serial controller is inaccessible." in output
    assert "[WARNING] CPU temperature is elevated." in output
    assert "No host-resource warnings were detected." not in output
    assert "HOST IDENTITY" not in output
    assert "OPERATING SYSTEM" not in output
    assert "Full scan saved:" in output

    runs = [path for path in (tmp_path / "local").iterdir() if path.name != "latest"]
    assert len(runs) == 1
    full_text = (runs[0] / "report.txt").read_text(encoding="utf-8")
    assert "HOST IDENTITY" in full_text
    assert "No host-resource warnings were detected." in full_text
    assert "Serial controller is inaccessible." in full_text
    assert (runs[0] / "snapshot.json").is_file()
    assert (runs[0] / "report.html").is_file()


def test_find_issues_can_add_agentic_reasoning_without_dumping_full_local_report(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.findings.append(
        Finding(
            code="ROS_DOMAIN_ID_INVALID",
            severity=FindingSeverity.ERROR,
            summary="ROS_DOMAIN_ID is invalid.",
            evidence="ROS_DOMAIN_ID=abc",
            recommendation="Set ROS_DOMAIN_ID to a valid integer and rescan.",
        )
    )

    with (
        patch("screwdriver.cli.collect_host", return_value=snapshot),
        patch(
            "screwdriver.cli._open_visual_report",
            return_value=(True, "opened locally via test"),
        ) as opener,
    ):
        assert (
            main(
                [
                    "inspect",
                    "--find-issues",
                    "--agentic",
                    "--provider",
                    "none",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out
    assert "SCREWDRIVER — AGENTIC ISSUE ANALYSIS" in output
    assert "ROS_DOMAIN_ID is invalid." in output
    assert "Analysis engine: deterministic analysis" in output
    assert "HOST IDENTITY" not in output
    assert "AGENTIC REPORTS" not in output
    assert "Full analysis saved:" in output
    assert "Agentic System Diagnostic Report" in output
    agentic_run = next(path for path in (tmp_path / "agentic").iterdir() if path.name != "latest")
    assert (agentic_run / "system-blueprint.html").is_file()
    assert (agentic_run / "diagnostic-report.html").is_file()
    assert not (agentic_run / "compact_snapshot.html").exists()
    assert {path.name for path in agentic_run.iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }
    opener.assert_called_once_with(
        agentic_run / "diagnostic-report.html",
        disabled=False,
    )


def test_find_issues_is_available_with_local_or_agentic_mode() -> None:
    parser = build_parser()

    local = parser.parse_args(["inspect", "--find-issues"])
    explicit_local = parser.parse_args(["inspect", "--local", "--find-issues"])
    agentic = parser.parse_args(["inspect", "--find-issues", "--agentic"])

    assert local.find_issues is True
    assert explicit_local.find_issues is True
    assert agentic.find_issues is True
    assert agentic.agentic is True


def test_agentic_mode_generates_only_blueprint_and_opens_it(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        patch("screwdriver.cli.collect_host", return_value=_snapshot()),
        patch(
            "screwdriver.cli._open_visual_report",
            return_value=(True, "opened locally via test"),
        ) as opener,
    ):
        assert (
            main(
                [
                    "inspect",
                    "--agentic",
                    "--provider",
                    "none",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out
    assert "Agentic System Blueprint Report" in output
    assert "HTML report:" in output
    assert "Analysis engine: deterministic analysis" in output
    assert "Compact snapshot:" not in output
    assert "Agentic System Diagnostic Report:" in output

    local_runs = [path for path in (tmp_path / "local").iterdir() if path.name != "latest"]
    agentic_runs = [path for path in (tmp_path / "agentic").iterdir() if path.name != "latest"]
    assert len(local_runs) == len(agentic_runs) == 1
    assert local_runs[0].name == agentic_runs[0].name
    assert (local_runs[0] / "snapshot.json").is_file()
    assert (agentic_runs[0] / "system-blueprint.html").is_file()
    assert (agentic_runs[0] / "diagnostic-report.html").is_file()
    assert not (agentic_runs[0] / "compact_snapshot.html").exists()
    assert {path.name for path in agentic_runs[0].iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }
    assert (tmp_path / "local" / "latest").resolve() == local_runs[0].resolve()
    assert (tmp_path / "agentic" / "latest").resolve() == agentic_runs[0].resolve()
    opener.assert_called_once_with(
        agentic_runs[0] / "system-blueprint.html",
        disabled=False,
    )


def test_agentic_mode_writes_blueprint_and_diagnostic_when_issue_exists(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.findings.append(
        Finding(
            code="MEMORY_HIGH_USAGE",
            severity=FindingSeverity.WARNING,
            summary="Physical memory usage is above 90%.",
            evidence="Measured usage: 91.0%",
            recommendation="Identify the process consuming memory; verify usage again.",
        )
    )

    with (
        patch("screwdriver.cli.collect_host", return_value=snapshot),
        patch(
            "screwdriver.cli._open_visual_report",
            return_value=(True, "opened locally via test"),
        ) as opener,
    ):
        assert (
            main(
                [
                    "inspect",
                    "--agentic",
                    "--provider",
                    "none",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out
    agentic_run = next(path for path in (tmp_path / "agentic").iterdir() if path.name != "latest")
    assert (agentic_run / "system-blueprint.html").is_file()
    assert (agentic_run / "diagnostic-report.html").is_file()
    assert {path.name for path in agentic_run.iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }
    assert "Agentic System Diagnostic Report:" in output
    # Plain --agentic still opens the Blueprint; the Diagnostic is generated
    # automatically for the issue and is available beside it.
    opener.assert_called_once_with(
        agentic_run / "system-blueprint.html",
        disabled=False,
    )


def test_find_issues_agentic_writes_diagnostic_even_when_no_issue(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        patch("screwdriver.cli.collect_host", return_value=_snapshot()),
        patch(
            "screwdriver.cli._open_visual_report",
            return_value=(True, "opened locally via test"),
        ) as opener,
    ):
        assert (
            main(
                [
                    "inspect",
                    "--find-issues",
                    "--agentic",
                    "--provider",
                    "none",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    agentic_run = next(path for path in (tmp_path / "agentic").iterdir() if path.name != "latest")
    assert (agentic_run / "system-blueprint.html").is_file()
    assert (agentic_run / "diagnostic-report.html").is_file()
    assert {path.name for path in agentic_run.iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }
    diagnostic = (agentic_run / "diagnostic-report.html").read_text(encoding="utf-8")
    assert "No issues found right now." in diagnostic
    output = capsys.readouterr().out
    assert "Agentic System Diagnostic Report" in output
    opener.assert_called_once_with(
        agentic_run / "diagnostic-report.html",
        disabled=False,
    )


def test_repeated_inspections_never_overwrite_timestamped_runs(tmp_path: Path) -> None:
    snapshot = _snapshot()
    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--output", str(tmp_path)]) == 0
        assert main(["inspect", "--output", str(tmp_path)]) == 0

    runs = sorted(path.name for path in (tmp_path / "local").iterdir() if path.name != "latest")
    assert runs == ["2026-08-10_05:00:00", "2026-08-10_05:00:00_01"]
    assert all((tmp_path / "local" / run / "snapshot.json").is_file() for run in runs)
    assert (tmp_path / "local" / "latest").resolve().name == "2026-08-10_05:00:00_01"


def test_default_report_root_is_plural_reports() -> None:
    parser = build_parser()

    assert parser.parse_args(["inspect"]).output == Path("reports")
    assert parser.parse_args(["analyze", "snapshot.json"]).output == Path("reports")


def test_agentic_cli_accepts_anthropic_and_openai_provider_model_pairs() -> None:
    parser = build_parser()

    anthropic = parser.parse_args(
        [
            "inspect",
            "--agentic",
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-5",
            "--effort",
            "high",
        ]
    )
    openai = parser.parse_args(
        [
            "inspect",
            "--agentic",
            "--provider",
            "openai",
            "--model",
            "gpt-5.4",
            "--effort",
            "light",
        ]
    )

    assert (anthropic.provider, anthropic.model, anthropic.effort) == (
        "anthropic",
        "claude-sonnet-5",
        "high",
    )
    assert (openai.provider, openai.model, openai.effort) == (
        "openai",
        "gpt-5.4",
        "light",
    )


def test_agentic_cli_exposes_only_light_medium_and_high_effort() -> None:
    parser = build_parser()

    assert parser.parse_args(["inspect", "--agentic"]).effort == "medium"
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["inspect", "--agentic", "--effort", "low"])

    assert error.value.code == 2


def test_empty_optional_runtime_inventories_are_not_printed(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.software_stack_inventory = []
    snapshot.sensor_inventory = []
    snapshot.actuator_inventory = []
    snapshot.ros_device_inventory = []

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    capsys.readouterr()
    run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    html_report = (run / "report.html").read_text(encoding="utf-8")
    assert "PHYSICAL SENSOR INVENTORY" not in html_report
    assert "CURRENT DEVICES IN USE BY ROS 2" not in html_report
    assert "PHYSICAL ACTUATOR / CONTROL INVENTORY" not in html_report
    assert "ROS 2 OVERVIEW" in html_report


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


def test_analyze_existing_snapshot_generates_exactly_two_agentic_reports(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "analysis"
    snapshot_path.write_text(
        json.dumps(_snapshot().to_dict()),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "analyze",
                str(snapshot_path),
                "--provider",
                "none",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "SCREWDRIVER AGENTIC ANALYSIS" in output
    assert "Agentic System Blueprint Report:" in output
    assert "Agentic System Diagnostic Report:" in output
    assert "Repairs executed:  no" in output
    runs = [path for path in (output_path / "agentic").iterdir() if path.name != "latest"]
    assert len(runs) == 1
    assert (output_path / "agentic" / "latest").resolve() == runs[0].resolve()
    assert not (runs[0] / "compact_snapshot.html").exists()
    assert (runs[0] / "system-blueprint.html").is_file()
    assert (runs[0] / "diagnostic-report.html").is_file()
    assert {path.name for path in runs[0].iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }


def test_analyze_local_latest_uses_real_scan_id_instead_of_latest(tmp_path: Path) -> None:
    snapshot = _snapshot()
    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    local_run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    latest_snapshot = tmp_path / "local" / "latest" / "snapshot.json"
    assert latest_snapshot.resolve() == (local_run / "snapshot.json").resolve()

    assert (
        main(
            [
                "analyze",
                str(latest_snapshot),
                "--provider",
                "none",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )

    agentic_runs = [path for path in (tmp_path / "agentic").iterdir() if path.name != "latest"]
    assert len(agentic_runs) == 1
    assert agentic_runs[0].name == local_run.name
    assert agentic_runs[0].name != "latest"


def test_html_hides_system_bus_noise_but_keeps_robot_relevant_bus_devices(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.hardware_bus_inventory = [
        Component(
            category="hardware interface",
            name="tegra-i2c-adapter",
            status=ComponentStatus.OK,
            details={
                "kind": "System",
                "bus": "I²C",
                "channel": "/dev/i2c-1",
                "driver": "tegra-i2c",
                "state": "PRESENT",
                "source": "Linux I2C/sysfs",
            },
        ),
        Component(
            category="hardware interface",
            name="BNO055 IMU",
            status=ComponentStatus.OK,
            details={
                "kind": "IMU",
                "bus": "I²C",
                "channel": "1-0028",
                "driver": "bno055",
                "state": "PRESENT",
                "source": "Linux I2C/sysfs",
            },
        ),
    ]

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    capsys.readouterr()
    run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    html_report = (run / "report.html").read_text(encoding="utf-8")
    snapshot_json = (run / "snapshot.json").read_text(encoding="utf-8")

    assert "BNO055 IMU" in html_report
    assert "tegra-i2c-adapter" not in html_report
    assert "BNO055 IMU" in snapshot_json
    assert "tegra-i2c-adapter" in snapshot_json


def test_html_software_stacks_use_one_full_functional_catalog_table(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.software_stack_inventory = [
        Component(
            category="software stack",
            name="Navigation2",
            status=ComponentStatus.OK,
            details={
                "stack_category": "Navigation",
                "state": "RUNNING",
                "running": True,
                "version": "nav2_bringup 1.1.18",
                "detected_packages": "nav2_bringup, nav2_controller",
                "original_category": "robotics software stack",
            },
        ),
        Component(
            category="software stack",
            name="SLAM Toolbox",
            status=ComponentStatus.UNKNOWN,
            details={
                "stack_category": "SLAM / Mapping",
                "state": "NOT_INSTALLED",
                "original_category": "robotics software stack",
            },
        ),
        Component(
            category="software stack",
            name="MoveIt",
            status=ComponentStatus.UNKNOWN,
            details={
                "stack_category": "Manipulation",
                "state": "NOT_INSTALLED",
                "original_category": "robotics software stack",
            },
        ),
        Component(
            category="software stack",
            name="Gazebo",
            status=ComponentStatus.UNKNOWN,
            details={
                "stack_category": "Simulation",
                "state": "NOT_INSTALLED",
                "original_category": "robotics software stack",
            },
        ),
        Component(
            category="software stack",
            name="teleop_twist_keyboard",
            status=ComponentStatus.UNKNOWN,
            details={
                "stack_category": "Teleoperation",
                "state": "NOT_INSTALLED",
                "original_category": "robotics software stack",
            },
        ),
        Component(
            category="software stack",
            name="Camera drivers",
            status=ComponentStatus.UNKNOWN,
            details={"state": "NOT_INSTALLED"},
        ),
        Component(
            category="software stack",
            name="Docker",
            status=ComponentStatus.OK,
            details={
                "state": "RUNNING",
                "original_category": "container runtime",
            },
        ),
    ]

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    capsys.readouterr()
    run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    html_report = (run / "report.html").read_text(encoding="utf-8")
    stack_section = html_report.split("5. ROBOTICS SOFTWARE STACKS", 1)[1].split(
        "6. DIAGNOSTICS", 1
    )[0]

    assert stack_section.count("<table") == 1
    for heading in ("Stack", "Type", "Version / Packages", "Operational Stage"):
        assert f"<th>{heading}</th>" in stack_section
    for name in (
        "Navigation2",
        "SLAM Toolbox",
        "MoveIt",
        "Gazebo",
        "teleop_twist_keyboard",
    ):
        assert name in stack_section
    assert "NOT_INSTALLED" in stack_section
    assert "Camera drivers" not in stack_section
    assert "Docker" not in stack_section
    assert stack_section.index("Navigation2") < stack_section.index("SLAM Toolbox")
    assert stack_section.index("SLAM Toolbox") < stack_section.index("MoveIt")
    assert stack_section.index("MoveIt") < stack_section.index("Gazebo")
    assert stack_section.index("Gazebo") < stack_section.index("teleop_twist_keyboard")


def test_ros_device_usage_correlates_audio_nodes_to_single_usb_audio_device(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.usb_devices.append(
        USBDevice(
            sysfs_name="1-7",
            vendor_id="2886",
            product_id="001a",
            manufacturer="Seeed Studio",
            product_name="reSpeaker XVF3800 4-Mic Array",
            bus_number=1,
            device_number=7,
            drivers=["snd-usb-audio", "usbhid"],
            device_nodes=[
                DeviceNode(
                    path="/dev/snd/pcmC2D0c",
                    node_type="character",
                    permissions="crw-rw----",
                    owner="root",
                    group="audio",
                    readable=True,
                    writable=True,
                ),
                DeviceNode(
                    path="/dev/snd/pcmC2D0p",
                    node_type="character",
                    permissions="crw-rw----",
                    owner="root",
                    group="audio",
                    readable=True,
                    writable=True,
                ),
            ],
        )
    )
    snapshot.ros_device_inventory.extend(
        [
            Component(
                category="ROS device",
                name="microphone — /cutie_mic_recorder",
                status=ComponentStatus.OK,
                details={
                    "kind": "microphone",
                    "ros_node": "/cutie_mic_recorder",
                    "source": "ROS 2 runtime",
                    "state": "IN_USE_BY_ROS",
                },
            ),
        ]
    )

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
        assert main(["inspect", "--no-open", "--output", str(tmp_path)]) == 0

    capsys.readouterr()
    run = next(path for path in (tmp_path / "local").iterdir() if path.name != "latest")
    html_report = (run / "report.html").read_text(encoding="utf-8")
    ros_device_section = html_report.split("ROS 2 DEVICE USAGE", 1)[1].split(
        "5. ROBOTICS SOFTWARE STACKS", 1
    )[0]

    assert "/cutie_mic_recorder" in ros_device_section
    assert "reSpeaker XVF3800 4-Mic Array" in ros_device_section
    assert "Microphone" in ros_device_section
    assert "/dev/snd/pcmC2D0c" in ros_device_section
    assert "/speaker_node" in ros_device_section
    assert "/dev/snd/pcmC2D0p" in ros_device_section


def test_agentic_no_open_disables_selected_report_launch(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        patch("screwdriver.cli.collect_host", return_value=_snapshot()),
        patch("screwdriver.cli._open_visual_report", wraps=_open_visual_report) as opener,
    ):
        assert (
            main(
                [
                    "inspect",
                    "--agentic",
                    "--provider",
                    "none",
                    "--no-open",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out
    assert "Agentic System Blueprint Report" in output
    assert "Browser: disabled by --no-open" in output
    agentic_run = next(path for path in (tmp_path / "agentic").iterdir() if path.name != "latest")
    opener.assert_called_once_with(
        agentic_run / "system-blueprint.html",
        disabled=True,
    )
