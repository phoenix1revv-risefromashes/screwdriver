"""Tests for the Screwdriver command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from screwdriver.cli import main


def run_cli(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> int:
    """Run the real CLI with controlled command-line arguments."""

    monkeypatch.setattr(
        sys,
        "argv",
        ["screwdriver", *arguments],
    )

    try:
        result = main()
    except SystemExit as error:
        return int(error.code or 0)

    return int(result or 0)


def test_help_lists_inspect_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = run_cli(monkeypatch, ["--help"])
    output = capsys.readouterr()

    assert exit_code == 0
    assert "inspect" in output.out + output.err


def test_inspect_runs_successfully(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_cli(monkeypatch, ["inspect"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "SCREWDRIVER SYSTEM INSPECTION" in output
    assert "PASSIVE" in output


def test_inspect_creates_all_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert run_cli(monkeypatch, ["inspect"]) == 0

    report_directory = tmp_path / "reports"

    assert (report_directory / "snapshot.json").is_file()
    assert (report_directory / "report.txt").is_file()
    assert (report_directory / "report.html").is_file()
    assert (report_directory / "inspection.log").is_file()


def test_snapshot_report_contains_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import json

    monkeypatch.chdir(tmp_path)

    assert run_cli(monkeypatch, ["inspect"]) == 0

    snapshot_path = tmp_path / "reports" / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert isinstance(snapshot, dict)
    assert snapshot
