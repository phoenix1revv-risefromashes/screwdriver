"""Tests for the Screwdriver v2 data models."""

from __future__ import annotations

import inspect
import json
from dataclasses import (
    MISSING,
    asdict,
    fields,
    is_dataclass,
)
from datetime import datetime

import screwdriver.models as models
from screwdriver.collectors.host import collect_host


def model_classes() -> list[type]:
    """Return dataclasses declared directly in screwdriver.models."""

    return [
        value
        for _, value in inspect.getmembers(
            models,
            inspect.isclass,
        )
        if value.__module__ == models.__name__ and is_dataclass(value)
    ]


def find_datetimes(value: object) -> list[datetime]:
    """Recursively find datetime values in a model tree."""

    if isinstance(value, datetime):
        return [value]

    if isinstance(value, dict):
        timestamps: list[datetime] = []

        for child in value.values():
            timestamps.extend(find_datetimes(child))

        return timestamps

    if isinstance(value, (list, tuple)):
        timestamps = []

        for child in value:
            timestamps.extend(find_datetimes(child))

        return timestamps

    return []


def test_models_are_dataclasses() -> None:
    """Verify that the model module contains dataclasses."""

    discovered_models = model_classes()

    assert discovered_models
    assert all(is_dataclass(model) for model in discovered_models)


def test_models_do_not_use_shared_mutable_defaults() -> None:
    """Prevent shared lists, dictionaries, and sets."""

    for model in model_classes():
        for field in fields(model):
            assert not isinstance(
                field.default,
                (list, dict, set),
            ), (
                f"{model.__name__}.{field.name} uses a shared "
                "mutable default; use default_factory instead."
            )

            if field.default_factory is MISSING:
                continue

            first_value = field.default_factory()
            second_value = field.default_factory()

            if isinstance(first_value, (list, dict, set)):
                assert first_value is not second_value


def test_collector_returns_system_snapshot() -> None:
    """Verify that collection returns the main snapshot model."""

    snapshot = collect_host()

    assert isinstance(snapshot, models.SystemSnapshot)
    assert is_dataclass(snapshot)


def test_snapshot_has_timezone_aware_timestamp() -> None:
    """Verify that snapshot timestamps include timezone information."""

    snapshot = collect_host()
    timestamps = find_datetimes(asdict(snapshot))

    assert timestamps

    assert all(
        timestamp.tzinfo is not None and timestamp.utcoffset() is not None
        for timestamp in timestamps
    )


def test_snapshot_converts_to_json() -> None:
    """Verify that a complete snapshot can be serialized."""

    snapshot = collect_host()

    encoded = json.dumps(
        asdict(snapshot),
        default=str,
    )

    decoded = json.loads(encoded)

    assert isinstance(decoded, dict)
    assert decoded
