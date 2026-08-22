"""Test the public inspect and analyze commands."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from screwdriver.cli import build_parser, main
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
        software_stack_inventory=[
            Component(
                category="software stack",
                name="Navigation2",
                status=ComponentStatus.OK,
                details={"state": "RUNNING", "running": True},
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
        assert main(["inspect", "--output", str(tmp_path)]) == 0

    output = capsys.readouterr().out

    assert "Inspection mode: local" in output
    assert "Hostname:           test-robot" in output
    assert "Model:              Test CPU" in output
    assert "IPv4:             192.168.10.25/24" in output
    assert "IPv6:              excluded by output preference" in output
    assert "USB device 1: Logitech Brio 100" in output
    assert "USB ID:           046d:094c" in output
    assert "Kernel drivers:   uvcvideo" in output
    assert "Access:           read-write" in output
    assert "Probe safety:    PASSIVE" in output
    assert "SERIAL / TTY DIAGNOSTICS" in output
    assert "Serial device 1: Silicon Labs CP2102N USB to UART Bridge" in output
    assert "Port:             /dev/ttyUSB0" in output
    assert "Stable by-id:     /dev/serial/by-id/usb-Silicon_Labs" in output
    assert "ROBOTICS SOFTWARE STACKS" in output
    assert "Navigation2" in output
    assert "CURRENT DEVICES IN USE BY ROS 2" in output
    assert "1. Camera" in output
    assert "2. Speaker" in output
    assert "3. Display unit" in output
    assert "4. Mobile base" in output
    assert "ROS 2 SENSOR / INPUT DEVICES" not in output
    assert "ROS 2 AUDIO DEVICES" not in output
    assert "speaker / audio output — /speaker_node" not in output
    assert "ROS 2 OVERVIEW" in output
    assert "ROS distribution:   humble" in output
    assert "ROS 2 NODES" in output
    assert "1. /camera_node" in output
    assert "ROS 2 TOPICS" in output
    assert "1. /camera/image_raw" in output
    assert "ROS 2 SERVICES" in output
    assert "1. /camera/get_parameters" in output
    assert "ROS 2 ACTIONS" in output
    assert "1. /navigate_to_pose" in output
    assert "Report timezone: America/Los_Angeles" in output
    assert "Boot time:          2026-08-08 17:00:00 PDT" in output
    assert "Device nodes" not in output
    assert "crw-rw----" not in output
    assert "analyze" not in output

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

    assert "/dev/video0" in snapshot_json
    assert '"permissions": "crw-rw----"' in snapshot_json
    assert "/dev/video0" in html_report
    assert "crw-rw----" in html_report
    assert "USB device-node details" in html_report
    assert "Serial / TTY details" in html_report
    assert "/dev/ttyUSB0" in html_report
    assert '"serial_devices"' in snapshot_json
    assert '"software_stack_inventory"' in snapshot_json
    assert '"sensor_inventory"' in snapshot_json
    assert '"actuator_inventory"' in snapshot_json
    assert '"ros_device_inventory"' in snapshot_json
    assert '"ros_runtime_inventory"' in snapshot_json
    assert "ROS 2 overview" in html_report
    assert "ROS 2 nodes" in html_report
    assert "ROS 2 topics" in html_report
    assert "ROS 2 services" in html_report
    assert "ROS 2 actions" in html_report
    assert "ROS 2 sensor / input devices" in html_report
    assert "ROS 2 audio devices" in html_report
    assert "ROS 2 displays / HMI" in html_report
    assert "ROS 2 actuators / output devices" in html_report
    assert "/camera/image_raw" in html_report
    assert '"report_timezone": "America/Los_Angeles"' in snapshot_json
    assert "Snapshot SHA-256:" in text_report
    assert "Screwdriver:      1.1.0" in text_report
    assert '"created_at": "2026-08-10T05:00:00-07:00"' in snapshot_json
    assert "software_stacks=1" in (run / "inspection.log").read_text(encoding="utf-8")
    assert "ros_devices=4" in (run / "inspection.log").read_text(encoding="utf-8")
    assert "CURRENT DEVICES IN USE BY ROS 2" in text_report


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

    with patch("screwdriver.cli.collect_host", return_value=snapshot):
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


def test_find_issues_is_available_with_local_or_agentic_mode() -> None:
    parser = build_parser()

    local = parser.parse_args(["inspect", "--find-issues"])
    explicit_local = parser.parse_args(["inspect", "--local", "--find-issues"])
    agentic = parser.parse_args(["inspect", "--find-issues", "--agentic"])

    assert local.find_issues is True
    assert explicit_local.find_issues is True
    assert agentic.find_issues is True
    assert agentic.agentic is True


def test_agentic_mode_separates_local_and_agentic_report_sets(
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
                    "--provider",
                    "none",
                    "--output",
                    str(tmp_path),
                ]
            )
            == 0
        )

    output = capsys.readouterr().out
    assert "Inspection mode: agentic" in output
    assert "System blueprint:" in output
    assert "Compact snapshot:" in output
    assert "Diagnostic report:" in output
    assert "Problems reported:" in output
    local_runs = [path for path in (tmp_path / "local").iterdir() if path.name != "latest"]
    agentic_runs = [path for path in (tmp_path / "agentic").iterdir() if path.name != "latest"]
    assert len(local_runs) == len(agentic_runs) == 1
    assert local_runs[0].name == agentic_runs[0].name
    assert (local_runs[0] / "snapshot.json").is_file()
    assert (agentic_runs[0] / "compact_snapshot.html").is_file()
    assert (agentic_runs[0] / "system-blueprint.html").is_file()
    assert (agentic_runs[0] / "diagnostic-report.html").is_file()
    assert (agentic_runs[0] / "agent-analysis.json").is_file()
    assert (agentic_runs[0] / "report-manifest.json").is_file()
    assert (tmp_path / "local" / "latest").resolve() == local_runs[0].resolve()
    assert (tmp_path / "agentic" / "latest").resolve() == agentic_runs[0].resolve()


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
        assert main(["inspect", "--output", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "SOFTWARE STACK INVENTORY" not in output
    assert "PHYSICAL SENSOR INVENTORY" not in output
    assert "CURRENT DEVICES IN USE BY ROS 2" not in output
    assert "PHYSICAL ACTUATOR / CONTROL INVENTORY" not in output
    assert "ROS 2 OVERVIEW" in output


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


def test_analyze_existing_snapshot_generates_timestamped_agentic_reports(
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
    assert "Repairs executed:  no" in output
    runs = [path for path in (output_path / "agentic").iterdir() if path.name != "latest"]
    assert len(runs) == 1
    assert (output_path / "agentic" / "latest").resolve() == runs[0].resolve()
    assert (runs[0] / "compact_snapshot.html").is_file()
    assert (runs[0] / "system-blueprint.html").is_file()
    assert (runs[0] / "diagnostic-report.html").is_file()
    assert (runs[0] / "agent-analysis.json").is_file()
