"""Tests for Screwdriver's hardware-interaction safety policy."""

import pytest

from screwdriver.safety import (
    InspectionMode,
    ProbeRequest,
    SafetyPolicy,
)


def test_passive_mode_allows_filesystem_metadata_reads() -> None:
    policy = SafetyPolicy()
    request = ProbeRequest(
        name="read sysfs TTY metadata",
        required_mode=InspectionMode.PASSIVE,
    )

    assert policy.evaluate(request).allowed is True


def test_passive_mode_rejects_active_device_query() -> None:
    policy = SafetyPolicy()
    request = ProbeRequest(
        name="query known device identity register",
        required_mode=InspectionMode.SAFE_ACTIVE,
    )

    with pytest.raises(
        PermissionError,
        match="requires SAFE_ACTIVE",
    ):
        policy.require(request)


def test_lab_state_change_still_requires_explicit_confirmation() -> None:
    policy = SafetyPolicy(mode=InspectionMode.LAB)
    unconfirmed = ProbeRequest(
        name="run device self-test",
        required_mode=InspectionMode.LAB,
        changes_state=True,
    )
    confirmed = ProbeRequest(
        name="run device self-test",
        required_mode=InspectionMode.LAB,
        changes_state=True,
        explicit_confirmation=True,
    )

    assert policy.evaluate(unconfirmed).allowed is False
    assert policy.evaluate(confirmed).allowed is True
