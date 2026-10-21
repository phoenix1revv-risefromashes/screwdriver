"""Define the command-line interface and human-readable host report."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import time
import webbrowser
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from screwdriver import __version__
from screwdriver.agent_providers import (
    DEFAULT_MODELS,
    EFFORT_CHOICES,
    PROVIDER_CHOICES,
    resolve_model,
)
from screwdriver.agentic import DiagnosticIssue, analyze_snapshot_file
from screwdriver.collectors import collect_host
from screwdriver.custom_analysis import analyze_custom_file, is_native_snapshot
from screwdriver.models import (
    Component,
    Finding,
    FindingSeverity,
    NetworkInterface,
    SerialDevice,
    SystemSnapshot,
    USBDevice,
)
from screwdriver.progress import AnalysisProgress, InspectionProgress
from screwdriver.report_time import REPORT_TIMEZONE_NAME, format_report_time
from screwdriver.storage import (
    ReportPaths,
    build_report_paths,
    create_report_run,
    save_reports,
)

_WIDTH = 72


def build_parser() -> argparse.ArgumentParser:
    """Create Screwdriver's argument parser."""

    parser = argparse.ArgumentParser(
        prog="screwdriver",
        description="Passively inspect a Linux-based robotic computer.",
    )
    subparsers = parser.add_subparsers(dest="command")
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect the local computer without changing device state."
    )
    modes = inspect_parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--local",
        action="store_true",
        help="Use deterministic offline collection and diagnostic rules (default).",
    )
    modes.add_argument(
        "--agentic",
        action="store_true",
        help=(
            "Generate both the Agentic System Blueprint Report and Agentic System "
            "Diagnostic Report after deterministic collection."
        ),
    )
    inspect_parser.add_argument(
        "--find-issues",
        action="store_true",
        help=(
            "Run the full inspection but print only actionable warning/error findings. "
            "With --agentic, emphasize diagnostic reasoning and open the Diagnostic Report."
        ),
    )
    inspect_parser.add_argument(
        "--no-open",
        action="store_true",
        help="Save the generated HTML report without opening it in a desktop browser.",
    )
    inspect_parser.add_argument(
        "--focus",
        help="Focus future agent-assisted interpretation on one subsystem.",
    )
    inspect_parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports"),
        help="Report root containing local/ and agentic/ runs (default: reports).",
    )
    _add_agent_options(inspect_parser)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze a Screwdriver snapshot or arbitrary JSON/YAML/text diagnostic file.",
    )
    analyze_parser.add_argument(
        "snapshot", type=Path, help="Path to snapshot.json, JSON, YAML, JSONL, LOG or text file."
    )
    analyze_parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports"),
        help="Report root containing agentic/<timestamp>/ (default: reports).",
    )
    analyze_parser.add_argument(
        "--focus",
        help="Focus analysis on one subsystem while retaining complete evidence.",
    )
    _add_agent_options(analyze_parser)
    return parser


def _add_agent_options(parser: argparse.ArgumentParser) -> None:
    """Add provider and passive-investigation options to an agent command."""

    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default="anthropic",
        help="Analysis provider: anthropic, openai, or none (default: anthropic).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Provider model name. Defaults: anthropic="
            f"{DEFAULT_MODELS['anthropic']}, openai={DEFAULT_MODELS['openai']}."
        ),
    )
    parser.add_argument(
        "--effort",
        choices=EFFORT_CHOICES,
        default="medium",
        help=(
            "Reasoning effort: light, medium, or high (default: medium). "
            "Unsupported models use their native default."
        ),
    )
    parser.add_argument(
        "--investigate",
        action="store_true",
        help="Allow a bounded catalog of additional read-only diagnostic probes.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run Screwdriver's CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "inspect":
        if args.focus and not args.agentic:
            parser.error("--focus can only be used with --agentic")
        if args.investigate and not args.agentic:
            parser.error("--investigate can only be used with --agentic")
        return _run_inspect(args)
    if args.command == "analyze":
        try:
            return _run_analyze(args)
        except ValueError as exception:
            parser.error(str(exception))
    parser.error(f"Unknown command: {args.command}")
    return 2


def _run_inspect(args: argparse.Namespace) -> int:
    """Collect, format, save, and display one passive inspection."""

    started_monotonic = time.monotonic()
    started_at = datetime.now(UTC)
    mode = "agentic" if args.agentic else "local"
    progress = InspectionProgress()
    progress.start(mode)
    try:
        snapshot = collect_host(progress=progress.stage)
        collection_duration = time.monotonic() - started_monotonic
        run = create_report_run(args.output, created_at=snapshot.created_at)
        paths = build_report_paths(run.local_directory)
        progress.stage(8, "Building & saving inspection reports")
        report = format_snapshot(
            snapshot,
            mode=mode,
            started_at=started_at,
            duration=collection_duration,
            paths=paths,
            focus=args.focus,
        )
        report_paths = save_reports(
            snapshot,
            report,
            run.local_directory,
            scan_id=run.scan_id,
            duration_seconds=collection_duration,
        )
    except KeyboardInterrupt:
        progress.fail("Inspection interrupted")
        raise
    except Exception:
        progress.fail("Inspection failed")
        raise
    else:
        progress.finish("Inspection complete")
    finally:
        progress.close()

    duration = collection_duration
    if not args.find_issues and not args.agentic:
        opened, browser_note = _open_visual_report(
            report_paths.html_report,
            disabled=args.no_open,
        )
        print(
            format_local_completion(
                report_paths,
                duration=duration,
                opened=opened,
                browser_note=browser_note,
            )
        )
    elif not args.agentic:
        print(
            format_issue_findings(
                snapshot,
                duration=duration,
                report_directory=run.local_directory,
            )
        )

    if args.agentic:
        # One agentic reasoning pass produces both locked human-facing reports.
        # This avoids a second provider call, avoids cleanup/preservation races,
        # and guarantees that Blueprint and Diagnostic describe the same evidence
        # and reasoning pass.
        agentic_outcome = _run_agentic_analysis(
            report_paths.snapshot,
            run.agentic_directory,
            args=args,
            scan_id=run.scan_id,
            collection_duration_seconds=collection_duration,
            report_mode="both",
        )

        if args.find_issues:
            print(
                format_agentic_issue_findings(
                    agentic_outcome.issues,
                    provider_status=agentic_outcome.provider_status,
                    duration=duration,
                    report_directory=run.agentic_directory,
                )
            )

        print(f"Agentic System Blueprint Report:  {agentic_outcome.paths.blueprint}")
        print(f"Agentic System Diagnostic Report: {agentic_outcome.paths.diagnostics}")

        selected_report = (
            agentic_outcome.paths.diagnostics
            if args.find_issues
            else agentic_outcome.paths.blueprint
        )
        report_name = (
            "Agentic System Diagnostic Report"
            if args.find_issues
            else "Agentic System Blueprint Report"
        )
        opened, browser_note = _open_visual_report(selected_report, disabled=args.no_open)
        print(
            format_agentic_completion(
                selected_report,
                report_name=report_name,
                provider_status=agentic_outcome.provider_status,
                opened=opened,
                browser_note=browser_note,
                screwdriver_args=(
                    ["inspect", "--find-issues", "--agentic"]
                    if args.find_issues
                    else ["inspect", "--agentic"]
                ),
            )
        )
    return 0


def _open_visual_report(path: Path, *, disabled: bool) -> tuple[bool, str]:
    """Open the report on this machine when this is a local graphical session."""

    if disabled:
        return False, "disabled by --no-open"

    # A process inside a normal SSH session cannot execute a browser on the SSH
    # client computer. The client-side screwdriver-ssh wrapper handles that case.
    if _is_ssh_session():
        return False, "client-side opening available via screwdriver-ssh"

    uri = path.resolve().as_uri()
    for executable, command in (
        ("xdg-open", ["xdg-open", uri]),
        ("gio", ["gio", "open", uri]),
    ):
        if not shutil.which(executable):
            continue
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return True, f"opened locally via {executable}"

    try:
        if webbrowser.open(uri, new=2):
            return True, "opened locally via browser"
    except (OSError, webbrowser.Error):
        pass
    return False, "local browser launch failed"


def _is_ssh_session() -> bool:
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))


