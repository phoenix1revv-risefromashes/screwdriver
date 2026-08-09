"""Central safety policy for hardware discovery and diagnostic probes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class InspectionMode(IntEnum):
    """Maximum probe level authorized for one inspection run."""

    PASSIVE = 0
    SAFE_ACTIVE = 1
    LAB = 2


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    """Describe one proposed hardware interaction before it is attempted."""

    name: str
    required_mode: InspectionMode
    changes_state: bool = False
    explicit_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    """Explain whether the policy authorized one proposed interaction."""

    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Authorize only interactions allowed by the selected inspection mode."""

    mode: InspectionMode = InspectionMode.PASSIVE

    def evaluate(self, request: ProbeRequest) -> SafetyDecision:
        """Return a deterministic decision without touching hardware."""

        if request.required_mode > self.mode:
            return SafetyDecision(
                allowed=False,
                reason=(
                    f"{request.name} requires {request.required_mode.name}, "
                    f"but this run is {self.mode.name}."
                ),
            )

        if request.changes_state and self.mode is not InspectionMode.LAB:
            return SafetyDecision(
                allowed=False,
                reason="State-changing operations are restricted to LAB mode.",
            )

        if request.changes_state and not request.explicit_confirmation:
            return SafetyDecision(
                allowed=False,
                reason="State-changing operations require explicit confirmation.",
            )

        return SafetyDecision(
            allowed=True,
            reason=f"Authorized by {self.mode.name} policy.",
        )

    def require(self, request: ProbeRequest) -> None:
        """Raise before collection when the request is not authorized."""

        decision = self.evaluate(request)

        if not decision.allowed:
            raise PermissionError(decision.reason)
