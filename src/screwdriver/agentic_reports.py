"""Structured, readable HTML reports for agentic Screwdriver analysis."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any, cast

from screwdriver import __version__
from screwdriver.report_time import format_report_time

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_ACTIONABLE_CLASSES = {"CONFIRMED_FAILURE", "DEGRADED", "CONFIGURATION_WARNING"}

# Older snapshots did not emit explicit NOT_INSTALLED records for every known
# robotics stack. This catalog keeps their Blueprint coverage complete without
# misclassifying optional, unobserved software as a fault.
_ROBOTICS_STACK_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("Navigation2", "navigation and localization", "autonomous navigation"),
    ("AMCL", "navigation and localization", "localization"),
    ("Robot Localization", "navigation and localization", "state estimation"),
    ("SLAM Toolbox", "SLAM and mapping", "2D mapping"),
    ("Cartographer", "SLAM and mapping", "2D/3D mapping"),
    ("RTAB-Map", "SLAM and mapping", "visual or RGB-D mapping"),
    ("ros2_control", "motion and control", "hardware and motion control"),
    ("MoveIt", "manipulation", "motion planning and manipulation"),
    ("Camera drivers", "perception and AI", "visual perception"),
    ("LiDAR drivers", "perception and AI", "range perception"),
    ("Audio and speech", "speech and interaction", "speech interaction"),
    ("micro-ROS", "MCU and embedded bridges", "embedded controller integration"),
    ("Gazebo ROS integration", "simulation and visualization", "simulation"),
    ("Isaac ROS", "simulation and visualization", "GPU-accelerated perception"),
    ("Webots ROS integration", "simulation and visualization", "simulation"),
    ("RViz", "simulation and visualization", "operator visualization"),
    ("Robot State Publisher", "simulation and visualization", "robot state and TF"),
    ("Teleoperation", "teleoperation", "manual robot control"),
    ("Rosbag", "recording and telemetry", "recording and playback"),
    ("Diagnostics", "recording and telemetry", "health monitoring"),
)


def build_report_context(
    snapshot: dict[str, Any],
    *,
    issues: list[dict[str, Any]],
    summary: str,
    observations: list[str],
    unknowns: list[str],
    agent_integration_chains: list[dict[str, str]],
    provider_status: str,
    provider: str,
    model: str,
    effort: str,
    agentic_status: str,
    report_mode: str,
    generated_at: datetime,
    scan_id: str,
    snapshot_sha256: str,
    collection_duration_seconds: float | None,
    focus: str | None,
) -> dict[str, Any]:
    """Normalize report facts once so every HTML view tells the same story."""

    coverage = _coverage(snapshot)
    checks = _working_checks(snapshot)
    verified_issues = sorted(
        issues, key=lambda issue: _SEVERITY_ORDER.get(str(issue.get("severity")), 9)
    )
    actionable = [
        issue
        for issue in verified_issues
        if str(issue.get("classification")) in _ACTIONABLE_CLASSES
        and str(issue.get("severity")) != "INFO"
    ]
    coverage_incomplete = any(item["state"] != "COLLECTED" for item in coverage)
    if any(str(issue.get("severity")) == "CRITICAL" for issue in actionable):
        overall = "CRITICAL ATTENTION"
        tone = "critical"
    elif any(str(issue.get("severity")) == "HIGH" for issue in actionable):
        overall = "ACTION REQUIRED"
        tone = "high"
    elif actionable:
        overall = "ATTENTION NEEDED"
        tone = "warning"
    elif coverage_incomplete:
        overall = "NO CONFIRMED FAILURE · COVERAGE PARTIAL"
        tone = "partial"
    else:
        overall = "NO CONFIRMED FAILURE IN COLLECTED EVIDENCE"
        tone = "ok"

    priority = _priority_next_check(actionable or verified_issues, unknowns, coverage)
    ros = _ros_overview(snapshot)
    physical = _physical_peripherals(snapshot)
    return {
        "snapshot": snapshot,
        "identity": _mapping(snapshot.get("identity")),
        "os": _mapping(snapshot.get("operating_system")),
        "platform": _mapping(snapshot.get("platform")),
        "cpu": _mapping(snapshot.get("cpu")),
        "memory": _mapping(snapshot.get("memory")),
        "network": _mapping(snapshot.get("network")),
        "ros": ros,
        "physical": physical,
        "issues": verified_issues,
        "actionable": actionable,
        "checks": checks,
        "coverage": coverage,
        "flows": _ros_flows(snapshot),
        "stacks": _records(snapshot.get("software_stack_inventory")),
        "component_matrix": _component_matrix(snapshot),
        "capabilities": _capability_assessments(snapshot),
        "hardware_chains": _hardware_chains(snapshot),
        "inventory_counts": _inventory_counts(snapshot),
        "summary": summary,
        "observations": observations,
        "unknowns": _deduplicate(unknowns),
        "agent_integration_chains": agent_integration_chains,
        "overall": overall,
        "tone": tone,
        "priority": priority,
        "provider_status": provider_status,
        "provider": provider,
        "model": model,
        "effort": effort,
        "agentic_status": agentic_status,
        "report_mode": report_mode,
        "generated_at": format_report_time(generated_at),
        "scan_id": scan_id,
        "snapshot_sha256": snapshot_sha256,
        "duration": _duration(collection_duration_seconds),
        "focus": focus,
        "created_at": _friendly_time(snapshot.get("created_at")),
        "schema_version": snapshot.get("schema_version") or "Not reported",
        "screwdriver_version": __version__,
    }


def render_system_blueprint(context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Render the locked Agentic System Blueprint Report."""

    identity = _mapping(context["identity"])
    hardware_rows = _blueprint_hardware_rows(snapshot)
    software_rows = _blueprint_software_rows(snapshot)
    chain_rows = _blueprint_integration_rows(
        snapshot, cast(list[dict[str, str]], context.get("agent_integration_chains") or [])
    )
    diagnostic_note = _blueprint_diagnostic_note(context)
    missing_software = _notable_missing_software(snapshot)

    body = f"""
{_agentic_header(context, "AGENTIC SYSTEM BLUEPRINT REPORT", "AGENTIC")}
<section id="summary"><h2>1. WHOLE SYSTEM SUMMARY</h2>
  <p>{_h(_whole_system_summary(context, snapshot))}</p>
  <p class="secondary-note">{_h(diagnostic_note)}</p>
</section>
<section id="core-specs"><h2>2. CORE SYSTEM SPECS</h2>
  {_paired_spec_table(_core_system_specs(snapshot))}
</section>
<section id="hardware"><h2>3. HARDWARE COMPONENTS STATUS</h2>
  {_table(["Hardware Component", "Type", "Connected Via", "Driver Bound", "System Role"], hardware_rows)}
</section>
<section id="software"><h2>4. SOFTWARE &amp; RUNTIME STATUS</h2>
  {_table(["Software / Stack", "Type", "Current State", "System Role"], software_rows)}
  <p class="legend"><strong>RUNNING</strong> currently active · <strong>INSTALLED</strong> present but not running · <strong>INACTIVE</strong> explicitly stopped or disabled.</p>
  {f'<p class="secondary-note">{_h(missing_software)}</p>' if missing_software else ""}
</section>
<section id="integration"><h2>5. VERIFIED INTEGRATION CHAINS</h2>
  {_table(["Physical Component", "→ Interface / Driver", "→ OS Interface", "→ Runtime Owner", "→ Endpoint / Consumer", "→ Integration Status"], chain_rows)}
  <p class="legend"><strong>VERIFIED</strong> complete chain established · <strong>PARTIAL</strong> one or more links unproven · <strong>INFERRED</strong> supported by evidence but not directly confirmed.</p>
</section>
"""
    return _classic_agentic_page(
        f"Agentic System Blueprint Report — {identity.get('hostname', 'robot')}", body
    )


def render_diagnostic_report(context: dict[str, Any], probes: list[dict[str, Any]]) -> str:
    """Render the concise, action-oriented Agentic System Diagnostic Report."""

    identity = _mapping(context["identity"])
    snapshot = _mapping(context.get("snapshot"))
    all_issues = cast(list[dict[str, Any]], context["issues"])
    issues = _diagnostic_report_issues(all_issues, snapshot)
    findings_rows = [
        [
            f"D-{index:03d}",
            issue.get("severity") or "INFO",
            issue.get("title") or issue.get("code") or "Unclassified finding",
            issue.get("affected_area") or "System",
            issue.get("diagnosis_status") or "UNRESOLVED",
        ]
        for index, issue in enumerate(issues, 1)
    ]
    rca_html = (
        "".join(_diagnostic_rca(issue, index) for index, issue in enumerate(issues, 1))
        if issues
        else _empty_state("No issues found right now. No root-cause analysis is required.")
    )
    integration_rows = _incomplete_integration_path_rows(context)
    integration_section = (
        '<section id="integration-gaps"><h2>4. INCOMPLETE INTEGRATION PATHS</h2>'
        + _table(
            ["Component", "Proven Up To", "Missing Link", "Why It Matters", "How To Verify"],
            integration_rows,
            raw_columns={4},
        )
        + '<p class="secondary-note">These are evidence gaps, not automatic faults. They become diagnostic findings only when evidence shows the missing integration is causing a real system problem.</p></section>'
        if integration_rows
        else ""
    )
    probe_note = _diagnostic_probe_note(probes)

    body = f"""
{_agentic_header(context, "AGENTIC SYSTEM DIAGNOSTIC REPORT", "AGENTIC")}
<section id="diagnostic-summary"><h2>1. DIAGNOSTIC SUMMARY</h2>
  <p>{_h(_diagnostic_summary(context, issues, len(integration_rows)))}</p>
  {probe_note}
</section>
<section id="prioritized-findings"><h2>2. PRIORITIZED FINDINGS</h2>
  {_table(["ID", "Severity", "Finding", "Affected Area", "Diagnosis"], findings_rows) if findings_rows else _empty_state("No issues found right now.")}
  <p class="legend"><strong>CONFIRMED</strong> directly proven · <strong>PROBABLE</strong> strongest evidence-backed explanation · <strong>PARTIAL</strong> problem proven but cause incomplete · <strong>UNRESOLVED</strong> cause not yet established.</p>
</section>
<section id="root-cause"><h2>3. ROOT-CAUSE ANALYSIS</h2>{rca_html}</section>
{integration_section}
"""
    return _classic_agentic_page(
        f"Agentic System Diagnostic Report — {identity.get('hostname', 'robot')}", body
    )