def _ssh_server_host() -> str | None:
    connection = os.environ.get("SSH_CONNECTION", "").split()
    if len(connection) >= 3:
        return connection[2]
    return None


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _remote_report_uri(path: Path) -> str | None:
    host = _ssh_server_host()
    if not host:
        return None
    user = quote(getpass.getuser(), safe="")
    remote_path = quote(path.resolve().as_posix(), safe="/")
    return f"sftp://{user}@{_url_host(host)}{remote_path}"


def _ssh_client_command(screwdriver_args: Sequence[str] = ("inspect",)) -> str | None:
    host = _ssh_server_host()
    if not host:
        return None
    target = f"{getpass.getuser()}@{host}"
    args = " ".join(str(item) for item in screwdriver_args)
    return f'screwdriver-ssh {target} --cwd "{Path.cwd()}" {args}'


def format_local_completion(
    paths: ReportPaths,
    *,
    duration: float,
    opened: bool,
    browser_note: str,
) -> str:
    """Render a concise handoff with directly usable report links."""

    html_path = paths.html_report.resolve()
    lines = [
        "",
        f"Inspection complete · {duration:.2f}s",
        f"HTML report: {html_path}",
        f"Report link: {html_path.as_uri()}",
        f"Text report: {paths.text_report.resolve()}",
        f"Browser: {browser_note}",
    ]
    if _is_ssh_session():
        remote_uri = _remote_report_uri(html_path)
        if remote_uri:
            lines.append(f"Remote report link: {remote_uri}")
        command = _ssh_client_command()
        if command:
            lines.extend(
                [
                    "Client auto-open command (run on the SSH client PC):",
                    f"  {command}",
                ]
            )
    return "\n".join(lines).rstrip()


def format_agentic_completion(
    report_path: Path,
    *,
    report_name: str,
    provider_status: str,
    opened: bool,
    browser_note: str,
    screwdriver_args: Sequence[str],
) -> str:
    """Render the final handoff for one generated agentic HTML report."""

    resolved = report_path.resolve()
    lines = [
        "",
        report_name,
        "─" * _WIDTH,
        f"HTML report: {resolved}",
        f"Report link: {resolved.as_uri()}",
        f"Analysis engine: {provider_status}",
        f"Browser: {browser_note}",
    ]
    if _is_ssh_session():
        remote_uri = _remote_report_uri(resolved)
        if remote_uri:
            lines.append(f"Remote report link: {remote_uri}")
        command = _ssh_client_command(screwdriver_args)
        if command:
            lines.extend(
                [
                    "Client auto-open command (run on the SSH client PC):",
                    f"  {command}",
                ]
            )
    return "\n".join(lines).rstrip()


def _actionable_findings(snapshot: SystemSnapshot) -> list[Finding]:
    """Return deterministic findings that require operator attention."""

    severity_order = {
        FindingSeverity.ERROR: 0,
        FindingSeverity.WARNING: 1,
    }
    findings = [finding for finding in snapshot.findings if finding.severity in severity_order]
    return sorted(findings, key=lambda finding: severity_order[finding.severity])


