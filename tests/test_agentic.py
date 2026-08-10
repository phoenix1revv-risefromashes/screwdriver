"""Test evidence-grounded agentic reporting and the passive probe boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from screwdriver.agentic import (
    ProbeRequest,
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
        "software_stack_inventory": [],
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


def test_deterministic_analysis_writes_detailed_two_report_contract(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    output = tmp_path / "analysis"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = analyze_snapshot_file(snapshot_path, output, provider="none")

    blueprint = result.paths.blueprint.read_text(encoding="utf-8")
    diagnostics = result.paths.diagnostics.read_text(encoding="utf-8")
    analysis = json.loads(result.paths.analysis.read_text(encoding="utf-8"))

    assert "Complete Robotic System Blueprint" not in blueprint
    assert "System blueprint — test-robot" in blueprint
    assert "Devices currently in use by ROS 2" in blueprint
    assert "Camera" in blueprint
    assert "Physical device → Linux interface/driver" in blueprint
    assert "ROS 2 computational graph" in blueprint
    assert "Unknowns and scan limitations" in blueprint
    assert "Problems and step-by-step solutions" in diagnostics
    assert "Physical memory usage is above 90%." in diagnostics
    assert "Primary step-by-step approach" in diagnostics
    assert "Success criteria" in diagnostics
    assert analysis["repairs_executed"] is False
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
        ]
    )

    assert commands == ["ros2 node list"]


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
        patch("screwdriver.agentic.urllib.request.urlopen", side_effect=fake_urlopen),
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
    assert "Anthropic Claude model claude-sonnet-5" in result.provider_status
    for path in (result.paths.blueprint, result.paths.diagnostics, result.paths.analysis):
        assert "test-secret-key" not in path.read_text(encoding="utf-8")


def test_missing_anthropic_key_generates_deterministic_fallback(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        result = analyze_snapshot_file(snapshot_path, tmp_path / "analysis")

    assert result.paths.blueprint.is_file()
    assert result.paths.diagnostics.is_file()
    assert result.paths.analysis.is_file()
    assert result.provider_status == (
        "Claude unavailable; deterministic fallback (ANTHROPIC_API_KEY is not set)"
    )
