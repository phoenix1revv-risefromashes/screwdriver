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
    _deterministic_issues,
    _evidence_view,
    _merge_agent_issues,
    _probe_command,
    _safe_recommended_commands,
    analyze_snapshot_file,
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


def test_deterministic_analysis_writes_compact_and_detailed_report_contract(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = analyze_snapshot_file(snapshot_path, output, provider="none")

    blueprint = result.paths.blueprint.read_text(encoding="utf-8")
    diagnostics = result.paths.diagnostics.read_text(encoding="utf-8")
    compact = result.paths.compact.read_text(encoding="utf-8")
    analysis = json.loads(result.paths.analysis.read_text(encoding="utf-8"))

    assert "COMPLETE ROBOT SYSTEM BLUEPRINT" in blueprint
    assert "System blueprint — test-robot" in blueprint
    assert "COMPLETE SYSTEM SUMMARY" in blueprint
    assert "Camera" in blueprint
    assert "Publisher → topic → subscriber relationships" in blueprint
    assert "ROS-to-hardware ownership" in blueprint
    assert "ROBOTICS SOFTWARE STACKS" in blueprint
    assert "Complete robotics stack status matrix" in blueprint
    for stack in (
        "Navigation2",
        "AMCL",
        "Robot Localization",
        "SLAM Toolbox",
        "Cartographer",
        "RTAB-Map",
        "ros2_control",
        "MoveIt",
        "Teleoperation",
        "Rosbag",
        "Diagnostics",
    ):
        assert stack in blueprint
    assert "NOT RECORDED IN SNAPSHOT" in blueprint
    assert 'id="stack-navigation2"' in blueprint
    blueprint_sections = (
        "summary",
        "platform",
        "storage",
        "buses",
        "devices",
        "linux",
        "network",
        "execution",
        "ros-environment",
        "ros-graph",
        "software",
        "capabilities",
        "interpretation",
        "coverage",
    )
    assert [blueprint.index(f'id="{name}"') for name in blueprint_sections] == sorted(
        blueprint.index(f'id="{name}"') for name in blueprint_sections
    )
    assert "QUICK SYSTEM SNAPSHOT" in compact
    for layer in (
        "Compute",
        "Physical hardware",
        "Linux integration",
        "ROS 2",
        "Robot capabilities",
    ):
        assert layer in compact
    assert "2026-08-10 05:00:00 PDT" in compact
    assert "Problems that can affect operation" in compact
    assert "Evidence boundary" not in compact
    assert "Complete USB topology" not in compact
    assert "ANALYSIS" in compact
    assert "deterministic analysis" in compact.split("</header>", 1)[0]
    assert "Installed</th><th>Configured" not in compact
    assert "COMPLETE ENGINEERING DIAGNOSTICS" in diagnostics
    assert "Degraded behavior" in diagnostics
    assert "Physical memory usage is above 90%." in diagnostics
    assert "Diagnostic commands" in diagnostics
    assert "Step-by-step solution" in diagnostics
    assert "Measurable success criteria" in diagnostics
    assert "Rollback plan" in diagnostics
    assert "CROSS-SYSTEM INCONSISTENCIES" in diagnostics
    assert "FINAL VERIFICATION" in diagnostics
    for section_id in (
        "confirmed_failure",
        "degraded",
        "configuration_warning",
        "advisory",
        "needs_confirmation",
        "probes",
    ):
        assert f'id="{section_id}"' in diagnostics
    assert 'id="platform"' in blueprint
    assert 'id="software"' in blueprint
    assert analysis["repairs_executed"] is False
    assert analysis["screwdriver_version"] == "1.1.0"
    assert analysis["snapshot_sha256"]
    assert analysis["successful_checks"]
    assert analysis["issues"][0]["code"] == "MEMORY_HIGH_USAGE"


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


def test_redesigned_reports_preserve_device_access_and_lead_with_findings(
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
            "physical_path": "/dev/serial/by-path/platform-usb-test",
            "device_node": {
                "path": "/dev/ttyUSB0",
                "permissions": "crw-rw----",
                "owner": "root",
                "group": "dialout",
                "access": "denied",
            },
        }
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
            },
        }
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = analyze_snapshot_file(snapshot_path, tmp_path / "agentic", provider="none")
    compact = result.paths.compact.read_text(encoding="utf-8")
    blueprint = result.paths.blueprint.read_text(encoding="utf-8")
    diagnostics = result.paths.diagnostics.read_text(encoding="utf-8")

    assert "/dev/serial/by-id/usb-cp2102n-test" in blueprint
    assert "crw-rw---- · root:dialout · denied" in blueprint
    assert "snd-usb-audio" in blueprint
    assert "PRESENT_NOT_EXERCISED" in blueprint
    assert "Physical hardware" in compact
    assert diagnostics.index('id="overview"') < diagnostics.index('id="degraded"')
    assert "Operational consequence" in diagnostics


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
        "summary": "Claude organized the verified robot evidence.",
        "architecture_observations": ["Camera evidence is connected across Linux and ROS 2."],
        "unknowns": ["Camera image quality was not actively tested."],
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
    assert "temperature" not in payload
    assert result.summary == provider_result["summary"]
    assert "Anthropic model claude-sonnet-5" in result.provider_status
    for path in (
        result.paths.compact,
        result.paths.blueprint,
        result.paths.diagnostics,
        result.paths.analysis,
    ):
        assert "test-secret-key" not in path.read_text(encoding="utf-8")


def test_anthropic_retries_transient_failure_and_records_request_metadata(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    provider_result = {
        "summary": "Anthropic completed after one transient failure.",
        "architecture_observations": [],
        "unknowns": [],
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

    analysis = json.loads(result.paths.analysis.read_text(encoding="utf-8"))
    assert attempts == 2
    assert analysis["provider_request"]["request_id"] == "msg_test_123"
    assert analysis["provider_request"]["input_tokens"] == 321
    assert analysis["provider_request"]["output_tokens"] == 45


def test_missing_anthropic_key_generates_deterministic_fallback(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        result = analyze_snapshot_file(snapshot_path, tmp_path / "analysis")

    assert result.paths.blueprint.is_file()
    assert result.paths.diagnostics.is_file()
    assert result.paths.analysis.is_file()
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
        "summary": "OpenAI organized the verified robot evidence.",
        "architecture_observations": ["Camera evidence joins Linux and ROS 2."],
        "unknowns": ["Camera image quality was not actively tested."],
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
    assert result.summary == provider_result["summary"]
    assert "OpenAI model gpt-5.6-terra (effort light)" in result.provider_status
    for path in (result.paths.blueprint, result.paths.diagnostics, result.paths.analysis):
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
        "summary": "Compatible OpenAI model used its default effort.",
        "architecture_observations": [],
        "unknowns": [],
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
        "summary": "Compatible Claude model used its default effort.",
        "architecture_observations": [],
        "unknowns": [],
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
