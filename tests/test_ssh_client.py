from pathlib import Path
from unittest.mock import patch

from screwdriver import ssh_client


def test_client_wrapper_runs_remote_inspect_copies_report_and_opens_locally(
    capsys,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "report.html"
    copied.write_text("<html>report</html>", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run_remote(command):
        commands.append(list(command))
        return "/home/phoenix/reports/local/run/report.html", 0

    with (
        patch("screwdriver.ssh_client._run_remote", side_effect=fake_run_remote),
        patch("screwdriver.ssh_client._copy_report_from_remote", return_value=copied),
        patch("screwdriver.ssh_client._open_local_report", return_value=(True, "xdg-open")),
    ):
        assert ssh_client.main(["phoenix@192.168.4.68", "inspect"]) == 0

    output = capsys.readouterr().out
    assert commands
    assert "screwdriver inspect --no-open" in commands[0][-1]
    assert f"Local report: {copied}" in output
    assert f"Report link: {copied.resolve().as_uri()}" in output
    assert "Browser: launch succeeded via xdg-open" in output


def test_client_wrapper_does_not_claim_open_when_local_opener_fails(
    capsys,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "report.html"
    copied.write_text("<html>report</html>", encoding="utf-8")
    with (
        patch(
            "screwdriver.ssh_client._run_remote",
            return_value=("/remote/report.html", 0),
        ),
        patch("screwdriver.ssh_client._copy_report_from_remote", return_value=copied),
        patch("screwdriver.ssh_client._open_local_report", return_value=(False, "xdg-open")),
    ):
        assert ssh_client.main(["robot", "inspect"]) == 4

    captured = capsys.readouterr()
    assert "Browser: launch failed" in captured.err
    assert "Browser: launch succeeded" not in captured.out


def test_remote_command_preserves_home_expansion_for_tilde_cwd() -> None:
    command = ssh_client._remote_command(
        "~/pro_projects/screwdriver",
        ["inspect", "--no-open"],
    )
    assert command == 'cd "$HOME"/pro_projects/screwdriver && screwdriver inspect --no-open'
