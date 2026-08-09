import pytest

from screwdriver.cli import main


def test_inspect_defaults_to_local(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["inspect"]) == 0
    assert "Inspection mode: local" in capsys.readouterr().out


def test_explicit_local_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["inspect", "--local"]) == 0
    assert "Inspection mode: local" in capsys.readouterr().out


def test_agentic_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["inspect", "--agentic"]) == 0
    assert "Inspection mode: agentic" in capsys.readouterr().out


def test_agentic_focus(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        ["inspect", "--agentic", "--focus", "camera and ROS 2"]
    )

    assert result == 0
    assert "Focus: camera and ROS 2" in capsys.readouterr().out


def test_focus_requires_agentic_mode() -> None:
    with pytest.raises(SystemExit) as error:
        main(["inspect", "--local", "--focus", "camera"])

    assert error.value.code == 2


def test_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as error:
        main(["inspect", "--local", "--agentic"])

    assert error.value.code == 2


def test_analyze_accepts_snapshot(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["analyze", "snapshot.json"]) == 0
    assert "Snapshot: snapshot.json" in capsys.readouterr().out