"""Test Screwdriver's shared inspection data structures."""

import json
from datetime import UTC

from screwdriver.models import (
    Component,
    ComponentStatus,
    Finding,
    FindingSeverity,
    NetworkInterface,
    SystemSnapshot,
)


def create_test_snapshot() -> SystemSnapshot:
    """Create a predictable system snapshot for model tests."""

    return SystemSnapshot(
        hostname="cutie",
        operating_system="Ubuntu 22.04",
        kernel="5.15.0",
        architecture="aarch64",
    )


def test_snapshot_has_utc_timestamp() -> None:
    """Verify that snapshots receive a timezone-aware UTC timestamp."""

    snapshot = create_test_snapshot()

    assert snapshot.created_at.tzinfo is UTC


def test_snapshot_lists_are_independent() -> None:
    """Verify that snapshots do not accidentally share mutable lists."""

    first_snapshot = create_test_snapshot()
    second_snapshot = create_test_snapshot()

    first_snapshot.components.append(
        Component(category="camera", name="Logitech Brio 100")
    )
    first_snapshot.network_interfaces.append(
        NetworkInterface(name="eth0")
    )

    assert len(first_snapshot.components) == 1
    assert len(first_snapshot.network_interfaces) == 1
    assert second_snapshot.components == []
    assert second_snapshot.network_interfaces == []


def test_component_converts_to_dictionary() -> None:
    """Verify that a component becomes JSON-compatible data."""

    component = Component(
        category="camera",
        name="Logitech Brio 100",
        status=ComponentStatus.OK,
        details={
            "device_node": "/dev/video0",
            "driver": "uvcvideo",
        },
    )

    result = component.to_dict()

    assert result["status"] == "ok"
    assert result["details"] == {
        "device_node": "/dev/video0",
        "driver": "uvcvideo",
    }


def test_network_interface_converts_to_dictionary() -> None:
    """Verify that network interface details become JSON-compatible data."""

    interface = NetworkInterface(
        name="eth0",
        ipv4_addresses=["192.168.1.25"],
        ipv6_addresses=["fe80::1234:abcd"],
        mac_address="48:b0:2d:11:22:33",
        state="up",
        is_loopback=False,
    )

    result = interface.to_dict()

    assert result == {
        "name": "eth0",
        "ipv4_addresses": ["192.168.1.25"],
        "ipv6_addresses": ["fe80::1234:abcd"],
        "mac_address": "48:b0:2d:11:22:33",
        "state": "up",
        "is_loopback": False,
    }


def test_snapshot_converts_to_json() -> None:
    """Verify that a complete snapshot can be serialized as JSON."""

    snapshot = create_test_snapshot()

    snapshot.network_interfaces.append(
        NetworkInterface(
            name="eth0",
            ipv4_addresses=["192.168.1.25"],
            mac_address="48:b0:2d:11:22:33",
            state="up",
        )
    )

    snapshot.components.append(
        Component(
            category="camera",
            name="Logitech Brio 100",
            status=ComponentStatus.OK,
        )
    )

    snapshot.findings.append(
        Finding(
            code="CAMERA_AVAILABLE",
            severity=FindingSeverity.INFO,
            summary="A USB camera is available.",
        )
    )

    result = snapshot.to_dict()
    encoded = json.dumps(result)

    assert result["hostname"] == "cutie"
    assert result["schema_version"] == "1.0"
    assert result["network_interfaces"][0]["name"] == "eth0"
    assert result["network_interfaces"][0]["ipv4_addresses"] == [
        "192.168.1.25"
    ]
    assert '"status": "ok"' in encoded
    assert '"severity": "info"' in encoded