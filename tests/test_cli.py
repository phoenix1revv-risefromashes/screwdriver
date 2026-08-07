"""Tests for the Screwdriver command-line interface."""

import pytest

from screwdriver.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI should display its installed version."""

    with pytest.raises(SystemExit) as result:
        main(["--version"])

    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == "screwdriver 0.0.0"


def test_inspect_placeholder(capsys: pytest.CaptureFixture[str]) -> None:
    """The initial inspect command should run successfully."""

    assert main(["inspect"]) == 0

    output = capsys.readouterr().out
    assert "foundation ready" in output.lower()