def format_issue_findings(
    snapshot: SystemSnapshot,
    *,
    duration: float,
    report_directory: Path,
) -> str:
    """Render only actionable deterministic findings for terminal-first triage."""

    findings = _actionable_findings(snapshot)
    error_count = sum(finding.severity is FindingSeverity.ERROR for finding in findings)
    warning_count = sum(finding.severity is FindingSeverity.WARNING for finding in findings)

    lines = [
        "SCREWDRIVER — FIND ISSUES",
        "─" * _WIDTH,
        "",
    ]
    if not findings:
        lines.extend(
            [
                "No actionable issues detected.",
                "",
                "0 errors · 0 warnings",
            ]
        )
    else:
        noun = "issue" if len(findings) == 1 else "issues"
        lines.extend([f"{len(findings)} {noun} found", ""])
        for finding in findings:
            lines.append(f"[{finding.severity.value.upper()}] {finding.summary}")
            if finding.evidence:
                lines.append(f"Evidence: {finding.evidence}")
            if finding.recommendation:
                lines.append(f"Next action: {finding.recommendation}")
            lines.append("")
        lines.append(f"{error_count} errors · {warning_count} warnings")

    lines.extend(
        [
            f"Inspection completed in {duration:.2f}s",
            f"Full scan saved: {report_directory}",
        ]
    )
    return "\n".join(lines).rstrip()


def _actionable_agentic_issues(issues: Sequence[DiagnosticIssue]) -> list[DiagnosticIssue]:
    """Keep agentic terminal output focused on evidence-backed actionable issues."""

    severity_order = {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }
    actionable = [
        issue
        for issue in issues
        if issue.severity.upper() in severity_order
        and issue.classification not in {"ADVISORY", "NEEDS_CONFIRMATION"}
    ]
    return sorted(actionable, key=lambda issue: severity_order[issue.severity.upper()])


def format_agentic_issue_findings(
    issues: Sequence[DiagnosticIssue],
    *,
    provider_status: str,
    duration: float,
    report_directory: Path,
) -> str:
    """Render issue-centered agentic reasoning without dumping the full report."""

    actionable = _actionable_agentic_issues(issues)
    lines = [
        "",
        "SCREWDRIVER — AGENTIC ISSUE ANALYSIS",
        "─" * _WIDTH,
        f"Analysis engine: {provider_status}",
        "",
    ]
    if not actionable:
        lines.append("No evidence-backed actionable issues detected.")
    else:
        noun = "issue" if len(actionable) == 1 else "issues"
        lines.extend([f"{len(actionable)} actionable {noun}", ""])
        for index, issue in enumerate(actionable, start=1):
            lines.append(f"{index}. [{issue.severity.upper()}] {issue.title}")
            lines.append(f"   Classification: {issue.classification}")
            if issue.operational_impact:
                lines.append(f"   Impact: {issue.operational_impact}")
            if issue.observed:
                lines.append(f"   Evidence: {issue.observed[0]}")
            if issue.probable_causes:
                lines.append(f"   Likely cause: {issue.probable_causes[0]}")
            if issue.primary_approach:
                lines.append(f"   Next action: {issue.primary_approach[0]}")
            if issue.success_criteria:
                lines.append(f"   Verify: {issue.success_criteria[0]}")
            lines.append("")

    lines.extend(
        [
            f"Local inspection completed in {duration:.2f}s",
            f"Full analysis saved: {report_directory}",
        ]
    )
    return "\n".join(lines).rstrip()


def _run_analyze(args: argparse.Namespace) -> int:
    """Analyze an existing snapshot without collecting or changing system state."""

    resolved_snapshot = args.snapshot.expanduser().resolve()
    source_scan_id = (
        resolved_snapshot.parent.name
        if resolved_snapshot.name == "snapshot.json"
        and resolved_snapshot.parent.parent.name == "local"
        else None
    )
    if not is_native_snapshot(resolved_snapshot):
        run = create_report_run(args.output)
        result = analyze_custom_file(
            resolved_snapshot,
            run.agentic_directory,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            focus=args.focus,
        )
        print("SCREWDRIVER CUSTOM FILE ANALYSIS")
        print("─" * _WIDTH)
        print(f"Source file:       {args.snapshot}")
        print(f"Diagnostic Report: {result.report}")
        print(f"Structured Results: {result.findings}")
        print(f"Analysis engine:   {result.provider_status}")
        print(f"Problems reported: {result.issue_count}")
        print("Read-only probes:  0 (file-only analysis)")
        print("Repairs executed:  no")
        return 0
    run = create_report_run(
        args.output,
        requested_scan_id=source_scan_id,
        allow_existing_local=source_scan_id is not None,
    )
    outcome = _run_agentic_analysis(
        args.snapshot,
        run.agentic_directory,
        args=args,
        scan_id=run.scan_id,
        report_mode="both",
    )
    print("SCREWDRIVER AGENTIC ANALYSIS")
    print("─" * _WIDTH)
    print(f"Source snapshot:   {args.snapshot}")
    print(f"Agentic System Blueprint Report:  {outcome.paths.blueprint}")
    print(f"Agentic System Diagnostic Report: {outcome.paths.diagnostics}")
    print(f"Analysis engine:   {outcome.provider_status}")
    print(f"Problems reported: {len(outcome.issues)}")
    print(f"Read-only probes:  {len(outcome.probes)}")
    print("Repairs executed:  no")
    return 0


