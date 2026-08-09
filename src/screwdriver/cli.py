"""Define the command-line interface and human-readable host report."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from screwdriver.collectors import collect_host
from screwdriver.models import (
    FindingSeverity,
    NetworkInterface,
    SystemSnapshot,
    USBDevice,
)
from screwdriver.storage import ReportPaths, build_report_paths, save_reports

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
        help="Reserve agent-assisted interpretation for a later implementation.",
    )
    inspect_parser.add_argument(
        "--focus",
        help="Focus future agent-assisted interpretation on one subsystem.",
    )
    inspect_parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports"),
        help="Report directory (default: reports).",
    )
    return parser


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
        return _run_inspect(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


def _run_inspect(args: argparse.Namespace) -> int:
    """Collect, format, save, and display one passive inspection."""

    started_monotonic = time.monotonic()
    started_at = datetime.now(UTC)
    snapshot = collect_host()
    duration = time.monotonic() - started_monotonic
    mode = "agentic" if args.agentic else "local"
    paths = build_report_paths(args.output)
    report = format_snapshot(
        snapshot,
        mode=mode,
        started_at=started_at,
        duration=duration,
        paths=paths,
        focus=args.focus,
    )
    save_reports(snapshot, report, args.output)
    print(report)
    return 0


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
        f"Started:         {started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
    ]

    if focus:
        lines.append(f"Focus:           {focus}")

    if mode == "agentic":
        lines.extend(
            [
                "Agentic status:  collection complete; agent reasoning not implemented yet",
                "                 (the report below remains deterministic and offline)",
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
                _row("Timezone", operating_system.timezone),
                _row(
                    "Boot time",
                    operating_system.boot_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
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

    network_lines.extend(
        [
            "IPv6:              excluded by output preference",
            f"Virtual interfaces: {len(hidden_interfaces)} detected, hidden from summary",
        ]
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
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
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


def _section(title: str, content: list[str]) -> list[str]:
    return ["", "", title, "─" * _WIDTH, *content]


def _row(label: str, value: object) -> str:
    display = "unavailable" if value is None or value == "" else str(value)
    return f"{label + ':':<20}{display}"


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
