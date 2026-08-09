"""Command-line interface for Screwdriver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from screwdriver.collectors import collect_host
from screwdriver.models import SystemSnapshot
from screwdriver.storage import ReportPaths, save_reports

app = typer.Typer(
    name="screwdriver",
    help="Passively inspect a Linux or robotics computer.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def root() -> None:
    """Screwdriver system-inspection commands."""


@app.command("inspect")
def inspect_system(
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Directory where inspection reports will be saved.",
        ),
    ] = Path("reports"),
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Print the complete snapshot as JSON.",
        ),
    ] = False,
) -> None:
    """Inspect the current computer without changing its state."""

    typer.echo("Inspecting system in passive mode...")

    try:
        snapshot = collect_host()
        terminal_report = build_terminal_report(snapshot)

        report_paths = save_reports(
            snapshot=snapshot,
            terminal_report=terminal_report,
            output_directory=output_directory,
        )
    except KeyboardInterrupt:
        typer.echo("\nInspection cancelled.", err=True)
        raise typer.Exit(code=130) from None
    except Exception as error:
        typer.echo(f"Inspection failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(json.dumps(snapshot.to_dict(), indent=2))
        return

    typer.echo()
    typer.echo(terminal_report)
    typer.echo()
    typer.echo(_render_saved_reports(report_paths))


def build_terminal_report(snapshot: SystemSnapshot) -> str:
    """Build a clean terminal representation of a system snapshot."""

    sections = [
        _render_header(snapshot),
        _render_identity(snapshot),
        _render_operating_system(snapshot),
        _render_platform(snapshot),
        _render_cpu(snapshot),
        _render_memory(snapshot),
        _render_storage(snapshot),
        _render_gpus(snapshot),
        _render_thermal(snapshot),
        _render_power(snapshot),
        _render_network(snapshot),
        _render_components(snapshot),
        _render_findings(snapshot),
    ]

    return "\n\n".join(sections)


def _render_header(snapshot: SystemSnapshot) -> str:
    """Render the inspection heading."""

    return "\n".join(
        [
            "SCREWDRIVER SYSTEM INSPECTION",
            "=" * 72,
            f"Host:       {snapshot.identity.hostname}",
            f"Created:    {snapshot.created_at.isoformat()}",
            "Mode:       PASSIVE",
            f"Schema:     {snapshot.schema_version}",
        ]
    )


def _render_identity(snapshot: SystemSnapshot) -> str:
    """Render host identity information."""

    identity = snapshot.identity

    return _section(
        "IDENTITY",
        [
            ("Hostname", identity.hostname),
            ("User", identity.username),
            ("Effective user", identity.effective_username),
            ("UID / GID", f"{identity.uid} / {identity.gid}"),
            ("Groups", ", ".join(identity.groups) or "none"),
            ("Login shell", identity.login_shell),
            ("Machine ID", identity.machine_id),
        ],
    )


def _render_operating_system(snapshot: SystemSnapshot) -> str:
    """Render operating-system information."""

    operating_system = snapshot.operating_system

    return _section(
        "OPERATING SYSTEM",
        [
            ("Distribution", operating_system.distribution),
            ("Kernel", operating_system.kernel),
            ("Architecture", operating_system.architecture),
            ("Boot mode", operating_system.boot_mode),
            ("Init system", operating_system.init_system),
            ("Package manager", operating_system.package_manager),
            ("Timezone", operating_system.timezone),
            ("Boot time", operating_system.boot_time.isoformat()),
            ("Uptime", _format_duration(operating_system.uptime_seconds)),
            ("Processes", str(operating_system.process_count)),
        ],
    )


def _render_platform(snapshot: SystemSnapshot) -> str:
    """Render physical-board or virtual-platform information."""

    platform = snapshot.platform

    rows = [
        ("Machine type", platform.machine_type),
        ("Family", platform.family),
        ("Manufacturer", platform.manufacturer),
        ("Product", platform.product_name),
        ("Board", platform.board_name),
        ("Board version", platform.board_version),
        ("Firmware", platform.firmware_version),
        ("Serial number", platform.serial_number),
        ("Virtualization", platform.virtualization),
        ("Enrichment", platform.enrichment_module),
    ]

    for key, value in platform.details.items():
        rows.append((key.replace("_", " ").title(), str(value)))

    return _section("PLATFORM", rows)


def _render_cpu(snapshot: SystemSnapshot) -> str:
    """Render processor information."""

    cpu = snapshot.cpu

    rows = [
        ("Model", cpu.model),
        ("Vendor", cpu.vendor),
        ("Sockets", _optional_number(cpu.sockets)),
        ("Physical cores", _optional_number(cpu.physical_cores)),
        ("Logical CPUs", str(cpu.logical_cpus)),
        ("Online CPUs", str(cpu.online_cpus)),
        ("Current frequency", _format_frequency(cpu.current_frequency_mhz)),
        ("Minimum frequency", _format_frequency(cpu.minimum_frequency_mhz)),
        ("Maximum frequency", _format_frequency(cpu.maximum_frequency_mhz)),
        ("Usage", f"{cpu.usage_percent:.1f}%"),
        ("Governor", cpu.governor),
    ]

    if cpu.load_average is not None:
        rows.append(
            (
                "Load average",
                " / ".join(f"{value:.2f}" for value in cpu.load_average),
            )
        )

    for cache_name, cache_size in cpu.caches.items():
        rows.append((cache_name, cache_size))

    return _section("CPU", rows)


def _render_memory(snapshot: SystemSnapshot) -> str:
    """Render memory and swap information."""

    memory = snapshot.memory

    return _section(
        "MEMORY",
        [
            ("Total", _format_bytes(memory.total_bytes)),
            ("Used", _format_bytes(memory.used_bytes)),
            ("Available", _format_bytes(memory.available_bytes)),
            ("Usage", f"{memory.usage_percent:.1f}%"),
            ("Shared", _format_bytes(memory.shared_bytes)),
            ("Swap total", _format_bytes(memory.swap_total_bytes)),
            ("Swap used", _format_bytes(memory.swap_used_bytes)),
            ("Swap free", _format_bytes(memory.swap_free_bytes)),
            ("Swap usage", f"{memory.swap_usage_percent:.1f}%"),
        ],
    )


def _render_storage(snapshot: SystemSnapshot) -> str:
    """Render storage devices and filesystems."""

    lines = ["STORAGE", "-" * 72]

    if not snapshot.storage_devices:
        lines.append("No storage devices detected.")
        return "\n".join(lines)

    for device in snapshot.storage_devices:
        lines.append(
            f"{device.path} | {device.media_type} | {_format_bytes(device.capacity_bytes)}"
        )
        lines.append(
            f"  Model: {_optional(device.model)} | "
            f"Connection: {_optional(device.connection)} | "
            f"Read-only: {_yes_no(device.read_only)}"
        )

        if not device.partitions:
            lines.append("  Partitions: none detected")
            continue

        for partition in device.partitions:
            usage = (
                f"{partition.usage_percent:.1f}%"
                if partition.usage_percent is not None
                else "unknown"
            )

            lines.append(
                f"  {partition.path} -> "
                f"{_optional(partition.mount_point)} | "
                f"{_optional(partition.filesystem)} | "
                f"usage {usage}"
            )

    return "\n".join(lines)


def _render_gpus(snapshot: SystemSnapshot) -> str:
    """Render graphics and compute accelerators."""

    lines = ["GPU / ACCELERATORS", "-" * 72]

    if not snapshot.gpus:
        lines.append("No GPU or compute accelerator detected.")
        return "\n".join(lines)

    for gpu in snapshot.gpus:
        lines.append(f"{gpu.vendor}: {gpu.model}")
        lines.append(f"  Driver: {_optional(gpu.driver)} | Bus: {_optional(gpu.bus_id)}")

        runtime_values: list[str] = []

        if gpu.memory_bytes is not None:
            runtime_values.append(f"memory {_format_bytes(gpu.memory_bytes)}")

        if gpu.usage_percent is not None:
            runtime_values.append(f"usage {gpu.usage_percent:.1f}%")

        if gpu.temperature_celsius is not None:
            runtime_values.append(f"temperature {gpu.temperature_celsius:.1f} C")

        if runtime_values:
            lines.append(f"  Runtime: {', '.join(runtime_values)}")

    return "\n".join(lines)


def _render_thermal(snapshot: SystemSnapshot) -> str:
    """Render temperature sensors."""

    lines = ["THERMAL", "-" * 72]

    if not snapshot.thermal_sensors:
        lines.append("No readable thermal sensors detected.")
        return "\n".join(lines)

    for sensor in snapshot.thermal_sensors:
        limits: list[str] = []

        if sensor.high_celsius is not None:
            limits.append(f"high {sensor.high_celsius:.1f} C")

        if sensor.critical_celsius is not None:
            limits.append(f"critical {sensor.critical_celsius:.1f} C")

        limit_text = f" | {', '.join(limits)}" if limits else ""

        lines.append(f"{sensor.name}: {sensor.temperature_celsius:.1f} C{limit_text}")

    return "\n".join(lines)


def _render_power(snapshot: SystemSnapshot) -> str:
    """Render power-source information."""

    power = snapshot.power

    rows = [
        ("Source", power.source),
        ("Battery present", _yes_no(power.battery_present)),
        (
            "Battery level",
            (f"{power.battery_percent:.1f}%" if power.battery_percent is not None else None),
        ),
        (
            "Charging",
            (_yes_no(power.charging) if power.charging is not None else None),
        ),
        (
            "Time remaining",
            (
                _format_duration(power.seconds_remaining)
                if power.seconds_remaining is not None
                else None
            ),
        ),
    ]

    for key, value in power.details.items():
        rows.append((key.replace("_", " ").title(), str(value)))

    return _section("POWER", rows)


def _render_network(snapshot: SystemSnapshot) -> str:
    """Render interfaces and IPv4 routing information."""

    network = snapshot.network

    lines = [
        "NETWORK",
        "-" * 72,
        f"Default interface: {_optional(network.default_interface)}",
        f"Default gateway:   {_optional(network.default_gateway)}",
        f"DNS servers:       {', '.join(network.dns_servers) or 'none'}",
        (f"Internet route:    {_yes_no(network.internet_route_available)}"),
    ]

    if not network.interfaces:
        lines.append("Interfaces:         none detected")
        return "\n".join(lines)

    lines.append("Interfaces:")

    for interface in network.interfaces:
        labels: list[str] = []

        if interface.is_default_route:
            labels.append("default")

        if interface.is_virtual:
            labels.append("virtual")

        if interface.is_loopback:
            labels.append("loopback")

        label_text = f" [{', '.join(labels)}]" if labels else ""

        lines.append(
            f"  {interface.name}: {interface.state} | {interface.interface_type}{label_text}"
        )
        lines.append(f"    IPv4: {', '.join(interface.ipv4_addresses) or 'none'}")
        lines.append(
            f"    MAC: {_optional(interface.mac_address)} | "
            f"Driver: {_optional(interface.driver)} | "
            f"MTU: {_optional_number(interface.mtu)}"
        )

    return "\n".join(lines)


def _render_components(snapshot: SystemSnapshot) -> str:
    """Render additional component inventory."""

    lines = ["COMPONENT INVENTORY", "-" * 72]

    if not snapshot.components:
        lines.append("No additional components recorded.")
        return "\n".join(lines)

    for component in snapshot.components:
        data = component.to_dict()
        name = data.get("name", "unnamed component")
        category = data.get("category", "unknown")

        lines.append(f"{name} | {category}")

    return "\n".join(lines)


def _render_findings(snapshot: SystemSnapshot) -> str:
    """Render diagnostic findings."""

    lines = ["FINDINGS", "-" * 72]

    if not snapshot.findings:
        lines.append("No findings generated by passive inspection.")
        return "\n".join(lines)

    for index, finding in enumerate(snapshot.findings, start=1):
        data = finding.to_dict()
        severity = data.get("severity", "unknown")
        title = data.get("title", "Untitled finding")
        message = data.get("message", "")

        lines.append(f"{index}. [{str(severity).upper()}] {title}")

        if message:
            lines.append(f"   {message}")

    return "\n".join(lines)


def _render_saved_reports(paths: ReportPaths) -> str:
    """Render paths to generated report files."""

    return "\n".join(
        [
            "REPORTS SAVED",
            "-" * 72,
            f"JSON snapshot:  {paths.snapshot}",
            f"Text report:    {paths.text_report}",
            f"HTML report:    {paths.html_report}",
            f"Inspection log: {paths.diagnostic_log}",
        ]
    )


def _section(
    title: str,
    rows: list[tuple[str, str | None]],
) -> str:
    """Render a simple aligned section."""

    lines = [title, "-" * 72]

    for label, value in rows:
        lines.append(f"{label:<20} {_optional(value)}")

    return "\n".join(lines)


def _optional(value: object) -> str:
    """Render absent values consistently."""

    if value is None:
        return "unknown"

    text = str(value).strip()

    return text or "unknown"


def _optional_number(value: int | None) -> str:
    """Render an optional integer."""

    return str(value) if value is not None else "unknown"


def _yes_no(value: bool) -> str:
    """Render a boolean as yes or no."""

    return "yes" if value else "no"


def _format_frequency(value: float | None) -> str:
    """Render a frequency in MHz or GHz."""

    if value is None:
        return "unknown"

    if value >= 1000:
        return f"{value / 1000:.2f} GHz"

    return f"{value:.0f} MHz"


def _format_bytes(value: int) -> str:
    """Render a byte count using binary units."""

    size = float(value)

    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:.1f} {unit}"

        size /= 1024

    return f"{size:.1f} PiB"


def _format_duration(seconds: float) -> str:
    """Render seconds as days, hours, minutes, and seconds."""

    total_seconds = max(0, int(seconds))
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, remaining_seconds = divmod(remainder, 60)

    values: list[str] = []

    if days:
        values.append(f"{days}d")

    if hours or days:
        values.append(f"{hours}h")

    if minutes or hours or days:
        values.append(f"{minutes}m")

    values.append(f"{remaining_seconds}s")

    return " ".join(values)


def main() -> None:
    """Run the Screwdriver CLI."""

    app()


if __name__ == "__main__":
    main()