def _run_agentic_analysis(
    snapshot: Path,
    output_directory: Path,
    *,
    args: argparse.Namespace,
    scan_id: str,
    collection_duration_seconds: float | None = None,
    report_mode: str | None = None,
    preserve_existing_reports: bool = False,
):
    """Run analysis with a heartbeat so a blocking provider call never looks frozen."""

    resolved_model = resolve_model(args.provider, args.model) if args.provider != "none" else "none"
    provider_label = {
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "none": "Deterministic",
    }[args.provider]
    progress = AnalysisProgress()
    progress.start(provider_label, resolved_model, args.effort)
    try:
        outcome = analyze_snapshot_file(
            snapshot,
            output_directory,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            investigate=args.investigate,
            focus=args.focus,
            scan_id=scan_id,
            collection_duration_seconds=collection_duration_seconds,
            progress=progress.stage,
            report_mode=(
                report_mode
                or ("diagnostic" if getattr(args, "find_issues", False) else "blueprint")
            ),
            preserve_existing_reports=preserve_existing_reports,
        )
    except KeyboardInterrupt:
        progress.fail("Agentic analysis interrupted")
        raise
    except Exception:
        progress.fail("Agentic analysis failed")
        raise
    else:
        progress.finish()
        return outcome
    finally:
        progress.close()


