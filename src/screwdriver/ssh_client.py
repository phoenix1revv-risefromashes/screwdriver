"""Run Screwdriver over SSH and open the generated report on the local client."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from collections.abc import Sequence
from pathlib import Path

_REPORT_RE = re.compile(r"^HTML report:\s*(?P<path>.+?)\s*$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screwdriver-ssh",
        description=(
            "Run Screwdriver on a remote Linux robotics computer, copy the generated "
            "HTML report back, and open it in this computer's browser."
        ),
    )
    parser.add_argument("target", help="SSH target, for example phoenix@192.168.4.68")
    parser.add_argument(
        "--cwd",
        default=None,
        help="Optional remote working directory before running Screwdriver.",
    )
    parser.add_argument(
        "--local-report-dir",
        type=Path,
        default=None,
        help="Directory for copied reports (default: a temporary directory).",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Pass one OpenSSH -o option; repeat for multiple options.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, screwdriver_args = parser.parse_known_args(list(argv) if argv is not None else None)
    screwdriver_args = list(screwdriver_args)
    if screwdriver_args[:1] == ["--"]:
        screwdriver_args = screwdriver_args[1:]
    if not screwdriver_args:
        screwdriver_args = ["inspect"]
    if screwdriver_args[0] != "inspect":
        raise SystemExit("screwdriver-ssh currently supports the inspect workflow only")
    if "--find-issues" in screwdriver_args or "--agentic" in screwdriver_args:
        raise SystemExit(
            "screwdriver-ssh currently opens the standard local inspection report only"
        )
    if "--no-open" not in screwdriver_args:
        screwdriver_args.append("--no-open")

    ssh_base = ["ssh"]
    for option in args.ssh_option:
        ssh_base.extend(["-o", option])

    remote_command = _remote_command(args.cwd, screwdriver_args)
    report_path, returncode = _run_remote(
        [*ssh_base, args.target, remote_command],
    )
    if returncode != 0:
        return returncode
    if report_path is None:
        print(
            "screwdriver-ssh: remote inspection completed but no HTML report path was emitted.",
            file=sys.stderr,
        )
        return 2

    local_path = _copy_report_from_remote(
        ssh_base=ssh_base,
        target=args.target,
        remote_path=report_path,
        destination=args.local_report_dir,
    )
    if local_path is None:
        return 3

    opened, opener = _open_local_report(local_path)
    print(f"Local report: {local_path}")
    print(f"Report link: {local_path.resolve().as_uri()}")
    if opened:
        print(f"Browser: launch succeeded via {opener}")
        return 0
    print(
        f"Browser: launch failed; open this file manually: {local_path}",
        file=sys.stderr,
    )
    return 4


def _remote_command(cwd: str | None, screwdriver_args: Sequence[str]) -> str:
    command = " ".join(shlex.quote(item) for item in ["screwdriver", *screwdriver_args])
    if not cwd:
        return command
    return f"cd {_remote_cwd_expression(cwd)} && {command}"


def _remote_cwd_expression(cwd: str) -> str:
    if cwd == "~":
        return '"$HOME"'
    if cwd.startswith("~/"):
        remainder = cwd[2:]
        return f'"$HOME"/{shlex.quote(remainder)}'
    return shlex.quote(cwd)


def _run_remote(command: Sequence[str]) -> tuple[str | None, int]:
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        print(f"screwdriver-ssh: could not start ssh: {exc}", file=sys.stderr)
        return None, 127

    report_path: str | None = None
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        match = _REPORT_RE.match(line.rstrip("\n"))
        if match:
            report_path = match.group("path")
    return report_path, process.wait()


def _copy_report_from_remote(
    *,
    ssh_base: Sequence[str],
    target: str,
    remote_path: str,
    destination: Path | None,
) -> Path | None:
    if destination is None:
        destination = Path(tempfile.mkdtemp(prefix="screwdriver-report-"))
    else:
        destination = destination.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
    local_path = destination / "report.html"

    cat_command = f"cat -- {shlex.quote(remote_path)}"
    try:
        with local_path.open("wb") as handle:
            completed = subprocess.run(
                [*ssh_base, target, cat_command],
                stdout=handle,
                stderr=subprocess.PIPE,
                check=False,
            )
    except OSError as exc:
        print(f"screwdriver-ssh: could not copy report: {exc}", file=sys.stderr)
        return None

    if completed.returncode != 0:
        stderr = completed.stderr or b""
        message = stderr.decode("utf-8", errors="replace").strip()
        print(
            "screwdriver-ssh: report copy failed" + (f": {message}" if message else ""),
            file=sys.stderr,
        )
        local_path.unlink(missing_ok=True)
        return None
    return local_path


def _open_local_report(path: Path) -> tuple[bool, str]:
    """Launch the copied report using the local operating system's normal opener."""

    if sys.platform == "darwin":
        return _run_local_opener(["open", str(path)], "open")
    if os.name == "nt":
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError:
            return False, "startfile"
        return True, "startfile"

    for executable, command in (
        ("xdg-open", ["xdg-open", str(path)]),
        ("gio", ["gio", "open", str(path)]),
    ):
        if shutil.which(executable):
            opened, _ = _run_local_opener(command, executable)
            if opened:
                return True, executable

    try:
        requested = webbrowser.open(path.resolve().as_uri(), new=2)
    except (OSError, webbrowser.Error):
        requested = False
    return requested, "webbrowser"


def _run_local_opener(command: Sequence[str], name: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, name
    return completed.returncode == 0, name


if __name__ == "__main__":
    raise SystemExit(main())
