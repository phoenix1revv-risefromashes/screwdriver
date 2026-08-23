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
    monkeypatch.setattr(collectors, "collect_runtime_fallback", fail)

    snapshot = collectors.collect_host()

    assert snapshot.identity.hostname
    assert snapshot.ros_runtime_inventory[0].details["state"] == "UNAVAILABLE"
    assert any(finding.code == "RUNTIME_INVENTORY_FAILED" for finding in snapshot.findings)


def test_runtime_failure_preserves_recovered_graph_and_software_stacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_snapshot = collectors._collect_host()
    static_stack = Component(
        category="robotics software stack",
        name="Robot State Publisher",
        status=ComponentStatus.OK,
        details={
            "installed": True,
            "detected_packages": "robot_state_publisher",
            "version": "robot_state_publisher 3.0.3",
        },
    )
    recovered_stack = Component(
        category="software stack",
        name="Robot State Publisher",
        status=ComponentStatus.OK,
        details={
            "state": "INSTALLED_INACTIVE",
            "detected_packages": "robot_state_publisher",
            "version": "robot_state_publisher 3.0.3",
        },
    )
    recovered_graph = Component(
        category="ROS runtime",
        name="ROS 2 graph",
        status=ComponentStatus.OK,
        details={"state": "RUNNING", "nodes": 5},
    )
    recovered_node = Component(
        category="ROS node",
        name="/cutie_mic_recorder",
        status=ComponentStatus.OK,
        details={"state": "DISCOVERED"},
    )

    monkeypatch.setattr(collectors, "_collect_host", lambda: base_snapshot)
    monkeypatch.setattr(
        collectors,
        "collect_robotics_software",
        lambda: ([static_stack], []),
    )

    def fail(*_arguments: object) -> RuntimeInventory:
        raise RuntimeError("simulated deep enrichment failure")

    monkeypatch.setattr(collectors, "collect_runtime_inventory", fail)
    monkeypatch.setattr(
        collectors,
        "collect_runtime_fallback",
        lambda *_arguments: RuntimeInventory(
            software_stacks=[recovered_stack],
            ros_runtime=[recovered_graph, recovered_node],
        ),
    )

    snapshot = collectors.collect_host()

    assert snapshot.software_stack_inventory == [recovered_stack]
    assert snapshot.ros_runtime_inventory == [recovered_graph, recovered_node]
    assert snapshot.ros_runtime_inventory[0].details["nodes"] == 5
    assert any(finding.code == "RUNTIME_INVENTORY_FAILED" for finding in snapshot.findings)


def test_collect_host_emits_real_progress_stages_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_snapshot = collectors._collect_host()
    events: list[tuple[int, str]] = []

    def fake_host(progress=None):
        assert progress is not None
        progress(1, "Inspecting host & operating system")
        progress(2, "Inspecting compute, memory & storage")
        progress(3, "Discovering hardware & device interfaces")
        progress(4, "Checking network, power & thermals")
        return base_snapshot

    monkeypatch.setattr(collectors, "_collect_host", fake_host)
    monkeypatch.setattr(collectors, "collect_robotics_software", lambda: ([], []))
    monkeypatch.setattr(
        collectors,
        "collect_runtime_inventory",
        lambda *_arguments: RuntimeInventory(),
    )

    collectors.collect_host(
        progress=lambda number, label, waiting=False: events.append((number, label))
    )

    assert [number for number, _label in events] == [1, 2, 3, 4, 5, 6, 7]
    assert events[-1][1] == "Evaluating system findings"