def format_snapshot(
    snapshot: SystemSnapshot,
    *,
    mode: str,
    started_at: datetime,
    duration: float,
    paths: ReportPaths | None,
    focus: str | None = None,
) -> str:
    """Format the complete universal-host snapshot for terminal display."""

    lines = [
        "╭" + "─" * (_WIDTH - 2) + "╮",
        "│ " + "SCREWDRIVER".ljust(_WIDTH - 4) + " │",
        "│ " + "Universal inspection of Linux-based robotic computers".ljust(_WIDTH - 4) + " │",
        "│ "
        + "Passive inspection — no hardware was activated or modified".ljust(_WIDTH - 4)
        + " │",
        "╰" + "─" * (_WIDTH - 2) + "╯",
        "",
        f"Inspection mode: {mode}",
        f"Screwdriver:     {__version__}",
        f"Scan ID:         {paths.snapshot.parent.name if paths else 'pending'}",
        "Probe safety:    PASSIVE",
        f"Report timezone: {REPORT_TIMEZONE_NAME}",
        f"Started:         {format_report_time(started_at)}",
    ]

    if focus:
        lines.append(f"Focus:           {focus}")

    if mode == "agentic":
        lines.extend(
            [
                "Agentic status:  Blueprint + Diagnostic reports always generated",
                "Repair policy:   recommendations only; no fixes are executed",
            ]
        )

    identity = snapshot.identity
    lines.extend(
        _section(
            "HOST IDENTITY",
            [
                _row("Hostname", identity.hostname),
                _row("Username", identity.username),
                _row("Effective user", identity.effective_username),
                _row("UID / GID", f"{identity.uid} / {identity.gid}"),
                _row("Groups", ", ".join(identity.groups) or "none"),
                _row("Login shell", identity.login_shell),
                _row("Machine ID", _abbreviate_secret(identity.machine_id)),
            ],
        )
    )

    operating_system = snapshot.operating_system
    lines.extend(
        _section(
            "OPERATING SYSTEM",
            [
                _row("Distribution", operating_system.distribution),
                _row("Kernel", operating_system.kernel),
                _row("Kernel build", operating_system.kernel_build),
                _row("Architecture", operating_system.architecture),
                _row("Boot mode", operating_system.boot_mode),
                _row("Init system", operating_system.init_system),
                _row("Package manager", operating_system.package_manager),
                _row("System timezone", operating_system.timezone),
                _row(
                    "Boot time",
                    format_report_time(operating_system.boot_time),
                ),
                _row("Uptime", _format_duration(operating_system.uptime_seconds)),
                _row("Running processes", operating_system.process_count),
            ],
        )
    )

    platform_info = snapshot.platform
    lines.extend(
        _section(
            "PLATFORM",
            [
                _row("Manufacturer", platform_info.manufacturer),
                _row("Product", platform_info.product_name),
                _row("Board", platform_info.board_name),
                _row("Board revision", platform_info.board_version),
                _row("Firmware", platform_info.firmware_version),
                _row("Machine type", platform_info.machine_type),
                _row("Virtualization", platform_info.virtualization or "none detected"),
                _row("Platform family", platform_info.family),
                _row("Enrichment module", platform_info.enrichment_module or "none"),
                "Serial number:     available in snapshot.json"
                if platform_info.serial_number
                else "Serial number:     not reported by platform",
            ],
        )
    )

    if platform_info.details:
        detail_lines = [
            _row(key.replace("_", " ").title(), value)
            for key, value in platform_info.details.items()
        ]
        lines.extend(
            _section(
                f"PLATFORM-SPECIFIC DETAILS — {platform_info.family.upper()}",
                detail_lines,
            )
        )

    cpu = snapshot.cpu
    cpu_lines = [
        _row("Model", cpu.model),
        _row("Vendor", cpu.vendor),
        _row("Sockets", cpu.sockets),
        _row("Physical cores", cpu.physical_cores),
        _row("Logical CPUs", cpu.logical_cpus),
        _row("Online CPUs", cpu.online_cpus),
        _row("Current frequency", _format_frequency(cpu.current_frequency_mhz)),
        _row("Minimum frequency", _format_frequency(cpu.minimum_frequency_mhz)),
        _row("Maximum frequency", _format_frequency(cpu.maximum_frequency_mhz)),
        _row("CPU usage", f"{cpu.usage_percent:.1f}%"),
        _row(
            "Load average",
            ", ".join(f"{value:.2f}" for value in cpu.load_average) if cpu.load_average else None,
        ),
        _row("Governor", cpu.governor),
    ]
    cpu_lines.extend(_row(f"Cache {name}", value) for name, value in cpu.caches.items())
    lines.extend(_section("CPU", cpu_lines))

    memory = snapshot.memory
    lines.extend(
        _section(
            "MEMORY",
            [
                "Physical memory:",
                _row("  Total", _format_bytes(memory.total_bytes)),
                _row("  Used", _format_bytes(memory.used_bytes)),
                _row("  Available", _format_bytes(memory.available_bytes)),
                _row("  Usage", f"{memory.usage_percent:.1f}%"),
                _row("  Shared", _format_bytes(memory.shared_bytes)),
                "",
                "Swap:",
                _row("  Total", _format_bytes(memory.swap_total_bytes)),
                _row("  Used", _format_bytes(memory.swap_used_bytes)),
                _row("  Available", _format_bytes(memory.swap_free_bytes)),
                _row("  Usage", f"{memory.swap_usage_percent:.1f}%"),
            ],
        )
    )

    storage_lines: list[str] = []

    if not snapshot.storage_devices:
        storage_lines.append("No physical storage devices were reported by lsblk.")

    for device in snapshot.storage_devices:
        storage_lines.extend(
            [
                _row("Device", device.path),
                _row("  Model", device.model),
                _row("  Connection", device.connection),
                _row("  Media type", device.media_type),
                _row("  Capacity", _format_bytes(device.capacity_bytes)),
                _row("  Firmware", device.firmware_version),
                _row("  Removable", _yes_no(device.removable)),
                _row("  Read-only", _yes_no(device.read_only)),
                "  Serial:           available in snapshot.json"
                if device.serial_number
                else "  Serial:           not reported",
            ]
        )

        if device.partitions:
            storage_lines.append("  Filesystems:")

        for partition in device.partitions:
            storage_lines.extend(
                [
                    f"    {partition.path}",
                    _row("      Filesystem", partition.filesystem),
                    _row("      Mount point", partition.mount_point or "not mounted"),
                    _row(
                        "      Capacity",
                        _format_optional_bytes(partition.total_bytes),
                    ),
                    _row(
                        "      Used",
                        _format_optional_bytes(partition.used_bytes),
                    ),
                    _row(
                        "      Available",
                        _format_optional_bytes(partition.available_bytes),
                    ),
                    _row(
                        "      Usage",
                        f"{partition.usage_percent:.1f}%"
                        if partition.usage_percent is not None
                        else "unavailable",
                    ),
                ]
            )

        storage_lines.append("")

    lines.extend(_section("STORAGE DEVICES", storage_lines))

    gpu_lines: list[str] = []

    if not snapshot.gpus:
        gpu_lines.append("No GPU or compute accelerator was detected.")

    for index, gpu in enumerate(snapshot.gpus):
        gpu_lines.extend(
            [
                f"GPU {index}:",
                _row("  Vendor", gpu.vendor),
                _row("  Model", gpu.model),
                _row("  Driver", gpu.driver),
                _row("  Bus ID", gpu.bus_id),
                _row("  Memory", _format_optional_bytes(gpu.memory_bytes)),
                _row(
                    "  Usage",
                    f"{gpu.usage_percent:.1f}%" if gpu.usage_percent is not None else None,
                ),
                _row(
                    "  Temperature",
                    f"{gpu.temperature_celsius:.1f}°C"
                    if gpu.temperature_celsius is not None
                    else None,
                ),
                "",
            ]
        )

    lines.extend(_section("GRAPHICS AND COMPUTE ACCELERATORS", gpu_lines))

    thermal_lines: list[str] = []

    if not snapshot.thermal_sensors:
        thermal_lines.append("No readable thermal sensors were exposed to this user.")

    for sensor in snapshot.thermal_sensors:
        health = _thermal_health(
            sensor.temperature_celsius,
            sensor.critical_celsius,
        )
        thermal_lines.append(_row(sensor.name, f"{sensor.temperature_celsius:.1f}°C  {health}"))

    lines.extend(_section("THERMAL AND COOLING", thermal_lines))

    power = snapshot.power
    power_lines = [
        _row("Power source", power.source),
        _row("Battery detected", _yes_no(power.battery_present)),
    ]

    if power.battery_present:
        power_lines.extend(
            [
                _row(
                    "Battery level",
                    f"{power.battery_percent:.1f}%" if power.battery_percent is not None else None,
                ),
                _row("Charging / plugged", _yes_no(power.charging)),
                _row(
                    "Time remaining",
                    _format_duration(power.seconds_remaining)
                    if power.seconds_remaining is not None
                    else None,
                ),
            ]
        )

    power_lines.extend(
        _row(key.replace("_", " ").title(), value) for key, value in power.details.items()
    )
    lines.extend(_section("POWER", power_lines))

    network = snapshot.network
    network_lines = [
        _row("Default route", network.default_interface),
        _row("Gateway", network.default_gateway),
        _row("DNS servers", ", ".join(network.dns_servers) or "none"),
        _row(
            "Internet route",
            "available" if network.internet_route_available else "not detected",
        ),
        "",
    ]

    visible_interfaces = [
        interface
        for interface in network.interfaces
        if not interface.is_loopback and not interface.is_virtual
    ]
    hidden_interfaces = [
        interface for interface in network.interfaces if interface not in visible_interfaces
    ]

    if not visible_interfaces:
        network_lines.append("No physical network interfaces were discovered.")

    for interface in visible_interfaces:
        network_lines.extend(_format_network_interface(interface))

    network_lines.append(
        f"Virtual interfaces: {len(hidden_interfaces)} detected, hidden from summary"
    )

    if hidden_interfaces:
        network_lines.append(
            "  Includes:        " + ", ".join(interface.name for interface in hidden_interfaces)
        )
        network_lines.append("  Full inventory:  available in snapshot.json")

    lines.extend(_section("NETWORK", network_lines))

    usb_lines: list[str] = []

    if not snapshot.usb_devices:
        usb_lines.append("No USB devices were exposed through sysfs.")

    for index, usb_device in enumerate(snapshot.usb_devices, start=1):
        usb_lines.extend(_format_usb_device(usb_device, index))

    lines.extend(_section("USB HARDWARE INVENTORY", usb_lines))

    serial_lines = [
        "Passive metadata only — serial ports were not opened and DTR/RTS were not toggled.",
        "",
    ]

    visible_serial = [
        device for device in snapshot.serial_devices if _serial_should_display(device)
    ]
    hidden_serial = len(snapshot.serial_devices) - len(visible_serial)

    if not visible_serial:
        serial_lines.append("No verified serial/TTY interfaces were discovered.")

    for index, serial_device in enumerate(visible_serial, start=1):
        serial_lines.extend(_format_serial_device(serial_device, index))

    if hidden_serial:
        serial_lines.append(
            f"{hidden_serial} unverified kernel TTY candidate"
            f"{'s' if hidden_serial != 1 else ''} retained in snapshot.json."
        )

    lines.extend(_section("SERIAL / TTY DIAGNOSTICS", serial_lines))

    display_lines: list[str] = []
    if not snapshot.display_inventory:
        display_lines.append("No connected DRM display units were detected.")
    for index, display in enumerate(snapshot.display_inventory, start=1):
        display_lines.extend(_format_display_unit(display, index))
    lines.extend(_section("DISPLAY UNITS", display_lines))

    if snapshot.software_stack_inventory:
        lines.extend(
            _section(
                "ROBOTICS SOFTWARE STACKS",
                _format_robotics_stack_inventory(snapshot.software_stack_inventory),
            )
        )
    physical_sensors = [
        component
        for component in snapshot.sensor_inventory
        if not _is_ros_inventory_component(component)
    ]
    if physical_sensors:
        lines.extend(
            _section(
                "PHYSICAL SENSOR INVENTORY",
                _format_component_inventory(physical_sensors),
            )
        )
    physical_actuators = [
        component
        for component in snapshot.actuator_inventory
        if not _is_ros_inventory_component(component)
    ]
    if physical_actuators:
        lines.extend(
            _section(
                "PHYSICAL ACTUATOR / CONTROL INVENTORY",
                _format_component_inventory(physical_actuators),
            )
        )
    lines.extend(_format_ros_sections(snapshot))

    severity_counts = {
        severity: sum(finding.severity is severity for finding in snapshot.findings)
        for severity in FindingSeverity
    }

    overall = (
        "ERRORS DETECTED"
        if severity_counts[FindingSeverity.ERROR]
        else "HEALTHY WITH WARNINGS"
        if severity_counts[FindingSeverity.WARNING]
        else "HEALTHY"
    )

    summary_lines = [
        _row("Overall status", overall),
        _row("Warnings", severity_counts[FindingSeverity.WARNING]),
        _row("Errors", severity_counts[FindingSeverity.ERROR]),
        _row("Informational", severity_counts[FindingSeverity.INFO]),
        "",
    ]

    for finding in snapshot.findings:
        summary_lines.append(f"[{finding.severity.value.upper()}] {finding.summary}")

        if finding.evidence:
            summary_lines.append(f"       Evidence: {finding.evidence}")

        if finding.recommendation:
            summary_lines.append(f"       Recommendation: {finding.recommendation}")

    lines.extend(_section("DIAGNOSTIC SUMMARY", summary_lines))

    report_lines = [
        _row("Snapshot", paths.snapshot if paths else "pending"),
        _row("Terminal report", paths.text_report if paths else "pending"),
        _row("HTML report", paths.html_report if paths else "pending"),
        _row("Diagnostic log", paths.diagnostic_log if paths else "pending"),
        "",
        _row("Duration", f"{duration:.2f} seconds"),
        _row(
            "Completed",
            format_report_time(datetime.now(UTC)),
        ),
        "",
        "No configuration, device state, or hardware output was changed.",
    ]

    lines.extend(_section("REPORTS", report_lines))
    return "\n".join(lines).rstrip()


