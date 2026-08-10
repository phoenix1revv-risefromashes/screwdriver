"""Expose passive Screwdriver collectors."""

from screwdriver.collectors.host import (
    collect_host as _collect_host,
)
from screwdriver.collectors.host import (
    collect_network_interfaces,
)
from screwdriver.collectors.ros import (
    collect_robotics_software,
)
from screwdriver.collectors.serial import (
    collect_serial_devices,
)
from screwdriver.collectors.usb import (
    collect_usb_devices,
)
from screwdriver.models import (
    FindingSeverity,
    SystemSnapshot,
)


def collect_host() -> SystemSnapshot:
    """Collect host, ROS, and robotics-software data without changing state."""

    snapshot = _collect_host()
    _remove_known_false_positives(snapshot)

    components, findings = collect_robotics_software()

    snapshot.components.extend(components)
    snapshot.findings.extend(findings)

    if any(
        finding.severity
        in {
            FindingSeverity.WARNING,
            FindingSeverity.ERROR,
        }
        for finding in snapshot.findings
    ):
        snapshot.findings = [
            finding for finding in snapshot.findings if finding.code != "HOST_RESOURCES_HEALTHY"
        ]

    return snapshot


def _remove_known_false_positives(
    snapshot: SystemSnapshot,
) -> None:
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
                    if (sensor.critical_celsius is not None and sensor.critical_celsius >= 65.0)
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
    "collect_serial_devices",
    "collect_usb_devices",
]
