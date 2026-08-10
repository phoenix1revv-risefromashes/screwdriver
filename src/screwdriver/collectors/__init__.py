"""Expose passive Screwdriver collectors."""

from screwdriver.collectors.host import (
    collect_host as _collect_host,
)
from screwdriver.collectors.host import collect_network_interfaces
from screwdriver.collectors.ros import collect_robotics_software
from screwdriver.collectors.runtime import collect_runtime_inventory
from screwdriver.collectors.serial import collect_serial_devices
from screwdriver.collectors.usb import collect_usb_devices
from screwdriver.models import (
    Component,
    ComponentStatus,
    Finding,
    FindingSeverity,
    SystemSnapshot,
)


def collect_host() -> SystemSnapshot:
    """Collect host, ROS, and robotics-software data without changing state."""

    snapshot = _collect_host()
    _remove_known_false_positives(snapshot)
    components, findings = collect_robotics_software()
    runtime_components = [*snapshot.components, *components]
    snapshot.components.extend(
        component for component in components if component.status is not ComponentStatus.UNKNOWN
    )
    snapshot.findings.extend(findings)

    try:
        runtime = collect_runtime_inventory(
            runtime_components,
            snapshot.usb_devices,
            snapshot.serial_devices,
        )
    except Exception as exception:  # Defensive boundary: host inspection must still finish.
        snapshot.ros_runtime_inventory.append(
            Component(
                category="ROS runtime",
                name="ROS 2 graph",
                status=ComponentStatus.ERROR,
                details={
                    "state": "UNAVAILABLE",
                    "probe": "metadata only; runtime collector failed",
                },
            )
        )
        snapshot.findings.append(
            Finding(
                code="RUNTIME_INVENTORY_FAILED",
                severity=FindingSeverity.ERROR,
                summary="Runtime inventory failed; host inspection still completed.",
                evidence=f"{type(exception).__name__}: {exception}",
                recommendation="Review the runtime collector error and run inspection again.",
            )
        )
    else:
        snapshot.software_stack_inventory = runtime.software_stacks
        snapshot.sensor_inventory = runtime.sensors
        snapshot.actuator_inventory = runtime.actuators
        snapshot.ros_device_inventory = runtime.devices
        snapshot.ros_runtime_inventory = runtime.ros_runtime
        snapshot.findings.extend(runtime.findings)

    if any(
        finding.severity in {FindingSeverity.WARNING, FindingSeverity.ERROR}
        for finding in snapshot.findings
    ):
        snapshot.findings = [
            finding for finding in snapshot.findings if finding.code != "HOST_RESOURCES_HEALTHY"
        ]

    return snapshot


def _remove_known_false_positives(snapshot: SystemSnapshot) -> None:
    """Remove two noisy host findings while preserving genuine failures."""

    filtered = []
    for finding in snapshot.findings:
        if finding.code == "THERMAL_CRITICAL":
            matching_sensors = [
                sensor for sensor in snapshot.thermal_sensors if sensor.name in finding.summary
            ]
            if matching_sensors and all(
                sensor.temperature_celsius
                < (
                    sensor.critical_celsius
                    if sensor.critical_celsius is not None and sensor.critical_celsius >= 65.0
                    else 90.0
                )
                for sensor in matching_sensors
            ):
                continue

        if finding.code in {
            "SERIAL_ACCESS_INCOMPLETE",
            "SERIAL_DEVICE_NODE_MISSING",
        }:
            matching_devices = [
                device for device in snapshot.serial_devices if device.port in finding.summary
            ]
            if matching_devices and all(
                not device.transport.startswith("usb-") for device in matching_devices
            ):
                continue

        filtered.append(finding)

    snapshot.findings = filtered


__all__ = [
    "collect_host",
    "collect_network_interfaces",
    "collect_robotics_software",
    "collect_runtime_inventory",
    "collect_serial_devices",
    "collect_usb_devices",
]