def _format_network_interface(interface: NetworkInterface) -> list[str]:
    return [
        _row("Interface", interface.name),
        _row("  Type", interface.interface_type),
        _row("  State", interface.state),
        _row("  IPv4", ", ".join(interface.ipv4_addresses) or "none"),
        _row("  IPv6", ", ".join(interface.ipv6_addresses) or "none"),
        _row("  MAC", interface.mac_address),
        _row(
            "  Link speed",
            f"{interface.speed_mbps:,} Mb/s" if interface.speed_mbps is not None else None,
        ),
        _row("  Duplex", interface.duplex),
        _row("  Driver", interface.driver),
        _row("  Default route", _yes_no(interface.is_default_route)),
        "",
    ]


def _format_usb_device(device: USBDevice, index: int) -> list[str]:
    location = (
        f"bus {device.bus_number:03d}, device {device.device_number:03d}"
        if device.bus_number is not None and device.device_number is not None
        else device.sysfs_name
    )

    lines = [
        f"USB device {index}: {device.display_name}",
        _row("  USB ID", device.usb_id),
        _row("  Location", location),
        _row("  USB version", device.usb_version),
        _row(
            "  Link speed",
            f"{device.speed_mbps:g} Mb/s" if device.speed_mbps is not None else None,
        ),
        _row(
            "  Device class",
            (
                f"{device.device_class} ({device.device_class_name})"
                if device.device_class and device.device_class_name
                else device.device_class
            ),
        ),
        _row(
            "  Kernel drivers",
            ", ".join(device.drivers) or "none bound",
        ),
    ]

    if device.serial_number:
        lines.append("  Serial:           available in snapshot.json")

    if device.device_nodes:
        access_levels = sorted({node.access for node in device.device_nodes})
        access = (
            access_levels[0] if len(access_levels) == 1 else f"mixed ({', '.join(access_levels)})"
        )
        lines.append(_row("  Access", access))

    lines.append("")
    return lines


