"""Test evidence-grounded agentic reporting and the passive probe boundary."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import patch

from screwdriver.agentic import (
    ProbeRequest,
    ProbeResult,
    _agent_schema,
    _deterministic_issues,
    _evidence_view,
    _merge_agent_issues,
    _normalized_guidance_steps,
    _probe_command,
    _safe_recommended_commands,
    _validated_agent_integration_chains,
    _validated_guidance_command,
    analyze_snapshot_file,
    has_meaningful_diagnostic_issues,
)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": "3.1",
        "created_at": "2026-08-10T05:00:00-07:00",
        "identity": {"hostname": "test-robot"},
        "operating_system": {
            "distribution": "Ubuntu 22.04",
            "kernel": "6.8.0-test",
            "architecture": "aarch64",
            "uptime_seconds": 200,
        },
        "platform": {"product_name": "Jetson Orin Nano"},
        "cpu": {"model": "ARM CPU", "logical_cpus": 6},
        "memory": {
            "total_bytes": 8 * 1024**3,
            "usage_percent": 91.0,
        },
        "storage_devices": [],
        "gpus": [],
        "thermal_sensors": [],
        "power": {"source": "external"},
        "network": {"interfaces": [], "internet_route_available": False},
        "usb_devices": [
            {
                "display_name": "Logitech Brio 100",
                "usb_id": "046d:094c",
                "drivers": ["uvcvideo"],
            }
        ],
        "serial_devices": [],
        "software_stack_inventory": [
            {
                "category": "robotics software stack",
                "name": "Navigation2",
                "status": "ok",
                "details": {
                    "stack_category": "navigation and localization",
                    "installed": True,
                    "configured": True,
                    "running": True,
                    "integrated": None,
                    "capability": "autonomous navigation",
                    "state": "RUNNING",
                    "detected_packages": "nav2_bringup, nav2_controller",
                },
            }
        ],
        "sensor_inventory": [],
        "actuator_inventory": [],
        "ros_device_inventory": [
            {
                "category": "ROS device",
                "name": "camera — /camera_node",
                "status": "ok",
                "details": {
                    "kind": "camera",
                    "state": "IN_USE_BY_ROS",
                    "ros_node": "/camera_node",
                    "topics": "/camera/image_raw",
                    "physical_component": "Logitech Brio 100",
                    "physical_channel": "/dev/video0",
                    "driver": "uvcvideo",
                    "confidence": "VERIFIED",
                },
            }
        ],
        "ros_runtime_inventory": [
            {
                "category": "ROS runtime",
                "name": "ROS 2 graph",
                "status": "ok",
                "details": {
                    "state": "RUNNING",
                    "nodes": 1,
                    "topics": 2,
                    "services": 0,
                    "actions": 0,
                    "domain_id": "0",
                    "middleware": "rmw_fastrtps_cpp",
                },
            },
            {
                "category": "ROS node",
                "name": "/camera_node",
                "status": "ok",
                "details": {"state": "RUNNING"},
            },
            {
                "category": "ROS topic",
                "name": "/camera/image_raw",
                "status": "ok",
                "details": {"type": "sensor_msgs/msg/Image"},
            },
        ],
        "findings": [
            {
                "code": "MEMORY_HIGH_USAGE",
                "severity": "warning",
                "summary": "Physical memory usage is above 90%.",
                "evidence": "Measured usage: 91.0%",
                "recommendation": "Identify the process consuming memory; verify usage again.",
            }
        ],
    }


def test_deterministic_analysis_writes_only_the_two_agentic_report_types(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    with patch("screwdriver.agentic.time.monotonic", side_effect=[100.0, 100.0]):
        result = analyze_snapshot_file(
            snapshot_path,
            output,
            provider="none",
            report_mode="both",
            scan_id="scan-test-001",
            collection_duration_seconds=0.42,
        )

    blueprint = result.paths.blueprint.read_text(encoding="utf-8")
    diagnostics = result.paths.diagnostics.read_text(encoding="utf-8")

    assert {path.name for path in output.iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }

    for report in (blueprint, diagnostics):
        for label in (
            "Scan ID",
            "Generated",
            "Target",
            "Report Mode",
            "Screwdriver",
            "Probe Safety",
            "Provider",
            "Model",
            "Effort",
            "Scan Duration",
            "Agentic Status",
        ):
            assert label in report
        assert "scan-test-001" in report
        assert "test-robot" in report
        assert "1.3.0" in report
        assert "PASSIVE" in report
        assert ">AGENTIC<" in report
        assert "420 ms" in report

    assert "AGENTIC SYSTEM BLUEPRINT REPORT" in blueprint
    blueprint_sections = (
        "1. WHOLE SYSTEM SUMMARY",
        "2. CORE SYSTEM SPECS",
        "3. HARDWARE COMPONENTS STATUS",
        "4. SOFTWARE &amp; RUNTIME STATUS",
        "5. VERIFIED INTEGRATION CHAINS",
    )
    assert [blueprint.index(section) for section in blueprint_sections] == sorted(
        blueprint.index(section) for section in blueprint_sections
    )
    assert "Specification</th><th>Details</th><th>Specification</th><th>Details" in blueprint
    assert "8.0 GiB total · 91.0% used" in blueprint
    hardware_section = blueprint[
        blueprint.index("3. HARDWARE COMPONENTS STATUS") : blueprint.index(
            "4. SOFTWARE &amp; RUNTIME STATUS"
        )
    ]
    assert "Hardware Component</th><th>Type</th><th>Connected Via</th>" in hardware_section
    assert "Driver Bound</th><th>System Role" in hardware_section
    assert "Integration Status" not in hardware_section
    assert "uvcvideo" in hardware_section
    assert ">usb<" not in hardware_section
    assert "Software / Stack</th><th>Type</th><th>Current State</th><th>System Role" in blueprint
    assert "Physical Component</th><th>→ Interface / Driver</th><th>→ OS Interface" in blueprint
    assert "→ Runtime Owner</th><th>→ Endpoint / Consumer</th><th>→ Integration Status" in blueprint
    assert "Logitech Brio 100" in blueprint
    assert "/camera_node" in blueprint
    assert "/camera/image_raw" in blueprint
    assert "NOT_INSTALLED" not in blueprint

    assert "AGENTIC SYSTEM DIAGNOSTIC REPORT" in diagnostics
    diagnostic_sections = (
        "1. DIAGNOSTIC SUMMARY",
        "2. PRIORITIZED FINDINGS",
        "3. ROOT-CAUSE ANALYSIS",
    )
    assert [diagnostics.index(section) for section in diagnostic_sections] == sorted(
        diagnostics.index(section) for section in diagnostic_sections
    )
    assert "VERIFICATION SUMMARY" not in diagnostics
    assert "UNRESOLVED EVIDENCE" not in diagnostics
    rca_headings = (
        "Observed Evidence",
        "Impact",
        "Root Cause",
        "Fix / Investigation Steps",
        "Verification",
    )
    for heading in rca_headings:
        assert heading in diagnostics
    assert [diagnostics.index(heading) for heading in rca_headings] == sorted(
        diagnostics.index(heading) for heading in rca_headings
    )
    assert "D-001" in diagnostics
    assert "Physical memory usage is above 90%." in diagnostics
    assert "Check the robot&#x27;s current memory pressure." in diagnostics
    assert "free -h" in diagnostics
    assert "ps -eo pid,comm,%cpu,%mem --sort=-%mem" in diagnostics
    assert "screwdriver inspect --find-issues --agentic" not in diagnostics
    assert "Root-Cause Chain" not in diagnostics
    assert "Expected Outcome" not in diagnostics
    assert (
        "Most likely:" in diagnostics
        or "Not proven yet." in diagnostics
        or "Root Cause" in diagnostics
    )
    assert "sudo " not in diagnostics
    assert has_meaningful_diagnostic_issues(result.issues)


def test_diagnostic_separates_incomplete_hardware_integration_paths(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot["findings"] = []
    snapshot["ros_device_inventory"] = []
    snapshot["usb_devices"] = [
        {
            "display_name": "Logitech Brio 100",
            "usb_id": "046d:094c",
            "drivers": ["uvcvideo"],
            "device_nodes": [{"path": "/dev/video0"}],
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")

    assert "4. INCOMPLETE INTEGRATION PATHS" in diagnostic
    assert "Component</th><th>Proven Up To</th><th>Missing Link</th>" in diagnostic
    assert "Why It Matters</th><th>How To Verify" in diagnostic
    assert "Logitech Brio 100" in diagnostic
    assert "Runtime owner + Endpoint / consumer" in diagnostic
    assert "lsof -- /dev/video0" in diagnostic
    assert "UNRESOLVED EVIDENCE" not in diagnostic
    assert "No issues found right now." in diagnostic


def test_probe_catalog_builds_arguments_without_a_shell() -> None:
    assert _probe_command(
        ProbeRequest("ros_topic_info", "/scan", "Inspect publisher metadata")
    ) == ("ros2", "topic", "info", "/scan", "--verbose")
    assert _probe_command(
        ProbeRequest("device_metadata", "/dev/ttyUSB0", "Inspect udev metadata")
    ) == ("udevadm", "info", "--query=property", "--name", "/dev/ttyUSB0")


def test_probe_catalog_rejects_injection_and_unknown_actions() -> None:
    assert _probe_command(ProbeRequest("ros_topic_info", "/scan; reboot", "bad")) is None
    assert _probe_command(ProbeRequest("device_metadata", "/dev/../etc/passwd", "bad")) is None
    assert _probe_command(ProbeRequest("repair_permissions", "/dev/ttyUSB0", "bad")) is None


def test_agent_recommended_state_changes_are_removed() -> None:
    commands = _safe_recommended_commands(
        [
            "ros2 node list",
            "sudo chmod 666 /dev/ttyUSB0",
            "systemctl restart robot.service",
            "ros2 topic pub /cmd_vel geometry_msgs/msg/Twist '{}'",
            "ros_param_list on /camera_node",
            "recent_kernel_logs for usb",
            "port_owner probe on /dev/ttyUSB0",
        ]
    )

    assert commands == ["ros2 node list"]


def test_provider_evidence_is_redacted_deduplicated_and_discloses_truncation() -> None:
    snapshot = _snapshot()
    duplicate = {
        "category": "robotics software stack",
        "name": "Navigation2",
        "details": {"serial_number": "private-serial", "note": "x" * 1300},
    }
    snapshot["software_stack_inventory"] = [duplicate, duplicate.copy()]
    snapshot["findings"].append(
        {
            "code": "SERIAL_NOTE",
            "severity": "info",
            "summary": "Device /dev/serial/by-id/private-unit at aa:bb:cc:dd:ee:ff",
        }
    )

    evidence = _evidence_view(snapshot)
    stacks = evidence["software_stack_inventory"]
    metadata = evidence["evidence_package_metadata"]

    assert len(stacks) == 1
    assert stacks[0]["details"]["serial_number"] == "[redacted]"
    assert len(stacks[0]["details"]["note"]) == 1200
    assert "[redacted]" in str(evidence["findings"])
    assert "[redacted-mac]" in str(evidence["findings"])
    omissions = metadata["omitted_or_truncated_paths"]
    assert any("duplicate records removed" in item for item in omissions)
    assert any("string truncated" in item for item in omissions)


def test_probe_result_can_be_cited_as_diagnostic_evidence() -> None:
    snapshot = _snapshot()
    probe = ProbeResult(
        probe="network_link",
        target="can0",
        command=("ip", "-details", "link", "show", "can0"),
        state="completed",
        stdout="can0: state DOWN",
        return_code=0,
    )
    accepted = _merge_agent_issues(
        snapshot,
        _deterministic_issues(snapshot),
        [
            {
                "code": "CAN_RUNTIME_STATE",
                "title": "CAN runtime state requires attention",
                "severity": "MEDIUM",
                "classification": "NEEDS_CONFIRMATION",
                "confidence": 90,
                "observation_confidence": 95,
                "diagnosis_confidence": 70,
                "expected_state": "The required CAN interface matches the robot configuration.",
                "operational_impact": "CAN communication may be unavailable.",
                "evidence_references": ["probe_results[0].stdout"],
                "evidence_level": "VERIFIED",
                "observed": ["can0 is down"],
                "probable_causes": [
                    "The interface state does not match the expected runtime state."
                ],
                "primary_approach": [],
                "alternative_approaches": [],
                "diagnostic_commands": [],
                "success_criteria": ["The interface reaches its expected state."],
                "affected_area": "Robot Communication",
                "diagnosis_status": "PROBABLE",
                "root_cause_chain": [
                    "can0 state DOWN",
                    "The expected configuration is not established.",
                ],
                "likely_root_cause": "The expected interface configuration remains unresolved.",
                "recommended_steps": [],
                "expected_outcome": "The expected interface state is established and verified.",
                "verification_steps": [],
            }
        ],
        probe_results=[probe],
    )

    issue = next(item for item in accepted if item.code == "CAN_RUNTIME_STATE")
    assert issue.evidence_references == ["probe_results[0].stdout"]
    assert "can0: state DOWN" in issue.observed


def test_new_model_issue_requires_a_real_snapshot_evidence_reference() -> None:
    snapshot = _snapshot()
    accepted = _merge_agent_issues(
        snapshot,
        _deterministic_issues(snapshot),
        [
            {
                "code": "INVENTED_WIFI_FAILURE",
                "title": "Wi-Fi is broken",
                "severity": "HIGH",
                "classification": "CONFIRMED_FAILURE",
                "confidence": 99,
                "observation_confidence": 99,
                "diagnosis_confidence": 99,
                "expected_state": "Wi-Fi must be up",
                "operational_impact": "Robot cannot work",
                "evidence_references": ["network.nonexistent"],
                "evidence_level": "VERIFIED",
                "observed": ["Wi-Fi is down"],
                "probable_causes": ["Unknown"],
                "primary_approach": ["Inspect it"],
                "alternative_approaches": [],
                "diagnostic_commands": [],
                "success_criteria": ["Wi-Fi is up"],
            }
        ],
    )

    assert all(issue.code != "INVENTED_WIFI_FAILURE" for issue in accepted)


def test_conditional_unused_serial_access_is_not_an_actionable_failure(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["serial_devices"] = [
        {"display_name": "CP2102", "port": "/dev/ttyUSB0", "stable_id_path": None}
    ]
    snapshot["findings"].append(
        {
            "code": "SERIAL_ACCESS_INCOMPLETE",
            "severity": "warning",
            "summary": "Current user lacks read-write access to /dev/ttyUSB0.",
            "evidence": "access=denied",
            "recommendation": "Confirm intended use.",
        }
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(snapshot_path, tmp_path / "agentic", provider="none")
    serial_issue = next(
        issue for issue in result.issues if issue.code == "SERIAL_ACCESS_INCOMPLETE"
    )

    assert serial_issue.classification == "NEEDS_CONFIRMATION"
    assert serial_issue.severity == "INFO"
    assert "No operational impact is proven" in serial_issue.operational_impact


def test_agentic_html_humanizes_bytes_uptime_and_container_values(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["operating_system"]["uptime_seconds"] = 1177.9
    snapshot["storage_devices"] = [
        {
            "model": "WD Green 500GB",
            "path": "/dev/nvme0n1",
            "connection": "nvme",
            "media_type": "NVMe SSD",
            "capacity_bytes": 500107862016,
            "partitions": [],
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(snapshot_path, tmp_path / "agentic", provider="none")
    blueprint = result.paths.blueprint.read_text(encoding="utf-8")

    assert "19 min 37 sec" in blueprint
    assert "465.8 GiB" in blueprint
    assert "<td>500107862016</td>" not in blueprint
    assert "[&quot;uvcvideo&quot;]" not in blueprint


def test_agent_integration_chain_requires_cited_evidence_for_every_displayed_value() -> None:
    snapshot = _snapshot()
    snapshot["components"] = [
        {
            "category": "software runtime",
            "name": "camera worker",
            "details": {
                "state": "RUNNING",
                "device": "/dev/video0",
                "endpoint": "/camera/image_raw",
            },
        }
    ]

    accepted = _validated_agent_integration_chains(
        snapshot,
        [
            {
                "physical_component": "Logitech Brio 100",
                "interface_driver": "uvcvideo",
                "os_interface": "/dev/video0",
                "runtime_owner": "camera worker",
                "endpoint_consumer": "/camera/image_raw",
                "evidence_references": ["usb_devices[0]", "components[0]"],
            },
            {
                "physical_component": "Logitech Brio 100",
                "interface_driver": "uvcvideo",
                "os_interface": "/dev/video0",
                "runtime_owner": "invented-camera-process",
                "endpoint_consumer": "/camera/image_raw",
                "evidence_references": ["usb_devices[0]", "components[0]"],
            },
        ],
    )

    assert accepted == [
        {
            "physical_component": "Logitech Brio 100",
            "interface_driver": "uvcvideo",
            "os_interface": "/dev/video0",
            "runtime_owner": "camera worker",
            "endpoint_consumer": "/camera/image_raw",
            "integration_status": "INFERRED",
        }
    ]


def test_blueprint_curates_hardware_noise_without_deleting_evidence(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot["serial_devices"] = [
        {
            "display_name": "CP2102N USB-UART",
            "port": "/dev/ttyUSB0",
            "transport": "usb-serial",
            "driver": "cp210x",
            "stable_id_path": "/dev/serial/by-id/usb-cp2102n-test",
            "device_node": {
                "path": "/dev/ttyUSB0",
                "permissions": "crw-rw----",
                "owner": "root",
                "group": "dialout",
                "access": "denied",
            },
        },
        {
            "display_name": "ttyS0",
            "port": "/dev/ttyS0",
            "transport": "onboard-uart",
            "driver": "serial8250",
            "device_node": {"path": "/dev/ttyS0"},
        },
        {
            "display_name": "ttyTHS1",
            "port": "/dev/ttyTHS1",
            "transport": "onboard-uart",
            "driver": "serial-tegra",
            "device_node": {"path": "/dev/ttyTHS1"},
        },
    ]
    snapshot["usb_devices"].append(
        {
            "display_name": "Linux Foundation 3.0 root hub",
            "product_name": "xHCI Host Controller",
            "device_class_name": "Hub",
            "drivers": ["hub"],
        }
    )
    snapshot["usb_devices"].append(
        {
            "display_name": "Realtek Bluetooth Radio",
            "device_class_name": "Wireless Controller",
            "drivers": ["rtk_btusb"],
            "device_nodes": [],
        }
    )
    snapshot["usb_devices"].append(
        {
            "display_name": "Mystery USB Peripheral",
            "device_class_name": "Peripheral",
            "drivers": [],
            "device_nodes": [],
        }
    )
    snapshot["hardware_bus_inventory"] = [
        {
            "category": "hardware interface",
            "name": "i2c-1",
            "details": {
                "kind": "I2C",
                "bus": "I2C",
                "channel": "/dev/i2c-1",
                "driver": "tegra-i2c",
                "state": "UP",
            },
        },
        {
            "category": "hardware interface",
            "name": "can0",
            "details": {
                "kind": "CAN",
                "bus": "CAN",
                "interface": "can0",
                "driver": "mttcan",
                "state": "DOWN",
            },
        },
    ]
    snapshot["sensor_inventory"] = [
        {
            "category": "sensor",
            "name": "USB microphone array",
            "details": {
                "kind": "microphone",
                "bus": "USB",
                "driver": "snd-usb-audio",
                "channel": "/dev/snd/by-id/usb-microphone-test, /dev/snd/pcmC2D0c",
                "health": "PRESENT_NOT_EXERCISED",
                "confidence": "VERIFIED",
                "source": "Linux USB/ALSA",
            },
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="blueprint",
    )
    blueprint = result.paths.blueprint.read_text(encoding="utf-8")

    assert "CP2102N USB-UART" in blueprint
    assert "/dev/ttyUSB0" in blueprint
    assert "cp210x" in blueprint
    assert "USB microphone array" in blueprint
    assert "snd-usb-audio" in blueprint
    assert "/dev/ttyS0" not in blueprint
    assert "/dev/ttyTHS1" not in blueprint
    assert "Linux Foundation 3.0 root hub" not in blueprint
    assert "xHCI Host Controller" not in blueprint
    assert "i2c-1" not in blueprint
    assert "tegra-i2c" not in blueprint
    assert "can0" in blueprint
    assert "mttcan" in blueprint
    assert "Realtek Bluetooth Radio" in blueprint
    bluetooth_index = blueprint.index("Realtek Bluetooth Radio")
    bluetooth_row = blueprint[bluetooth_index : bluetooth_index + 500]
    assert "Wireless communication" in bluetooth_row
    assert "Motion / actuation" not in bluetooth_row
    assert "Mystery USB Peripheral" in blueprint
    mystery_index = blueprint.index("Mystery USB Peripheral")
    mystery_row = blueprint[mystery_index : mystery_index + 300]
    assert "Driver Bound" in blueprint
    assert "UNKNOWN" not in mystery_row
    can_row = blueprint[blueprint.index("can0") : blueprint.index("can0") + 300]
    assert "mttcan" in can_row
    hardware_section = blueprint[
        blueprint.index("3. HARDWARE COMPONENTS STATUS") : blueprint.index(
            "4. SOFTWARE &amp; RUNTIME STATUS"
        )
    ]
    assert "Integration Status" not in hardware_section
    assert "INACTIVE" not in hardware_section
    assert "crw-rw----" not in blueprint
    assert "PRESENT_NOT_EXERCISED" not in blueprint
    assert not result.paths.diagnostics.exists()

    raw_snapshot = snapshot_path.read_text(encoding="utf-8")
    assert "/dev/ttyS0" in raw_snapshot
    assert "/dev/ttyTHS1" in raw_snapshot
    assert "Linux Foundation 3.0 root hub" in raw_snapshot


def test_report_mode_generates_only_the_requested_human_report(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    blueprint = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "blueprint",
        provider="none",
        report_mode="blueprint",
    )
    diagnostic = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "diagnostic",
        provider="none",
        report_mode="diagnostic",
    )

    assert blueprint.paths.blueprint.is_file()
    assert not blueprint.paths.diagnostics.exists()
    assert diagnostic.paths.diagnostics.is_file()
    assert not diagnostic.paths.blueprint.exists()
    assert {path.name for path in (tmp_path / "blueprint").iterdir()} == {"system-blueprint.html"}
    assert {path.name for path in (tmp_path / "diagnostic").iterdir()} == {"diagnostic-report.html"}

    combined_dir = tmp_path / "conditional"
    first = analyze_snapshot_file(
        snapshot_path,
        combined_dir,
        provider="none",
        report_mode="blueprint",
    )
    second = analyze_snapshot_file(
        snapshot_path,
        combined_dir,
        provider="none",
        report_mode="diagnostic",
        preserve_existing_reports=True,
    )
    assert first.paths.blueprint.is_file()
    assert second.paths.diagnostics.is_file()
    assert {path.name for path in combined_dir.iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }


def test_ros_unsourced_shell_remains_visible_without_claiming_robot_runtime_failure(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot["ros_runtime_inventory"] = [
        {
            "category": "ROS runtime",
            "name": "ROS 2 graph",
            "status": "warning",
            "details": {
                "state": "UNAVAILABLE",
                "ros_distro": "humble",
                "environment_recovered": False,
            },
        }
    ]
    snapshot["findings"] = [
        {
            "code": "ROS_ENVIRONMENT_NOT_SOURCED",
            "severity": "warning",
            "summary": "ROS 2 Humble is installed but unavailable in the collection shell.",
            "evidence": "Installed distributions: humble",
            "recommendation": "Source /opt/ros/humble/setup.bash and repeat ROS inspection.",
        }
    ]

    issues = _deterministic_issues(snapshot)
    ros_issue = next(issue for issue in issues if issue.code == "ROS_ENVIRONMENT_NOT_SOURCED")
    assert ros_issue.severity == "MEDIUM"
    assert ros_issue.classification == "CONFIGURATION_WARNING"
    assert ros_issue.diagnosis_status in {"PARTIAL", "PROBABLE", "CONFIRMED"}
    assert ros_issue.affected_area == "ROS 2 Inspection Environment"
    assert "does not prove" in ros_issue.operational_impact
    assert has_meaningful_diagnostic_issues(issues)

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")
    assert "ROS 2 Humble is installed but unavailable in the collection shell." in diagnostic
    assert "ROS 2 Inspection Environment" in diagnostic
    assert "No issues found right now" not in diagnostic
    assert "deployed robot ROS runtime is down" in diagnostic


def test_generic_ros_runtime_unavailability_stays_unresolved_context_limit() -> None:
    snapshot = _snapshot()
    snapshot["ros_runtime_inventory"] = [
        {
            "category": "ROS runtime",
            "name": "ROS 2 graph",
            "status": "warning",
            "details": {"state": "UNAVAILABLE", "ros_distro": "humble"},
        }
    ]
    snapshot["findings"] = []

    issues = _deterministic_issues(snapshot)
    runtime_issue = next(issue for issue in issues if issue.code == "ROS_RUNTIME_UNAVAILABLE")
    assert runtime_issue.severity == "INFO"
    assert runtime_issue.classification == "NEEDS_CONFIRMATION"
    assert runtime_issue.diagnosis_status == "UNRESOLVED"
    assert not has_meaningful_diagnostic_issues(issues)


def test_agent_cannot_suppress_deterministic_ros_unsourced_finding() -> None:
    snapshot = _snapshot()
    snapshot["ros_runtime_inventory"] = [
        {
            "category": "ROS runtime",
            "name": "ROS 2 graph",
            "status": "warning",
            "details": {
                "state": "UNAVAILABLE",
                "ros_distro": "humble",
                "environment_recovered": False,
            },
        }
    ]
    snapshot["findings"] = [
        {
            "code": "ROS_ENVIRONMENT_NOT_SOURCED",
            "severity": "warning",
            "summary": "ROS 2 Humble is installed but unavailable in the collection shell.",
            "evidence": "Installed distributions: humble",
        }
    ]
    baseline = _deterministic_issues(snapshot)

    merged = _merge_agent_issues(
        snapshot,
        baseline,
        [
            {
                "code": "ROS_ENVIRONMENT_NOT_SOURCED",
                "title": "ROS shell context is incomplete",
                "severity": "INFO",
                "confidence": 60,
                "classification": "NEEDS_CONFIRMATION",
                "observation_confidence": 95,
                "diagnosis_confidence": 60,
                "expected_state": "ROS is visible to the inspection shell.",
                "operational_impact": "Inspection visibility is limited.",
                "evidence_references": ["findings[0]"],
                "evidence_level": "VERIFIED",
                "observed": [],
                "probable_causes": [],
                "primary_approach": [],
                "alternative_approaches": [],
                "diagnostic_commands": [],
                "success_criteria": [],
                "affected_area": "ROS 2 Inspection Environment",
                "diagnosis_status": "UNRESOLVED",
                "root_cause_chain": [],
                "likely_root_cause": "",
                "recommended_steps": [],
                "expected_outcome": "ROS is visible to Screwdriver.",
                "verification_steps": [],
            }
        ],
    )

    issue = next(item for item in merged if item.code == "ROS_ENVIRONMENT_NOT_SOURCED")
    assert issue.severity == "MEDIUM"
    assert issue.classification == "CONFIGURATION_WARNING"
    assert has_meaningful_diagnostic_issues(merged)


def test_guidance_keeps_passive_discovery_before_grounded_state_change() -> None:
    snapshot = _snapshot()
    snapshot["hardware_bus_inventory"] = [
        {
            "category": "hardware interface",
            "name": "can0",
            "details": {"kind": "CAN", "interface": "can0", "state": "DOWN"},
        }
    ]
    snapshot["findings"] = [
        {
            "code": "CAN_LINK_DOWN",
            "severity": "warning",
            "summary": "can0 is required by this robot and is down; expected bitrate 500000.",
            "evidence": "can0 state=DOWN bitrate=500000",
        }
    ]

    steps = _normalized_guidance_steps(
        snapshot,
        [
            {
                "instruction": "Bring up the confirmed CAN interface.",
                "command": "sudo ip link set can0 up",
                "look_for": "Command completes without error.",
                "meaning": "The known interface was changed only after evidence established it.",
                "next_step": "Verify the link state.",
            },
            {
                "instruction": "Inspect the current CAN state first.",
                "command": "ip -details link show can0",
                "look_for": "state DOWN",
                "meaning": "This confirms the current passive state.",
                "next_step": "Only then consider the grounded correction.",
            },
        ],
        code="CAN_LINK_DOWN",
        allow_state_changes=True,
    )

    assert [step["command"] for step in steps] == [
        "ip -details link show can0",
        "sudo ip link set can0 up",
    ]


def test_diagnostic_schema_is_diagnostic_only_and_compact() -> None:
    schema = _agent_schema("diagnostic")

    assert schema["required"] == ["issues", "probe_requests"]
    assert set(schema["properties"]) == {"issues", "probe_requests"}
    assert "summary" not in schema["properties"]
    assert "integration_chains" not in schema["properties"]
    issue_properties = schema["properties"]["issues"]["items"]["properties"]
    for unused in (
        "expected_state",
        "root_cause_chain",
        "expected_outcome",
        "alternative_approaches",
        "diagnostic_commands",
        "success_criteria",
    ):
        assert unused not in issue_properties


def test_blueprint_schema_only_requests_visible_blueprint_intelligence() -> None:
    schema = _agent_schema("blueprint")

    assert schema["required"] == ["integration_chains"]
    assert set(schema["properties"]) == {"integration_chains"}
    assert "issues" not in schema["properties"]
    assert "probe_requests" not in schema["properties"]


def test_model_cannot_promote_unconfirmed_diagnosis_to_confirmed() -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "CAN_LINK_DOWN",
            "severity": "warning",
            "summary": "CAN interface can0 is down.",
            "evidence": "can0 state DOWN",
        }
    ]
    snapshot["hardware_bus_inventory"] = [
        {
            "category": "hardware interface",
            "name": "can0",
            "details": {"kind": "CAN", "interface": "can0", "state": "DOWN"},
        }
    ]
    baseline = _deterministic_issues(snapshot)
    accepted = _merge_agent_issues(
        snapshot,
        baseline,
        [
            {
                "code": "CAN_LINK_DOWN",
                "title": "CAN link is down",
                "severity": "HIGH",
                "classification": "CONFIRMED_FAILURE",
                "confidence": 99,
                "observation_confidence": 99,
                "diagnosis_confidence": 75,
                "expected_state": "The required CAN link is operational.",
                "operational_impact": "CAN communication is not currently established.",
                "evidence_references": ["findings[0]", "hardware_bus_inventory[0]"],
                "evidence_level": "VERIFIED",
                "observed": ["can0 is down"],
                "probable_causes": ["The interface may not have been brought up."],
                "primary_approach": [],
                "alternative_approaches": [],
                "diagnostic_commands": [],
                "success_criteria": ["can0 is operational"],
                "affected_area": "Robot Communication",
                "diagnosis_status": "CONFIRMED",
                "root_cause_chain": [
                    "can0 state DOWN",
                    "The exact reason the interface is down is not established.",
                ],
                "likely_root_cause": "The interface may not have been brought up.",
                "recommended_steps": [],
                "expected_outcome": "The required CAN link becomes operational.",
                "verification_steps": [],
            }
        ],
    )

    issue = next(item for item in accepted if item.code == "CAN_LINK_DOWN")
    assert issue.diagnosis_status != "CONFIRMED"
    assert issue.diagnosis_status in {"PROBABLE", "PARTIAL"}


def test_diagnostic_observed_evidence_stays_deterministic() -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "MEMORY_PRESSURE",
            "severity": "warning",
            "summary": "Memory usage is elevated.",
            "evidence": "Memory usage 91%",
        }
    ]
    baseline = _deterministic_issues(snapshot)
    accepted = _merge_agent_issues(
        snapshot,
        baseline,
        [
            {
                "code": "MEMORY_PRESSURE",
                "title": "Memory pressure",
                "severity": "MEDIUM",
                "classification": "DEGRADED",
                "confidence": 90,
                "observation_confidence": 90,
                "diagnosis_confidence": 65,
                "expected_state": "Memory remains below the warning threshold.",
                "operational_impact": "Headroom is reduced.",
                "evidence_references": ["findings[0]"],
                "evidence_level": "VERIFIED",
                "observed": ["A nonexistent process robot_magic is leaking memory."],
                "probable_causes": ["A workload may be consuming memory."],
                "primary_approach": [],
                "alternative_approaches": [],
                "diagnostic_commands": [],
                "success_criteria": ["Memory pressure clears."],
                "affected_area": "Memory",
                "diagnosis_status": "PROBABLE",
                "root_cause_chain": ["Memory usage 91%", "Responsible process is unresolved."],
                "likely_root_cause": "A workload may be consuming memory.",
                "recommended_steps": [],
                "expected_outcome": "Memory pressure clears.",
                "verification_steps": [],
            }
        ],
    )

    issue = next(item for item in accepted if item.code == "MEMORY_PRESSURE")
    assert issue.observed == ["Memory usage 91%"]
    assert all("robot_magic" not in item for item in issue.observed)


def test_verification_guidance_rejects_state_changes() -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "CAN_LINK_DOWN",
            "severity": "warning",
            "summary": "CAN interface can0 is down.",
            "evidence": "can0 state DOWN",
        }
    ]
    snapshot["hardware_bus_inventory"] = [
        {
            "category": "hardware interface",
            "name": "can0",
            "details": {"kind": "CAN", "interface": "can0", "state": "DOWN"},
        }
    ]

    steps = _normalized_guidance_steps(
        snapshot,
        [
            {
                "instruction": "Bring the link up.",
                "command": "sudo ip link set can0 up",
                "look_for": "Command succeeds.",
                "meaning": "Link state changed.",
                "next_step": "Check the link.",
            },
            {
                "instruction": "Inspect the resulting link state.",
                "command": "ip -details link show can0",
                "look_for": "state UP",
                "meaning": "This passively verifies the resulting state.",
                "next_step": "Re-run Screwdriver if the expected state is present.",
            },
        ],
        code="CAN_LINK_DOWN",
        allow_state_changes=False,
    )

    assert [step["command"] for step in steps] == ["ip -details link show can0"]


def test_state_changing_guidance_requires_exact_problem_evidence() -> None:
    snapshot = _snapshot()
    snapshot["hardware_bus_inventory"] = [
        {
            "category": "hardware interface",
            "name": "can0",
            "details": {
                "kind": "CAN",
                "bus": "CAN",
                "interface": "can0",
                "state": "DOWN",
            },
        }
    ]
    snapshot["findings"].append(
        {
            "code": "CAN_INTERFACE_DOWN",
            "severity": "warning",
            "summary": "CAN interface can0 is down.",
            "evidence": "can0 state DOWN; expected bitrate 500000",
        }
    )

    assert _validated_guidance_command(snapshot, "timeout 5 candump can0")
    assert not _validated_guidance_command(snapshot, "candump can0")
    assert _validated_guidance_command(snapshot, "sudo ip link set can0 up")
    assert _validated_guidance_command(snapshot, "sudo ip link set can0 type can bitrate 500000")
    assert not _validated_guidance_command(
        snapshot, "sudo ip link set can0 type can bitrate 250000"
    )
    assert not _validated_guidance_command(snapshot, "sudo ip link set can9 up")
    assert not _validated_guidance_command(snapshot, "sudo systemctl restart robot.service")


def test_serial_diagnostic_never_invents_a_default_device_path() -> None:
    snapshot = _snapshot()
    snapshot["serial_devices"] = []
    snapshot["findings"] = [
        {
            "code": "SERIAL_ACCESS_INCOMPLETE",
            "severity": "warning",
            "summary": "Serial access could not be verified.",
            "evidence": "No concrete serial device path was recorded.",
            "recommendation": "Identify the intended serial interface before changing permissions.",
        }
    ]
    issues = _deterministic_issues(snapshot)
    issue = next(item for item in issues if item.code == "SERIAL_ACCESS_INCOMPLETE")

    assert issue.diagnostic_commands == []
    assert "/dev/ttyUSB0" not in json.dumps(issue.to_dict())


class _FakeAnthropicResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def __enter__(self) -> _FakeAnthropicResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")


def test_anthropic_provider_uses_sonnet_five_structured_output_without_leaking_key(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "",
        "architecture_observations": [],
        "unknowns": [],
        "integration_chains": [],
        "issues": [],
        "probe_requests": [],
    }
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: int) -> _FakeAnthropicResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeAnthropicResponse(
            {
                "content": [{"type": "text", "text": json.dumps(provider_result)}],
                "stop_reason": "end_turn",
            }
        )

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret-key"}),
        patch("screwdriver.agent_providers.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        result = analyze_snapshot_file(snapshot_path, output, provider="anthropic")

    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert captured["timeout"] == 120
    assert headers["x-api-key"] == "test-secret-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-sonnet-5"
    assert payload["output_config"]["effort"] == "medium"
    assert payload["output_config"]["format"]["type"] == "json_schema"
    schema = payload["output_config"]["format"]["schema"]
    assert "integration_chains" in schema["required"]
    step_schema = schema["properties"]["issues"]["items"]["properties"]["recommended_steps"][
        "items"
    ]
    assert "next_step" in step_schema["required"]
    assert "temperature" not in payload
    assert "robotics" in result.summary.casefold()
    assert "Anthropic model claude-sonnet-5" in result.provider_status
    for path in (result.paths.blueprint, result.paths.diagnostics):
        assert "test-secret-key" not in path.read_text(encoding="utf-8")


def test_anthropic_retries_transient_failure_and_records_request_metadata(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "",
        "architecture_observations": [],
        "unknowns": [],
        "integration_chains": [],
        "issues": [],
        "probe_requests": [],
    }
    attempts = 0

    def fake_urlopen(request: Any, *, timeout: int) -> _FakeAnthropicResponse:
        nonlocal attempts
        assert timeout == 120
        attempts += 1
        if attempts == 1:
            error_body = json.dumps({"error": {"message": "temporarily unavailable"}}).encode(
                "utf-8"
            )
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                {},
                io.BytesIO(error_body),
            )
        return _FakeAnthropicResponse(
            {
                "id": "msg_test_123",
                "content": [{"type": "text", "text": json.dumps(provider_result)}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 321, "output_tokens": 45},
            }
        )

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret-key"}, clear=True),
        patch("screwdriver.agent_providers.urllib.request.urlopen", side_effect=fake_urlopen),
        patch("screwdriver.agent_providers.time.sleep"),
    ):
        result = analyze_snapshot_file(
            snapshot_path,
            tmp_path / "analysis",
            provider="anthropic",
        )

    assert attempts == 2
    assert "Anthropic model claude-sonnet-5" in result.provider_status
    assert {path.name for path in (tmp_path / "analysis").iterdir()} == {
        "system-blueprint.html",
        "diagnostic-report.html",
    }


def test_missing_anthropic_key_generates_deterministic_fallback(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        result = analyze_snapshot_file(snapshot_path, tmp_path / "analysis")

    assert result.paths.blueprint.is_file()
    assert result.paths.diagnostics.is_file()
    assert result.provider_status == (
        "Anthropic unavailable; deterministic fallback (ANTHROPIC_API_KEY is not set)"
    )


def test_openai_provider_uses_responses_structured_output_without_leaking_key(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "",
        "architecture_observations": [],
        "unknowns": [],
        "integration_chains": [],
        "issues": [],
        "probe_requests": [],
    }
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: int) -> _FakeAnthropicResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeAnthropicResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(provider_result)}],
                    }
                ],
            }
        )

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test-secret"}, clear=True),
        patch("screwdriver.agent_providers.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        result = analyze_snapshot_file(
            snapshot_path,
            output,
            provider="openai",
            effort="light",
        )

    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert captured["timeout"] == 120
    assert headers["authorization"] == "Bearer openai-test-secret"
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["reasoning"]["effort"] == "low"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["store"] is False
    assert "temperature" not in payload
    assert "robotics" in result.summary.casefold()
    assert "OpenAI model gpt-5.6-terra (effort light)" in result.provider_status
    for path in (result.paths.blueprint, result.paths.diagnostics):
        assert "openai-test-secret" not in path.read_text(encoding="utf-8")


def test_missing_openai_key_generates_deterministic_fallback(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        result = analyze_snapshot_file(
            snapshot_path,
            tmp_path / "analysis",
            provider="openai",
        )

    assert result.provider_status == (
        "OpenAI unavailable; deterministic fallback (OPENAI_API_KEY is not set)"
    )


def test_openai_retries_without_effort_when_compatible_model_rejects_it(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "",
        "architecture_observations": [],
        "unknowns": [],
        "integration_chains": [],
        "issues": [],
        "probe_requests": [],
    }
    payloads: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: int) -> _FakeAnthropicResponse:
        assert timeout == 120
        payloads.append(json.loads(request.data.decode("utf-8")))
        if len(payloads) == 1:
            error_body = json.dumps(
                {
                    "error": {
                        "message": (
                            "Unsupported parameter: 'reasoning' is not supported with this model."
                        )
                    }
                }
            ).encode("utf-8")
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        return _FakeAnthropicResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(provider_result)}],
                    }
                ],
            }
        )

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test-secret"}, clear=True),
        patch("screwdriver.agent_providers.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        result = analyze_snapshot_file(
            snapshot_path,
            tmp_path / "analysis",
            provider="openai",
            model="gpt-4.1",
            effort="high",
        )

    assert payloads[0]["reasoning"] == {"effort": "high"}
    assert "reasoning" not in payloads[1]
    assert result.provider_status == (
        "OpenAI model gpt-4.1 (effort model default; requested high unsupported)"
    )


def test_anthropic_retries_without_effort_when_compatible_model_rejects_it(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "",
        "architecture_observations": [],
        "unknowns": [],
        "integration_chains": [],
        "issues": [],
        "probe_requests": [],
    }
    payloads: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: int) -> _FakeAnthropicResponse:
        assert timeout == 120
        payloads.append(json.loads(request.data.decode("utf-8")))
        if len(payloads) == 1:
            error_body = json.dumps(
                {"error": {"message": "output_config.effort: Extra inputs are not permitted"}}
            ).encode("utf-8")
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        return _FakeAnthropicResponse(
            {
                "content": [{"type": "text", "text": json.dumps(provider_result)}],
                "stop_reason": "end_turn",
            }
        )

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret-key"}, clear=True),
        patch("screwdriver.agent_providers.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        result = analyze_snapshot_file(
            snapshot_path,
            tmp_path / "analysis",
            provider="anthropic",
            model="claude-haiku-4-5",
            effort="light",
        )

    assert payloads[0]["output_config"]["effort"] == "low"
    assert "effort" not in payloads[1]["output_config"]
    assert payloads[1]["output_config"]["format"]["type"] == "json_schema"
    assert result.provider_status == (
        "Anthropic model claude-haiku-4-5 (effort model default; requested light unsupported)"
    )


def test_deterministic_analysis_progress_is_sequential(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    events: list[tuple[int, str, bool]] = []

    analyze_snapshot_file(
        snapshot_path,
        output,
        provider="none",
        progress=lambda number, label, waiting=False: events.append((number, label, waiting)),
    )

    assert [number for number, _label, _waiting in events] == [1, 2, 3, 4, 5, 6]
    assert events[2][1] == "Evaluating deterministic diagnostic rules…"
    assert all(waiting is False for _number, _label, waiting in events)


def test_blueprint_missing_software_note_is_based_on_running_state(tmp_path: Path) -> None:
    snapshot = _snapshot()
    stack = snapshot["software_stack_inventory"][0]  # type: ignore[index]
    stack["details"]["running"] = False  # type: ignore[index]
    stack["details"]["state"] = "INSTALLED"  # type: ignore[index]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="blueprint",
    )
    blueprint = result.paths.blueprint.read_text(encoding="utf-8")

    assert "Navigation2" in blueprint
    assert "INSTALLED" in blueprint
    assert "No active navigation, SLAM, manipulation, or simulation stack" in blueprint


def test_deterministic_warning_taxonomy_does_not_hide_new_issue_families() -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "CAMERA_CONFIGURATION_INVALID",
            "severity": "warning",
            "summary": "Camera configuration is invalid.",
            "evidence": "camera profile references an unsupported mode",
        },
        {
            "code": "NETWORK_MTU_MISMATCH",
            "severity": "warning",
            "summary": "Network MTU does not match the expected configuration.",
            "evidence": "enP8p1s0 mtu=1500 expected=9000",
        },
        {
            "code": "SERVICE_DISABLED",
            "severity": "warning",
            "summary": "Required runtime service is disabled.",
            "evidence": "robot-runtime.service disabled",
        },
        {
            "code": "FILESYSTEM_NEAR_FULL",
            "severity": "warning",
            "summary": "Runtime filesystem is near capacity.",
            "evidence": "/var is 94% used",
        },
        {
            "code": "ROBOT_RUNTIME_ANOMALY",
            "severity": "warning",
            "summary": "Robot runtime reported an anomalous state.",
            "evidence": "runtime state=degraded",
        },
        {
            "code": "DEVICE_DRIVER_FAILED",
            "severity": "error",
            "summary": "A required device driver failed.",
            "evidence": "driver bind failed",
        },
    ]

    issues = {issue.code: issue for issue in _deterministic_issues(snapshot)}

    for code in {
        "CAMERA_CONFIGURATION_INVALID",
        "NETWORK_MTU_MISMATCH",
        "SERVICE_DISABLED",
    }:
        assert issues[code].severity == "MEDIUM"
        assert issues[code].classification == "CONFIGURATION_WARNING"

    for code in {"FILESYSTEM_NEAR_FULL", "ROBOT_RUNTIME_ANOMALY"}:
        assert issues[code].severity == "MEDIUM"
        assert issues[code].classification == "DEGRADED"

    assert issues["DEVICE_DRIVER_FAILED"].severity == "HIGH"
    assert issues["DEVICE_DRIVER_FAILED"].classification == "CONFIRMED_FAILURE"
    assert has_meaningful_diagnostic_issues(list(issues.values()))


def test_model_cannot_downgrade_or_hide_deterministic_warning() -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "CAMERA_CONFIGURATION_INVALID",
            "severity": "warning",
            "summary": "Camera configuration is invalid.",
            "evidence": "camera profile references an unsupported mode",
        }
    ]
    baseline = _deterministic_issues(snapshot)
    assert baseline[0].severity == "MEDIUM"
    assert baseline[0].classification == "CONFIGURATION_WARNING"
    assert baseline[0].diagnosis_status == "PARTIAL"

    merged = _merge_agent_issues(
        snapshot,
        baseline,
        [
            {
                "code": "CAMERA_CONFIGURATION_INVALID",
                "title": "Camera configuration is invalid",
                "severity": "INFO",
                "classification": "ADVISORY",
                "diagnosis_status": "UNRESOLVED",
                "evidence_references": ["findings[0]"],
                "evidence_level": "VERIFIED",
                "observation_confidence": 95,
                "diagnosis_confidence": 20,
            }
        ],
    )

    issue = next(item for item in merged if item.code == "CAMERA_CONFIGURATION_INVALID")
    assert issue.severity == "MEDIUM"
    assert issue.classification == "CONFIGURATION_WARNING"
    assert issue.diagnosis_status == "PARTIAL"
    assert has_meaningful_diagnostic_issues(merged)


def test_definitive_serial_permission_failure_is_not_hidden_as_optional_noise() -> None:
    snapshot = _snapshot()
    snapshot["serial_devices"] = [
        {
            "display_name": "CP2102N USB-UART",
            "port": "/dev/ttyUSB0",
            "stable_id_path": "/dev/serial/by-id/usb-cp2102n-test",
        }
    ]
    snapshot["findings"] = [
        {
            "code": "SERIAL_PERMISSION_DENIED",
            "severity": "error",
            "summary": "Current user cannot access /dev/ttyUSB0.",
            "evidence": "/dev/ttyUSB0 access=denied",
        }
    ]

    issue = _deterministic_issues(snapshot)[0]

    assert issue.severity == "HIGH"
    assert issue.classification == "CONFIRMED_FAILURE"
    assert issue.diagnosis_status == "CONFIRMED"


def test_generic_warning_is_rendered_in_diagnostic_instead_of_disappearing(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "ROBOT_RUNTIME_ANOMALY",
            "severity": "warning",
            "summary": "Robot runtime reported an anomalous state.",
            "evidence": "runtime state=degraded",
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")

    assert "Robot runtime reported an anomalous state." in diagnostic
    assert "No issues found right now." not in diagnostic


def test_blueprint_summary_explains_power_current_system_and_headroom(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["memory"]["usage_percent"] = 44.0
    snapshot["findings"] = []
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    blueprint = result.paths.blueprint.read_text(encoding="utf-8")
    summary = blueprint[
        blueprint.index("1. WHOLE SYSTEM SUMMARY") : blueprint.index("2. CORE SYSTEM SPECS")
    ].casefold()

    assert "robotics computer" in summary
    assert "currently running as" in summary or "consistent with" in summary
    assert "headroom" in summary or "additional" in summary
    assert "limit" in summary or "bottleneck" in summary
    assert "/dev/" not in summary


def test_thermal_normalization_anomaly_is_not_promoted_to_robot_fault(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["thermal_sensors"] = [
        {
            "name": "tj-thermal",
            "temperature_celsius": 53.25,
            "high_celsius": 1.0449999999999999e-07,
            "critical_celsius": 1.0449999999999999e-07,
        }
    ]
    snapshot["findings"] = [
        {
            "code": "THERMAL_WARNING",
            "severity": "warning",
            "summary": "tj-thermal threshold values are below the reported current temperature",
            "evidence": (
                "tj-thermal current=53.25 C high=1.0449999999999999e-07 C "
                "critical=1.0449999999999999e-07 C"
            ),
            "recommendation": "Inspect raw thermal-zone values.",
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")

    assert all(issue.code != "THERMAL_WARNING" for issue in result.issues)
    assert "tj-thermal threshold values are below" not in diagnostic
    assert "No issues found right now." in diagnostic


def test_diagnostic_rca_is_concise_and_does_not_use_rescan_as_primary_guidance(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")

    assert "Fix / Investigation Steps" in diagnostic
    assert "Root-Cause Chain" not in diagnostic
    assert "Expected Outcome" not in diagnostic
    assert "VERIFICATION SUMMARY" not in diagnostic
    assert "screwdriver inspect --find-issues --agentic" not in diagnostic
    assert "No command is issued until" not in diagnostic


def test_prioritized_findings_lists_every_meaningful_real_problem(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["findings"] = [
        {
            "code": "ROS_ENVIRONMENT_NOT_SOURCED",
            "severity": "warning",
            "summary": "ROS 2 is installed but the inspection shell is not sourced.",
            "evidence": "ROS_DISTRO is empty while ROS Humble is installed.",
        },
        {
            "code": "NETWORK_MTU_MISMATCH",
            "severity": "warning",
            "summary": "Network MTU does not match the expected configuration.",
            "evidence": "enP8p1s0 mtu=1500 expected=9000",
        },
        {
            "code": "SERVICE_DISABLED",
            "severity": "warning",
            "summary": "Required runtime service is disabled.",
            "evidence": "robot-runtime.service disabled",
        },
        {
            "code": "FILESYSTEM_NEAR_FULL",
            "severity": "warning",
            "summary": "Runtime filesystem is near capacity.",
            "evidence": "/var is 94% used",
        },
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")
    prioritized = diagnostic[
        diagnostic.index("2. PRIORITIZED FINDINGS") : diagnostic.index("3. ROOT-CAUSE ANALYSIS")
    ]

    for title in (
        "ROS 2 is installed but the inspection shell is not sourced.",
        "Network MTU does not match the expected configuration.",
        "Required runtime service is disabled.",
        "Runtime filesystem is near capacity.",
    ):
        assert title in prioritized
    assert prioritized.count("D-00") >= 4


def test_rca_does_not_duplicate_severity_and_diagnosis_header(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = analyze_snapshot_file(
        snapshot_path,
        tmp_path / "agentic",
        provider="none",
        report_mode="both",
    )
    diagnostic = result.paths.diagnostics.read_text(encoding="utf-8")
    rca = diagnostic[diagnostic.index("D-001") :]

    assert "<strong>Severity:</strong>" in rca
    assert "<strong>Diagnosis:</strong>" in rca
    title_line = rca[
        rca.index('<div class="rca-title">') : rca.index(
            "</div>", rca.index('<div class="rca-title">')
        )
    ]
    assert "<span>" not in title_line
