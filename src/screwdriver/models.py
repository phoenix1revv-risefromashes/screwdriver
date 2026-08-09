"""Define the shared data structures for Screwdriver inspection results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ComponentStatus(StrEnum):
    """Represent the operational state of an inspected component."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class FindingSeverity(StrEnum):
    """Represent the importance of a diagnostic finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class Component:
    """Represent one hardware or software component found during inspection."""

    category: str
    name: str
    status: ComponentStatus = ComponentStatus.UNKNOWN
    details: dict[str, str | int | float | bool | None] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, object]:
        """Convert the component into a JSON-compatible dictionary."""

        return {
            "category": self.category,
            "name": self.name,
            "status": self.status.value,
            "details": self.details.copy(),
        }


@dataclass(slots=True)
class Finding:
    """Represent a potential problem or useful diagnostic observation."""

    code: str
    severity: FindingSeverity
    summary: str
    evidence: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert the finding into a JSON-compatible dictionary."""

        return {
            "code": self.code,
            "severity": self.severity.value,
            "summary": self.summary,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class NetworkInterface:
    """Represent one network interface belonging to the inspected host."""

    name: str
    ipv4_addresses: list[str] = field(default_factory=list)
    ipv6_addresses: list[str] = field(default_factory=list)
    mac_address: str | None = None
    state: str = "unknown"
    is_loopback: bool = False

    def to_dict(self) -> dict[str, object]:
        """Convert the network interface into JSON-compatible data."""

        return {
            "name": self.name,
            "ipv4_addresses": self.ipv4_addresses.copy(),
            "ipv6_addresses": self.ipv6_addresses.copy(),
            "mac_address": self.mac_address,
            "state": self.state,
            "is_loopback": self.is_loopback,
        }


@dataclass(slots=True)
class SystemSnapshot:
    """Represent a complete inspection of one robotic computer."""

    hostname: str
    operating_system: str
    kernel: str
    architecture: str
    schema_version: str = "1.0"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    network_interfaces: list[NetworkInterface] = field(
        default_factory=list
    )
    components: list[Component] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert the complete snapshot into JSON-compatible data."""

        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at.isoformat(),
            "hostname": self.hostname,
            "operating_system": self.operating_system,
            "kernel": self.kernel,
            "architecture": self.architecture,
            "network_interfaces": [
                interface.to_dict()
                for interface in self.network_interfaces
            ],
            "components": [
                component.to_dict()
                for component in self.components
            ],
            "findings": [
                finding.to_dict()
                for finding in self.findings
            ],
        }