def _format_display_unit(component: Component, index: int) -> list[str]:
    details = component.details
    return [
        f"Display unit {index}: {component.name}",
        _row("  Type", "Display"),
        _row("  Connector", details.get("connector")),
        _row("  State", details.get("state")),
        _row("  Enabled", details.get("enabled")),
        _row("  Resolution", details.get("resolution")),
        _row("  Driver", details.get("driver")),
        "",
    ]


def _serial_should_display(device: SerialDevice) -> bool:
    """Return whether a serial record has positive evidence for the human report."""

    if device.verification is not None:
        return device.hardware_verified
    name = Path(device.port).name
    if device.usb_id or device.stable_id_path or device.physical_path:
        return True
    return name.startswith(
        (
            "ttyUSB",
            "ttyACM",
            "ttyTHS",
            "ttyAMA",
            "ttymxc",
            "ttyO",
            "ttyMSM",
            "ttyXRUSB",
            "rfcomm",
        )
    )


def _format_serial_device(device: SerialDevice, index: int) -> list[str]:
    lines = [
        f"Serial device {index}: {device.display_name}",
        _row("  Port", device.port),
        _row("  Transport", device.transport),
        _row("  Kernel driver", device.driver),
        _row("  USB ID", device.usb_id),
        _row("  Stable by-id", device.stable_id_path or "not available"),
        _row("  Physical path", device.physical_path or "not available"),
    ]

    if device.device_node is None:
        lines.append(_row("  Access", "device node missing"))
    else:
        lines.append(_row("  Access", device.device_node.access))

    lines.append("")
    return lines


def _format_component_inventory(
    components: list[Component],
    *,
    limit: int = 30,
) -> list[str]:
    """Format a bounded inventory summary; JSON and HTML retain every item."""

    lines = [
        "Passive metadata only — no sensor stream was read and no actuator was commanded.",
        "",
    ]
    for index, component in enumerate(components[:limit], start=1):
        details = component.details
        lines.extend(
            [
                f"{index}. {component.name}",
                _row("  Category", component.category),
                _row("  Status", component.status.value.upper()),
                _row("  State", details.get("state")),
            ]
        )
        for label, key in (
            ("  Kind", "kind"),
            ("  Source", "source"),
            ("  Bus", "bus"),
            ("  Device / channel", "channel"),
            ("  Driver", "driver"),
            ("  ROS node", "ros_node"),
            ("  ROS publisher", "hardware_node"),
            ("  ROS endpoint", "ros_endpoint"),
            ("  Message type", "message_type"),
            ("  Configured device", "configured_device"),
            ("  Health", "health"),
            ("  Confidence", "confidence"),
            ("  Physical match", "physical_component"),
        ):
            value = details.get(key)
            if value is not None and value != "":
                lines.append(_row(label, value))

        lines.append("")

    remaining = len(components) - limit
    if remaining > 0:
        lines.append(
            f"{remaining} additional items are available in snapshot.json and report.html."
        )

    return lines


def _format_robotics_stack_inventory(components: list[Component]) -> list[str]:
    """Present deterministic stack state, integration, I/O, and capability evidence."""

    lines = [
        "Installed software is not treated as operational without runtime evidence.",
        "",
    ]
    groups: dict[str, list[Component]] = {}
    for component in components:
        category = str(component.details.get("stack_category") or component.category)
        groups.setdefault(category, []).append(component)

    for category, stacks in groups.items():
        lines.append(category.upper())
        for stack in stacks:
            details = stack.details
            lines.extend(
                [
                    f"  {stack.name}",
                    _row("    Version", details.get("version")),
                    _row("    Installed", _yes_no(bool(details.get("installed")))),
                    _row("    Configured", _tri_state(details.get("configured"))),
                    _row("    Running", _tri_state(details.get("running"))),
                    _row("    Connected", _tri_state(details.get("connected"))),
                    _row("    Integrated", _tri_state(details.get("integrated"))),
                    _row("    Capability", details.get("capability")),
                    _row("    Capability state", details.get("capability_state")),
                    _row("    State", details.get("state") or stack.status.value.upper()),
                    _row("    Runtime owner", details.get("runtime_owner")),
                    _row("    Required inputs", details.get("required_inputs")),
                    _row("    Expected outputs", details.get("expected_outputs")),
                    _row("    Observed inputs", details.get("observed_inputs")),
                    _row("    Observed outputs", details.get("observed_outputs")),
                    _row("    Configuration", details.get("configuration_source")),
                    _row("    Detected packages", details.get("detected_packages")),
                    "",
                ]
            )
    return lines


def _tri_state(value: object) -> str:
    if value is None:
        return "Not evaluated"
    return _yes_no(bool(value))


def _format_ros_sections(snapshot: SystemSnapshot) -> list[str]:
    """Render the ROS graph as distinct, readable property groups."""

    sections: list[str] = []
    runtime_groups = {
        category: [
            component
            for component in snapshot.ros_runtime_inventory
            if component.category == category
        ]
        for category in (
            "ROS runtime",
            "ROS node",
            "ROS topic",
            "ROS service",
            "ROS action",
            "ros2_control hardware",
        )
    }

    overview = runtime_groups["ROS runtime"]
    if overview:
        sections.extend(_section("ROS 2 OVERVIEW", _format_ros_overview(overview[0])))

    for title, category in (
        ("ROS 2 NODES", "ROS node"),
        ("ROS 2 TOPICS", "ROS topic"),
        ("ROS 2 SERVICES", "ROS service"),
        ("ROS 2 ACTIONS", "ROS action"),
    ):
        components = runtime_groups[category]
        if components:
            sections.extend(
                _section(
                    title,
                    _format_ros_graph_items(components, category=category),
                )
            )

    device_labels = _current_ros_device_labels(snapshot.ros_device_inventory)
    if device_labels:
        sections.extend(
            _section(
                "CURRENT DEVICES IN USE BY ROS 2",
                [f"{index}. {label}" for index, label in enumerate(device_labels, start=1)],
            )
        )

    control_hardware = runtime_groups["ros2_control hardware"]
    if control_hardware:
        sections.extend(
            _section(
                "ROS 2 CONTROL HARDWARE INTERFACES",
                _format_component_inventory(control_hardware),
            )
        )

    return sections


