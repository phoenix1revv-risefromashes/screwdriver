"""Tests for host and network discovery."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from unittest.mock import patch

from screwdriver.collectors.host import (
    collect_host,
    collect_network_interfaces,
)


def test_collect_network_interfaces() -> None:
    """Verify that network interfaces are collected."""

    command_output = [
        {
            "ifname": "lo",
            "flags": ["LOOPBACK", "UP"],
            "operstate": "UNKNOWN",
            "link_type": "loopback",
            "address": "00:00:00:00:00:00",
            "mtu": 65536,
            "addr_info": [
                {
                    "family": "inet",
                    "local": "127.0.0.1",
                    "prefixlen": 8,
                }
            ],
        },
        {
            "ifname": "eth0",
            "flags": ["BROADCAST", "UP", "LOWER_UP"],
            "operstate": "UP",
            "link_type": "ether",
            "address": "00:11:22:33:44:55",
            "mtu": 1500,
            "addr_info": [
                {
                    "family": "inet",
                    "local": "192.168.10.25",
                    "prefixlen": 24,
                }
            ],
        },
    ]

    with patch("screwdriver.collectors.host.subprocess.run") as mocked_run:
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = json.dumps(command_output)
        mocked_run.return_value.stderr = ""

        interfaces = collect_network_interfaces()

    names = [interface.name for interface in interfaces]

    assert "lo" in names
    assert "eth0" in names

    ethernet = next(interface for interface in interfaces if interface.name == "eth0")

    assert ethernet.state == "up"
    assert ethernet.mac_address == "00:11:22:33:44:55"
    assert ethernet.ipv4_addresses


def test_collect_host_returns_structured_snapshot() -> None:
    """Verify that host collection returns a structured snapshot."""

    snapshot = collect_host()

    assert is_dataclass(snapshot)

    payload = asdict(snapshot)

    assert isinstance(payload, dict)
    assert payload


def test_host_snapshot_is_json_serializable() -> None:
    """Verify that the collected snapshot can be encoded as JSON."""

    snapshot = collect_host()

    encoded = json.dumps(
        asdict(snapshot),
        default=str,
    )

    decoded = json.loads(encoded)

    assert isinstance(decoded, dict)
    assert decoded


def test_missing_ip_command_is_handled() -> None:
    """Verify that a missing ip command does not crash collection."""

    with patch(
        "screwdriver.collectors.host.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        interfaces = collect_network_interfaces()

    assert interfaces == []
