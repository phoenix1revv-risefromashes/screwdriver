"""Save Screwdriver inspection results as JSON, text, HTML, and log files."""

from __future__ import annotations

import hashlib
import html
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from screwdriver import __version__
from screwdriver.models import Component, SystemSnapshot
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
    while (
        (report_root / "local" / scan_id).exists() and not allow_existing_local
    ) or (report_root / "agentic" / scan_id).exists():
        scan_id = f"{base_id}_{suffix:02d}"
        suffix += 1

    return ReportRun(
        scan_id=scan_id,
        root=report_root,
        local_directory=report_root / "local" / scan_id,
        agentic_directory=report_root / "agentic" / scan_id,
    )


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
    """Build the detailed HTML inspection report."""

    title = html.escape(f"Screwdriver report — {snapshot.identity.hostname}")
    content = html.escape(report)
    usb_details = _build_usb_details(snapshot)
    serial_details = _build_serial_details(snapshot)
    inventory_details = _build_inventory_details(snapshot)
    robotics_stack_details = _build_robotics_stack_details(snapshot)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}

    body {{
      margin: 0;
      background: #0b1020;
      color: #e8edf7;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    }}

    main {{
      max-width: 1040px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}

    pre {{
      margin: 0;
      padding: 24px;
      overflow-x: auto;
      white-space: pre-wrap;
      background: #11182b;
      border: 1px solid #26314d;
      border-radius: 14px;
      box-shadow: 0 18px 50px #0006;
      line-height: 1.45;
    }}

    section {{
      margin-top: 28px;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      background: #11182b;
    }}

    th,
    td {{
      padding: 10px 12px;
      border: 1px solid #26314d;
      text-align: left;
    }}

    th {{
      background: #18223a;
    }}
  </style>
</head>
<body>
  <main>
    <pre>{content}</pre>
    {usb_details}
    {serial_details}
    {robotics_stack_details}
    {inventory_details}
  </main>
</body>
</html>
"""


def _build_usb_details(snapshot: SystemSnapshot) -> str:
    """Render detailed USB device-node evidence for HTML only."""

    rows: list[str] = []

    for device in snapshot.usb_devices:
        for node in device.device_nodes:
            owner = ":".join(value or "unknown" for value in (node.owner, node.group))

            values = (
                device.display_name,
                device.usb_id,
                node.path,
                node.node_type,
                node.permissions,
                owner,
                node.access,
            )

            cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)

            rows.append(f"<tr>{cells}</tr>")

    if not rows:
        return ""

    body = "".join(rows)

    return f"""
<section>
  <h2>USB device-node details</h2>
  <table>
    <thead>
      <tr>
        <th>Device</th>
        <th>USB ID</th>
        <th>Path</th>
        <th>Type</th>
        <th>Permissions</th>
        <th>Owner</th>
        <th>Current access</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</section>
"""


def _build_serial_details(snapshot: SystemSnapshot) -> str:
    """Render detailed serial identity and access evidence for HTML."""

    rows: list[str] = []

    for device in snapshot.serial_devices:
        node = device.device_node
        values = (
            device.display_name,
            device.port,
            device.transport,
            device.driver or "unbound",
            device.usb_id or "not USB",
            device.stable_id_path or "not available",
            node.permissions if node else "missing",
            node.access if node else "missing",
        )
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
        rows.append(f"<tr>{cells}</tr>")

    if not rows:
        return ""

    body = "".join(rows)

    return f"""
<section>
  <h2>Serial / TTY details</h2>
  <table>
    <thead>
      <tr>
        <th>Device</th>
        <th>Port</th>
        <th>Transport</th>
        <th>Driver</th>
        <th>USB ID</th>
        <th>Stable by-id path</th>
        <th>Permissions</th>
        <th>Current access</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</section>
"""


def _build_inventory_details(snapshot: SystemSnapshot) -> str:
    """Render inventory tables grouped by physical and ROS 2 responsibility."""

    ros_categories = (
        ("ROS 2 nodes", "ROS node"),
        ("ROS 2 topics", "ROS topic"),
        ("ROS 2 services", "ROS service"),
        ("ROS 2 actions", "ROS action"),
        ("ROS 2 control hardware interfaces", "ros2_control hardware"),
    )
    physical_sensors = [
        component
        for component in snapshot.sensor_inventory
        if not _is_ros_inventory_component(component)
    ]
    physical_actuators = [
        component
        for component in snapshot.actuator_inventory
        if not _is_ros_inventory_component(component)
    ]

    sections: list[str] = []
    overview = next(
        (
            component
            for component in snapshot.ros_runtime_inventory
            if component.category == "ROS runtime"
        ),
        None,
    )
    if overview is not None:
        sections.append(_build_ros_overview_table(overview))

    groups = [
        ("Physical sensor inventory", physical_sensors),
        ("Physical actuator / control inventory", physical_actuators),
        *[
            (
                title,
                [
                    component
                    for component in snapshot.ros_runtime_inventory
                    if component.category == category
                ],
            )
            for title, category in ros_categories
        ],
        *[
            (
                title,
                [
                    component
                    for component in snapshot.ros_device_inventory
                    if component.details.get("device_class") == device_class
                ],
            )
            for title, device_class in (
                ("ROS 2 sensor / input devices", "sensor / input"),
                ("ROS 2 audio devices", "audio"),
                ("ROS 2 displays / HMI", "display / HMI"),
                ("ROS 2 actuators / output devices", "actuator / output"),
                (
                    "ROS 2 controllers / hardware interfaces",
                    "controller / interface",
                ),
                ("ROS 2 power devices", "power"),
                ("ROS 2 communication devices", "communication"),
                ("ROS 2 I/O / lighting devices", "I/O / lighting"),
                ("ROS 2 other hardware devices", "other hardware"),
            )
        ],
    ]

    for title, components in groups:
        table = _build_component_table(title, components)
        if table:
            sections.append(table)

    return "".join(sections)


def _build_robotics_stack_details(snapshot: SystemSnapshot) -> str:
    """Render the local robotics-stack summary with operational-stage semantics."""

    if not snapshot.software_stack_inventory:
        return ""
    rows: list[str] = []
    for component in snapshot.software_stack_inventory:
        details = component.details
        values = (
            component.name,
            details.get("stack_category") or component.category,
            details.get("version"),
            _html_bool(details.get("installed")),
            _html_bool(details.get("configured"), unknown="Not evaluated"),
            _html_bool(details.get("running")),
            _html_bool(details.get("connected"), unknown="Not evaluated"),
            _html_bool(details.get("integrated")),
            details.get("capability"),
            details.get("capability_state"),
            details.get("state") or component.status.value,
        )
        cells = "".join(f"<td>{html.escape(_html_value(value))}</td>" for value in values)
        rows.append(f"<tr>{cells}</tr>")
    return f"""
<section id="robotics-software-stacks">
  <h2>Robotics software stacks</h2>
  <p>Package presence alone is not proof that a stack is configured, running, or integrated.</p>
  <table>
    <thead><tr>
      <th>Stack</th><th>Category</th><th>Version</th><th>Installed</th>
      <th>Configured</th><th>Running</th><th>Connected</th><th>Integrated</th>
      <th>Capability</th><th>Capability state</th><th>Operational stage</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
"""


def _html_bool(value: object, *, unknown: str = "No") -> str:
    if value is None:
        return unknown
    return "Yes" if bool(value) else "No"


def _build_component_table(title: str, components: list[Component]) -> str:
    """Build one detailed component table, omitting empty groups."""

    if not components:
        return ""

    rows: list[str] = []
    for component in components:
        details = component.details
        values = (
            component.name,
            component.status.value,
            details.get("state"),
            details.get("device_class"),
            details.get("kind"),
            details.get("direction"),
            details.get("source"),
            details.get("bus"),
            details.get("topics") or details.get("channel"),
            details.get("driver"),
            details.get("ros_node") or details.get("hardware_node"),
            details.get("ros_endpoint"),
            details.get("message_types") or details.get("message_type") or details.get("type"),
            details.get("health"),
        )
        cells = "".join(f"<td>{html.escape(_html_value(item))}</td>" for item in values)
        rows.append(f"<tr>{cells}</tr>")

    return f"""
<section>
  <h2>{html.escape(title)}</h2>
  <table>
    <thead>
      <tr>
        <th>Name</th>
        <th>Status</th>
        <th>State</th>
        <th>Device class</th>
        <th>Kind</th>
        <th>Direction</th>
        <th>Source</th>
        <th>Bus</th>
        <th>Channel</th>
        <th>Driver</th>
        <th>ROS node</th>
        <th>ROS endpoint</th>
        <th>Message type</th>
        <th>Health</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</section>
"""


def _build_ros_overview_table(component: Component) -> str:
    """Build a compact ROS graph overview before the detailed graph tables."""

    details = component.details
    properties = (
        ("Graph state", details.get("state")),
        ("ROS distribution", details.get("ros_distro")),
        ("Domain ID", details.get("domain_id")),
        ("DDS middleware", details.get("middleware")),
        ("Discovery mode", details.get("discovery_mode")),
        ("Environment recovered", details.get("environment_recovered")),
        ("Nodes", details.get("nodes")),
        ("Topics", details.get("topics")),
        ("Services", details.get("services")),
        ("Actions", details.get("actions")),
        ("Probe", details.get("probe")),
    )
    rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(_html_value(value))}</td></tr>"
        for label, value in properties
    )
    return f"""
<section>
  <h2>ROS 2 overview</h2>
  <table>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _is_ros_inventory_component(component: Component) -> bool:
    details = component.details
    source = str(details.get("source") or "")
    return source.startswith("ROS 2") or details.get("state") == "IN_USE_BY_ROS"


def _html_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)