def _agentic_header(context: dict[str, Any], title: str, report_mode: str) -> str:
    identity = _mapping(context.get("identity"))
    rows = [
        ["Scan ID", context.get("scan_id"), "Generated", context.get("generated_at")],
        ["Target", identity.get("hostname") or "robot", "Report Mode", report_mode],
        ["Screwdriver", context.get("screwdriver_version"), "Probe Safety", "PASSIVE"],
        ["Provider", context.get("provider"), "Model", context.get("model")],
        ["Effort", context.get("effort"), "Scan Duration", context.get("duration")],
        ["Agentic Status", context.get("agentic_status"), "", ""],
    ]
    return f"""
<header class="report-header">
  <div class="brand">SCREWDRIVER</div>
  <h1>{_h(title)}</h1>
</header>
<div class="metadata-table">{_four_column_table(["", "", "", ""], rows, preserve_blanks=True)}</div>
"""


def _whole_system_summary(context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Explain practical compute power, current robot role, headroom, and system condition."""

    candidate = " ".join(str(context.get("summary") or "").split())
    if str(context.get("agentic_status")) == "COMPLETE" and _summary_is_system_focused(
        candidate, snapshot
    ):
        return candidate

    identity = _mapping(snapshot.get("identity"))
    hostname = str(identity.get("hostname") or "This machine")
    compute = _practical_compute_assessment(snapshot)
    role = _current_robot_system_assessment(snapshot)
    headroom = _headroom_assessment(snapshot)
    condition = _system_condition_assessment(snapshot)
    return f"{hostname} {compute} {role} {headroom} {condition}".strip()


def _summary_is_system_focused(value: str, snapshot: dict[str, Any]) -> bool:
    if not value:
        return False
    words = value.split()
    if not 55 <= len(words) <= 190:
        return False
    lowered = value.casefold()
    forbidden = ("/dev/", "ros2 node", "ros2 topic", "ttyusb", "ttyacm")
    if any(token in lowered for token in forbidden):
        return False
    power_terms = ("compute", "cpu", "gpu", "memory", "edge-ai", "edge ai", "capable", "powerful")
    role_terms = ("robot", "robotics", "running as", "currently", "system")
    headroom_terms = (
        "headroom",
        "additional",
        "more workload",
        "can handle",
        "could handle",
        "limit",
        "bottleneck",
    )
    system_terms = (
        "ros 2",
        "camera",
        "vision",
        "audio",
        "speech",
        "navigation",
        "slam",
        "manipulation",
        "serial",
        "can",
        "lidar",
        "display",
        "perception",
    )
    platform = _mapping(snapshot.get("platform"))
    identity_terms = [
        token.casefold()
        for token in re.findall(
            r"[A-Za-z0-9]+",
            str(platform.get("product_name") or platform.get("board_name") or ""),
        )
        if len(token) >= 4
        and token.casefold() not in {"developer", "reference", "engineering", "computer", "system"}
    ]
    identity_grounded = not identity_terms or any(term in lowered for term in identity_terms[:6])
    return (
        identity_grounded
        and any(term in lowered for term in power_terms)
        and any(term in lowered for term in role_terms)
        and any(term in lowered for term in headroom_terms)
        and any(term in lowered for term in system_terms)
    )


def _practical_compute_assessment(snapshot: dict[str, Any]) -> str:
    platform = _mapping(snapshot.get("platform"))
    cpu = _mapping(snapshot.get("cpu"))
    memory = _mapping(snapshot.get("memory"))
    gpus = _records(snapshot.get("gpus"))
    software = _records(snapshot.get("software_stack_inventory"))

    product = str(
        platform.get("product_name") or platform.get("board_name") or "Linux robotics computer"
    )
    cores = int(cpu.get("logical_cpus") or cpu.get("physical_cores") or 0)
    memory_gib = float(memory.get("total_bytes") or 0) / 1024**3
    has_gpu = bool(gpus)
    has_cuda = any("cuda" in str(item.get("name") or "").casefold() for item in software)
    fast_storage = any(
        token
        in " ".join(
            str(device.get(key) or "") for key in ("model", "connection", "media_type")
        ).casefold()
        for device in _records(snapshot.get("storage_devices"))
        for token in ("nvme", "ssd")
    )

    facts: list[str] = [product]
    if cores:
        facts.append(f"{cores} CPU cores")
    if has_gpu:
        facts.append("GPU-accelerated")
    if memory_gib:
        facts.append(f"about {memory_gib:.1f} GiB RAM")
    if fast_storage:
        facts.append("fast solid-state storage")
    fact_text = ", ".join(facts)

    if has_gpu and (has_cuda or "jetson" in product.casefold()):
        workload = (
            "real-time perception, ROS 2, audio/vision processing, and moderate local AI inference"
        )
        level = "a capable edge-AI robotics computer"
    elif has_gpu:
        workload = "ROS 2, perception pipelines, and GPU-assisted robotics workloads"
        level = "a capable robotics computer with hardware acceleration"
    elif cores >= 8 and memory_gib >= 16:
        workload = "multiple ROS 2 services, perception pipelines, planning, and substantial local processing"
        level = "a strong general-purpose robotics computer"
    elif cores >= 4 and memory_gib >= 4:
        workload = "ROS 2, control, sensor processing, and lightweight-to-moderate perception"
        level = "a practical mid-range robotics computer"
    else:
        workload = "control, telemetry, device integration, and lightweight perception"
        level = "a lightweight robotics computer"
    return f"is running on {fact_text}. That makes it {level}. In practical terms it can support {workload} on the robot itself."


def _current_robot_system_assessment(snapshot: dict[str, Any]) -> str:
    running = [
        str(item.get("name") or "")
        for item in _records(snapshot.get("software_stack_inventory"))
        if _mapping(item.get("details")).get("running")
        or str(_mapping(item.get("details")).get("state") or "").upper() == "RUNNING"
    ]
    infrastructure_terms = (
        "docker",
        "cuda",
        "colcon",
        "rosdep",
        "vcstool",
        "rqt",
        "rviz",
        "rosbag",
    )
    running_robot_software = [
        name
        for name in running
        if not any(term in name.casefold() for term in infrastructure_terms)
    ]
    running_text = " ".join(running_robot_software).casefold()

    ros_devices = _records(snapshot.get("ros_device_inventory"))
    active_device_text = " ".join(
        " ".join(
            str(value or "")
            for value in (
                item.get("name"),
                _mapping(item.get("details")).get("kind"),
                _mapping(item.get("details")).get("ros_node"),
                _mapping(item.get("details")).get("topics"),
            )
        )
        for item in ros_devices
        if str(_mapping(item.get("details")).get("state") or "").upper()
        in {"IN_USE_BY_ROS", "RUNNING", "ACTIVE"}
        or _mapping(item.get("details")).get("ros_node")
    ).casefold()

    sensors = _records(snapshot.get("sensor_inventory"))
    displays = _records(snapshot.get("display_inventory"))
    serial = _meaningful_serial_devices(snapshot)
    buses = _records(snapshot.get("hardware_bus_inventory"))
    hardware_text = json.dumps([*sensors, *displays], ensure_ascii=False).casefold()
    ros = _ros_overview(snapshot)
    ros_running = bool(ros and str(ros.get("state") or "").upper() == "RUNNING")

    active_camera = any(token in active_device_text for token in ("camera", "image", "video"))
    active_audio = any(
        token in active_device_text for token in ("microphone", "audio", "speech", "sound")
    )
    active_motion = any(
        token in f"{running_text} {active_device_text}"
        for token in (
            "nav2",
            "navigation",
            "amcl",
            "slam",
            "cmd_vel",
            "moveit",
            "ros2_control",
            "controller",
        )
    )
    has_nav = any(
        token in running_text for token in ("nav2", "navigation", "amcl", "slam", "cartographer")
    )
    has_manip = any(token in running_text for token in ("moveit", "ros2_control", "manip", "arm"))

    if has_nav:
        active_role = "an autonomous/mobile robot runtime"
    elif has_manip:
        active_role = "a manipulation/control robot runtime"
    elif active_camera and active_audio:
        active_role = "an interactive perception robot runtime"
    elif active_camera:
        active_role = "a vision/perception robot runtime"
    elif active_audio:
        active_role = "an audio/interaction robot runtime"
    elif active_motion:
        active_role = "a robot control runtime"
    elif running_robot_software:
        active_role = "a robotics application runtime"
    else:
        active_role = ""

    if active_role and ros_running:
        return f"The machine is currently running as {active_role}, with an active ROS 2 graph and robot-facing runtime evidence visible to the inspection."
    if active_role:
        return f"The machine is currently running as {active_role}; active robot software is visible even though a complete ROS 2 graph is not proven from this scan."

    has_camera = any(token in hardware_text for token in ("camera", "video", "vision"))
    has_audio = any(
        token in hardware_text for token in ("microphone", "audio", "speaker", "speech")
    )
    has_display = bool(displays)
    has_embedded_io = bool(serial) or any(
        token in json.dumps(item, ensure_ascii=False).casefold()
        for item in buses
        for token in ("can", "uart", "serial")
    )
    if has_camera and has_audio and has_display:
        supported_role = "an interactive, perception-oriented robot system"
    elif has_camera or has_audio:
        supported_role = "a perception and interaction robot system"
    elif has_embedded_io:
        supported_role = "a robotics integration and hardware-control system"
    else:
        supported_role = "a general robotics compute and integration system"

    installed_text = " ".join(
        str(item.get("name") or "")
        for item in _records(snapshot.get("software_stack_inventory"))
        if _mapping(item.get("details")).get("installed")
    ).casefold()
    development_markers = sum(
        token in installed_text
        for token in ("colcon", "rosdep", "vcstool", "rqt", "rviz", "docker", "cuda")
    )
    if development_markers >= 3:
        return (
            f"Its connected hardware and installed software are consistent with {supported_role}, but no active "
            "end-to-end robot application is proven. Right now it looks more like a robotics development/integration "
            "host than a fully active robot runtime."
        )
    return (
        f"Its connected hardware and installed software are consistent with {supported_role}, but this inspection "
        "does not yet prove an active end-to-end robot application."
    )


def _headroom_assessment(snapshot: dict[str, Any]) -> str:
    memory = _mapping(snapshot.get("memory"))
    memory_usage = float(memory.get("usage_percent") or 0.0)
    findings = _records(snapshot.get("findings"))
    codes = {
        str(item.get("code") or "").upper()
        for item in findings
        if not _raw_finding_is_inspection_noise(item, snapshot)
    }
    gpus = _records(snapshot.get("gpus"))

    if any(code.startswith(("MEMORY_", "CPU_", "THERMAL_", "POWER_", "GPU_")) for code in codes):
        limits: list[str] = []
        if any(code.startswith("MEMORY_") for code in codes) or memory_usage >= 85:
            limits.append("memory")
        if any(code.startswith("CPU_") for code in codes):
            limits.append("CPU load")
        if any(code.startswith("THERMAL_") for code in codes):
            limits.append("thermal headroom")
        if any(code.startswith("POWER_") for code in codes):
            limits.append("power")
        if any(code.startswith("GPU_") for code in codes):
            limits.append("GPU capacity")
        limit_text = ", ".join(_deduplicate(limits)) or "current resource pressure"
        return f"It can still take on additional lightweight robot services, but {limit_text} is already the clearest limit; heavier AI or multi-stream perception should be added only after that pressure is resolved."

    available_gib = float(memory.get("available_bytes") or 0) / 1024**3
    if gpus:
        available_note = (
            f" About {available_gib:.1f} GiB of memory was available at scan time."
            if available_gib
            else ""
        )
        return (
            "It has additional headroom for more ROS 2 nodes, sensor processing, tracking, and moderate local AI inference."
            + available_note
            + " The first practical limit for substantially heavier workloads would likely be shared memory/GPU capacity, especially with several large models or multiple high-rate vision pipelines running together."
        )
    return (
        "It has additional headroom for more control, telemetry, and lightweight perception work. "
        "The practical limit for this class of machine would be heavy local AI or several high-rate "
        "perception pipelines running together."
    )


def _raw_finding_is_inspection_noise(finding: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    code = str(finding.get("code") or "").upper()
    text = " ".join(
        str(finding.get(key) or "") for key in ("code", "summary", "evidence", "recommendation")
    ).casefold()
    if any(
        token in text
        for token in (
            "collector",
            "normalization",
            "normalisation",
            "parser",
            "parse error",
            "telemetry conversion",
            "data quality",
            "inspection data",
            "evidence quality",
        )
    ):
        return True
    return (
        code.startswith("THERMAL_")
        and _thermal_trip_data_is_implausible(snapshot)
        and any(token in text for token in ("threshold", "trip", "critical", "high"))
    )


def _system_condition_assessment(snapshot: dict[str, Any]) -> str:
    rows = _blueprint_integration_rows(snapshot, [])
    verified = sum(len(row) >= 6 and row[5] == "VERIFIED" for row in rows)
    partial = sum(len(row) >= 6 and row[5] == "PARTIAL" for row in rows)
    if partial and not verified:
        return f"Right now, {partial} hardware path(s) stop before Screwdriver can prove which program or ROS endpoint is using them. The computer is capable; the main unknown is whether every connected device is actually part of the running robot system."
    if partial:
        return f"Screwdriver verified {verified} complete hardware-to-software path(s), while {partial} path(s) still stop before a proven program or ROS consumer. The main limitation is incomplete integration evidence, not lack of computing power."
    if verified:
        return f"Screwdriver verified {verified} complete hardware-to-software path(s), so the current robot role is supported by active integration evidence rather than hardware presence alone."
    return "The robot-facing hardware is visible, but Screwdriver still cannot prove which running programs consume it, so the complete robot application path is not yet established."


def _blueprint_diagnostic_note(context: dict[str, Any]) -> str:
    actionable = cast(list[dict[str, Any]], context.get("actionable", []))
    if actionable:
        top = actionable[0]
        return (
            f"{len(actionable)} actionable diagnostic finding(s) are present; the highest-priority item is "
            f"{str(top.get('title') or top.get('code')).rstrip(' .')}. The Agentic System Diagnostic Report "
            "generated with this scan contains the fix/investigation steps and direct verification."
        )
    return (
        "No actionable fault was identified in the collected evidence. The accompanying Agentic System "
        "Diagnostic Report records that state and lists incomplete integration paths separately when they exist."
    )


def _core_system_specs(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    identity = _mapping(snapshot.get("identity"))
    os_info = _mapping(snapshot.get("operating_system"))
    platform = _mapping(snapshot.get("platform"))
    cpu = _mapping(snapshot.get("cpu"))
    memory = _mapping(snapshot.get("memory"))
    network = _mapping(snapshot.get("network"))
    power = _mapping(snapshot.get("power"))
    specs: list[tuple[str, str]] = []

    system = _join_values(
        identity.get("hostname"),
        platform.get("manufacturer"),
        platform.get("product_name"),
        platform.get("board_name"),
        platform.get("machine_type"),
    )
    _append_spec(specs, "System", system)
    _append_spec(
        specs, "Architecture", _join_values(os_info.get("architecture"), platform.get("family"))
    )

    compute_bits: list[Any] = [cpu.get("model")]
    if cpu.get("physical_cores"):
        compute_bits.append(f"{cpu['physical_cores']} physical cores")
    if cpu.get("logical_cpus"):
        compute_bits.append(f"{cpu['logical_cpus']} logical CPUs")
    if cpu.get("online_cpus") and cpu.get("online_cpus") != cpu.get("logical_cpus"):
        compute_bits.append(f"{cpu['online_cpus']} online")
    if cpu.get("minimum_frequency_mhz") or cpu.get("maximum_frequency_mhz"):
        compute_bits.append(_frequency_range(cpu))
    _append_spec(specs, "Compute", _join_values(*compute_bits))

    gpu_bits = []
    for gpu in _records(snapshot.get("gpus")):
        parts = [gpu.get("vendor"), gpu.get("model")]
        if gpu.get("driver"):
            parts.append(f"driver {gpu['driver']}")
        if gpu.get("memory_bytes"):
            parts.append(f"{_bytes(gpu['memory_bytes'])} memory")
        gpu_bits.append(_join_values(*parts))
    _append_spec(specs, "GPU", " ; ".join(value for value in gpu_bits if value))

    memory_bits: list[Any] = []
    if memory.get("total_bytes") is not None:
        memory_bits.append(f"{_bytes(memory.get('total_bytes'))} total")
    if memory.get("used_bytes") is not None:
        memory_bits.append(f"{_bytes(memory.get('used_bytes'))} used")
    if memory.get("available_bytes") is not None:
        memory_bits.append(f"{_bytes(memory.get('available_bytes'))} available")
    if memory.get("usage_percent") is not None:
        memory_bits.append(f"{_percent(memory.get('usage_percent'))} used")
    if memory.get("swap_total_bytes"):
        memory_bits.append(f"swap {_bytes(memory.get('swap_total_bytes'))}")
    _append_spec(specs, "Memory", _join_values(*memory_bits))

    storage_bits = _primary_storage_descriptions(snapshot)
    _append_spec(specs, "Primary Storage", " ; ".join(storage_bits))

    _append_spec(
        specs,
        "Operating System",
        _join_values(
            os_info.get("distribution"),
            f"kernel {os_info['kernel']}" if os_info.get("kernel") else None,
        ),
    )
    boot_bits = [os_info.get("boot_mode"), os_info.get("init_system")]
    if os_info.get("uptime_seconds") is not None:
        boot_bits.append(f"uptime {_duration(os_info.get('uptime_seconds'))}")
    if os_info.get("process_count") is not None:
        boot_bits.append(f"{os_info['process_count']} processes")
    _append_spec(specs, "Boot / Runtime", _join_values(*boot_bits))

    primary = _primary_network_interface(network)
    if primary:
        network_bits: list[Any] = [primary.get("interface_type"), primary.get("name")]
        if primary.get("speed_mbps"):
            network_bits.append(f"{primary['speed_mbps']} Mbps")
        network_bits.extend([primary.get("duplex"), primary.get("driver")])
        _append_spec(specs, "Network", _join_values(*network_bits))
        addressing = _join_values(
            *cast(list[Any], primary.get("ipv4_addresses") or []),
            "internet route available" if network.get("internet_route_available") else None,
        )
        _append_spec(specs, "Addressing", addressing)

    power_bits: list[Any] = [power.get("source")]
    if power.get("battery_present"):
        power_bits.append("battery present")
        if power.get("battery_percent") is not None:
            power_bits.append(f"{power['battery_percent']}%")
        if power.get("charging") is not None:
            power_bits.append("charging" if power.get("charging") else "not charging")
    _append_spec(specs, "Power", _join_values(*power_bits))
    _append_spec(specs, "Timezone", os_info.get("timezone"))
    if platform.get("virtualization"):
        _append_spec(specs, "Virtualization", str(platform["virtualization"]))
    firmware = platform.get("firmware_version") or _mapping(platform.get("details")).get("l4t")
    if firmware:
        _append_spec(specs, "Firmware / Platform", str(firmware))
    return specs


def _primary_storage_descriptions(snapshot: dict[str, Any]) -> list[str]:
    """Keep Core System Specs focused on real persistent system storage."""

    devices = _records(snapshot.get("storage_devices"))
    root_device_names: set[str] = set()
    for device in devices:
        for partition in _records(device.get("partitions")):
            if partition.get("mount_point") == "/":
                for value in (device.get("name"), device.get("path"), device.get("model")):
                    if value:
                        root_device_names.add(str(value))

    candidates: list[tuple[int, dict[str, Any]]] = []
    for device in devices:
        name = str(device.get("name") or "")
        model = str(device.get("model") or "")
        media = str(device.get("media_type") or "")
        connection = str(device.get("connection") or "")
        descriptor = f"{name} {model} {media} {connection}".casefold()
        capacity = int(device.get("capacity_bytes") or 0)
        if name.startswith(("zram", "ram", "loop")) or any(
            token in descriptor for token in ("zram", "swap", "microcontroller")
        ):
            continue
        # Tiny removable/debug volumes are peripherals, not primary storage.
        if capacity and capacity < 2 * 1024**3:
            continue
        is_root = any(
            value and value in root_device_names
            for value in (name, model, str(device.get("path") or ""))
        )
        score = (
            2
            if is_root
            else 1
            if any(token in descriptor for token in ("nvme", "ssd", "emmc", "mmc"))
            else 0
        )
        candidates.append((score, device))

    candidates.sort(
        key=lambda pair: (pair[0], int(pair[1].get("capacity_bytes") or 0)), reverse=True
    )
    descriptions: list[str] = []
    for _, device in candidates[:3]:
        parts: list[Any] = [device.get("model") or device.get("name")]
        if device.get("capacity_bytes"):
            parts.append(_bytes(device.get("capacity_bytes")))
        parts.extend([device.get("connection"), device.get("media_type")])
        text = _join_values(*parts)
        if text:
            descriptions.append(text)
    return descriptions


def _append_spec(specs: list[tuple[str, str]], label: str, value: Any) -> None:
    text = str(value or "").strip()
    if text and text.casefold() not in {"none", "not reported", "unknown"}:
        specs.append((label, text))


def _paired_spec_table(specs: list[tuple[str, str]]) -> str:
    rows: list[list[Any]] = []
    for index in range(0, len(specs), 2):
        left = specs[index]
        right = specs[index + 1] if index + 1 < len(specs) else ("", "")
        rows.append([left[0], left[1], right[0], right[1]])
    return _four_column_table(
        ["Specification", "Details", "Specification", "Details"],
        rows,
        preserve_blanks=True,
    )


def _four_column_table(
    headers: list[str], rows: list[list[Any]], *, preserve_blanks: bool = False
) -> str:
    """Render a fixed four-column report table without inventing missing values."""

    if not rows:
        return '<p class="empty">No reportable values.</p>'
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    row_html = []
    for row in rows:
        cells = []
        for value in [*row, "", "", "", ""][:4]:
            if preserve_blanks and value in (None, ""):
                rendered = ""
            else:
                rendered = _display(value)
            cells.append(f"<td>{html.escape(str(rendered))}</td>")
        row_html.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + "".join(row_html)
        + "</tbody></table></div>"
    )


def _join_values(*values: Any) -> str:
    cleaned: list[str] = []
    for value in values:
        if value in (None, "", [], {}):
            continue
        text = str(value).strip()
        if not text or text.casefold() in {"none", "not reported", "unknown"}:
            continue
        if text not in cleaned:
            cleaned.append(text)
    return " · ".join(cleaned)


def _primary_network_interface(network: dict[str, Any]) -> dict[str, Any]:
    interfaces = _records(network.get("interfaces"))
    default_name = str(network.get("default_interface") or "")
    for interface in interfaces:
        if interface.get("name") == default_name or interface.get("is_default_route"):
            return interface
    for interface in interfaces:
        if not interface.get("is_loopback") and not interface.get("is_virtual"):
            return interface
    return {}


def _blueprint_hardware_rows(snapshot: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    seen: set[str] = set()
    ros_links = _ros_physical_links(snapshot)
    usb_drivers: dict[str, list[str]] = {}
    for usb in _records(snapshot.get("usb_devices")):
        names = [
            usb.get("display_name"),
            _join_values(usb.get("manufacturer"), usb.get("product_name")),
            usb.get("usb_id"),
        ]
        drivers = _driver_values(usb.get("drivers"))
        for value in names:
            key = _hardware_key(value)
            if key:
                usb_drivers.setdefault(key, [])
                for driver in drivers:
                    if driver not in usb_drivers[key]:
                        usb_drivers[key].append(driver)

    def add(
        name: Any,
        kind: Any,
        connected: Any,
        drivers: Any,
        role: str,
        *aliases: Any,
    ) -> None:
        display_name = str(name or "").strip()
        if not display_name:
            return
        keys = {_hardware_key(display_name), *(_hardware_key(alias) for alias in aliases if alias)}
        if any(key and key in seen for key in keys):
            return
        seen.update(key for key in keys if key)
        rows.append(
            [
                display_name,
                str(kind or "Hardware"),
                str(connected or "—"),
                _driver_bound(drivers),
                role,
            ]
        )

    for item in _records(snapshot.get("display_inventory")):
        details = _mapping(item.get("details"))
        add(
            item.get("name"),
            details.get("kind") or "Display",
            _compact_connection(details.get("bus"), details.get("connector")),
            details.get("driver"),
            "Visual output",
        )

    for item, default_role in (
        *((item, "Sensor input") for item in _records(snapshot.get("sensor_inventory"))),
        *((item, "Actuation / output") for item in _records(snapshot.get("actuator_inventory"))),
    ):
        details = _mapping(item.get("details"))
        physical = details.get("physical_component")
        source = str(details.get("source") or "")
        if physical:
            name = physical
        elif "linux" in source.casefold() or "usb" in str(details.get("bus") or "").casefold():
            name = item.get("name")
        else:
            continue
        kind = details.get("kind") or item.get("category") or "Hardware"
        link = ros_links.get(_hardware_key(name), {})
        role = _hardware_role(str(kind), default_role)
        add(
            name,
            kind,
            _compact_connection(
                details.get("physical_bus") or details.get("bus") or link.get("physical_bus"),
                details.get("physical_channel")
                or details.get("channel")
                or link.get("physical_channel"),
            ),
            [details.get("driver"), link.get("driver"), usb_drivers.get(_hardware_key(name), [])],
            role,
            details.get("usb_id"),
        )

    for device in _meaningful_serial_devices(snapshot):
        device_node = _mapping(device.get("device_node"))
        name = (
            device.get("display_name")
            or _join_values(device.get("manufacturer"), device.get("product_name"))
            or device.get("port")
        )
        link = ros_links.get(_hardware_key(name), {})
        add(
            name,
            "Serial / MCU Interface",
            _compact_connection(
                device.get("transport") or link.get("physical_bus"),
                device.get("port") or device_node.get("path") or link.get("physical_channel"),
            ),
            [device.get("driver"), link.get("driver"), usb_drivers.get(_hardware_key(name), [])],
            "Embedded-device communication",
            device.get("usb_id"),
            device.get("port"),
        )

    for device in _records(snapshot.get("usb_devices")):
        if _usb_is_infrastructure(device):
            continue
        name = device.get("display_name") or _join_values(
            device.get("manufacturer"), device.get("product_name")
        )
        if not name:
            continue
        kind = _usb_kind(device)
        link = ros_links.get(_hardware_key(name), {})
        node = _compact_device_path(link.get("physical_channel") or _primary_device_path(device))
        add(
            name,
            kind,
            _compact_connection("USB", node),
            [device.get("drivers"), link.get("driver")],
            _hardware_role(kind, "Peripheral hardware"),
            device.get("usb_id"),
        )

    for item in _records(snapshot.get("hardware_bus_inventory")):
        if not _bus_item_robot_relevant(item, snapshot):
            continue
        details = _mapping(item.get("details"))
        kind = str(details.get("kind") or "Robot Interface")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        add(
            name,
            kind,
            _compact_connection(
                details.get("bus"), details.get("interface") or details.get("channel")
            ),
            details.get("driver"),
            _hardware_role(kind, "Robot hardware interface"),
        )

    return rows


def _driver_values(value: Any) -> list[str]:
    values: list[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                collect(nested)
            return
        text = str(item).strip()
        if not text or text.casefold() in {"none", "unknown", "not reported"}:
            return
        for part in re.split(r"\s*[,;]\s*", text):
            # "usb" is a transport label, not a component-specific bound driver.
            if part.casefold() in {"usb", "usbcore"}:
                continue
            if part and part not in values:
                values.append(part)

    collect(value)
    return values


def _driver_bound(value: Any) -> str:
    """Render all evidence-backed bound drivers without inventing a status."""

    values = _driver_values(value)
    return ", ".join(values) if values else "—"


def _hardware_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _ros_physical_links(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    links: dict[str, dict[str, Any]] = {}
    for item in _records(snapshot.get("ros_device_inventory")):
        details = _mapping(item.get("details"))
        physical = details.get("physical_component")
        if physical:
            links[_hardware_key(physical)] = details
    return links


def _hardware_role(kind: str, fallback: str) -> str:
    text = kind.casefold()
    if any(token in text for token in ("bluetooth", "wireless", "wifi", "wi-fi")):
        return "Wireless communication"
    if "camera" in text:
        return "Visual sensing"
    if any(token in text for token in ("microphone", "audio input")):
        return "Audio input"
    if "speaker" in text or "audio output" in text:
        return "Audio output"
    if "display" in text:
        return "Visual output"
    if "touch" in text:
        return "User input"
    if any(token in text for token in ("motor", "actuator", "servo", "drive", "controller")):
        return "Motion / actuation"
    if any(token in text for token in ("imu", "lidar", "gps", "gnss", "sensor")):
        return "Robot sensing"
    return fallback


def _compact_connection(bus: Any, channel: Any, driver: Any = None) -> str:
    return _join_values(
        _friendly_transport(bus),
        _compact_device_path(channel),
        _first_nonempty(driver),
    )


def _friendly_transport(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.casefold().replace("_", "-")
    aliases = {
        "usb-serial": "USB / UART",
        "usb serial": "USB / UART",
        "serial-usb": "USB / UART",
        "onboard-uart": "UART",
        "uart": "UART",
        "ethernet": "Ethernet",
        "usb": "USB",
        "can": "CAN",
        "i2c": "I²C",
        "i²c": "I²C",
        "spi": "SPI",
        "gpio": "GPIO",
        "drm": "DRM",
    }
    return aliases.get(normalized, text)


def _compact_device_path(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    paths = [part.strip() for part in text.split(",") if part.strip()]
    preferred = next(
        (
            path
            for path in paths
            if path.startswith(
                (
                    "/dev/video",
                    "/dev/tty",
                    "/dev/can",
                    "/dev/i2c",
                    "/dev/spidev",
                    "/dev/input",
                    "/dev/snd",
                )
            )
        ),
        paths[0] if paths else text,
    )
    return preferred


def _meaningful_serial_devices(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return serial devices backed by positive robot-facing hardware evidence."""

    values: list[dict[str, Any]] = []
    ros_text = json.dumps(snapshot.get("ros_device_inventory", []), ensure_ascii=False)
    for device in _records(snapshot.get("serial_devices")):
        port = str(device.get("port") or "")
        name = port.rsplit("/", 1)[-1]
        onboard_candidate = bool(re.fullmatch(r"tty(?:S|THS|AMA)\d+", name)) or str(
            device.get("transport") or ""
        ).casefold().startswith("onboard")
        positive_evidence = bool(
            device.get("hardware_verified")
            or device.get("stable_id_path")
            or device.get("usb_id")
            or device.get("usb_vendor_id")
            or device.get("manufacturer")
            or device.get("product_name")
            or (port and port in ros_text)
        )
        if onboard_candidate and not positive_evidence:
            continue
        if positive_evidence or name.startswith(("ttyUSB", "ttyACM", "ttyXRUSB", "rfcomm")):
            values.append(device)
    return values


def _usb_is_infrastructure(device: dict[str, Any]) -> bool:
    name = str(device.get("display_name") or "").casefold()
    manufacturer = str(device.get("manufacturer") or "").casefold()
    product = str(device.get("product_name") or "").casefold()
    device_class = str(device.get("device_class_name") or "").casefold()
    if device_class == "hub":
        return True
    return any(
        token in f"{manufacturer} {product} {name}"
        for token in (
            "xhci host controller",
            "ehci host controller",
            "linux foundation root hub",
            "root hub",
        )
    )


def _usb_kind(device: dict[str, Any]) -> str:
    text = " ".join(
        str(value or "")
        for value in (
            device.get("display_name"),
            device.get("product_name"),
            device.get("device_class_name"),
            device.get("drivers"),
        )
    ).casefold()
    for tokens, kind in (
        (("camera", "uvcvideo"), "Camera"),
        (("touch", "hid-multitouch"), "Touch Input"),
        (("microphone", "respeaker"), "Microphone"),
        (("audio", "snd-usb-audio"), "Audio Device"),
        (("lidar",), "LiDAR"),
        (("imu", "inertial"), "IMU"),
        (("stlink", "stm32"), "MCU Interface"),
        (("cp210", "ftdi", "ch340", "uart", "serial"), "Serial Interface"),
        (("motor", "servo", "actuator"), "Actuator"),
    ):
        if any(token in text for token in tokens):
            return kind
    device_class = str(device.get("device_class_name") or "").strip()
    if not device_class:
        return "USB Peripheral"
    if device_class.casefold() in {"vendor specific", "vendor-specific", "per interface"}:
        return "USB Peripheral"
    return device_class.title()


def _primary_device_path(device: dict[str, Any]) -> str:
    nodes = _records(device.get("device_nodes"))
    candidates = [str(node.get("path")) for node in nodes if node.get("path")]
    for prefix in ("/dev/video", "/dev/tty", "/dev/input", "/dev/snd", "/dev/hidraw"):
        for candidate in candidates:
            if candidate.startswith(prefix):
                return candidate
    return candidates[0] if candidates else ""


def _first_nonempty(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")


def _bus_item_robot_relevant(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    details = _mapping(item.get("details"))
    name = str(item.get("name") or "").strip()
    kind = str(details.get("kind") or "").strip()
    channel = str(details.get("channel") or details.get("interface") or "").strip()
    driver = str(details.get("driver") or "").strip()
    haystack = " ".join(value for value in (name, kind, channel, driver) if value).casefold()

    # An interface type such as PCI/I2C/SPI/GPIO does not by itself make host/SoC
    # infrastructure a robot component. Keep only obviously robot-facing buses or
    # records that can be tied back to collected robot evidence.
    if (
        re.search(r"(?:^|[^a-z0-9])can\d*(?:$|[^a-z0-9])", haystack)
        or "controller area network" in haystack
    ):
        return True
    if any(
        token in haystack
        for token in (
            "lidar",
            "imu",
            "camera",
            "touch",
            "motor",
            "servo",
            "actuator",
            "gnss",
            "gps",
            "stlink",
            "stm32",
            "microphone",
            "speaker",
        )
    ):
        return True

    evidence = json.dumps(
        [
            *_records(snapshot.get("ros_device_inventory")),
            *_records(snapshot.get("sensor_inventory")),
            *_records(snapshot.get("actuator_inventory")),
        ],
        ensure_ascii=False,
    ).casefold()
    candidates = [value.casefold() for value in (name, channel) if len(value.strip()) >= 4]
    return any(candidate in evidence for candidate in candidates)


def _blueprint_software_rows(snapshot: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    seen: set[str] = set()

    ros = _ros_overview(snapshot)
    if ros and str(ros.get("state") or "").upper() == "RUNNING":
        distro = ros.get("ros_distro")
        name = f"ROS 2 {str(distro).title()}" if distro else "ROS 2"
        rows.append(
            [name, "Robotics Runtime", "RUNNING", "Core robot middleware and communication"]
        )
        seen.add(_hardware_key(name))

    for item in _records(snapshot.get("software_stack_inventory")):
        details = _mapping(item.get("details"))
        state = _software_current_state(item)
        if state is None:
            continue
        name = str(item.get("name") or "").strip()
        if not name or _hardware_key(name) in seen:
            continue
        seen.add(_hardware_key(name))
        stack_type = (
            details.get("stack_category")
            or details.get("original_category")
            or item.get("category")
            or "Software"
        )
        role = details.get("capability") or _software_role(name, str(stack_type))
        rows.append([name, str(stack_type), state, str(role)])

    for item in _records(snapshot.get("components")):
        category = str(item.get("category") or "").casefold()
        if not any(token in category for token in ("software", "runtime", "container", "tool")):
            continue
        details = _mapping(item.get("details"))
        state = _software_current_state(item)
        name = str(item.get("name") or "").strip()
        if state is None or not name or _hardware_key(name) in seen:
            continue
        seen.add(_hardware_key(name))
        rows.append(
            [
                name,
                str(item.get("category") or "Software"),
                state,
                str(details.get("capability") or _software_role(name, category)),
            ]
        )
    return rows


def _software_current_state(item: dict[str, Any]) -> str | None:
    details = _mapping(item.get("details"))
    state = str(details.get("state") or item.get("status") or "").upper()
    if details.get("running") is True or state in {"RUNNING", "ACTIVE", "STARTED"}:
        return "RUNNING"
    if state in {"INACTIVE", "STOPPED", "DISABLED", "DOWN"}:
        return "INACTIVE"
    if details.get("installed") is True or state in {
        "INSTALLED",
        "AVAILABLE",
        "PRESENT",
        "DETECTED",
    }:
        return "INSTALLED"
    return None


def _software_role(name: str, stack_type: str) -> str:
    text = f"{name} {stack_type}".casefold()
    for token, role in (
        ("navigation", "Autonomous navigation"),
        ("amcl", "Localization"),
        ("slam", "Mapping / localization"),
        ("moveit", "Motion planning / manipulation"),
        ("control", "Robot hardware / motion control"),
        ("docker", "Containerized software execution"),
        ("cuda", "GPU-accelerated compute"),
        ("rviz", "Robot visualization"),
        ("rosbag", "Recording and playback"),
        ("colcon", "ROS workspace builds"),
        ("rosdep", "ROS dependency management"),
        ("vcstool", "Workspace/source management"),
    ):
        if token in text:
            return role
    return "Robot software / runtime support"


def _notable_missing_software(snapshot: dict[str, Any]) -> str:
    running = " ".join(
        row[0] + " " + row[1]
        for row in _blueprint_software_rows(snapshot)
        if len(row) >= 3 and row[2] == "RUNNING"
    ).casefold()
    missing = []
    for label, tokens in (
        ("navigation", ("navigation", "nav2")),
        ("SLAM", ("slam", "cartographer", "rtab")),
        ("manipulation", ("moveit", "manipulation")),
        ("simulation", ("gazebo", "webots", "simulation", "isaac sim")),
    ):
        if not any(token in running for token in tokens):
            missing.append(label)
    if not missing:
        return ""
    if len(missing) == 1:
        categories = missing[0]
    else:
        categories = ", ".join(missing[:-1]) + f", or {missing[-1]}"
    return f"No active {categories} stack was detected on this system."


def _blueprint_integration_rows(
    snapshot: dict[str, Any], agent_chains: list[dict[str, str]] | None = None
) -> list[list[str]]:
    """Reconstruct every evidence-backed physical chain without inventing missing links."""

    rows: list[list[str]] = []
    represented: set[str] = set()

    def add(
        physical: Any, interface: Any, os_interface: Any, owner: Any, endpoint: Any, status: str
    ) -> None:
        name = str(physical or "").strip()
        if not name:
            return
        key = _hardware_key(name)
        signature = (key, str(owner or "").strip(), str(endpoint or "").strip())
        if any(
            (_hardware_key(row[0]), row[3] if len(row) > 3 else "", row[4] if len(row) > 4 else "")
            == signature
            for row in rows
        ):
            return
        rows.append(
            [
                name,
                str(interface or "—"),
                str(os_interface or "—"),
                str(owner or "—"),
                str(endpoint or "—"),
                status,
            ]
        )
        represented.add(key)

    # Strongest source first: deterministic ROS↔hardware correlations.
    for item in _records(snapshot.get("ros_device_inventory")):
        details = _mapping(item.get("details"))
        physical = str(details.get("physical_component") or "").strip()
        if not physical:
            continue
        interface = _join_values(details.get("physical_bus"), details.get("driver"))
        os_interface = _compact_device_path(
            details.get("physical_channel") or details.get("device_path")
        )
        owner = str(
            details.get("ros_node")
            or details.get("hardware_node")
            or details.get("runtime_owner")
            or ""
        ).strip()
        endpoint = str(details.get("topics") or details.get("endpoint") or "").strip()
        confidence = str(details.get("confidence") or "").upper()
        complete = all((physical, interface, os_interface, owner, endpoint))
        if complete and confidence == "VERIFIED":
            status = "VERIFIED"
        elif confidence in {"CORRELATED", "INFERRED"} and owner and endpoint:
            status = "INFERRED"
        else:
            status = "PARTIAL"
        add(physical, interface, os_interface, owner, endpoint, status)

    # Model-proposed relationships are never promoted to VERIFIED. They enter only
    # after orchestration validates every displayed value against cited snapshot evidence.
    for chain in agent_chains or []:
        add(
            chain.get("physical_component"),
            chain.get("interface_driver"),
            chain.get("os_interface"),
            chain.get("runtime_owner"),
            chain.get("endpoint_consumer"),
            chain.get("integration_status") or "PARTIAL",
        )

    # Every curated hardware component should remain visible even when ownership
    # is unresolved. This is where the Blueprint exposes the missing relationship.
    for hardware in _blueprint_hardware_rows(snapshot):
        if not hardware:
            continue
        physical = hardware[0]
        if _hardware_key(physical) in represented:
            continue
        connected = str(hardware[2] if len(hardware) > 2 else "")
        driver_bound = str(hardware[3] if len(hardware) > 3 else "").strip()
        pieces = [
            piece.strip()
            for piece in connected.split("·")
            if piece.strip() and piece.strip() != "—"
        ]
        os_interface = next(
            (
                piece
                for piece in pieces
                if piece.startswith("/dev/")
                or re.fullmatch(r"(?:can|eth|en|wl|wlan)[A-Za-z0-9_.:-]*", piece)
            ),
            "",
        )
        interface_parts = [piece for piece in pieces if piece != os_interface]
        if driver_bound and driver_bound != "—":
            interface_parts.append(driver_bound)
        add(physical, " · ".join(interface_parts), os_interface, "", "", "PARTIAL")

    return rows


def _diagnostic_report_issues(
    issues: list[dict[str, Any]], snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return every meaningful real problem, excluding evidence/tool noise and pure integration gaps."""

    selected = []
    for issue in issues:
        if str(issue.get("severity") or "INFO").upper() == "INFO":
            continue
        if _is_inspection_data_quality_issue(issue, snapshot):
            continue
        if _is_pure_integration_gap_issue(issue):
            continue
        selected.append(issue)
    return sorted(
        selected,
        key=lambda issue: _SEVERITY_ORDER.get(str(issue.get("severity") or "INFO").upper(), 9),
    )


def _is_inspection_data_quality_issue(issue: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    code = str(issue.get("code") or "").upper()
    text = " ".join(
        [
            str(issue.get("code") or ""),
            str(issue.get("title") or ""),
            *[str(value) for value in _string_list(issue.get("observed"))],
        ]
    ).casefold()
    explicit_tokens = (
        "collector",
        "normalization",
        "normalisation",
        "parser",
        "parse error",
        "telemetry conversion",
        "data quality",
        "inspection data",
        "evidence quality",
    )
    if any(token in text for token in explicit_tokens):
        return True
    if code.startswith("THERMAL_") and _thermal_trip_data_is_implausible(snapshot):
        thermal_text = " ".join(
            [text, *[str(value) for value in _string_list(issue.get("observed"))]]
        ).casefold()
        if any(token in thermal_text for token in ("threshold", "trip", "critical", "high")):
            return True
    return False


def _thermal_trip_data_is_implausible(snapshot: dict[str, Any]) -> bool:
    for sensor in _records(snapshot.get("thermal_sensors")):
        current = _number_from_mapping(
            sensor,
            "temperature_celsius",
            "current_celsius",
            "temperature",
            "current",
        )
        if current is None or not 10.0 <= current <= 150.0:
            continue
        for key in (
            "high_celsius",
            "critical_celsius",
            "high",
            "critical",
            "trip_point_celsius",
        ):
            threshold = _maybe_number(sensor.get(key))
            if threshold is not None and 0 <= threshold < 5.0 and current > 20.0:
                return True
    return False


def _number_from_mapping(value: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _maybe_number(value.get(key))
        if number is not None:
            return number
    return None


def _maybe_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_pure_integration_gap_issue(issue: dict[str, Any]) -> bool:
    code = str(issue.get("code") or "").upper()
    text = " ".join(
        [
            code,
            str(issue.get("title") or ""),
            str(issue.get("affected_area") or ""),
            *[str(value) for value in _string_list(issue.get("observed"))],
        ]
    ).casefold()
    gap_terms = (
        "runtime owner",
        "endpoint",
        "consumer",
        "integration path",
        "ownership not",
        "not mapped",
    )
    failure_terms = (
        "failed",
        "failure",
        "denied",
        "down",
        "unavailable",
        "error",
        "misconfig",
        "mismatch",
        "blocked",
    )
    return any(term in text for term in gap_terms) and not any(
        term in text for term in failure_terms
    )


def _diagnostic_summary(
    context: dict[str, Any], issues: list[dict[str, Any]], integration_gap_count: int
) -> str:
    """Give a short operator-level status, not a second copy of the findings table."""

    if not issues:
        if integration_gap_count:
            return (
                f"No issues found right now. Screwdriver found {integration_gap_count} incomplete integration "
                "path(s), listed separately because missing ownership or endpoints are evidence gaps, not proven faults."
            )
        return "No issues found right now. The collected evidence does not show an actionable fault or misconfiguration."

    top = issues[0]
    top_title = (
        str(top.get("title") or top.get("code") or "the highest-priority finding")
        .strip()
        .rstrip(" .;:")
    )
    top_area = str(top.get("affected_area") or "the system")
    severity = str(top.get("severity") or "INFO").upper()
    status = str(top.get("diagnosis_status") or "UNRESOLVED").upper()
    impact = str(top.get("operational_impact") or "").strip()
    sentence = (
        f"Screwdriver found {len(issues)} actionable problem(s). Highest priority is {top_title} "
        f"({severity}, {status}) in {top_area}."
    )
    if impact:
        sentence += f" {impact}"
    if integration_gap_count:
        sentence += f" {integration_gap_count} incomplete integration path(s) are listed separately and are not counted as faults."
    return sentence


def _diagnostic_probe_note(probes: list[dict[str, Any]]) -> str:
    if not probes:
        return ""
    completed = sum(str(probe.get("state")) == "completed" for probe in probes)
    return f'<p class="secondary-note">Read-only investigation: {_h(completed)} of {_h(len(probes))} requested probe(s) completed and were included as evidence.</p>'


def _diagnostic_rca(issue: dict[str, Any], index: int) -> str:
    code = f"D-{index:03d}"
    observed = _string_list(issue.get("observed"))
    recommended = _concise_guidance_steps(_report_guidance_steps(issue, "recommended_steps"))
    verification = _concise_guidance_steps(
        _report_guidance_steps(issue, "verification_steps"), verification=True
    )
    if not recommended:
        recommended = _concise_guidance_steps(_fallback_report_steps(issue))
    if not verification:
        verification = _direct_verification_steps(issue)
    root_cause = _diagnostic_root_cause(issue)
    return f"""
<article class="rca" id="{_issue_id(issue)}">
  <div class="rca-title"><h3>{_h(code)} · {_h(issue.get("title") or issue.get("code"))}</h3></div>
  <div class="rca-meta"><strong>Severity:</strong> {_h(issue.get("severity") or "INFO")} &nbsp; <strong>Diagnosis:</strong> {_h(issue.get("diagnosis_status") or "UNRESOLVED")}</div>
  <h4>Observed Evidence</h4>{_list(observed, "No accepted observation was supplied.")}
  <h4>Impact</h4><p>{_h(issue.get("operational_impact") or "Impact has not been established.")}</p>
  <h4>Root Cause</h4><p>{_h(root_cause)}</p>
  <h4>Fix / Investigation Steps</h4>{_guidance_steps_html(recommended)}
  <h4>Verification</h4>{_guidance_steps_html(verification)}
</article>
"""


def _diagnostic_root_cause(issue: dict[str, Any]) -> str:
    """Render causal certainty plainly instead of turning a hypothesis into a fact."""

    status = str(issue.get("diagnosis_status") or "UNRESOLVED").upper()
    cause = (
        str(issue.get("likely_root_cause") or _first(issue.get("probable_causes")) or "")
        .strip()
        .rstrip(" .")
    )
    if status == "CONFIRMED":
        return (
            (cause + ".")
            if cause
            else "The cause is directly established by the collected evidence."
        )
    if status in {"PROBABLE", "PARTIAL"}:
        return (
            f"Most likely: {cause}."
            if cause
            else "The problem is real, but the exact cause is not fully proven yet."
        )
    return (
        f"Not proven yet. Leading possibility: {cause}."
        if cause
        else "Not proven yet. Use the steps below to isolate the cause."
    )


def _report_guidance_steps(issue: dict[str, Any], key: str) -> list[dict[str, str]]:
    values = issue.get(key)
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if not isinstance(value, dict):
            continue
        instruction = str(value.get("instruction") or "").strip()
        if not instruction:
            continue
        result.append(
            {
                "instruction": instruction,
                "command": str(value.get("command") or "").strip(),
                "look_for": str(value.get("look_for") or "").strip(),
                "meaning": str(value.get("meaning") or "").strip(),
                "next_step": str(value.get("next_step") or "").strip(),
            }
        )
    return result


def _concise_guidance_steps(
    steps: list[dict[str, str]], *, verification: bool = False
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for step in steps:
        command = str(step.get("command") or "").strip()
        instruction = str(step.get("instruction") or "").strip()
        combined = f"{instruction} {command}".casefold()
        if (
            command.startswith("screwdriver inspect")
            or "re-run screwdriver" in combined
            or "rerun screwdriver" in combined
        ):
            continue
        if verification and command and _looks_state_changing_for_report(command):
            continue
        key = (instruction.casefold(), command.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(step)
        if len(result) >= 6:
            break
    return result


def _looks_state_changing_for_report(command: str) -> bool:
    lowered = command.strip().casefold()
    prefixes = (
        "sudo ",
        "systemctl start ",
        "systemctl stop ",
        "systemctl restart ",
        "ip link set ",
        "ip addr add ",
        "chmod ",
        "chown ",
        "usermod ",
        "nmcli connection up ",
        "docker restart ",
        "docker stop ",
        "docker start ",
    )
    return lowered.startswith(prefixes)


def _direct_verification_steps(issue: dict[str, Any]) -> list[dict[str, str]]:
    commands = [
        command
        for command in _string_list(issue.get("diagnostic_commands"))
        if not command.startswith("screwdriver inspect")
    ][:2]
    if not commands:
        return []
    recovery = str(
        issue.get("expected_outcome")
        or _first(issue.get("success_criteria"))
        or "The original problem is no longer present."
    )
    return [
        {
            "instruction": "Verify the corrected state directly.",
            "command": command,
            "look_for": recovery,
            "meaning": "The finding is resolved only when the direct check shows the expected healthy state.",
            "next_step": "Close the finding if the recovery condition is met; otherwise continue from this command's new evidence.",
        }
        for command in commands
    ]


def _fallback_report_steps(issue: dict[str, Any]) -> list[dict[str, str]]:
    commands = [
        command
        for command in _string_list(issue.get("diagnostic_commands"))
        if not command.startswith("screwdriver inspect")
    ]
    approaches = _string_list(issue.get("primary_approach"))
    steps: list[dict[str, str]] = []
    for command in commands[:4]:
        steps.append(
            {
                "instruction": "Run this passive check.",
                "command": command,
                "look_for": "The exact state, owner, configuration, or resource condition tied to this finding.",
                "meaning": "Use the result to confirm the cause before changing system state.",
                "next_step": "Follow the evidence: fix the confirmed cause, or continue to the next passive check if the cause is still unclear.",
            }
        )
    for approach in approaches:
        if len(steps) >= 6:
            break
        steps.append(
            {
                "instruction": approach,
                "command": "",
                "look_for": "A concrete result that confirms or rejects this cause.",
                "meaning": "This step narrows the problem to a specific component or configuration.",
                "next_step": "Apply the smallest justified correction once the cause is established.",
            }
        )
    return steps


def _guidance_steps_html(steps: list[dict[str, str]]) -> str:
    if not steps:
        return '<p class="muted">No safe direct step is available from the current evidence.</p>'
    chunks = []
    for index, step in enumerate(steps, 1):
        command = step.get("command") or ""
        command_html = f"<pre><code>{html.escape(command)}</code></pre>" if command else ""
        look_for = step.get("look_for") or "The condition described in this step."
        meaning = (
            step.get("meaning") or "Use the result to decide whether the next action is justified."
        )
        next_step = (
            step.get("next_step") or "Continue only with the action supported by this result."
        )
        chunks.append(
            f'<div class="guidance-step"><div class="step-number">{index}</div><div><strong>{_h(step.get("instruction"))}</strong>{command_html}<p><b>Look for:</b> {_h(look_for)}</p><p><b>What it means:</b> {_h(meaning)}</p><p><b>What to do next:</b> {_h(next_step)}</p></div></div>'
        )
    return '<div class="guidance-steps">' + "".join(chunks) + "</div>"


def _incomplete_integration_path_rows(context: dict[str, Any]) -> list[list[str]]:
    """List hardware chains that are proven through Linux but lack a runtime owner/consumer."""

    snapshot = _mapping(context.get("snapshot"))
    rows: list[list[str]] = []
    seen: set[str] = set()
    for chain in _blueprint_integration_rows(
        snapshot,
        cast(list[dict[str, str]], context.get("agent_integration_chains") or []),
    ):
        if len(chain) < 6 or chain[5] != "PARTIAL":
            continue
        component, interface, os_interface, runtime_owner, endpoint = chain[:5]
        if component in {"", "—"}:
            continue
        # This section is specifically for device/driver/OS paths that stop before
        # the software owner or endpoint. Other uncertainty classes do not belong here.
        if interface in {"", "—"} and os_interface in {"", "—"}:
            continue
        missing: list[str] = []
        if runtime_owner in {"", "—"}:
            missing.append("Runtime owner")
        if endpoint in {"", "—"}:
            missing.append("Endpoint / consumer")
        if not missing:
            continue
        key = _hardware_key(component)
        if key in seen:
            continue
        seen.add(key)
        proven = " → ".join(value for value in (interface, os_interface) if value not in {"", "—"})
        why = (
            "Hardware and its interface/OS path are present, but Screwdriver cannot prove which running software uses it."
            if "Runtime owner" in missing
            else "A runtime owner is visible, but the downstream endpoint or consumer is not proven."
        )
        rows.append(
            [
                component,
                proven or "Physical component detected",
                " + ".join(missing),
                why,
                _integration_verification_commands(snapshot, interface, os_interface),
            ]
        )
    return rows[:20]


def _integration_verification_commands(
    snapshot: dict[str, Any], interface: str, os_interface: str
) -> str:
    commands: list[str] = []
    path = str(os_interface or "").strip()
    interface_text = str(interface or "").strip()
    if path.startswith("/dev/"):
        commands.append(f"lsof -- {path}")
        commands.append(f"fuser -v {path}")
    elif any(
        token in f"{interface_text} {path}".casefold()
        for token in ("hw:", "alsa", "/snd/", "audio")
    ):
        commands.extend(["arecord -l", "fuser -v /dev/snd/*"])
    elif any(token in f"{interface_text} {path}".casefold() for token in ("drm", "dp-", "hdmi")):
        commands.append("fuser -v /dev/dri/*")
    ros = _ros_overview(snapshot)
    if ros and str(ros.get("state") or "").upper() == "RUNNING":
        commands.extend(["ros2 node list", "ros2 topic list -t"])
    if not commands:
        return '<span class="muted">Inspect the process or service that owns the proven OS interface.</span>'
    return "<br>".join(f"<code>{html.escape(command)}</code>" for command in commands[:4])


def _classic_agentic_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_h(title)}</title>
<style>
:root{{color-scheme:dark;--paper:#080808;--panel:#0d0d0d;--panel2:#111;--ink:#f1f1f1;--muted:#aaa;--line:#353535;--line2:#565656}}
*{{box-sizing:border-box}}html{{background:var(--paper)}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;font-size:14px;line-height:1.55}}
main{{max-width:1220px;margin:0 auto;padding:28px 24px 60px}}.report-header{{border:1px solid var(--line2);padding:18px 20px;margin-bottom:12px;background:var(--panel)}}.brand{{font-size:.78rem;letter-spacing:.18em;color:#d8d8d8;margin-bottom:5px}}h1{{font-size:1.32rem;margin:0;font-weight:700;letter-spacing:.02em}}h2{{font-size:1.05rem;margin:0 0 16px;border-bottom:1px solid var(--line);padding-bottom:9px}}h3{{font-size:1rem;margin:0}}h4{{font-size:.88rem;margin:18px 0 7px;color:#ddd}}p{{margin:.55rem 0}}section{{border:1px solid var(--line);background:var(--panel);margin:12px 0;padding:20px}}.secondary-note,.legend,.muted{{color:var(--muted)}}.legend{{font-size:.8rem;margin-top:9px}}.metadata-table{{margin-bottom:12px}}.metadata-table .table-wrap{{border-radius:0}}.metadata-table th{{display:none}}.metadata-table td:nth-child(odd){{color:var(--muted);width:130px;font-size:.78rem}}.metadata-table td:nth-child(even){{font-weight:650}}.table-wrap{{overflow-x:auto;border:1px solid var(--line)}}table{{border-collapse:collapse;width:100%;min-width:720px;background:var(--panel)}}th,td{{border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:9px 11px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th:last-child,td:last-child{{border-right:0}}tr:last-child td{{border-bottom:0}}th{{font-size:.78rem;color:#d7d7d7;background:var(--panel2);font-weight:700}}.rca{{border:1px solid var(--line2);padding:16px;margin:14px 0;background:#0a0a0a}}.rca-title{{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding-bottom:10px}}.rca-title span{{font-size:.76rem;color:var(--muted);white-space:nowrap}}.rca-meta{{font-size:.8rem;color:var(--muted);margin:9px 0}}ul,ol{{padding-left:22px}}.guidance-step{{display:grid;grid-template-columns:34px 1fr;gap:10px;border-top:1px solid var(--line);padding:12px 0}}.guidance-step:first-child{{border-top:0}}.step-number{{width:28px;height:28px;border:1px solid var(--line2);display:grid;place-items:center;font-size:.76rem}}pre{{margin:8px 0;background:#050505;border:1px solid var(--line2);padding:10px;white-space:pre-wrap;overflow:auto}}code{{font-family:inherit;color:#f5f5f5}}.empty{{border:1px dashed var(--line2);padding:14px;color:var(--muted)}}footer{{margin-top:18px;padding-top:10px;border-top:1px solid var(--line);color:var(--muted);font-size:.75rem}}
@media(max-width:800px){{main{{padding:14px 10px 40px}}section{{padding:14px}}.rca-title{{flex-direction:column}}}}
@media print{{body{{background:#fff;color:#111}}main{{max-width:none;padding:0}}section,.report-header,.rca,table,th,td,pre{{background:#fff!important;color:#111;border-color:#aaa}}.secondary-note,.legend,.muted,.rca-meta,.rca-title span,footer{{color:#444}}section,.rca{{break-inside:avoid}}}}
</style></head><body><main>{body}<footer>Built from passive deterministic evidence. Unproven links are shown as incomplete rather than guessed.</footer></main></body></html>"""


def _frequency_range(cpu: dict[str, Any]) -> str:
    current = cpu.get("current_frequency_mhz")
    minimum = cpu.get("minimum_frequency_mhz")
    maximum = cpu.get("maximum_frequency_mhz")
    values = [
        f"current {current} MHz" if current is not None else None,
        f"range {minimum}–{maximum} MHz" if minimum is not None and maximum is not None else None,
    ]
    return " · ".join(value for value in values if value) or "Not reported"


def _inventory_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    stacks = _records(snapshot.get("software_stack_inventory"))
    return {
        "robot_peripherals": len(_physical_peripherals(snapshot)),
        "serial_interfaces": len(_records(snapshot.get("serial_devices"))),
        "sensors": len(_records(snapshot.get("sensor_inventory"))),
        "actuators": len(_records(snapshot.get("actuator_inventory"))),
        "software_present": sum(
            bool(_mapping(item.get("details")).get("installed")) for item in stacks
        ),
        "software_running": sum(
            bool(_mapping(item.get("details")).get("running")) for item in stacks
        ),
    }


def _capability_assessments(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    assessments: list[dict[str, str]] = []
    ros = _ros_overview(snapshot)
    if ros:
        state = str(ros.get("state") or "UNKNOWN").upper()
        assessments.append(
            {
                "name": "ROS 2 runtime",
                "state": state,
                "tone": "ok" if state == "RUNNING" else "warning",
                "evidence": (
                    f"{ros.get('nodes', 0)} nodes, {ros.get('topics', 0)} topics, "
                    f"{ros.get('services', 0)} services on domain {ros.get('domain_id', 'unknown')}"
                ),
                "meaning": (
                    "Graph discovery succeeded; endpoint presence still does not prove message flow or physical function."
                    if state == "RUNNING"
                    else "The active ROS graph and ROS-linked hardware could not be verified from this scan context."
                ),
                "href": "system-blueprint.html#ros",
            }
        )
    for item in _records(snapshot.get("software_stack_inventory")):
        details = _mapping(item.get("details"))
        name = str(item.get("name") or "Unnamed stack")
        installed = details.get("installed")
        configured = details.get("configured")
        running = details.get("running")
        connected = details.get("connected")
        integrated = details.get("integrated")
        stage = str(details.get("state") or item.get("status") or "UNKNOWN").upper()
        if running:
            tone = "ok"
            meaning = (
                "Runtime evidence exists, but end-to-end robot behavior was not actively exercised."
            )
        elif integrated or connected:
            tone = "partial"
            meaning = "Some integration evidence exists without a verified active runtime path."
        elif configured:
            tone = "partial"
            meaning = "Configuration was found, but the stack was not observed running."
        elif installed:
            tone = "neutral"
            meaning = "Software is available on the host; no active capability is established."
        else:
            tone = "muted"
            meaning = "No installation evidence was collected; this is not a fault unless the robot requires it."
        packages = details.get("version") or details.get("detected_packages")
        evidence_parts = [f"stage {stage}"]
        if packages:
            evidence_parts.append(str(packages))
        capability = details.get("capability")
        if capability:
            evidence_parts.append(f"capability: {capability}")
        assessments.append(
            {
                "name": name,
                "state": stage.replace("_", " "),
                "tone": tone,
                "evidence": " · ".join(evidence_parts),
                "meaning": meaning,
                "href": f"system-blueprint.html#stack-{_slug(name)}",
            }
        )
    rank = {"ok": 0, "partial": 1, "warning": 2, "neutral": 3, "muted": 4}
    return sorted(assessments, key=lambda item: (rank.get(item["tone"], 9), item["name"]))


def _hardware_chains(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    chains: list[dict[str, str]] = []
    claimed: set[str] = set()
    for item in _records(snapshot.get("ros_device_inventory")):
        details = _mapping(item.get("details"))
        physical = str(details.get("physical_component") or "Physical component not proven")
        claimed.add(physical.casefold())
        node = details.get("ros_node") or details.get("hardware_node")
        endpoint = details.get("topics") or details.get("channel")
        linux = (
            " · ".join(
                str(value)
                for value in (details.get("driver"), details.get("physical_channel"))
                if value
            )
            or "Linux binding not proven"
        )
        ros_path = " → ".join(str(value) for value in (node, endpoint) if value)
        chains.append(
            {
                "name": str(details.get("kind") or item.get("name") or "ROS device"),
                "physical": physical,
                "linux": linux,
                "ros": ros_path or "ROS ownership not proven",
                "state": str(details.get("state") or item.get("status") or "PRESENCE ONLY"),
                "evidence": str(details.get("confidence") or details.get("health") or "CORRELATED"),
            }
        )
    for item in _records(snapshot.get("sensor_inventory")):
        name = str(item.get("name") or "Detected sensor")
        if name.casefold() in claimed:
            continue
        details = _mapping(item.get("details"))
        chains.append(
            {
                "name": str(details.get("kind") or "sensor"),
                "physical": name,
                "linux": " · ".join(
                    str(value)
                    for value in (
                        details.get("driver"),
                        _channel_summary(details.get("channel")),
                    )
                    if value
                )
                or "Linux binding not reported",
                "ros": "No physical-to-ROS mapping was established",
                "state": str(details.get("health") or details.get("state") or "DETECTED"),
                "evidence": str(details.get("confidence") or "VERIFIED PRESENCE"),
            }
        )
        claimed.add(name.casefold())
    for item in _records(snapshot.get("serial_devices")):
        if str(item.get("transport") or "").startswith("onboard"):
            continue
        name = str(item.get("display_name") or item.get("port") or "Serial interface")
        if name.casefold() in claimed:
            continue
        node = _mapping(item.get("device_node"))
        chains.append(
            {
                "name": "serial / MCU interface",
                "physical": name,
                "linux": " · ".join(
                    str(value)
                    for value in (
                        item.get("driver"),
                        item.get("stable_id_path") or item.get("port"),
                    )
                    if value
                ),
                "ros": "Runtime owner and ROS role not established",
                "state": str(node.get("access") or "ACCESS NOT REPORTED").upper(),
                "evidence": "VERIFIED LINUX ENUMERATION",
            }
        )
    return chains


def _channel_summary(value: Any) -> str:
    channels = _csv(value)
    if not channels:
        return ""
    preferred = [
        channel
        for channel in channels
        if "/by-id/" in channel
        or channel.startswith("/dev/video")
        or channel.startswith("/dev/tty")
    ]
    selected = (preferred or channels)[:3]
    remainder = len(channels) - len(selected)
    suffix = f" · {remainder} more device nodes" if remainder > 0 else ""
    return ", ".join(selected) + suffix


def _working_checks(snapshot: dict[str, Any]) -> list[str]:
    checks: list[str] = []
    cpu = _mapping(snapshot.get("cpu"))
    memory = _mapping(snapshot.get("memory"))
    if isinstance(cpu.get("usage_percent"), (int, float)) and float(cpu["usage_percent"]) < 90:
        checks.append(
            f"CPU snapshot is below the warning threshold ({_percent(cpu['usage_percent'])})."
        )
    if (
        isinstance(memory.get("usage_percent"), (int, float))
        and float(memory["usage_percent"]) < 90
    ):
        checks.append(
            f"Memory snapshot is below the warning threshold ({_percent(memory['usage_percent'])})."
        )
    if _records(snapshot.get("storage_devices")):
        full = [
            partition
            for device in _records(snapshot.get("storage_devices"))
            for partition in _records(device.get("partitions"))
            if isinstance(partition.get("usage_percent"), (int, float))
            and float(partition["usage_percent"]) >= 90
        ]
        if not full:
            checks.append("No collected filesystem is at or above 90% usage.")
    thermals = _records(snapshot.get("thermal_sensors"))
    if thermals and all(
        not isinstance(item.get("critical_celsius"), (int, float))
        or float(item.get("temperature_celsius", 0)) < float(item["critical_celsius"])
        for item in thermals
    ):
        checks.append("All collected thermal readings are below their reported critical limits.")
    ros = _ros_overview(snapshot)
    if str(ros.get("state")) == "RUNNING":
        checks.append(
            f"ROS 2 graph discovery succeeded ({ros.get('nodes', 0)} nodes, {ros.get('topics', 0)} topics)."
        )
    network = _mapping(snapshot.get("network"))
    if network.get("default_interface"):
        checks.append(f"Default network route is present on {network['default_interface']}.")
    return checks or [
        "Snapshot collection completed, but no positive functional check was established."
    ]


def _coverage(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    specs = [
        ("Host / OS", ("identity", "operating_system", "platform")),
        ("Compute / memory", ("cpu", "memory")),
        ("Storage", ("storage_devices",)),
        ("Thermals / power", ("thermal_sensors", "power")),
        ("Network", ("network",)),
        ("USB / serial", ("usb_devices", "serial_devices")),
        ("Robotics software", ("software_stack_inventory",)),
        ("ROS 2 runtime", ("ros_runtime_inventory",)),
        ("ROS ↔ hardware mapping", ("ros_device_inventory",)),
    ]
    coverage: list[dict[str, str]] = []
    for label, keys in specs:
        present = [snapshot.get(key) not in (None, [], {}) for key in keys]
        state = "COLLECTED" if all(present) else "PARTIAL" if any(present) else "NOT AVAILABLE"
        coverage.append({"area": label, "state": state, "source": ", ".join(keys)})
    return coverage


def _priority_next_check(
    actionable: list[dict[str, Any]], unknowns: list[str], coverage: list[dict[str, str]]
) -> str:
    if actionable:
        issue = actionable[0]
        steps = _string_list(issue.get("primary_approach"))
        return steps[0] if steps else f"Verify: {issue.get('title', 'highest-severity finding')}"
    if unknowns:
        return unknowns[0]
    partial = next((item for item in coverage if item["state"] != "COLLECTED"), None)
    if partial:
        return f"Collect missing evidence for {partial['area']}."
    return "Run the intended robot function and compare a new passive snapshot afterward."


def _physical_peripherals(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    devices = []
    for device in _records(snapshot.get("usb_devices")):
        name = str(device.get("display_name") or "").lower()
        device_class = str(device.get("device_class_name") or "").lower()
        if device_class == "hub" or "host controller" in name or "root hub" in name:
            continue
        devices.append(device)
    return devices


def _component_matrix(snapshot: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in _records(snapshot.get("ros_device_inventory")):
        details = _mapping(item.get("details"))
        physical = details.get("physical_component")
        ownership = "Verified physical mapping" if physical else "ROS role only"
        rows.append(
            [
                str(details.get("kind") or item.get("name") or "Unknown role"),
                str(physical or "Not proven"),
                str(details.get("driver") or "Not proven"),
                str(details.get("ros_node") or "Not reported"),
                str(details.get("topics") or details.get("channel") or "Not reported"),
                ownership,
                str(details.get("health") or "Presence only"),
            ]
        )
    return rows


def _ros_flows(snapshot: dict[str, Any]) -> list[list[str]]:
    runtime = _records(snapshot.get("ros_runtime_inventory"))
    topic_types = {
        str(item.get("name")): str(_mapping(item.get("details")).get("type") or "Type not reported")
        for item in runtime
        if item.get("category") == "ROS topic"
    }
    publishers: dict[str, list[str]] = {}
    subscribers: dict[str, list[str]] = {}
    for item in runtime:
        if item.get("category") != "ROS node":
            continue
        name = str(item.get("name") or "Unknown node")
        details = _mapping(item.get("details"))
        for topic in _csv(details.get("publishers")):
            publishers.setdefault(topic, []).append(name)
        for topic in _csv(details.get("subscribers")):
            subscribers.setdefault(topic, []).append(name)
    rows: list[list[str]] = []
    for topic in sorted(set(topic_types) | set(publishers) | set(subscribers)):
        if topic in {"/parameter_events", "/rosout"}:
            continue
        rows.append(
            [
                ", ".join(publishers.get(topic, [])) or "Publisher not captured",
                topic,
                topic_types.get(topic, "Type not reported"),
                ", ".join(subscribers.get(topic, [])) or "No subscriber captured",
            ]
        )
    return rows


def _ros_overview(snapshot: dict[str, Any]) -> dict[str, Any]:
    for item in _records(snapshot.get("ros_runtime_inventory")):
        if item.get("category") == "ROS runtime":
            return _mapping(item.get("details"))
    return {}


def _table(
    headers: list[str], rows: list[list[Any]], *, raw_columns: set[int] | None = None
) -> str:
    if not rows:
        return '<p class="muted">No records available.</p>'
    raw_columns = raw_columns or set()
    head = "".join(f"<th>{_h(value)}</th>" for value in headers)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{value if index in raw_columns else _h(_display(value))}</td>"
            for index, value in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _list(values: list[str], empty: str) -> str:
    return (
        f"<ul>{''.join(f'<li>{_h(value)}</li>' for value in values)}</ul>"
        if values
        else f'<p class="muted">{_h(empty)}</p>'
    )


def _empty_state(message: str) -> str:
    return f'<div class="empty"><p>{_h(message)}</p></div>'


def _metric(label: str, value: Any, tone: str = "neutral") -> str:
    return f'<div class="metric tone-{_h(tone)}"><span>{_h(label)}</span><strong>{_h(_display(value))}</strong></div>'


def _records(value: Any) -> list[dict[str, Any]]:
    return (
        [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    return (
        [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, list)
        else []
    )


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _deduplicate(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _display(value: Any) -> str:
    if value is None or value == "":
        return "Not reported"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value) or "None"
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_display(item)}" for key, item in value.items()) or "None"
    return str(value)


def _bytes(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "Not reported"
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(amount) < 1024 or unit == "PiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "Not reported"


def _duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "Not reported"
    seconds_value = max(0.0, float(value))
    if seconds_value == 0:
        return "0 sec"
    if seconds_value < 1:
        milliseconds = max(1, round(seconds_value * 1000))
        return f"{milliseconds} ms"
    if seconds_value < 60:
        rounded = round(seconds_value, 1)
        return f"{rounded:g} sec"

    total = int(seconds_value)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds:
        parts.append(f"{seconds} sec")
    return " ".join(parts)


def _friendly_time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return _display(value)
    return format_report_time(parsed)


def _percent(value: Any) -> str:
    return f"{float(value):.1f}%" if isinstance(value, (int, float)) else "Not reported"


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _yes_no(value: Any) -> str:
    if value is None:
        return "Not reported"
    return "Yes" if bool(value) else "No"


def _first(value: Any) -> str:
    values = _string_list(value)
    return values[0] if values else "No accepted observation."


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-") or "unknown"


def _issue_id(issue: dict[str, Any]) -> str:
    return "issue-" + _slug(str(issue.get("code") or issue.get("title") or "unknown"))


def _h(value: Any) -> str:
    return html.escape(_display(value), quote=True)


__all__ = [
    "build_report_context",
    "render_diagnostic_report",
    "render_system_blueprint",
]