def _format_ros_overview(component: Component) -> list[str]:
    details = component.details
    return [
        _row("Graph state", details.get("state")),
        _row("ROS distribution", details.get("ros_distro")),
        _row("Domain ID", details.get("domain_id")),
        _row("DDS middleware", details.get("middleware")),
        _row("Discovery mode", details.get("discovery_mode")),
        _row("Environment recovered", _yes_no(bool(details.get("environment_recovered")))),
        _row("Nodes", details.get("nodes")),
        _row("Topics", details.get("topics")),
        _row("Services", details.get("services")),
        _row("Actions", details.get("actions")),
        _row("Probe", details.get("probe")),
    ]


def _format_ros_graph_items(
    components: list[Component],
    *,
    category: str,
    limit: int = 50,
) -> list[str]:
    """List ROS graph objects separately while keeping terminal output bounded."""

    lines: list[str] = []
    for index, component in enumerate(components[:limit], start=1):
        details = component.details
        lines.append(f"{index}. {component.name}")
        if category == "ROS node":
            for label, key in (
                ("  State", "state"),
                ("  Publishers", "publishers"),
                ("  Subscribers", "subscribers"),
                ("  Services", "services"),
                ("  Actions", "actions"),
                ("  Hardware parameters", "hardware_parameters"),
            ):
                value = details.get(key)
                if value is not None and value != "":
                    lines.append(_row(label, value))
        else:
            lines.append(_row("  Type", details.get("type")))
        lines.append("")

    remaining = len(components) - limit
    if remaining > 0:
        lines.append(
            f"{remaining} additional {category.lower()} items are available in "
            "snapshot.json and report.html."
        )
    return lines


def _current_ros_device_labels(components: list[Component]) -> list[str]:
    """Return one concise, deduplicated label per device kind currently in use."""

    aliases = {
        "camera": "Camera",
        "lidar": "LiDAR",
        "point-cloud sensor": "Point-cloud sensor",
        "imu": "IMU",
        "gps/gnss": "GPS/GNSS",
        "range sensor": "Range sensor",
        "joint-state feedback": "Joint-state feedback device",
        "magnetometer": "Magnetometer",
        "pressure sensor": "Pressure sensor",
        "temperature sensor": "Temperature sensor",
        "humidity sensor": "Humidity sensor",
        "light sensor": "Light sensor",
        "force/torque sensor": "Force/torque sensor",
        "microphone": "Microphone",
        "microphone / audio capture": "Microphone",
        "speaker / audio output": "Speaker",
        "display / visual output": "Display unit",
        "mobile base drive": "Mobile base",
        "motor / actuator controller": "Motor / actuator",
        "joint/motor controller": "Joint / motor controller",
        "gripper": "Gripper",
        "power / battery device": "Battery / power system",
        "digital i/o / lighting device": "GPIO / lighting",
        "hardware communication interface": "Communication interface",
        "ros2_control controller": "ROS 2 controller",
        "ros2_control hardware component": "ROS 2 control hardware",
        "unclassified ros-attached device": "Other ROS-attached hardware",
    }
    labels: list[str] = []
    seen: set[str] = set()

    for component in components:
        details = component.details
        state = str(details.get("state") or "").upper()
        if state not in {"IN_USE_BY_ROS", "ACTIVE", "RUNNING"}:
            continue

        kind = str(details.get("kind") or "").strip()
        if not kind:
            continue
        label = aliases.get(kind.lower(), kind.replace("_", " ").capitalize())
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)

    return labels


def _is_ros_inventory_component(component: Component) -> bool:
    source = str(component.details.get("source") or "")
    return source.startswith("ROS 2") or component.details.get("state") == "IN_USE_BY_ROS"


def _section(title: str, content: list[str]) -> list[str]:
    return ["", "", title, "─" * _WIDTH, *content]


def _row(label: str, value: object) -> str:
    display = "unavailable" if value is None or value == "" else str(value)
    field = f"{label}:"
    separator = " " if len(field) >= 20 else ""
    return f"{field:<20}{separator}{display}"


def _format_bytes(value: int) -> str:
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    unit = units[0]

    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            break
        amount /= 1024

    if unit == "B":
        return f"{int(amount)} {unit}"

    return f"{amount:.2f} {unit}"


def _format_optional_bytes(value: int | None) -> str:
    return _format_bytes(value) if value is not None else "unavailable"


def _format_frequency(value_mhz: float | None) -> str:
    if value_mhz is None or value_mhz <= 0:
        return "unavailable"

    if value_mhz >= 1000:
        return f"{value_mhz / 1000:.2f} GHz"

    return f"{value_mhz:.0f} MHz"


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []

    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")

    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")

    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    if not parts:
        parts.append(f"{secs} seconds")

    return ", ".join(parts)


def _thermal_health(current: float, critical: float | None) -> str:
    if critical is not None and current >= critical:
        return "critical"

    if current >= 80:
        return "hot"

    return "healthy"


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "unavailable"

    return "yes" if value else "no"


def _abbreviate_secret(value: str | None) -> str:
    if not value:
        return "unavailable"

    if len(value) <= 12:
        return value

    return f"{value[:8]}…{value[-4:]}"


if __name__ == "__main__":
    raise SystemExit(main())
