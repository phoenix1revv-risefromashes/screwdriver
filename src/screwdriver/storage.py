"""Save Screwdriver inspection results as JSON, text, HTML, and log files."""

from __future__ import annotations

import hashlib
import html
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from screwdriver import __version__
from screwdriver.models import Component, ComponentStatus, SerialDevice, SystemSnapshot
from screwdriver.report_time import report_isoformat, to_report_timezone


@dataclass(frozen=True, slots=True)
class ReportPaths:
    """Hold paths to all files created for one inspection."""

    snapshot: Path
    text_report: Path
    html_report: Path
    diagnostic_log: Path


@dataclass(frozen=True, slots=True)
class ReportRun:
    """Directory contract shared by local and agentic output from one scan."""

    scan_id: str
    root: Path
    local_directory: Path
    agentic_directory: Path


def create_report_run(
    report_root: Path,
    *,
    created_at: datetime | None = None,
    requested_scan_id: str | None = None,
    allow_existing_local: bool = False,
) -> ReportRun:
    """Reserve a non-overwriting timestamp directory for one report run."""

    instant = created_at or datetime.now(UTC)
    base_id = requested_scan_id or to_report_timezone(instant).strftime("%Y-%m-%d_%H:%M:%S")
    scan_id = base_id
    suffix = 1
    while ((report_root / "local" / scan_id).exists() and not allow_existing_local) or (
        report_root / "agentic" / scan_id
    ).exists():
        scan_id = f"{base_id}_{suffix:02d}"
        suffix += 1

    return ReportRun(
        scan_id=scan_id,
        root=report_root,
        local_directory=report_root / "local" / scan_id,
        agentic_directory=report_root / "agentic" / scan_id,
    )


def create_custom_report_directory(
    report_root: Path,
    *,
    created_at: datetime | None = None,
) -> Path:
    """Choose a unique custom-analysis run path, separate from native reports.

    No directories are created here: a failed provider request must not replace
    the previous successful latest report.
    """
    instant = created_at or datetime.now(UTC)
    base_id = to_report_timezone(instant).strftime("%Y-%m-%d_%H:%M:%S")
    custom_root = report_root / "custom"
    candidate = custom_root / base_id
    suffix = 1
    while candidate.exists():
        candidate = custom_root / f"{base_id}_{suffix:02d}"
        suffix += 1
    return candidate


def save_reports(
    snapshot: SystemSnapshot,
    terminal_report: str,
    output_directory: Path,
    *,
    scan_id: str | None = None,
    duration_seconds: float | None = None,
) -> ReportPaths:
    """Persist all reports without changing any inspected system state."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths = build_report_paths(output_directory)

    snapshot_payload = (json.dumps(snapshot.to_dict(), indent=2) + "\n").encode("utf-8")
    snapshot_fingerprint = hashlib.sha256(snapshot_payload).hexdigest()
    resolved_scan_id = scan_id or output_directory.name
    enriched_report = "\n".join(
        [
            terminal_report,
            "",
            "PROVENANCE",
            "─" * 72,
            f"Scan ID:          {resolved_scan_id}",
            f"Snapshot SHA-256: {snapshot_fingerprint}",
            f"Schema version:   {snapshot.schema_version}",
            f"Screwdriver:      {__version__}",
        ]
    )

    paths.snapshot.write_bytes(snapshot_payload)

    paths.text_report.write_text(
        enriched_report + "\n",
        encoding="utf-8",
    )

    paths.html_report.write_text(
        _build_html_report(snapshot, enriched_report),
        encoding="utf-8",
    )

    paths.diagnostic_log.write_text(
        "\n".join(
            [
                f"created_at={report_isoformat(snapshot.created_at)}",
                f"hostname={snapshot.identity.hostname}",
                f"schema_version={snapshot.schema_version}",
                f"usb_devices={len(snapshot.usb_devices)}",
                f"serial_devices={len(snapshot.serial_devices)}",
                f"display_units={len(snapshot.display_inventory)}",
                f"hardware_bus_items={len(snapshot.hardware_bus_inventory)}",
                f"software_stacks={len(snapshot.software_stack_inventory)}",
                f"sensors={len(snapshot.sensor_inventory)}",
                f"actuators={len(snapshot.actuator_inventory)}",
                f"ros_devices={len(snapshot.ros_device_inventory)}",
                f"ros_runtime_items={len(snapshot.ros_runtime_inventory)}",
                f"findings={len(snapshot.findings)}",
                "inspection_mode=passive",
                "state_changed=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (output_directory / "report-manifest.json").write_text(
        json.dumps(
            {
                "report_kind": "local",
                "scan_id": resolved_scan_id,
                "created_at": report_isoformat(snapshot.created_at),
                "schema_version": snapshot.schema_version,
                "screwdriver_version": __version__,
                "hostname": snapshot.identity.hostname,
                "collection_duration_seconds": duration_seconds,
                "snapshot_sha256": snapshot_fingerprint,
                "artifacts": [
                    paths.snapshot.name,
                    paths.text_report.name,
                    paths.html_report.name,
                    paths.diagnostic_log.name,
                ],
                "inspection_mode": "passive",
                "state_changed": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    update_latest_reference(output_directory)

    return paths


def update_latest_reference(run_directory: Path) -> None:
    """Atomically point a report type's ``latest`` symlink at a completed scan."""

    parent = run_directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    latest = parent / "latest"
    temporary = parent / f".latest-{os.getpid()}-{run_directory.name}"
    try:
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(run_directory.name, target_is_directory=True)
        os.replace(temporary, latest)
    finally:
        temporary.unlink(missing_ok=True)


