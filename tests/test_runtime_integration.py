"""Test runtime inventory integration with the main host inspection."""

from __future__ import annotations

import pytest

from screwdriver import collectors
from screwdriver.collectors.runtime import RuntimeInventory
from screwdriver.models import Component, ComponentStatus


def test_collect_host_places_each_runtime_inventory_on_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_snapshot = collectors._collect_host()
    software = Component(
        category="software stack",
        name="Navigation2",
        status=ComponentStatus.OK,
        details={"state": "RUNNING"},
    )
    sensor = Component(
        category="sensor",
        name="camera",
        status=ComponentStatus.OK,
        details={"state": "DETECTED"},
    )
    actuator = Component(
        category="actuator/control",
        name="motor controller",
        status=ComponentStatus.OK,
        details={"state": "DETECTED"},
    )
    ros_graph = Component(
        category="ROS runtime",
        name="ROS 2 graph",
        status=ComponentStatus.OK,
        details={"state": "RUNNING"},
    )
    expected = RuntimeInventory(
        software_stacks=[software],
        sensors=[sensor],
        actuators=[actuator],
        devices=[sensor],
        ros_runtime=[ros_graph],
    )
    monkeypatch.setattr(collectors, "_collect_host", lambda: base_snapshot)
    monkeypatch.setattr(collectors, "collect_robotics_software", lambda: ([], []))
    monkeypatch.setattr(
        collectors,
        "collect_runtime_inventory",
        lambda *_arguments: expected,
    )

    snapshot = collectors.collect_host()

    assert snapshot.software_stack_inventory == [software]
    assert snapshot.sensor_inventory == [sensor]
    assert snapshot.actuator_inventory == [actuator]
    assert snapshot.ros_device_inventory == [sensor]
    assert snapshot.ros_runtime_inventory == [ros_graph]


def test_runtime_failure_does_not_destroy_host_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_snapshot = collectors._collect_host()
    monkeypatch.setattr(collectors, "_collect_host", lambda: base_snapshot)
    monkeypatch.setattr(collectors, "collect_robotics_software", lambda: ([], []))

    def fail(*_arguments: object) -> RuntimeInventory:
        raise RuntimeError("simulated collector failure")

    monkeypatch.setattr(collectors, "collect_runtime_inventory", fail)

    snapshot = collectors.collect_host()

    assert snapshot.identity.hostname
    assert snapshot.ros_runtime_inventory[0].details["state"] == "UNAVAILABLE"
    assert any(finding.code == "RUNTIME_INVENTORY_FAILED" for finding in snapshot.findings)