def build_report_paths(output_directory: Path) -> ReportPaths:
    """Return the deterministic paths used for one inspection report set."""

    return ReportPaths(
        snapshot=output_directory / "snapshot.json",
        text_report=output_directory / "report.txt",
        html_report=output_directory / "report.html",
        diagnostic_log=output_directory / "inspection.log",
    )


def _build_html_report(
    snapshot: SystemSnapshot,
    report: str,
) -> str:
    """Build a classic, deeply structured HTML inspection report."""

    title = html.escape(f"Screwdriver report — {snapshot.identity.hostname}")
    header, text_sections = _split_text_report(report)
    core = _build_core_system_specs(snapshot, text_sections)
    connectivity = _build_connectivity(snapshot)
    hardware = _build_hardware_inventory(snapshot)
    stacks = _build_robotics_stack_tables(snapshot)
    ros = _build_ros_tables(snapshot)
    diagnostics = _build_diagnostics(snapshot)
    report_info = _build_report_and_provenance(text_sections)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --paper: #0a0a0a;
      --ink: #f1f1f1;
      --muted: #b0b0b0;
      --line: #6a6a6a;
      --soft-line: #3f3f3f;
      --fill: #171717;
      --fill-2: #111111;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Courier New", Courier, ui-monospace, monospace;
      font-size: 14px;
      line-height: 1.45;
    }}

    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 22px 64px;
    }}

    .report-header {{
      margin: 0 0 26px;
      padding: 0;
      overflow-x: auto;
      white-space: pre;
      background: transparent;
      border: 0;
      color: var(--ink);
      font: inherit;
      line-height: 1.45;
    }}

    details.main-section {{
      margin: 0 0 14px;
      border: 1px solid var(--line);
      background: transparent;
    }}

    details.main-section > summary {{
      cursor: pointer;
      padding: 11px 13px;
      background: var(--fill);
      border-bottom: 0;
      font-weight: 700;
      letter-spacing: .02em;
      user-select: none;
    }}

    details.main-section[open] > summary {{
      border-bottom: 1px solid var(--line);
    }}

    .section-body {{ padding: 18px 16px 22px; }}

    .subsection {{ margin: 0 0 26px; }}
    .subsection:last-child {{ margin-bottom: 0; }}

    h2,
    h3,
    h4 {{
      margin: 0;
      font: inherit;
      font-weight: 700;
    }}

    h3 {{
      margin-bottom: 8px;
      padding-bottom: 5px;
      border-bottom: 1px solid var(--soft-line);
    }}

    h4 {{ margin: 14px 0 7px; }}

    p {{ margin: 7px 0; }}
    .note {{ color: var(--muted); }}

    .classic-text {{
      margin: 0;
      padding: 0;
      overflow-x: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: transparent;
      border: 0;
      color: var(--ink);
      font: inherit;
    }}

    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      margin: 8px 0 18px;
    }}

    table {{
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
      background: transparent;
    }}

    th,
    td {{
      padding: 7px 9px;
      border: 1px solid var(--soft-line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}

    th {{
      background: var(--fill-2);
      font-weight: 700;
      white-space: nowrap;
    }}

    .kv {{ min-width: 520px; width: auto; }}
    .kv th {{ width: 220px; }}

    .path-list {{ line-height: 1.55; }}
    .nowrap {{ white-space: nowrap; }}

    .section-empty {{
      margin: 8px 0 0;
      color: var(--muted);
    }}

    footer {{
      margin-top: 28px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      color: var(--muted);
    }}

    @media (max-width: 760px) {{
      main {{ padding: 18px 10px 42px; }}
      .section-body {{ padding: 14px 10px 18px; }}
      body {{ font-size: 13px; }}
    }}

    @media print {{
      body {{ background: white; }}
      main {{ max-width: none; padding: 0; }}
      details.main-section {{ break-inside: avoid; }}
      details.main-section > summary {{ background: #eee; }}
    }}
  </style>
</head>
<body>
  <main>
    <pre class="report-header">{html.escape(header)}</pre>
    {_main_section("1. CORE SYSTEM SPECS", core, opened=True)}
    {_main_section("2. CONNECTIVITY", connectivity)}
    {_main_section("3. HARDWARE INVENTORY", hardware)}
    {_main_section("4. ROS 2", ros)}
    {_main_section("5. ROBOTICS SOFTWARE STACKS", stacks)}
    {_main_section("6. DIAGNOSTICS", diagnostics)}
    {_main_section("7. REPORT &amp; PROVENANCE", report_info)}
    <footer>
      Screwdriver {html.escape(__version__)} · Passive inspection · No device state changed
    </footer>
  </main>
</body>
</html>
"""


def _split_text_report(report: str) -> tuple[str, dict[str, str]]:
    """Split the original terminal report without changing its section content."""

    lines = report.splitlines()
    headings: list[tuple[int, str]] = []
    for index in range(len(lines) - 1):
        underline = lines[index + 1]
        if (
            lines[index]
            and lines[index] == lines[index].upper()
            and len(underline) >= 20
            and set(underline) <= {"─", "-", "="}
        ):
            headings.append((index, lines[index]))

    if not headings:
        return report, {}

    header = "\n".join(lines[: headings[0][0]]).rstrip()
    sections: dict[str, str] = {}
    for position, (index, heading) in enumerate(headings):
        next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = "\n".join(lines[index + 2 : next_index]).strip("\n")
        sections[heading] = body
    return header, sections


def _main_section(title: str, body: str, *, opened: bool = False) -> str:
    open_attribute = " open" if opened else ""
    return (
        f'<details class="main-section"{open_attribute}>'
        f"<summary>{title}</summary>"
        f'<div class="section-body">{body}</div>'
        "</details>"
    )


def _classic_subsection(title: str, body: str) -> str:
    if not body:
        return ""
    return (
        '<section class="subsection">'
        f"<h3>{html.escape(title)}</h3>"
        f'<pre class="classic-text">{html.escape(body)}</pre>'
        "</section>"
    )


def _build_core_system_specs(
    snapshot: SystemSnapshot,
    sections: dict[str, str],
) -> str:
    parts: list[str] = []
    for heading in (
        "HOST IDENTITY",
        "OPERATING SYSTEM",
        "PLATFORM",
    ):
        parts.append(_classic_subsection(heading, sections.get(heading, "")))

    for heading, body in sections.items():
        if heading.startswith("PLATFORM-SPECIFIC DETAILS"):
            parts.append(_classic_subsection(heading, body))

    for heading in ("CPU", "MEMORY"):
        parts.append(_classic_subsection(heading, sections.get(heading, "")))

    parts.append(_build_storage_tables(snapshot))
    parts.append(_build_gpu_table(snapshot))
    parts.append(_build_thermal_table(snapshot))
    parts.append(_classic_subsection("POWER", sections.get("POWER", "")))
    return "".join(part for part in parts if part)


def _build_storage_tables(snapshot: SystemSnapshot) -> str:
    if not snapshot.storage_devices:
        return _empty_subsection("STORAGE DEVICES", "No storage devices were reported.")

    device_rows: list[list[object]] = []
    partition_rows: list[list[object]] = []
    for device in snapshot.storage_devices:
        device_rows.append(
            [
                device.path,
                device.model,
                device.connection,
                device.media_type,
                _human_bytes(device.capacity_bytes),
                device.firmware_version,
                _yes_no_html(device.removable),
                _yes_no_html(device.read_only),
                "available in snapshot.json" if device.serial_number else "not reported",
            ]
        )
        for partition in device.partitions:
            partition_rows.append(
                [
                    device.path,
                    partition.path,
                    partition.filesystem,
                    partition.mount_point or "not mounted",
                    _human_optional_bytes(partition.total_bytes),
                    _human_optional_bytes(partition.used_bytes),
                    _human_optional_bytes(partition.available_bytes),
                    (
                        f"{partition.usage_percent:.1f}%"
                        if partition.usage_percent is not None
                        else "unavailable"
                    ),
                    _yes_no_html(partition.read_only),
                ]
            )

    body = _table(
        [
            "Device",
            "Model",
            "Connection",
            "Media type",
            "Capacity",
            "Firmware",
            "Removable",
            "Read-only",
            "Serial",
        ],
        device_rows,
    )
    if partition_rows:
        body += "<h4>FILESYSTEMS / PARTITIONS</h4>"
        body += _table(
            [
                "Device",
                "Partition",
                "Filesystem",
                "Mount point",
                "Capacity",
                "Used",
                "Available",
                "Usage",
                "Read-only",
            ],
            partition_rows,
        )
    return _subsection("STORAGE DEVICES", body)


def _build_gpu_table(snapshot: SystemSnapshot) -> str:
    if not snapshot.gpus:
        return _empty_subsection(
            "GRAPHICS AND COMPUTE ACCELERATORS",
            "No GPU or compute accelerator was detected.",
        )
    rows = [
        [
            gpu.vendor,
            gpu.model,
            gpu.driver,
            gpu.bus_id,
            _human_optional_bytes(gpu.memory_bytes),
            f"{gpu.usage_percent:.1f}%" if gpu.usage_percent is not None else None,
            (f"{gpu.temperature_celsius:.1f}°C" if gpu.temperature_celsius is not None else None),
        ]
        for gpu in snapshot.gpus
    ]
    return _subsection(
        "GRAPHICS AND COMPUTE ACCELERATORS",
        _table(
            ["Vendor", "Model", "Driver", "Bus ID", "Memory", "Usage", "Temperature"],
            rows,
        ),
    )


def _build_thermal_table(snapshot: SystemSnapshot) -> str:
    if not snapshot.thermal_sensors:
        return _empty_subsection(
            "THERMAL AND COOLING",
            "No readable thermal sensors were exposed to this user.",
        )
    rows = [
        [
            sensor.name,
            f"{sensor.temperature_celsius:.1f}°C",
            f"{sensor.high_celsius:.1f}°C" if sensor.high_celsius is not None else None,
            (f"{sensor.critical_celsius:.1f}°C" if sensor.critical_celsius is not None else None),
        ]
        for sensor in snapshot.thermal_sensors
    ]
    return _subsection(
        "THERMAL AND COOLING",
        _table(["Sensor", "Temperature", "High", "Critical"], rows),
    )


def _build_connectivity(snapshot: SystemSnapshot) -> str:
    network = snapshot.network
    summary_rows: list[list[object]] = [
        ["Default route", network.default_interface],
        ["Gateway", network.default_gateway],
        ["DNS servers", ", ".join(network.dns_servers) or "none"],
        [
            "Internet route",
            "available" if network.internet_route_available else "not detected",
        ],
    ]
    interface_rows = [
        [
            interface.name,
            interface.interface_type,
            interface.state,
            ", ".join(interface.ipv4_addresses) or "none",
            interface.mac_address,
            interface.mtu,
            (f"{interface.speed_mbps:,} Mb/s" if interface.speed_mbps is not None else None),
            interface.duplex,
            interface.driver,
            _yes_no_html(interface.is_default_route),
            _yes_no_html(interface.is_virtual),
        ]
        for interface in network.interfaces
    ]
    return "".join(
        [
            _subsection("NETWORK SUMMARY", _key_value_table(summary_rows)),
            _subsection(
                "NETWORK INTERFACES",
                _table(
                    [
                        "Interface",
                        "Type",
                        "State",
                        "IPv4",
                        "MAC",
                        "MTU",
                        "Link speed",
                        "Duplex",
                        "Driver",
                        "Default route",
                        "Virtual",
                    ],
                    interface_rows,
                ),
            ),
        ]
    )


def _build_hardware_inventory(snapshot: SystemSnapshot) -> str:
    parts = [
        _build_usb_inventory(snapshot),
        _build_serial_inventory(snapshot),
        _build_display_inventory(snapshot),
    ]
    parts.extend(_build_non_usb_bus_tables(snapshot))
    return "".join(part for part in parts if part)


def _build_usb_inventory(snapshot: SystemSnapshot) -> str:
    if not snapshot.usb_devices:
        return _empty_subsection("USB HARDWARE", "No USB devices were exposed through sysfs.")

    roles = _physical_usb_roles(snapshot)
    rows: list[list[object]] = []
    for device in snapshot.usb_devices:
        role = roles.get(device.usb_id)
        location = (
            f"bus {device.bus_number:03d}, device {device.device_number:03d}"
            if device.bus_number is not None and device.device_number is not None
            else device.sysfs_name
        )
        device_class = (
            f"{device.device_class} ({device.device_class_name})"
            if device.device_class and device.device_class_name
            else device.device_class
        )
        access = ", ".join(sorted({node.access for node in device.device_nodes})) or "—"
        nodes = _line_break_list(node.path for node in device.device_nodes)
        rows.append(
            [
                device.display_name,
                _usb_hardware_type(device, role),
                device.usb_id,
                location,
                device_class,
                ", ".join(device.drivers) or "none bound",
                access,
                nodes,
            ]
        )

    return _subsection(
        "USB HARDWARE",
        '<p class="note">Passive metadata only. Device serial numbers remain in snapshot.json.</p>'
        + _table(
            [
                "Device",
                "Type",
                "USB ID",
                "Location",
                "Class",
                "Drivers",
                "Access",
                "Device nodes",
            ],
            rows,
            raw_columns={7},
        ),
    )


def _build_serial_inventory(snapshot: SystemSnapshot) -> str:
    meaningful = [device for device in snapshot.serial_devices if _serial_is_meaningful(device)]
    note = "Passive metadata only — serial ports were not opened and DTR/RTS were not toggled."

    if not meaningful:
        return _subsection(
            "SERIAL / TTY",
            f'<p class="note">{html.escape(note)}</p>'
            '<p class="section-empty">No verified serial interfaces were recorded.</p>',
        )

    rows: list[list[object]] = []
    for device in meaningful:
        node = device.device_node
        owner = f"{node.owner or 'unknown'}:{node.group or 'unknown'}" if node is not None else "—"
        rows.append(
            [
                device.display_name,
                device.port,
                _serial_hardware_type(snapshot, device),
                _serial_classification(device),
                device.transport,
                device.driver,
                device.usb_id,
                device.stable_id_path,
                device.physical_path,
                node.permissions if node is not None else "missing",
                owner,
                node.access if node is not None else "missing",
            ]
        )

    return _subsection(
        "SERIAL / TTY",
        f'<p class="note">{html.escape(note)}</p>'
        + _table(
            [
                "Device",
                "Port",
                "Type",
                "Classification",
                "Transport",
                "Driver",
                "USB ID",
                "Stable by-id",
                "Physical path",
                "Permissions",
                "Owner",
                "Access",
            ],
            rows,
        ),
    )


def _serial_is_meaningful(device: SerialDevice) -> bool:
    """Return true only when the snapshot carries positive serial-hardware evidence."""

    if device.verification is not None:
        return device.hardware_verified

    # Compatibility with snapshots created before explicit verification was
    # added. USB-backed serial names and stable Linux identities are strong
    # evidence. Platform UART candidates such as ttyTHS/ttyAMA stay in
    # snapshot.json unless the collector explicitly verified the hardware.
    name = Path(device.port).name
    if device.usb_id or device.stable_id_path or device.physical_path:
        return True
    return name.startswith(("ttyUSB", "ttyACM", "ttyXRUSB", "rfcomm"))


def _serial_classification(device: SerialDevice) -> str:
    name = Path(device.port).name
    if device.usb_id or name.startswith(("ttyUSB", "ttyXRUSB")):
        return "USB serial"
    if name.startswith("ttyACM"):
        return "USB CDC/ACM"
    if name.startswith("rfcomm"):
        return "Bluetooth serial"
    if name.startswith("ttyTHS"):
        return "NVIDIA high-speed UART"
    if name.startswith(("ttyAMA", "ttymxc", "ttyO", "ttyMSM")):
        return "Platform UART"
    return "Hardware-backed serial"


def _physical_usb_roles(snapshot: SystemSnapshot) -> dict[str, str]:
    roles: dict[str, str] = {}
    for component in [*snapshot.sensor_inventory, *snapshot.actuator_inventory]:
        if _is_ros_inventory_component(component):
            continue
        details = component.details
        usb_id = details.get("usb_id")
        if usb_id:
            roles[str(usb_id)] = _canonical_hardware_type(details.get("kind") or component.category)
    return roles


def _usb_hardware_type(device: object, role: str | None) -> str:
    if role:
        return role
    text = " ".join(
        str(value)
        for value in (
            getattr(device, "display_name", ""),
            getattr(device, "device_class_name", ""),
            *(getattr(device, "drivers", []) or []),
            *(node.path for node in (getattr(device, "device_nodes", []) or [])),
        )
        if value
    )
    return _infer_hardware_type(text)


def _serial_hardware_type(snapshot: SystemSnapshot, device: SerialDevice) -> str:
    for component in [*snapshot.sensor_inventory, *snapshot.actuator_inventory]:
        if _is_ros_inventory_component(component):
            continue
        details = component.details
        same_channel = details.get("channel") == device.port
        same_usb = bool(device.usb_id and details.get("usb_id") == device.usb_id)
        if same_channel or same_usb:
            return _canonical_hardware_type(details.get("kind") or component.category)
    return _infer_hardware_type(f"{device.display_name} {device.driver or ''} serial")


def _canonical_hardware_type(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "Unknown"
    if "camera" in text:
        return "Camera"
    if "microphone" in text or text == "mic":
        return "Microphone"
    if "speaker" in text or "audio output" in text:
        return "Speaker"
    if "touch" in text:
        return "Touch Input"
    if "display" in text or "screen" in text or "monitor" in text:
        return "Display"
    if "lidar" in text:
        return "LiDAR"
    if "imu" in text or "inertial" in text:
        return "IMU"
    if "gps" in text or "gnss" in text:
        return "GPS"
    if "motor controller" in text:
        return "Motor Controller"
    if "servo" in text or "gripper" in text or "actuator" in text or "drive" in text:
        return "Actuator"
    if "mcu" in text or "microcontroller" in text:
        return "MCU"
    if "sensor" in text or "radar" in text:
        return "Sensor"
    if "system" in text or "controller" in text:
        return "System"
    return value if isinstance(value, str) and value[:1].isupper() else "Unknown"


def _infer_hardware_type(text: str) -> str:
    lowered = text.lower()
    for tokens, kind in (
        (("uvcvideo", "/dev/video", "webcam", "camera"), "Camera"),
        (("microphone", "4-mic", "mic array"), "Microphone"),
        (("speaker", "audio output"), "Speaker"),
        (("touchscreen", "touch screen", "touch input"), "Touch Input"),
        (("lidar", "rplidar"), "LiDAR"),
        (("imu", "inertial"), "IMU"),
        (("gps", "gnss"), "GPS"),
        (("motor controller", "roboclaw", "odrive", "vesc"), "Motor Controller"),
        (("servo", "gripper"), "Actuator"),
        (("microcontroller", "arduino", "teensy", "stm32"), "MCU"),
    ):
        if any(token in lowered for token in tokens):
            return kind
    if any(token in lowered for token in ("keyboard", "mouse", "hub", "serial", "audio", "hid")):
        return "System"
    return "Unknown"


def _build_display_inventory(snapshot: SystemSnapshot) -> str:
    if not snapshot.display_inventory:
        return _empty_subsection("DISPLAY UNITS", "No connected DRM display units were detected.")
    rows = []
    for component in snapshot.display_inventory:
        details = component.details
        identity = (
            " / ".join(
                str(value)
                for value in (details.get("manufacturer"), details.get("product_code"))
                if value
            )
            or "—"
        )
        rows.append(
            [
                component.name,
                "Display",
                details.get("connector"),
                details.get("state"),
                details.get("enabled"),
                details.get("resolution"),
                details.get("driver"),
                identity,
            ]
        )
    return _subsection(
        "DISPLAY UNITS",
        _table(
            [
                "Device",
                "Type",
                "Connector",
                "State",
                "Enabled",
                "Resolution / mode",
                "Driver",
                "EDID identity",
            ],
            rows,
        ),
    )


def _build_non_usb_bus_tables(snapshot: SystemSnapshot) -> list[str]:
    """Render only externally meaningful/robot-relevant non-USB bus records."""

    groups: dict[str, list[Component]] = {}
    components = [
        *snapshot.hardware_bus_inventory,
        *snapshot.sensor_inventory,
        *snapshot.actuator_inventory,
    ]
    for interface in snapshot.network.interfaces:
        if interface.interface_type == "can" and not interface.is_virtual:
            components.append(
                Component(
                    category="hardware interface",
                    name=interface.name,
                    status=ComponentStatus.OK,
                    details={
                        "kind": "System",
                        "bus": "CAN",
                        "channel": interface.name,
                        "driver": interface.driver,
                        "state": interface.state.upper(),
                        "source": "Linux network/sysfs",
                    },
                )
            )

    seen: set[tuple[str, str, str]] = set()
    for component in components:
        if _is_ros_inventory_component(component):
            continue
        bus = str(component.details.get("bus") or "").strip()
        if not bus or bus.upper() in {"USB", "DDS", "ROS 2", "DRM"}:
            continue
        if not _hardware_component_is_report_relevant(component):
            continue
        normalized = _normalize_bus_name(bus)
        channel = str(component.details.get("channel") or "")
        key = (normalized, component.name, channel)
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault(normalized, []).append(component)

    preferred = ["PCI / PCIE", "I²C", "SPI", "GPIO", "CAN", "OTHER HARDWARE"]
    ordered = [name for name in preferred if name in groups]
    ordered.extend(name for name in groups if name not in ordered)

    sections: list[str] = []
    for bus in ordered:
        rows = []
        for component in groups[bus]:
            details = component.details
            identity = _hardware_identity(details)
            rows.append(
                [
                    component.name,
                    _canonical_hardware_type(details.get("kind") or component.category),
                    details.get("channel"),
                    details.get("driver"),
                    details.get("state") or component.status.value.upper(),
                    identity,
                ]
            )
        if not rows:
            continue
        sections.append(
            _subsection(
                bus,
                _table(
                    [
                        "Device",
                        "Type",
                        "Device / Channel",
                        "Driver",
                        "State",
                        "Identity / Details",
                    ],
                    rows,
                ),
            )
        )
    return sections


def _hardware_component_is_report_relevant(component: Component) -> bool:
    """Exclude obvious host/SoC infrastructure while retaining robotics hardware in JSON."""

    details = component.details
    kind = _canonical_hardware_type(details.get("kind") or component.category)
    if kind in {"System", "Unknown", "Display"}:
        return False

    # Adapters/controllers are infrastructure unless another collector classified them
    # as a concrete robot-facing device type above.
    name = component.name.casefold()
    infrastructure_terms = (
        "root complex",
        "host bridge",
        "pci bridge",
        "i2c adapter",
        "i²c adapter",
        "gpio controller",
        "spi controller",
        "tegra",
        "soc",
    )
    return not any(term in name for term in infrastructure_terms)


def _hardware_identity(details: Mapping[str, object]) -> str:
    values: list[str] = []
    vendor = details.get("vendor_id")
    device = details.get("device_id")
    if vendor or device:
        values.append(f"vendor={vendor or '—'}, device={device or '—'}")
    if details.get("class"):
        values.append(f"class={details['class']}")
    if details.get("lines"):
        values.append(f"lines={details['lines']}")
    if details.get("protocol"):
        values.append(f"protocol={details['protocol']}")
    return "; ".join(values) or "—"


def _normalize_bus_name(bus: str) -> str:
    normalized = bus.upper().replace("-", "").replace("_", "").replace(" ", "")
    if normalized in {"I2C", "I²C"}:
        return "I²C"
    if normalized in {"PCIE", "PCI"}:
        return "PCI / PCIE"
    if normalized == "SPI":
        return "SPI"
    if normalized == "GPIO":
        return "GPIO"
    if normalized == "CAN":
        return "CAN"
    return bus.upper()


_STACK_TYPE_ORDER = {
    "Navigation": 10,
    "Localization": 20,
    "SLAM / Mapping": 30,
    "Control": 40,
    "Manipulation": 50,
    "Planning / Behavior": 60,
    "Simulation": 70,
    "Perception / Compute": 80,
    "Visualization": 90,
    "Visualization / TF": 91,
    "Visualization / Telemetry": 92,
    "Embedded / MCU": 100,
    "Teleoperation": 110,
    "Teleoperation / Input": 111,
    "Recording / Playback": 120,
    "Diagnostics": 130,
    "Diagnostics / Visualization": 131,
    "Perception": 140,
    "Camera": 150,
    "Camera / Depth": 151,
    "LiDAR": 160,
    "GNSS": 170,
    "Sensor Processing": 180,
    "Industrial / Fieldbus": 190,
    "Remote / Web Integration": 200,
    "ROS Bridge": 210,
    "Fleet / Multi-Robot": 220,
    "Aerial / Autopilot": 230,
    "Autonomous Driving": 240,
    "Command / Safety": 250,
}


def _build_robotics_stack_tables(snapshot: SystemSnapshot) -> str:
    """Render the full tracked robotics stack catalog as one functional table."""

    catalog = [
        component
        for component in snapshot.software_stack_inventory
        if _software_stack_is_report_visible(component)
    ]
    if not catalog:
        return '<p class="section-empty">No robotics software catalog was recorded.</p>'

    catalog.sort(
        key=lambda component: (
            _STACK_TYPE_ORDER.get(str(component.details.get("stack_category") or ""), 999),
            component.name.casefold(),
        )
    )
    rows: list[list[object]] = []
    for component in catalog:
        details = component.details
        rows.append(
            [
                component.name,
                details.get("stack_category") or "Robotics Software",
                _stack_version_packages(details),
                details.get("state") or component.status.value.upper(),
            ]
        )

    return _table(
        ["Stack", "Type", "Version / Packages", "Operational Stage"],
        rows,
        keep_columns={0, 1, 2, 3},
    )


def _software_stack_is_report_visible(component: Component) -> bool:
    """Return whether a component belongs to the concrete tracked robotics catalog."""

    details = component.details
    original_category = str(details.get("original_category") or "")
    return bool(
        details.get("stack_category")
        and original_category in {"", "robotics software stack", "robotics stack"}
    )


def _stack_version_packages(details: Mapping[str, object]) -> str:
    version = _html_value(details.get("version"))
    packages = _html_value(details.get("detected_packages"))
    values = [value for value in (version, packages) if value not in {"—", "unavailable"}]
    return " · ".join(dict.fromkeys(values)) or "—"


def _build_ros_tables(snapshot: SystemSnapshot) -> str:
    groups = {
        category: [item for item in snapshot.ros_runtime_inventory if item.category == category]
        for category in (
            "ROS runtime",
            "ROS node",
            "ROS topic",
            "ROS service",
            "ROS action",
            "ros2_control hardware",
        )
    }
    parts: list[str] = []
    if groups["ROS runtime"]:
        overview = groups["ROS runtime"][0].details
        parts.append(
            _subsection(
                "ROS 2 OVERVIEW",
                _key_value_table(
                    [
                        ["Graph state", overview.get("state")],
                        ["ROS distribution", overview.get("ros_distro")],
                        ["Domain ID", overview.get("domain_id")],
                        ["DDS middleware", overview.get("middleware")],
                        ["Discovery mode", overview.get("discovery_mode")],
                        [
                            "Environment recovered",
                            _yes_no_html(bool(overview.get("environment_recovered"))),
                        ],
                        ["Nodes", overview.get("nodes")],
                        ["Topics", overview.get("topics")],
                        ["Services", overview.get("services")],
                        ["Actions", overview.get("actions")],
                        ["Probe", overview.get("probe")],
                    ]
                ),
            )
        )
    else:
        parts.append(_empty_subsection("ROS 2 OVERVIEW", "No ROS runtime inventory was recorded."))

    parts.append(
        _ros_runtime_table(
            "ROS 2 NODES",
            groups["ROS node"],
            [
                ("Node", None),
                ("State", "state"),
                ("Publishers", "publishers"),
                ("Subscribers", "subscribers"),
            ],
            keep_columns={0, 1, 2, 3},
        )
    )
    parts.append(
        _ros_runtime_table(
            "ROS 2 TOPICS",
            groups["ROS topic"],
            [
                ("Topic", None),
                ("State", "state"),
                ("Type", "type"),
                ("Publishers", "publishers"),
                ("Subscribers", "subscribers"),
            ],
        )
    )
    parts.append(
        _ros_runtime_table(
            "ROS 2 SERVICES",
            groups["ROS service"],
            [("Service", None), ("State", "state"), ("Type", "type")],
        )
    )
    parts.append(
        _ros_runtime_table(
            "ROS 2 ACTIONS",
            groups["ROS action"],
            [("Action", None), ("State", "state"), ("Type", "type")],
        )
    )

    if snapshot.ros_device_inventory:
        rows = _ros_device_usage_rows(snapshot)
        if rows:
            parts.append(
                _subsection(
                    "ROS 2 DEVICE USAGE",
                    _table(
                        ["ROS Node", "Physical Device", "Type", "Device Path"],
                        rows,
                    ),
                )
            )

    control = groups["ros2_control hardware"]
    if control:
        parts.append(
            _subsection(
                "ROS 2 CONTROL HARDWARE INTERFACES",
                _generic_component_table(control),
            )
        )
    return "".join(part for part in parts if part)


def _ros_device_usage_rows(snapshot: SystemSnapshot) -> list[list[object]]:
    """Map ROS nodes to concrete physical devices without repeating forensic metadata."""

    rows: list[list[object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for component in snapshot.ros_device_inventory:
        details = component.details
        node = str(details.get("ros_node") or "").strip()
        if not node:
            continue
        kind = _canonical_hardware_type(details.get("kind") or details.get("device_class"))
        physical = str(details.get("physical_component") or "").strip()
        path = str(details.get("physical_channel") or "").strip()

        if not physical:
            correlated = _correlate_ros_physical_device(snapshot, kind)
            if correlated is not None:
                physical, correlated_path = correlated
                if not path:
                    path = correlated_path

        if not physical:
            continue
        key = (node, physical, kind, path)
        if key in seen:
            continue
        seen.add(key)
        rows.append([node, physical, kind, path or None])
    return rows


def _correlate_ros_physical_device(
    snapshot: SystemSnapshot,
    kind: str,
) -> tuple[str, str] | None:
    """Return a unique physical-device candidate for a ROS device type when evidence permits."""

    candidates: list[tuple[str, str]] = []

    if kind == "Display":
        for component in snapshot.display_inventory:
            details = component.details
            connector = str(details.get("connector") or "")
            candidates.append((component.name, connector))

    for usb_device in snapshot.usb_devices:
        usb_kind = _usb_hardware_type(usb_device, None)
        audio_match = kind in {"Microphone", "Speaker"} and any(
            "audio" in str(driver).casefold() for driver in usb_device.drivers
        )
        if usb_kind != kind and not audio_match:
            continue
        paths = [node.path for node in usb_device.device_nodes]
        preferred_path = _preferred_device_path(paths, kind)
        candidates.append((usb_device.display_name, preferred_path))

    if kind in {"Actuator", "Motor Controller", "MCU", "Sensor", "IMU", "GPS", "LiDAR"}:
        for serial_device in snapshot.serial_devices:
            if not _serial_is_meaningful(serial_device):
                continue
            if _serial_hardware_type(snapshot, serial_device) != kind:
                continue
            candidates.append((serial_device.display_name, serial_device.port))

    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


def _preferred_device_path(paths: list[str], kind: str) -> str:
    if not paths:
        return ""
    if kind == "Microphone":
        capture = next(
            (path for path in paths if path.startswith("/dev/snd/pcm") and path.endswith("c")),
            None,
        )
        if capture:
            return capture
    if kind == "Speaker":
        playback = next(
            (path for path in paths if path.startswith("/dev/snd/pcm") and path.endswith("p")),
            None,
        )
        if playback:
            return playback
    preferences = {
        "Camera": ("/dev/video",),
        "Microphone": ("/dev/snd/pcm", "/dev/snd/by-id", "/dev/snd/"),
        "Speaker": ("/dev/snd/pcm", "/dev/snd/by-id", "/dev/snd/"),
        "Touch Input": ("/dev/input/by-id", "/dev/input/event"),
    }
    for prefix in preferences.get(kind, ()):
        for path in paths:
            if path.startswith(prefix):
                return path
    return paths[0]


def _ros_runtime_table(
    title: str,
    components: list[Component],
    columns: list[tuple[str, str | None]],
    *,
    keep_columns: set[int] | None = None,
) -> str:
    if not components:
        return ""
    rows = []
    for component in components:
        values: list[object] = []
        for _, key in columns:
            values.append(component.name if key is None else component.details.get(key))
        rows.append(values)
    return _subsection(
        title,
        _table(
            [label for label, _ in columns],
            rows,
            keep_columns=keep_columns,
        ),
    )


def _generic_component_table(components: list[Component]) -> str:
    rows = []
    for component in components:
        details = component.details
        rows.append(
            [
                component.name,
                component.status.value.upper(),
                details.get("state"),
                details.get("kind"),
                details.get("source"),
                details.get("bus"),
                details.get("channel"),
                details.get("driver"),
                details.get("health"),
                details.get("confidence"),
            ]
        )
    return _table(
        [
            "Name",
            "Status",
            "State",
            "Kind",
            "Source",
            "Bus",
            "Channel",
            "Driver",
            "Health",
            "Confidence",
        ],
        rows,
    )


def _build_diagnostics(snapshot: SystemSnapshot) -> str:
    warning_count = sum(finding.severity.value == "warning" for finding in snapshot.findings)
    error_count = sum(finding.severity.value == "error" for finding in snapshot.findings)
    info_count = sum(finding.severity.value == "info" for finding in snapshot.findings)
    overall = (
        "ERRORS DETECTED"
        if error_count
        else "HEALTHY WITH WARNINGS"
        if warning_count
        else "HEALTHY"
    )
    summary = _key_value_table(
        [
            ["Overall status", overall],
            ["Warnings", warning_count],
            ["Errors", error_count],
            ["Informational", info_count],
        ]
    )
    rows = [
        [
            finding.severity.value.upper(),
            finding.code,
            finding.summary,
            finding.evidence,
            finding.recommendation,
        ]
        for finding in snapshot.findings
    ]
    body = _subsection("DIAGNOSTIC SUMMARY", summary)
    if rows:
        body += _subsection(
            "FINDINGS",
            _table(["Severity", "Code", "Finding", "Evidence", "Recommendation"], rows),
        )
    return body


def _build_report_and_provenance(sections: dict[str, str]) -> str:
    return "".join(
        [
            _classic_subsection("REPORTS", sections.get("REPORTS", "")),
            _classic_subsection("PROVENANCE", sections.get("PROVENANCE", "")),
        ]
    )


def _subsection(title: str, body: str) -> str:
    if not body:
        return ""
    return f'<section class="subsection"><h3>{html.escape(title)}</h3>{body}</section>'


def _empty_subsection(title: str, message: str) -> str:
    return _subsection(title, f'<p class="section-empty">{html.escape(message)}</p>')


def _table(
    headers: list[str],
    rows: Sequence[Sequence[object]],
    *,
    raw_columns: set[int] | None = None,
    keep_columns: set[int] | None = None,
) -> str:
    """Render a table while dropping columns that are empty for the entire scan."""

    if not rows:
        return '<p class="section-empty">No records.</p>'
    raw_columns = raw_columns or set()
    keep_columns = keep_columns or set()

    active_columns = [
        index
        for index in range(len(headers))
        if index in keep_columns
        or any(index < len(row) and _table_value_is_meaningful(row[index]) for row in rows)
    ]
    if not active_columns:
        return '<p class="section-empty">No reportable values.</p>'

    header_html = "".join(f"<th>{html.escape(headers[index])}</th>" for index in active_columns)
    row_html: list[str] = []
    for row in rows:
        cells: list[str] = []
        for index in active_columns:
            value = row[index] if index < len(row) else None
            rendered = _html_value(value)
            cell = rendered if index in raw_columns else html.escape(rendered)
            cells.append(f"<td>{cell}</td>")
        row_html.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + "".join(row_html)
        + "</tbody></table></div>"
    )


def _table_value_is_meaningful(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_table_value_is_meaningful(item) for item in value)
    if isinstance(value, str):
        return value.strip().casefold() not in {
            "—",
            "-",
            "unavailable",
            "not reported",
            "n/a",
            "none",
        }
    return True


def _key_value_table(rows: Sequence[Sequence[object]]) -> str:
    row_html = "".join(
        "<tr>"
        f"<th>{html.escape(_html_value(label))}</th>"
        f"<td>{html.escape(_html_value(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return '<div class="table-wrap"><table class="kv"><tbody>' + row_html + "</tbody></table></div>"


def _line_break_list(values: Iterable[object]) -> str:
    items = [str(value) for value in values]
    if not items:
        return "—"
    return '<span class="path-list">' + "<br>".join(html.escape(item) for item in items) + "</span>"


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024.0 or unit == "PiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{value} B"


def _human_optional_bytes(value: int | None) -> str:
    return _human_bytes(value) if value is not None else "unavailable"


def _yes_no_html(value: bool) -> str:
    return "yes" if value else "no"


def _html_bool(value: object, *, unknown: str = "No") -> str:
    if value is None:
        return unknown
    return "Yes" if bool(value) else "No"


def _is_ros_inventory_component(component: Component) -> bool:
    details = component.details
    source = str(details.get("source") or "")
    return source.startswith("ROS 2") or details.get("state") == "IN_USE_BY_ROS"


def _html_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)
