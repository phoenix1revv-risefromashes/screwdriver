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
    provider_status: str,
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
        "overall": overall,
        "tone": tone,
        "priority": priority,
        "provider_status": provider_status,
        "scan_id": scan_id,
        "snapshot_sha256": snapshot_sha256,
        "duration": _duration(collection_duration_seconds),
        "focus": focus,
        "created_at": _friendly_time(snapshot.get("created_at")),
        "schema_version": snapshot.get("schema_version") or "Not reported",
        "screwdriver_version": __version__,
    }


def render_compact_snapshot(context: dict[str, Any]) -> str:
    """Render the locked one-page, bottom-to-top operational snapshot."""

    attention = cast(list[dict[str, Any]], context["actionable"])
    attention_html = (
        "".join(_compact_issue(issue) for issue in attention[:5])
        if attention
        else '<div class="empty"><strong>No immediate problem is confirmed.</strong><p>This passive result does not prove that every robot function was exercised.</p></div>'
    )
    return _page(
        f"Quick snapshot — {_mapping(context['identity']).get('hostname', 'robot')}",
        f"""
<header class="hero tone-{_h(context["tone"])}">
  <p class="eyebrow">SCREWDRIVER · QUICK SYSTEM SNAPSHOT</p>
  <div class="title-row"><div><h1>{_h(_mapping(context["identity"]).get("hostname") or "robot")}</h1><p class="lede">{_h(context["overall"])}</p></div><div class="report-links"><a href="system-blueprint.html">System Blueprint</a><a href="diagnostic-report.html">Diagnostic Report</a></div></div>
  {_provenance_strip(context)}
</header>
{_analysis_notice(context)}
<section id="system-stack" class="quick-stack"><div class="section-head"><div><p class="eyebrow">BOTTOM → TOP</p><h2>System stack</h2></div><span class="muted">Only the current operational view</span></div>{_quick_system_layers(context)}</section>
<section id="attention" class="quick-attention"><div class="section-head"><div><p class="eyebrow">IMMEDIATE ATTENTION</p><h2>Problems that can affect operation</h2></div><a href="diagnostic-report.html">Open full diagnosis →</a></div>{attention_html}</section>
""",
    )


def render_system_blueprint(context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Render the locked factual blueprint from base specifications to capabilities."""

    identity = _mapping(context["identity"])
    os_info = _mapping(context["os"])
    platform = _mapping(context["platform"])
    cpu = _mapping(context["cpu"])
    memory = _mapping(context["memory"])
    ros = _mapping(context["ros"])
    software = _complete_robotics_software_inventory(
        _records(snapshot.get("software_stack_inventory"))
    )
    root = _root_partition(snapshot)
    ros_environment = _ros_environment(snapshot)
    return _page(
        f"System blueprint — {identity.get('hostname', 'robot')}",
        f"""
<header class="hero"><p class="eyebrow">SCREWDRIVER · COMPLETE ROBOT SYSTEM BLUEPRINT</p><h1>{_h(identity.get("hostname", "robot"))}</h1><p class="lede">A bottom-to-top specification of the collected robot computer: hardware foundation, buses, devices, Linux integration, execution environment, ROS graph, software stacks and end-to-end capabilities.</p>{_provenance_strip(context)}</header>
<nav class="toc" aria-label="Report sections"><a href="#summary">Summary</a><a href="#platform">Platform</a><a href="#storage">Storage</a><a href="#buses">Buses</a><a href="#devices">Devices</a><a href="#linux">Linux</a><a href="#network">Network</a><a href="#execution">Execution</a><a href="#ros-environment">ROS env</a><a href="#ros-graph">ROS graph</a><a href="#software">Stacks</a><a href="#capabilities">Capabilities</a><a href="#interpretation">Interpretation</a></nav>
{_analysis_notice(context)}
<section id="summary"><p class="eyebrow">01 · COMPLETE SYSTEM SUMMARY</p><h2>What system was inspected</h2>
  <p class="lede">{_h(context["summary"])}</p>
  {_system_summary_table(context, snapshot)}
</section>
<section id="platform"><p class="eyebrow">02 · BASE HARDWARE PLATFORM</p><h2>Board, operating system and compute resources</h2>
  <h3>Board and platform identity</h3>{_kv_table({"Hostname": identity.get("hostname"), "Manufacturer": platform.get("manufacturer"), "Product": platform.get("product_name"), "Board": platform.get("board_name"), "Board version": platform.get("board_version"), "Firmware / L4T": platform.get("firmware_version") or _mapping(platform.get("details")).get("l4t"), "Machine type": platform.get("machine_type"), "Operating system": os_info.get("distribution"), "Kernel": os_info.get("kernel"), "Kernel build": os_info.get("kernel_build"), "Architecture": os_info.get("architecture"), "Boot mode": os_info.get("boot_mode"), "Init system": os_info.get("init_system"), "Package manager": os_info.get("package_manager"), "Uptime": _duration(os_info.get("uptime_seconds")), "Processes observed": os_info.get("process_count")})}
  <div class="two-col"><div><h3>CPU</h3>{_kv_table({"Model": cpu.get("model"), "Vendor": cpu.get("vendor"), "Physical cores": cpu.get("physical_cores"), "Logical / online CPUs": f"{cpu.get('logical_cpus')} / {cpu.get('online_cpus')}", "Frequency": _frequency_range(cpu), "Governor": cpu.get("governor"), "Usage snapshot": _percent(cpu.get("usage_percent")), "Load average": cpu.get("load_average"), "Caches": cpu.get("caches")})}</div><div><h3>Memory</h3>{_kv_table({"Total": _bytes(memory.get("total_bytes")), "Used": _bytes(memory.get("used_bytes")), "Available": _bytes(memory.get("available_bytes")), "Usage": _percent(memory.get("usage_percent")), "Swap total": _bytes(memory.get("swap_total_bytes")), "Swap used": _bytes(memory.get("swap_used_bytes")), "Swap usage": _percent(memory.get("swap_usage_percent"))})}</div></div>
  <h3>GPU and accelerators</h3>{_gpu_table(_records(snapshot.get("gpus")))}
</section>
<section id="storage"><p class="eyebrow">03 · STORAGE, POWER AND THERMALS</p><h2>Persistent storage and operating envelope</h2>
  <p class="section-intro">Root filesystem: {_h(root.get("path") if root else "not identified")} · {_h(root.get("mount_point") if root else "mount not identified")} · {_h(_percent(root.get("usage_percent")) if root else "usage not reported")}</p>
  {_storage_table(_records(snapshot.get("storage_devices")))}
  <div class="two-col"><div><h3>Power</h3>{_kv_table(_mapping(snapshot.get("power")))}</div><div><h3>Thermal and cooling observations</h3>{_thermal_table(_records(snapshot.get("thermal_sensors")))}</div></div>
</section>
<section id="buses"><p class="eyebrow">04 · PHYSICAL BUSES AND CONTROLLERS</p><h2>How hardware reaches the computer</h2>
  {_bus_summary(snapshot)}
  <h3>Complete USB topology</h3>{_usb_topology_table(_records(snapshot.get("usb_devices")))}
  <p class="section-intro">PCIe, I²C, SPI and GPIO controller inventories are shown only when collected. Their absence from this snapshot is not interpreted as hardware absence.</p>
</section>
<section id="devices"><p class="eyebrow">05 · PHYSICAL DEVICE INVENTORY</p><h2>Robot-facing hardware grouped by function</h2>
  <h3>USB peripherals</h3>{_usb_detail_table(context["physical"])}
  <h3>Serial and MCU interfaces</h3>{_serial_detail_table(_records(snapshot.get("serial_devices")))}
  <h3>Detected sensors</h3>{_inventory_detail_table(_records(snapshot.get("sensor_inventory")), "sensor")}
  <h3>Detected actuators and outputs</h3>{_inventory_detail_table(_records(snapshot.get("actuator_inventory")), "actuator")}
</section>
<section id="linux"><p class="eyebrow">06 · LINUX DEVICE AND DRIVER LAYER</p><h2>Physical device → driver → device path → access</h2>
  {_linux_binding_table(snapshot)}
  <p class="section-intro">Process ownership is displayed only when the collector or a validated probe established it.</p>
</section>
<section id="network"><p class="eyebrow">07 · NETWORK AND COMMUNICATION ARCHITECTURE</p><h2>External, internal and virtual transports</h2>{_network_table(_mapping(context["network"]))}</section>
<section id="execution"><p class="eyebrow">08 · PROCESSES, SERVICES AND CONTAINERS</p><h2>Software execution environment</h2>
  {_execution_environment(snapshot)}
</section>
<section id="ros-environment"><p class="eyebrow">09 · ROS 2 INSTALLATION AND ENVIRONMENT</p><h2>Installation, shell context and DDS identity</h2>
  {_kv_table({"ROS detected": _yes_no(ros_environment.get("detected")), "Installed distributions": ros_environment.get("installed_distributions"), "Active distribution in collection shell": ros_environment.get("active_distribution"), "Environment sourced in collection shell": _yes_no(ros_environment.get("environment_sourced")), "ROS executable": ros_environment.get("ros2_executable"), "Domain ID": ros.get("domain_id") if ros.get("domain_id") is not None else ros_environment.get("ros_domain_id"), "ROS localhost only": ros_environment.get("ros_localhost_only"), "DDS middleware": _middleware(ros.get("middleware") or ros_environment.get("rmw_implementation")), "DDS configuration": ros_environment.get("dds_configuration"), "Indexed packages": ros_environment.get("indexed_package_count"), "Installation prefixes": ros_environment.get("prefix_paths"), "Workspaces": ros_environment.get("workspaces"), "Environment recovered from runtime": _yes_no(ros.get("environment_recovered"))})}
  <div class="callout"><strong>State distinction:</strong> installed software, a sourced shell, a discoverable ROS graph and a functioning robot application are separate evidence states.</div>
</section>
<section id="ros-graph"><p class="eyebrow">10 · COMPLETE ROS 2 RUNTIME GRAPH</p><h2>Nodes, topics, services and actions</h2>
  {_kv_table({"Graph state": ros.get("state"), "Distribution": ros.get("ros_distro"), "Domain ID": ros.get("domain_id"), "DDS middleware": _middleware(ros.get("middleware")), "Discovery": ros.get("discovery_mode"), "Environment recovered": _yes_no(ros.get("environment_recovered")), "Nodes": ros.get("nodes"), "Topics": ros.get("topics"), "Services": ros.get("services"), "Actions": ros.get("actions"), "Probe boundary": ros.get("probe")})}
  {_ros_inventory_tables(snapshot)}
  <h3 id="data-flow">Publisher → topic → subscriber relationships</h3><p class="section-intro">Graph participation does not prove message rate, payload quality or physical ownership.</p>{_flow_table(context["flows"])}
  <h3>ROS-to-hardware ownership</h3>{_matrix_table(context["component_matrix"])}
</section>
<section id="software"><p class="eyebrow">11 · ROBOTICS SOFTWARE STACKS</p><h2>Installation → configuration → runtime → integration</h2>
  <p class="section-intro">Software is grouped by capability. Installed never means operational; each later stage requires separate evidence.</p>
  <h3>Complete robotics stack status matrix</h3>{_robotics_stack_status_matrix(software)}
  <h3>Collected package, configuration and runtime evidence</h3>
  {_software_table(software, include_anchors=True)}
</section>
<section id="capabilities"><p class="eyebrow">12 · END-TO-END ROBOT CAPABILITY PATHS</p><h2>Physical input/output → Linux → ROS → robot function</h2>
  {_chain_cards(context["hardware_chains"])}
  <h3>Capability readiness</h3>{_capability_cards(context["capabilities"])}
</section>
<section id="interpretation"><p class="eyebrow">13 · ENGINEERING INTERPRETATION</p><h2>Meaning of the complete collected system</h2>
  <h3>Cross-layer observations</h3>{_list(context["observations"], "No additional model interpretation was accepted.")}
  <h3>What cannot yet be concluded</h3>{_list(context["unknowns"], "No explicit evidence limit was recorded.")}
  <div class="callout"><strong>Passive boundary:</strong> sensor payloads were not judged for quality, actuators were not commanded, and endpoint presence was not treated as proof of successful robot behavior.</div>
</section>
<section id="coverage"><p class="eyebrow">14 · BLUEPRINT COMPLETENESS</p><h2>Collected and missing evidence</h2>{_coverage_table(context["coverage"])}</section>
{_report_metadata(context)}
{_evidence_appendix(snapshot)}
""",
    )


def render_diagnostic_report(context: dict[str, Any], probes: list[dict[str, Any]]) -> str:
    """Render the locked problem-centered diagnostic and recovery report."""

    identity = _mapping(context["identity"])
    issues = cast(list[dict[str, Any]], context["issues"])
    groups = [
        ("CONFIRMED_FAILURE", "Confirmed failures"),
        ("DEGRADED", "Degraded behavior"),
        ("CONFIGURATION_WARNING", "Configuration warnings"),
        ("ADVISORY", "Advisories"),
        ("NEEDS_CONFIRMATION", "Requires operator confirmation"),
    ]
    issue_sections: list[str] = []
    for classification, title in groups:
        selected = [issue for issue in issues if issue.get("classification") == classification]
        issue_sections.append(
            f'<section id="{classification.lower()}"><h2>{_h(title)} <span class="count">{len(selected)}</span></h2>'
            + (
                "".join(_detailed_issue(issue, index) for index, issue in enumerate(selected, 1))
                if selected
                else _empty_state(f"No {title.casefold()} were accepted from this snapshot.")
            )
            + "</section>"
        )
    probe_section = _probe_section(probes)
    counts = {
        severity: sum(issue.get("severity") == severity for issue in issues)
        for severity in _SEVERITY_ORDER
    }
    return _page(
        f"Diagnostic report — {identity.get('hostname', 'robot')}",
        f"""
<header class="hero tone-{_h(context["tone"])}"><p class="eyebrow">SCREWDRIVER · COMPLETE ENGINEERING DIAGNOSTICS</p><h1>{_h(context["overall"])}</h1><p class="lede">Misconfigurations, failures, inconsistencies and operational risks—each traced to evidence, diagnostic commands, a controlled solution, success criteria and rollback guidance.</p>{_provenance_strip(context)}</header>
<nav class="toc" aria-label="Report sections"><a href="#overview">Summary</a><a href="#confirmed_failure">Failures</a><a href="#degraded">Degraded</a><a href="#configuration_warning">Misconfigurations</a><a href="#advisory">Advisories</a><a href="#needs_confirmation">Unconfirmed</a><a href="#inconsistencies">Inconsistencies</a><a href="#verification">Verification</a></nav>
{_analysis_notice(context)}
<section id="overview"><p class="eyebrow">01 · DIAGNOSTIC SUMMARY</p><h2>Prioritized system problems</h2><div class="metric-grid">{_metric("Critical", counts["CRITICAL"], "critical" if counts["CRITICAL"] else "neutral")}{_metric("High", counts["HIGH"], "high" if counts["HIGH"] else "neutral")}{_metric("Medium", counts["MEDIUM"], "warning" if counts["MEDIUM"] else "neutral")}{_metric("Low", counts["LOW"])}{_metric("Misconfigurations", sum(issue.get("classification") == "CONFIGURATION_WARNING" for issue in issues), "warning")}{_metric("Unconfirmed risks", sum(issue.get("classification") == "NEEDS_CONFIRMATION" for issue in issues))}</div>
  <div class="priority"><p class="eyebrow">FIRST INVESTIGATION STEP</p><strong>{_h(context["priority"])}</strong></div>
  {_issue_register(issues)}
</section>
{"".join(issue_sections)}
{probe_section}
<section id="inconsistencies"><p class="eyebrow">07 · CROSS-SYSTEM INCONSISTENCIES</p><h2>Relationships that do not fully agree</h2>{_cross_system_inconsistencies(context)}</section>
<section id="risks"><p class="eyebrow">08 · UNCONFIRMED RISKS</p><h2>Possible problems awaiting evidence</h2>{_unconfirmed_risks(issues, context["unknowns"])}</section>
<section id="verification"><p class="eyebrow">09 · FINAL VERIFICATION</p><h2>Closeout checklist</h2>{_verification_checklist()}<div class="callout"><strong>No repairs executed.</strong> System-changing commands are recommendations for human review only. Apply one controlled change at a time and retain a rollback path.</div></section>
{_report_metadata(context)}
""",
    )


def _compact_issue(issue: dict[str, Any]) -> str:
    target = _issue_id(issue)
    severity = str(issue.get("severity") or "INFO")
    classification = str(issue.get("classification") or "NEEDS_CONFIRMATION")
    return f"""<article class="finding severity-{_h(severity.lower())}"><div><span class="pill">{_h(severity)} · {_h(classification)}</span><h3>{_h(issue.get("title"))}</h3></div><p><strong>Impact:</strong> {_h(issue.get("operational_impact") or "Impact not established.")}</p><p><strong>Observed:</strong> {_h(_first(issue.get("observed")))}</p><a href="diagnostic-report.html#{target}">Open finding evidence and recovery criteria →</a></article>"""


def _quick_system_layers(context: dict[str, Any]) -> str:
    snapshot = _mapping(context.get("snapshot"))
    platform = _mapping(context.get("platform"))
    os_info = _mapping(context.get("os"))
    cpu = _mapping(context.get("cpu"))
    memory = _mapping(context.get("memory"))
    network = _mapping(context.get("network"))
    ros = _mapping(context.get("ros"))
    counts = _mapping(context.get("inventory_counts"))
    root = _root_partition(snapshot)
    gpu = _accelerator_summary(snapshot)
    serial = _records(snapshot.get("serial_devices"))
    denied = sum(_mapping(item.get("device_node")).get("access") == "denied" for item in serial)
    drivers = sorted(
        {
            str(driver)
            for item in cast(list[dict[str, Any]], context.get("physical", []))
            for driver in item.get("drivers", [])
            if driver
        }
    )
    stacks = _records(context.get("capabilities"))
    relevant = [
        f"{item.get('name')}: {item.get('state')}" for item in stacks if item.get("tone") != "muted"
    ][:6]
    physical_names = [
        str(item.get("display_name"))
        for item in cast(list[dict[str, Any]], context.get("physical", []))
        if item.get("display_name")
    ][:6]
    primary_ip = _primary_ip(network)
    layers = [
        (
            "01",
            "Compute",
            "RUNNING",
            f"{platform.get('product_name') or platform.get('board_name') or 'Linux computer'} · {os_info.get('distribution') or 'Linux'} · kernel {os_info.get('kernel') or 'not reported'}",
            f"{cpu.get('physical_cores') or cpu.get('logical_cpus') or 'Unknown'} CPU cores · {gpu} · memory {_percent(memory.get('usage_percent'))} · root {_bytes(root.get('total_bytes')) if root else 'not identified'}",
        ),
        (
            "02",
            "Physical hardware",
            "PRESENT" if counts.get("robot_peripherals") else "NOT ESTABLISHED",
            ", ".join(physical_names) or "No robot-facing peripheral identified",
            f"{counts.get('sensors', 0)} sensor records · {counts.get('actuators', 0)} actuator records · {counts.get('serial_interfaces', 0)} serial interfaces · primary network {network.get('default_interface') or 'not established'} {primary_ip}",
        ),
        (
            "03",
            "Linux integration",
            "PARTIAL" if denied else "PRESENT",
            f"Drivers: {', '.join(drivers[:8]) or 'not reported'}",
            f"{denied} serial access issue{'s' if denied != 1 else ''} · Docker {_stack_state(snapshot, 'Docker')} · stable USB/serial identities retained in Blueprint",
        ),
        (
            "04",
            "ROS 2",
            str(ros.get("state") or "NOT ESTABLISHED"),
            f"{ros.get('ros_distro') or _installed_ros_distribution(snapshot)} · domain {ros.get('domain_id', 'not reported')} · {_middleware(ros.get('middleware'))}",
            f"{ros.get('nodes', 0)} nodes · {ros.get('topics', 0)} topics · {ros.get('services', 0)} services · {ros.get('actions', 0)} actions · {len(context.get('component_matrix', []))} verified hardware mappings",
        ),
        (
            "05",
            "Robot capabilities",
            "PARTIAL" if relevant else "NOT ESTABLISHED",
            " · ".join(relevant) or "No capability stage established",
            "Installed is not treated as operational; complete capability paths are documented in the System Blueprint.",
        ),
    ]
    return (
        '<div class="layer-stack">'
        + "".join(
            f"""<article class="system-layer"><span class="layer-number">{number}</span><div class="layer-copy"><div class="layer-title"><h3>{_h(title)}</h3><span class="layer-state">{_h(state)}</span></div><p>{_h(primary)}</p><small>{_h(secondary)}</small></div></article>"""
            for number, title, state, primary, secondary in layers
        )
        + "</div>"
    )


def _detailed_issue(issue: dict[str, Any], index: int) -> str:
    commands = _string_list(issue.get("diagnostic_commands"))
    references = _string_list(issue.get("evidence_references"))
    command_html = _diagnostic_commands(issue, commands)
    refs = (
        " ".join(
            f'<a class="evidence-ref" href="system-blueprint.html#{_evidence_id(ref)}">{_h(ref)}</a>'
            for ref in references
        )
        if references
        else '<span class="muted">No exact evidence reference accepted.</span>'
    )
    alternatives = (
        [
            _string_list(value)
            for value in issue.get("alternative_approaches", [])
            if isinstance(value, list)
        ]
        if isinstance(issue.get("alternative_approaches"), list)
        else []
    )
    alternative_html = "".join(
        f"<h5>Alternative {number}</h5>{_ordered(steps)}"
        for number, steps in enumerate(alternatives, 1)
        if steps
    )
    return f"""<details id="{_issue_id(issue)}" class="issue severity-{_h(str(issue.get("severity", "INFO")).lower())}" open><summary><span class="issue-number">{index}</span><span><strong>{_h(issue.get("title"))}</strong><small>{_h(issue.get("severity"))} · {_h(issue.get("classification"))} · {_h(issue.get("evidence_level") or "UNKNOWN")} evidence · observation {_h(issue.get("observation_confidence", issue.get("confidence")))}% · diagnosis {_h(issue.get("diagnosis_confidence", issue.get("confidence")))}%</small></span></summary><div class="issue-body"><div class="issue-scope">{_issue_scope(issue)}</div><div class="two-col"><div><h4>Expected state</h4><p>{_h(issue.get("expected_state") or "No expected state was supplied.")}</p></div><div><h4>Observed evidence</h4>{_list(_string_list(issue.get("observed")), "No accepted observation.")}</div></div><div class="impact"><h4>Operational impact</h4><p>{_h(issue.get("operational_impact") or "Impact has not been established.")}</p></div><h4>Evidence trace</h4><p>{refs}</p><p><a href="system-blueprint.html#linux">Inspect the related system layer and source evidence →</a></p><h4>Probable causes, in diagnostic order</h4>{_list(_string_list(issue.get("probable_causes")), "Cause not established.")}{command_html}{_system_change_examples(issue)}<h4>Step-by-step solution</h4>{_ordered(_solution_steps(issue))}{f"<h4>Alternative investigation paths</h4>{alternative_html}" if alternative_html else ""}<h4>Measurable success criteria</h4>{_list(_string_list(issue.get("success_criteria")), "Repeat inspection no longer reports the condition.")}<h4>Rollback plan</h4>{_ordered(_rollback_steps(issue))}</div></details>"""


def _system_summary_table(context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    platform = _mapping(context.get("platform"))
    os_info = _mapping(context.get("os"))
    cpu = _mapping(context.get("cpu"))
    memory = _mapping(context.get("memory"))
    network = _mapping(context.get("network"))
    ros = _mapping(context.get("ros"))
    root = _root_partition(snapshot)
    counts = _mapping(context.get("inventory_counts"))
    present_stacks = [
        str(item.get("name"))
        for item in _records(snapshot.get("software_stack_inventory"))
        if _mapping(item.get("details")).get("installed")
    ]
    return _table(
        ["System layer", "Collected specification"],
        [
            [
                "Computer",
                f"{platform.get('manufacturer')} · {platform.get('product_name') or platform.get('board_name')}",
            ],
            [
                "Operating system",
                f"{os_info.get('distribution')} · kernel {os_info.get('kernel')} · {os_info.get('architecture')}",
            ],
            [
                "Compute",
                f"{cpu.get('model')} · {cpu.get('physical_cores') or cpu.get('logical_cpus')} cores · {_accelerator_summary(snapshot)}",
            ],
            [
                "Memory",
                f"{_bytes(memory.get('used_bytes'))} used of {_bytes(memory.get('total_bytes'))} ({_percent(memory.get('usage_percent'))}) · swap {_percent(memory.get('swap_usage_percent'))}",
            ],
            [
                "Root storage",
                f"{root.get('path') if root else 'Not identified'} · {root.get('filesystem') if root else 'filesystem not reported'} · {_bytes(root.get('total_bytes')) if root else 'capacity not reported'} · {_percent(root.get('usage_percent')) if root else 'usage not reported'} used",
            ],
            [
                "Primary network",
                f"{network.get('default_interface') or 'Not established'} · {_primary_ip(network)} · gateway {network.get('default_gateway') or 'not reported'}",
            ],
            [
                "Physical I/O",
                f"{counts.get('robot_peripherals', 0)} robot-facing USB peripherals · {counts.get('serial_interfaces', 0)} serial interfaces · {counts.get('sensors', 0)} sensors · {counts.get('actuators', 0)} actuators",
            ],
            [
                "ROS 2",
                f"{ros.get('ros_distro') or _installed_ros_distribution(snapshot)} · graph {ros.get('state') or 'not established'} · domain {ros.get('domain_id', 'not reported')} · {ros.get('nodes', 0)} nodes / {ros.get('topics', 0)} topics / {ros.get('services', 0)} services / {ros.get('actions', 0)} actions",
            ],
            [
                "Robotics software",
                ", ".join(present_stacks) or "No installed robotics stack was collected",
            ],
        ],
    )


def _root_partition(snapshot: dict[str, Any]) -> dict[str, Any]:
    for device in _records(snapshot.get("storage_devices")):
        for partition in _records(device.get("partitions")):
            if partition.get("mount_point") == "/":
                return partition
    return {}


def _primary_ip(network: dict[str, Any]) -> str:
    default = network.get("default_interface")
    for interface in _records(network.get("interfaces")):
        if interface.get("name") == default or interface.get("is_default_route"):
            addresses = _string_list(interface.get("ipv4_addresses"))
            return addresses[0] if addresses else "IP not reported"
    return "IP not reported"


def _ros_environment(snapshot: dict[str, Any]) -> dict[str, Any]:
    for source in (snapshot.get("components"), snapshot.get("software_stack_inventory")):
        for item in _records(source):
            if "ROS installation" in str(item.get("name")):
                return _mapping(item.get("details"))
    return {}


def _installed_ros_distribution(snapshot: dict[str, Any]) -> str:
    environment = _ros_environment(snapshot)
    return str(
        environment.get("active_distribution")
        or environment.get("installed_distributions")
        or "distribution not reported"
    )


def _stack_state(snapshot: dict[str, Any], name: str) -> str:
    for item in _records(snapshot.get("software_stack_inventory")):
        if str(item.get("name")).casefold() == name.casefold():
            details = _mapping(item.get("details"))
            return str(details.get("state") or item.get("status") or "detected").upper()
    return "NOT ESTABLISHED"


def _frequency_range(cpu: dict[str, Any]) -> str:
    current = cpu.get("current_frequency_mhz")
    minimum = cpu.get("minimum_frequency_mhz")
    maximum = cpu.get("maximum_frequency_mhz")
    values = [
        f"current {current} MHz" if current is not None else None,
        f"range {minimum}–{maximum} MHz" if minimum is not None and maximum is not None else None,
    ]
    return " · ".join(value for value in values if value) or "Not reported"


def _gpu_table(records: list[dict[str, Any]]) -> str:
    return _table(
        ["GPU / accelerator", "Vendor", "Driver", "Bus", "Memory", "Utilization", "Temperature"],
        [
            [
                item.get("model"),
                item.get("vendor"),
                item.get("driver"),
                item.get("bus_id"),
                _bytes(item.get("memory_bytes")),
                _percent(item.get("usage_percent")),
                f"{item.get('temperature_celsius')} °C"
                if item.get("temperature_celsius") is not None
                else None,
            ]
            for item in records
        ],
    )


def _bus_summary(snapshot: dict[str, Any]) -> str:
    usb = _records(snapshot.get("usb_devices"))
    serial = _records(snapshot.get("serial_devices"))
    network = _mapping(snapshot.get("network"))
    can = [
        item
        for item in _records(network.get("interfaces"))
        if str(item.get("name", "")).startswith("can")
        or str(item.get("interface_type", "")).casefold() == "can"
    ]
    hubs = sum(str(item.get("device_class_name", "")).casefold() == "hub" for item in usb)
    controllers = sum(
        "host controller" in str(item.get("display_name", "")).casefold() for item in usb
    )
    return _table(
        ["Bus / transport", "Collected evidence", "Role"],
        [
            [
                "USB",
                f"{controllers} host controllers · {hubs} hubs · {max(0, len(usb) - hubs - controllers)} downstream devices",
                "Sensors, audio, HID, MCU/debug and serial bridges",
            ],
            [
                "Serial / UART",
                f"{len(serial)} interfaces · {sum(bool(item.get('stable_id_path')) for item in serial)} stable identities",
                "MCU, controller and board communication",
            ],
            [
                "CAN",
                ", ".join(f"{item.get('name')} ({item.get('state')})" for item in can)
                or "No CAN interface collected",
                "Robot control bus when required",
            ],
            [
                "PCIe / I²C / SPI / GPIO",
                "Dedicated controller inventory not collected in this schema",
                "Not interpreted as absent",
            ],
        ],
    )


def _usb_topology_table(records: list[dict[str, Any]]) -> str:
    return _table(
        ["Bus/device", "Identity", "Class", "USB link", "Drivers"],
        [
            [
                f"{item.get('bus_number')}:{item.get('device_number')}",
                f"{item.get('display_name')} [{item.get('usb_id')}]",
                item.get("device_class_name"),
                f"USB {item.get('usb_version')} · {item.get('speed_mbps')} Mb/s",
                item.get("drivers"),
            ]
            for item in records
        ],
    )


def _linux_binding_table(snapshot: dict[str, Any]) -> str:
    rows: list[list[Any]] = []
    for item in _physical_peripherals(snapshot):
        nodes = [_node_access(node) for node in _records(item.get("device_nodes"))]
        rows.append(
            [
                item.get("display_name"),
                f"USB {item.get('usb_id')}",
                item.get("drivers"),
                nodes,
                "Process owner not collected",
            ]
        )
    for item in _records(snapshot.get("serial_devices")):
        rows.append(
            [
                item.get("display_name") or item.get("port"),
                item.get("transport"),
                item.get("driver"),
                _node_access(item.get("device_node")),
                "Process owner not collected",
            ]
        )
    return _table(
        [
            "Physical component",
            "Bus / identity",
            "Kernel driver",
            "Device path and access",
            "Runtime owner",
        ],
        rows,
    )


def _execution_environment(snapshot: dict[str, Any]) -> str:
    os_info = _mapping(snapshot.get("operating_system"))
    docker = next(
        (
            item
            for item in _records(snapshot.get("software_stack_inventory"))
            if str(item.get("name")).casefold() == "docker"
        ),
        None,
    )
    details = _mapping(docker.get("details")) if docker else {}
    return _kv_table(
        {
            "Init system": os_info.get("init_system"),
            "Processes observed": os_info.get("process_count"),
            "Docker installed": _yes_no(details.get("installed")) if docker else "Not collected",
            "Docker runtime state": details.get("state")
            or ("Detected" if docker else "Not collected"),
            "Docker executable": details.get("executable"),
            "Running containers": "Container inventory not collected",
            "Robotics systemd services": "Service inventory not collected",
            "Device-owning processes": "Ownership requires validated process/port probes",
            "Host versus container workload": "Not established by this snapshot",
        }
    )


def _ros_inventory_tables(snapshot: dict[str, Any]) -> str:
    runtime = _records(snapshot.get("ros_runtime_inventory"))
    groups = [
        ("ROS nodes", "ROS node", ("state", "publishers", "subscribers", "services", "actions")),
        ("ROS topics", "ROS topic", ("state", "type", "transport")),
        ("ROS services", "ROS service", ("state", "type", "transport")),
        ("ROS actions", "ROS action", ("state", "type", "transport")),
    ]
    sections = []
    for title, category, keys in groups:
        items = [item for item in runtime if item.get("category") == category]
        if not items:
            sections.append(
                f"<h3>{_h(title)}</h3>{_empty_state(f'No {title.casefold()} were captured.')}"
            )
            continue
        rows = []
        for item in items:
            details = _mapping(item.get("details"))
            rows.append([item.get("name"), *(details.get(key) for key in keys)])
        sections.append(
            f"<h3>{_h(title)}</h3>"
            + _table(["Name", *(key.replace("_", " ").title() for key in keys)], rows)
        )
    return "".join(sections)


def _issue_scope(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    if code.startswith("ROS_"):
        layer, capability = "ROS environment / runtime", "ROS discovery and robot application"
    elif code.startswith("SERIAL_"):
        layer, capability = "Linux device access", "MCU, controller or telemetry path"
    elif code.startswith(("CPU_", "MEMORY_")):
        layer, capability = "Compute resources", "Timing, perception and interaction workloads"
    elif code.startswith("FILESYSTEM_"):
        layer, capability = "Storage", "Logs, recordings and runtime data"
    elif code.startswith("THERMAL_"):
        layer, capability = "Thermal / cooling", "Sustained compute performance"
    else:
        layer, capability = "Cross-system", "Robot capability requires confirmation"
    return f"<span><small>AFFECTED LAYER</small><strong>{_h(layer)}</strong></span><span><small>POSSIBLE CAPABILITY IMPACT</small><strong>{_h(capability)}</strong></span>"


def _diagnostic_commands(issue: dict[str, Any], commands: list[str]) -> str:
    if not commands:
        return '<h4>Diagnostic commands</h4><p class="muted">No executable read-only command was validated for this finding.</p>'
    cards = []
    for command in commands:
        if command.startswith("ros2 node"):
            purpose = (
                "Enumerates discoverable ROS nodes in the active domain and middleware context."
            )
            healthy = "The operator-declared nodes are present. Missing nodes indicate launch, discovery or environment mismatch."
        elif command.startswith("ros2 topic"):
            purpose = "Lists discovered topics and message types without publishing data."
            healthy = "Required topics and types match the robot graph contract."
        elif command.startswith("udevadm"):
            purpose = (
                "Confirms kernel identity, driver metadata and stable attributes for the device."
            )
            healthy = "The intended device resolves consistently to the expected driver and stable identity."
        elif command.startswith("lsof"):
            purpose = "Shows whether a process currently owns the device path."
            healthy = "The expected process owns the port, or no owner exists when the application is intentionally stopped."
        elif command.startswith("df"):
            purpose = "Reports filesystem type, capacity and free space."
            healthy = "The runtime filesystem remains below its warning threshold with adequate write headroom."
        elif command.startswith("sensors"):
            purpose = "Reads exposed thermal sensors without changing cooling policy."
            healthy = (
                "Temperatures remain below warning and critical limits under the expected workload."
            )
        else:
            purpose = "Collects read-only evidence relevant to this finding."
            healthy = "Output matches the declared healthy state for the affected component."
        cards.append(
            f'<div class="command-card"><span class="safe-label">READ-ONLY</span><pre><code>{_h(command)}</code></pre><p><strong>Checks:</strong> {_h(purpose)}</p><p><strong>Healthy result:</strong> {_h(healthy)}</p></div>'
        )
    return f'<h4>Diagnostic commands</h4><div class="command-grid">{"".join(cards)}</div>'


def _solution_steps(issue: dict[str, Any]) -> list[str]:
    code = str(issue.get("code") or "")
    primary = _string_list(issue.get("primary_approach"))
    steps = [
        "Confirm that the affected component and capability are required by the deployed robot profile.",
        "Run the read-only diagnostic commands above and save their output with this scan ID.",
    ]
    steps.extend(primary)
    if code.startswith("ROS_"):
        steps.extend(
            [
                "Record the environment of the known-good launch context: ROS_DISTRO, ROS_DOMAIN_ID, RMW_IMPLEMENTATION and active workspace prefixes.",
                "Back up the affected launch, environment or DDS configuration before editing it.",
                "Apply one human-approved correction so the inspection shell and robot workload use the same ROS underlay, overlay, domain and middleware.",
                "Reload only the affected shell, service or container; do not restart unrelated robot components.",
            ]
        )
    elif code.startswith("SERIAL_"):
        steps.extend(
            [
                "Resolve the intended peripheral by its stable /dev/serial/by-id identity instead of relying only on tty numbering.",
                "Record the current owner, group, mode, udev properties and active process owner before any change.",
                "If access is required, apply a reviewed identity/group or udev-rule correction for the intended runtime user; do not use world-writable permissions.",
                "Reload the relevant device rule or reconnect the device during an approved maintenance window.",
            ]
        )
    elif code.startswith(("CPU_", "MEMORY_")):
        steps.extend(
            [
                "Identify the process responsible for sustained resource pressure and correlate it with the expected robot workload.",
                "Capture the existing service/container resource configuration before changing limits or application settings.",
                "Apply one reviewed workload, leak, cache or resource-limit correction and observe the same operating scenario again.",
            ]
        )
    elif code.startswith("FILESYSTEM_"):
        steps.extend(
            [
                "Identify which logs, recordings, images, containers or datasets consume the affected filesystem.",
                "Back up or archive required data before any deletion, rotation or relocation.",
                "Apply one approved retention, rotation, cleanup or storage-allocation correction.",
            ]
        )
    elif code.startswith("THERMAL_"):
        steps.extend(
            [
                "Inspect fan operation, airflow, heatsink contact and the workload that coincides with the high reading.",
                "Record the current power mode and cooling policy before changing either.",
                "Apply one approved cooling, power-mode or workload correction and repeat the same load safely.",
            ]
        )
    else:
        steps.append("Apply one human-approved correction to the smallest affected scope.")
    steps.extend(
        [
            "Repeat the original diagnostic commands and compare the result with the saved pre-change evidence.",
            "Verify the affected robot capability, then create a new passive Screwdriver scan and confirm the finding is resolved.",
        ]
    )
    return _deduplicate(steps)


def _system_change_examples(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    if code.startswith("ROS_"):
        commands = [
            "source /opt/ros/<distribution>/setup.bash",
            "source <workspace>/install/setup.bash",
        ]
        note = "Use the exact underlay, overlay, domain and middleware confirmed from the deployed robot launch context."
    elif code.startswith("SERIAL_"):
        commands = [
            "sudo usermod -aG <device-group> <runtime-user>",
            "sudo udevadm control --reload-rules",
        ]
        note = "Use only after the required device, intended runtime identity and existing group/udev policy are confirmed. Re-login may be required. Never use chmod 666."
    else:
        return ""
    blocks = "".join(f"<pre><code>{_h(command)}</code></pre>" for command in commands)
    return f'<div class="change-warning"><span>SYSTEM-CHANGING EXAMPLES — HUMAN REVIEW REQUIRED</span><p>{_h(note)}</p>{blocks}</div>'


def _rollback_steps(issue: dict[str, Any]) -> list[str]:
    code = str(issue.get("code") or "")
    if code.startswith("ROS_"):
        specific = "Restore the backed-up launch/environment/DDS configuration and reload only the affected runtime context."
    elif code.startswith("SERIAL_"):
        specific = "Restore the previous group, identity or udev rule, reload the rule and reconnect the device during the maintenance window."
    elif code.startswith(("CPU_", "MEMORY_")):
        specific = "Restore the previous service, container or application resource configuration."
    elif code.startswith("FILESYSTEM_"):
        specific = "Restore archived data or the previous retention configuration; do not overwrite newer runtime data."
    elif code.startswith("THERMAL_"):
        specific = "Restore the recorded power mode and cooling policy if the change worsens stability or temperature."
    else:
        specific = "Restore the backed-up configuration or previous component setting."
    return [
        specific,
        "Repeat the read-only diagnostic check after rollback.",
        "Record the rollback result and retain both scan IDs for comparison.",
    ]


def _cross_system_inconsistencies(context: dict[str, Any]) -> str:
    chains = _records(context.get("hardware_chains"))
    rows = []
    for chain in chains:
        ros = str(chain.get("ros") or "")
        state = str(chain.get("state") or "")
        if (
            "not established" in ros.casefold()
            or "not proven" in ros.casefold()
            or state in {"DENIED", "PRESENT_NOT_EXERCISED"}
        ):
            rows.append(
                [
                    chain.get("physical"),
                    chain.get("linux"),
                    ros,
                    state,
                    "Confirm requirement and runtime ownership before classifying as failure.",
                ],
            )
    if not rows:
        return _empty_state(
            "No cross-layer inconsistency was derived from the collected relationships."
        )
    return _table(
        [
            "Physical component",
            "Linux evidence",
            "ROS / application relationship",
            "Observed state",
            "Required resolution",
        ],
        rows,
    )


def _unconfirmed_risks(issues: list[dict[str, Any]], unknowns: Any) -> str:
    risks = [
        f"{issue.get('title')}: {issue.get('operational_impact')}"
        for issue in issues
        if issue.get("classification") == "NEEDS_CONFIRMATION"
    ]
    risks.extend(_string_list(unknowns))
    return _list(_deduplicate(risks), "No unconfirmed risk was recorded.")


def _verification_checklist() -> str:
    return _list(
        [
            "All critical and high findings have been reproduced and retested.",
            "Required hardware resolves through stable identities and is accessible to the intended runtime user.",
            "Required processes, services and containers are running in the expected execution context.",
            "ROS distribution, workspace, domain and middleware are consistent with the deployed workload.",
            "Expected nodes, topics, services, actions and TF relationships are visible.",
            "The affected end-to-end robot capability has been verified under its intended operating scenario.",
            "No unrelated subsystem regressed after the controlled change.",
            "A new passive scan was completed and compared with the original scan ID.",
        ],
        "No verification item is available.",
    )


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


def _capability_cards(value: Any, limit: int | None = None) -> str:
    records = _records(value)
    selected = records[:limit] if limit else records
    if not selected:
        return _empty_state("No robotics capability assessment was produced.")
    cards = []
    for item in selected:
        href = str(item.get("href") or "system-blueprint.html#software")
        cards.append(
            f'''<article class="capability tone-{_h(item.get("tone") or "neutral")}">
<div class="capability-head"><h3><a href="{_h(href)}">{_h(item.get("name"))}</a></h3><span class="state">{_h(item.get("state"))}</span></div>
<p class="evidence-line">{_h(item.get("evidence"))}</p><p>{_h(item.get("meaning"))}</p></article>'''
        )
    remainder = len(records) - len(selected)
    more = (
        f'<p class="muted">{remainder} additional optional or unavailable stacks are documented in the system blueprint.</p>'
        if remainder > 0
        else ""
    )
    return f'<div class="capability-grid">{"".join(cards)}</div>{more}'


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


def _chain_cards(value: Any, limit: int | None = None) -> str:
    records = _records(value)
    selected = records[:limit] if limit else records
    if not selected:
        return _empty_state(
            "No physical → Linux → ROS ownership chain was proven. Device and ROS inventories remain available below as separate evidence."
        )
    cards = []
    for item in selected:
        cards.append(
            f"""<article class="chain"><div class="chain-head"><h3>{_h(item.get("name"))}</h3><span>{_h(item.get("evidence"))}</span></div>
<div class="chain-path"><div><small>PHYSICAL</small><strong>{_h(item.get("physical"))}</strong></div><b>→</b><div><small>LINUX</small><strong>{_h(item.get("linux"))}</strong></div><b>→</b><div><small>ROS / CAPABILITY</small><strong>{_h(item.get("ros"))}</strong></div></div>
<p class="state-line">Observed state: <strong>{_h(item.get("state"))}</strong></p></article>"""
        )
    return "".join(cards)


def _provenance_strip(context: dict[str, Any]) -> str:
    return f"""<div class="provenance-strip">
<span><small>ANALYSIS</small><strong>{_h(context.get("provider_status"))}</strong></span>
<span><small>COLLECTED</small><strong>{_h(context.get("created_at"))}</strong></span>
<span><small>SCAN</small><strong>{_h(context.get("scan_id"))}</strong></span>
<span><small>MODE</small><strong>Passive · no repairs</strong></span>
</div>"""


def _compact_provenance(context: dict[str, Any]) -> str:
    return f"""<section class="compact-provenance"><p><strong>Analysis provenance:</strong> {_h(context.get("provider_status"))} · Screwdriver {_h(context.get("screwdriver_version"))} · schema {_h(context.get("schema_version"))} · snapshot SHA-256 <code>{_h(context.get("snapshot_sha256"))}</code>.</p></section>"""


def _issue_register(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return _empty_state("No diagnostic issue was accepted from this snapshot.")
    rows = []
    for issue in issues:
        rows.append(
            [
                f'<a href="#{_issue_id(issue)}">{_h(issue.get("title"))}</a>',
                issue.get("classification"),
                issue.get("severity"),
                issue.get("evidence_level"),
                issue.get("operational_impact"),
            ]
        )
    return _table(
        ["Finding", "Classification", "Severity", "Evidence", "Operational consequence"],
        rows,
        raw_columns={0},
    )


def _accelerator_summary(snapshot: dict[str, Any]) -> str:
    values = []
    for item in _records(snapshot.get("gpus")):
        values.append(str(item.get("model") or item.get("name") or item.get("vendor") or "GPU"))
    return ", ".join(values) or "No accelerator record collected"


def _thermal_table(records: list[dict[str, Any]]) -> str:
    return _table(
        ["Sensor", "Temperature", "Critical limit", "State"],
        [
            [
                item.get("label") or item.get("name") or item.get("source"),
                f"{item.get('temperature_celsius')} °C"
                if item.get("temperature_celsius") is not None
                else None,
                f"{item.get('critical_celsius')} °C"
                if item.get("critical_celsius") is not None
                else None,
                item.get("state") or item.get("status"),
            ]
            for item in records
        ],
    )


def _node_access(value: Any) -> str:
    node = _mapping(value)
    if not node:
        return "Not reported"
    return " · ".join(
        str(item)
        for item in (
            node.get("path"),
            node.get("permissions"),
            f"{node.get('owner')}:{node.get('group')}"
            if node.get("owner") or node.get("group")
            else None,
            node.get("access"),
        )
        if item
    )


def _usb_detail_table(records: list[dict[str, Any]]) -> str:
    return _table(
        ["Device", "USB identity", "Link", "Kernel drivers", "Device nodes / access"],
        [
            [
                item.get("display_name"),
                item.get("usb_id"),
                f"bus {item.get('bus_number')} · USB {item.get('usb_version')} · {item.get('speed_mbps')} Mb/s",
                item.get("drivers"),
                [_node_access(node) for node in _records(item.get("device_nodes"))],
            ]
            for item in records
        ],
    )


def _serial_detail_table(records: list[dict[str, Any]]) -> str:
    return _table(
        [
            "Interface",
            "Driver / transport",
            "Stable identity",
            "Physical path",
            "Permissions / access",
        ],
        [
            [
                f"{item.get('display_name') or item.get('port')} · {item.get('port')}",
                f"{item.get('driver') or 'driver not reported'} · {item.get('transport') or 'transport not reported'}",
                item.get("stable_id_path"),
                item.get("physical_path"),
                _node_access(item.get("device_node")),
            ]
            for item in records
        ],
    )


def _inventory_detail_table(records: list[dict[str, Any]], kind: str) -> str:
    if not records:
        return _empty_state(f"No {kind} inventory record was collected.")
    rows = []
    for item in records:
        details = _mapping(item.get("details"))
        rows.append(
            [
                item.get("name"),
                details.get("kind") or item.get("category"),
                details.get("bus") or details.get("protocol"),
                details.get("driver"),
                details.get("channel"),
                details.get("health") or details.get("state") or item.get("status"),
                details.get("confidence"),
            ]
        )
    return _table(
        ["Component", "Role", "Bus / protocol", "Driver", "Channel", "Observed state", "Evidence"],
        rows,
    )


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


def _ros_graph_summary(snapshot: dict[str, Any]) -> str:
    runtime = _records(snapshot.get("ros_runtime_inventory"))
    nodes = [item for item in runtime if item.get("category") == "ROS node"]
    topics = [item for item in runtime if item.get("category") == "ROS topic"]
    actions = [item for item in runtime if item.get("category") == "ROS action"]
    node_names = [str(item.get("name")) for item in nodes]
    topic_names = [
        f"{item.get('name')} · {_mapping(item.get('details')).get('type', 'type not reported')}"
        for item in topics
    ]
    action_names = [str(item.get("name")) for item in actions]
    return (
        '<div class="three-col"><div><h3>Nodes</h3>'
        + _list(node_names, "None captured.")
        + "</div><div><h3>Topics with types</h3>"
        + _list(topic_names, "None captured.")
        + "</div><div><h3>Actions</h3>"
        + _list(action_names, "None captured.")
        + "</div></div>"
    )


def _storage_table(records: list[dict[str, Any]]) -> str:
    rows = []
    for item in records:
        path = str(item.get("path") or "")
        media = str(item.get("media_type") or "")
        if "zram" in path:
            group = "Compressed RAM swap"
        elif str(item.get("connection") or "").lower() == "nvme":
            group = "Primary NVMe storage"
        elif (
            str(item.get("connection") or "").lower() == "usb"
            and _number(item.get("capacity_bytes")) < 64 * 1024**2
        ):
            group = "Embedded/debug removable media"
        else:
            group = media or "Other storage"
        rows.append(
            [
                group,
                item.get("model") or "Model not reported",
                path,
                item.get("connection"),
                _bytes(item.get("capacity_bytes")),
                "Read-only" if item.get("read_only") else "Read-write",
                "Device",
            ]
        )
        for partition in _records(item.get("partitions")):
            rows.append(
                [
                    "Root filesystem"
                    if partition.get("mount_point") == "/"
                    else "Mounted filesystem",
                    item.get("model") or item.get("name"),
                    partition.get("path"),
                    partition.get("filesystem"),
                    _bytes(partition.get("total_bytes")),
                    "Read-only" if partition.get("read_only") else "Read-write",
                    f"{partition.get('mount_point') or 'not mounted'} · {_percent(partition.get('usage_percent'))} used · {_bytes(partition.get('available_bytes'))} available",
                ]
            )
    return _table(
        [
            "Function",
            "Device",
            "Path",
            "Connection / filesystem",
            "Capacity",
            "Access",
            "Mount / usage",
        ],
        rows,
    )


def _network_table(network: dict[str, Any]) -> str:
    interfaces = _records(network.get("interfaces"))
    rows = []
    for item in interfaces:
        name = str(item.get("name") or "")
        kind = str(item.get("interface_type") or "").lower()
        if item.get("is_loopback"):
            group = "Loopback"
        elif item.get("is_virtual"):
            group = "Virtual"
        elif kind == "can" or name.startswith("can"):
            group = "CAN"
        elif name.startswith("usb"):
            group = "USB gadget"
        elif item.get("is_default_route"):
            group = "Primary"
        else:
            group = "Secondary"
        rows.append(
            [
                group,
                name,
                item.get("interface_type"),
                item.get("state"),
                _display(item.get("ipv4_addresses")),
                item.get("mac_address"),
                item.get("speed_mbps"),
                item.get("mtu"),
                item.get("driver"),
            ]
        )
    dns = [
        "127.0.0.53 (systemd-resolved local stub)" if value == "127.0.0.53" else value
        for value in _string_list(network.get("dns_servers"))
    ]
    return _kv_table(
        {
            "Default interface": network.get("default_interface"),
            "Gateway": network.get("default_gateway"),
            "Internet route": _yes_no(network.get("internet_route_available")),
            "DNS": ", ".join(dns) or "Not reported",
        }
    ) + _table(
        ["Role", "Interface", "Type", "State", "IPv4", "MAC", "Mb/s", "MTU", "Driver"],
        rows,
    )


def _complete_robotics_software_inventory(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Backfill explicit unknown records for stacks omitted by older snapshots."""

    completed = [dict(item) for item in records]
    index = {
        str(item.get("name") or "").casefold(): position for position, item in enumerate(completed)
    }
    for name, category, capability in _ROBOTICS_STACK_CATALOG:
        position = index.get(name.casefold())
        if position is not None:
            item = completed[position]
            details = dict(_mapping(item.get("details")))
            details.setdefault("stack_category", category)
            details.setdefault("capability", capability)
            item["details"] = details
            continue
        completed.append(
            {
                "category": "robotics software stack",
                "name": name,
                "status": "unknown",
                "details": {
                    "installed": None,
                    "configured": None,
                    "running": None,
                    "connected": None,
                    "integrated": None,
                    "state": "NOT_RECORDED_IN_SNAPSHOT",
                    "stack_category": category,
                    "capability": capability,
                    "optional": True,
                    "evidence_note": (
                        "This snapshot predates explicit status records for this stack; "
                        "absence of a record is not proof that the software is absent."
                    ),
                },
            }
        )
    return completed


def _robotics_stack_status_matrix(records: list[dict[str, Any]]) -> str:
    """Render an always-visible status row for every recognized robotics domain."""

    by_name = {str(item.get("name") or "").casefold(): item for item in records}
    rows = []
    tracked: list[dict[str, Any]] = []
    for name, category, capability in _ROBOTICS_STACK_CATALOG:
        item = by_name[name.casefold()]
        details = _mapping(item.get("details"))
        tracked.append(details)
        rows.append(
            [
                name,
                category,
                capability,
                str(details.get("state") or item.get("status") or "UNKNOWN").replace("_", " "),
                _stack_stage_text(details.get("installed")),
                _stack_stage_text(details.get("configured")),
                _stack_stage_text(details.get("running")),
                _stack_stage_text(details.get("connected")),
                _stack_stage_text(details.get("integrated")),
                details.get("version")
                or details.get("detected_packages")
                or "No package evidence in snapshot",
            ]
        )
    metrics = (
        '<div class="metric-grid">'
        + _metric("Stacks tracked", len(tracked))
        + _metric("Installed", sum(item.get("installed") is True for item in tracked), "ok")
        + _metric("Configured", sum(item.get("configured") is True for item in tracked))
        + _metric("Running", sum(item.get("running") is True for item in tracked), "ok")
        + _metric("Integrated", sum(item.get("integrated") is True for item in tracked))
        + _metric(
            "Not recorded",
            sum(item.get("state") == "NOT_RECORDED_IN_SNAPSHOT" for item in tracked),
            "warning",
        )
        + "</div>"
    )
    return metrics + _table(
        [
            "Stack",
            "Domain",
            "Robot capability",
            "Snapshot state",
            "Installed",
            "Configured",
            "Running",
            "Connected",
            "Integrated",
            "Packages / version",
        ],
        rows,
    )


def _stack_stage_text(value: Any) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return "NOT ESTABLISHED"


def _software_table(
    records: list[dict[str, Any]],
    *,
    include_anchors: bool = False,
    link_to_blueprint: bool = False,
) -> str:
    expanded: list[str] = []
    absent: dict[str, list[str]] = {}
    for item in records:
        details = _mapping(item.get("details"))
        name = str(item.get("name") or "Unnamed stack")
        installed = details.get("installed")
        configured = details.get("configured")
        running = details.get("running")
        connected = details.get("connected")
        integrated = details.get("integrated")
        category = str(details.get("stack_category") or item.get("category") or "Other")
        if not any(
            value is True for value in (installed, configured, running, connected, integrated)
        ):
            absent.setdefault(category, []).append(name)
            continue
        display_name = (
            f'<a href="system-blueprint.html#stack-{_slug(name)}">{_h(name)}</a>'
            if link_to_blueprint
            else _h(name)
        )
        row_id = f' id="stack-{_slug(name)}"' if include_anchors else ""
        stage = str(details.get("state") or item.get("status") or "UNKNOWN").replace("_", " ")
        packages = (
            details.get("version") or details.get("detected_packages") or "Version not reported"
        )
        expanded.append(
            f'''<article class="stack-card"{row_id}>
<div class="stack-title"><div><p class="eyebrow">{_h(category)}</p><h3>{display_name}</h3></div><span class="stage">{_h(stage)}</span></div>
<p><strong>Packages / version:</strong> {_h(packages)}</p>
<div class="stage-ladder">{_stage("Installed", installed)}{_stage("Configured", configured)}{_stage("Running", running)}{_stage("Connected", connected)}{_stage("Integrated", integrated)}</div>
<div class="two-col"><p><strong>Robot capability:</strong><br>{_h(details.get("capability") or "Not declared")}</p><p><strong>Capability state:</strong><br>{_h(details.get("capability_state") or "Not established")}</p></div>
{_software_evidence(details)}</article>'''
        )
    absent_html = ""
    if absent:
        groups = []
        for category, names in sorted(absent.items()):
            groups.append(
                f'<div class="absent-group"><strong>{_h(category)}</strong><p>{_h(", ".join(names))}</p></div>'
            )
        absent_html = (
            '<details class="absent-stacks"><summary>Optional stacks without installation evidence '
            f'<span class="count">{sum(len(names) for names in absent.values())}</span></summary>'
            '<p class="section-intro">These are capability observations, not failures. A stack is relevant only when the robot profile requires it.</p>'
            f'<div class="absent-grid">{"".join(groups)}</div></details>'
        )
    return f'<div class="stack-grid">{"".join(expanded)}</div>{absent_html}'


def _stage(label: str, value: Any) -> str:
    state = "yes" if value is True else "no" if value is False else "unknown"
    rendered = "Yes" if value is True else "No" if value is False else "Not established"
    return f'<span class="stage-step {state}"><small>{_h(label)}</small><strong>{rendered}</strong></span>'


def _software_evidence(details: dict[str, Any]) -> str:
    ignored = {
        "installed",
        "configured",
        "running",
        "connected",
        "integrated",
        "state",
        "stack_category",
        "capability",
        "capability_state",
        "version",
        "detected_packages",
        "optional",
        "original_category",
    }
    rows = [
        [key.replace("_", " ").title(), value]
        for key, value in details.items()
        if key not in ignored and value not in (None, "", [], {})
    ]
    if not rows:
        return '<p class="muted">No additional configuration or runtime evidence was reported.</p>'
    return f'<details class="stack-evidence"><summary>Configuration and runtime evidence</summary>{_table(["Evidence field", "Observed value"], rows)}</details>'


def _evidence_appendix(snapshot: dict[str, Any]) -> str:
    groups = [
        ("Identity and OS", ("identity", "operating_system", "platform")),
        (
            "Compute, storage, thermal and power",
            ("cpu", "memory", "storage_devices", "gpus", "thermal_sensors", "power"),
        ),
        ("Network and Linux devices", ("network", "usb_devices", "serial_devices")),
        (
            "Robotics and ROS",
            (
                "software_stack_inventory",
                "sensor_inventory",
                "actuator_inventory",
                "ros_device_inventory",
                "ros_runtime_inventory",
            ),
        ),
        ("Collector findings", ("findings",)),
    ]
    content = []
    for title, keys in groups:
        rows = []
        for key in keys:
            rows.append(
                f'<details class="evidence" id="{_evidence_id(key)}"><summary>{_h(key)}</summary><pre>{_h(json.dumps(snapshot.get(key), indent=2, ensure_ascii=False))}</pre></details>'
            )
        content.append(f"<h3>{_h(title)}</h3>{''.join(rows)}")
    return f'<section id="evidence"><h2>11. Categorized evidence appendix</h2><p class="muted">Exact source fields used by the reports. Use the browser find function to search within expanded records.</p>{"".join(content)}</section>'


def _probe_section(probes: list[dict[str, Any]]) -> str:
    cards = []
    for probe in probes:
        command = (
            " ".join(str(value) for value in probe.get("command", []))
            or "Rejected before execution"
        )
        cards.append(
            f"""<details class="probe"><summary>{_h(probe.get("probe"))} · {_h(probe.get("target") or "system")} · {_h(probe.get("state"))}</summary><div class="two-col"><p><strong>Command</strong><br><code>{_h(command)}</code></p><p><strong>Exit / duration</strong><br>{_h(probe.get("return_code"))} · {_h(probe.get("duration_ms"))} ms · truncated {_h(_yes_no(probe.get("truncated")))}</p></div><h4>stdout</h4><pre>{_h(probe.get("stdout") or "No stdout.")}</pre><h4>stderr / rejection reason</h4><pre>{_h(probe.get("stderr") or probe.get("output") or "No stderr.")}</pre></details>"""
        )
    return (
        f'<section id="probes"><h2>Read-only investigation evidence</h2>{"".join(cards)}</section>'
    )


def _report_metadata(context: dict[str, Any]) -> str:
    return f"""<section class="metadata"><h2>Report provenance</h2>{_kv_table({"Scan ID": context["scan_id"], "Snapshot SHA-256": context["snapshot_sha256"], "Schema": context["schema_version"], "Screwdriver version": context["screwdriver_version"], "Collected": context["created_at"], "Collection duration": context["duration"], "Analysis engine": context["provider_status"], "Focus": context.get("focus") or "Complete system"})}</section>"""


def _analysis_notice(context: dict[str, Any]) -> str:
    status = str(context.get("provider_status") or "")
    if "fallback" not in status.casefold():
        return ""
    return f'<aside class="analysis-notice" style="display:flex;justify-content:space-between;gap:16px;border:1px solid #ffc85c;background:#2c2417;color:#ffe4a5;border-radius:12px;padding:13px 16px;margin:16px 0"><strong>DETERMINISTIC FALLBACK</strong><span>{_h(status)}</span></aside>'


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_h(title)}</title><style>
:root{{--bg:#07101c;--panel:#0e1a2a;--panel2:#13243a;--line:#29415e;--text:#eef6ff;--muted:#a9bdd2;--cyan:#62d6ff;--green:#53dda2;--amber:#ffc85c;--orange:#ff9f5a;--red:#ff6476;--shadow:0 18px 50px #0005}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:linear-gradient(145deg,#07101c,#0a1727 48%,#07101c);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:34px 22px 80px}}h1{{font-size:clamp(2rem,5vw,4rem);line-height:1.05;margin:.25rem 0 1rem}}h2{{font-size:1.55rem;margin:0 0 1rem}}h3{{margin:.6rem 0}}h4{{margin:1.2rem 0 .45rem}}p{{margin:.45rem 0 1rem}}a{{color:var(--cyan)}}section,.hero,.toc{{background:#0e1a2aee;border:1px solid var(--line);border-radius:18px;padding:24px;margin:18px 0;box-shadow:var(--shadow)}}.hero{{padding:36px;background:linear-gradient(135deg,#102a43,#0e1a2a)}}.hero.tone-critical,.hero.tone-high{{background:linear-gradient(135deg,#4a1d2c,#0e1a2a)}}.hero.tone-warning{{background:linear-gradient(135deg,#45341b,#0e1a2a)}}.hero.tone-ok{{background:linear-gradient(135deg,#123a32,#0e1a2a)}}.lede{{max-width:920px;color:#dbe9f7;font-size:1.05rem}}.eyebrow{{margin:0;letter-spacing:.16em;font-size:.72rem;font-weight:800;color:var(--cyan)}}.meta{{display:flex;gap:8px;flex-wrap:wrap}}.meta span,.pill,.evidence-ref{{border:1px solid #426383;border-radius:999px;padding:4px 9px;font-size:.74rem;text-decoration:none}}.toc{{position:sticky;top:8px;z-index:3;display:flex;gap:14px;flex-wrap:wrap;padding:11px 18px}}.toc a{{text-decoration:none;font-weight:700}}.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px}}.metric{{background:var(--panel2);border:1px solid var(--line);border-radius:13px;padding:15px}}.metric strong{{display:block;font-size:1.22rem;color:var(--cyan);overflow-wrap:anywhere}}.metric.tone-ok strong{{color:var(--green)}}.metric.tone-warning strong{{color:var(--amber)}}.metric.tone-high strong,.metric.tone-critical strong{{color:var(--red)}}.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.three-col{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.section-head{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.priority,.callout,.status-line{{border-left:5px solid var(--amber);background:#262219;padding:17px 19px;border-radius:12px}}.status-line{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}.finding{{border:1px solid var(--line);border-left:6px solid var(--amber);border-radius:13px;padding:16px;margin:12px 0;background:#0b1625}}.severity-critical,.severity-high{{border-left-color:var(--red)}}.severity-low,.severity-info{{border-left-color:var(--cyan)}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:12px}}.card{{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:14px}}.card.ok{{border-left:4px solid var(--green)}}.empty{{border:1px dashed #52708f;border-radius:13px;padding:20px}}.muted,small{{color:var(--muted)}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse;min-width:650px;background:#0b1625}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;max-width:460px;overflow-wrap:anywhere}}th{{position:sticky;top:0;background:#172b43;color:#dcecff}}tr:last-child td{{border-bottom:0}}.state{{font-weight:800}}.state-collected{{color:var(--green)}}.state-partial{{color:var(--amber)}}.state-not-available{{color:var(--red)}}details{{border:1px solid var(--line);border-radius:12px;margin:11px 0;background:#0b1625}}summary{{cursor:pointer;padding:14px;font-weight:700}}.issue summary{{display:flex;gap:12px;align-items:flex-start}}.issue summary small{{display:block;font-weight:500}}.issue-body{{padding:0 18px 18px}}.issue-number{{display:grid;place-items:center;min-width:30px;height:30px;border-radius:50%;background:#203754}}pre{{white-space:pre-wrap;word-break:break-word;background:#050c15;border:1px solid #20364f;border-radius:9px;padding:12px;max-height:520px;overflow:auto}}code{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}.count{{font-size:.8rem;color:var(--muted)}}.metadata{{background:#0a1421}}@media(max-width:800px){{.two-col,.three-col{{grid-template-columns:1fr}}.toc{{position:static}}.section-head{{align-items:flex-start;flex-direction:column}}section,.hero{{padding:18px}}}}@media print{{:root{{--text:#111;--muted:#555;--line:#bbb}}body{{background:white;color:#111;font-size:10pt}}main{{max-width:none;padding:0}}section,.hero,.toc,details{{background:white!important;box-shadow:none;border-color:#bbb;break-inside:avoid}}.toc{{display:none}}.hero{{color:#111}}.metric,.card,.finding,table,pre{{background:white!important;color:#111}}details{{break-inside:auto}}details>summary{{list-style:none}}details>.issue-body,details>pre{{display:block}}a{{color:#111;text-decoration:none}}}}
.provenance-strip{{display:grid;grid-template-columns:2fr 1.25fr 1fr 1fr;gap:10px;margin-top:22px}}.provenance-strip span{{display:flex;flex-direction:column;gap:3px;border-top:1px solid #426383;padding-top:9px;min-width:0}}.provenance-strip small{{font-size:.65rem;letter-spacing:.12em}}.provenance-strip strong{{font-size:.78rem;overflow-wrap:anywhere}}.section-intro{{max-width:900px;color:var(--muted)}}.capability-grid,.stack-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.capability,.stack-card,.chain{{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:17px}}.capability{{border-left:5px solid #52708f}}.capability.tone-ok{{border-left-color:var(--green)}}.capability.tone-partial,.capability.tone-warning{{border-left-color:var(--amber)}}.capability.tone-muted{{opacity:.76}}.capability-head,.stack-title,.chain-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.capability-head h3,.stack-title h3,.chain-head h3{{margin:0}}.capability-head .state,.stage,.chain-head span{{border:1px solid #426383;border-radius:999px;padding:4px 9px;font-size:.7rem;font-weight:800;white-space:nowrap}}.evidence-line{{color:var(--cyan);font-size:.84rem}}.chain{{margin:12px 0}}.chain-path{{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr) auto minmax(0,1fr);gap:10px;align-items:center}}.chain-path div{{background:#091524;border:1px solid var(--line);border-radius:10px;padding:11px;min-height:80px}}.chain-path small{{display:block;font-size:.63rem;letter-spacing:.1em;margin-bottom:5px}}.chain-path strong{{display:block;overflow-wrap:anywhere}}.chain-path b{{color:var(--cyan)}}.state-line{{margin:10px 0 0;color:var(--muted)}}.stack-card{{margin:0}}.stage-ladder{{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;margin:14px 0}}.stage-step{{border:1px solid var(--line);border-radius:9px;padding:8px;min-width:0}}.stage-step small,.stage-step strong{{display:block;overflow-wrap:anywhere}}.stage-step.yes{{border-color:#287a5d}}.stage-step.no{{border-color:#684b4b}}.stage-step.unknown{{opacity:.68}}.absent-stacks{{margin-top:16px}}.absent-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:0 14px 14px}}.absent-group{{border-left:3px solid #52708f;padding-left:12px}}.impact{{border-left:4px solid var(--amber);padding:1px 15px;margin:14px 0;background:#201e1d}}h5{{margin:1rem 0 .3rem}}.compact-provenance{{font-size:.82rem}}.title-row{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end}}.report-links{{display:flex;gap:8px;flex-wrap:wrap}}.report-links a{{border:1px solid #426383;border-radius:999px;padding:6px 11px;text-decoration:none;font-size:.78rem}}.quick-stack,.quick-attention{{padding:20px}}.layer-stack{{display:flex;flex-direction:column}}.system-layer{{display:grid;grid-template-columns:42px 1fr;gap:13px;padding:13px 0;border-bottom:1px solid var(--line)}}.system-layer:last-child{{border-bottom:0}}.layer-number{{display:grid;place-items:center;width:34px;height:34px;border:1px solid #426383;border-radius:50%;color:var(--cyan);font-weight:800}}.layer-title{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.layer-title h3{{margin:0}}.layer-state{{font-size:.68rem;font-weight:800;letter-spacing:.08em;border:1px solid #426383;border-radius:999px;padding:3px 8px}}.layer-copy p{{margin:.25rem 0}}.layer-copy small{{display:block}}.issue-scope{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:15px 0}}.issue-scope span{{border:1px solid var(--line);border-radius:10px;padding:10px}}.issue-scope small,.issue-scope strong{{display:block}}.command-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.command-card{{border:1px solid var(--line);border-radius:12px;padding:12px}}.command-card pre{{margin:.45rem 0}}.safe-label{{font-size:.65rem;font-weight:800;color:var(--green);letter-spacing:.1em}}@media(max-width:850px){{.provenance-strip,.capability-grid,.stack-grid,.absent-grid,.issue-scope,.command-grid{{grid-template-columns:1fr}}.title-row{{align-items:flex-start;flex-direction:column}}.chain-path{{grid-template-columns:1fr}}.chain-path b{{transform:rotate(90deg);text-align:center}}.stage-ladder{{grid-template-columns:repeat(2,1fr)}}}}@media print{{@page{{size:auto;margin:13mm 11mm}}body{{font-size:9pt;-webkit-print-color-adjust:exact;print-color-adjust:exact}}section,.hero,details{{break-inside:auto}}h1,h2,h3,h4,.section-head,.capability-head,.stack-title{{break-after:avoid}}.capability,.stack-card,.finding,.chain,.metric,.priority,.status-line,.system-layer,.command-card{{break-inside:avoid}}.provenance-strip{{grid-template-columns:2fr 1.2fr 1fr 1fr}}.capability-grid,.stack-grid,.command-grid{{grid-template-columns:1fr 1fr}}.chain-path{{grid-template-columns:minmax(0,1fr) auto minmax(0,1fr) auto minmax(0,1fr)}}table{{min-width:0;font-size:8pt;table-layout:auto}}th,td{{padding:6px 7px;max-width:none;overflow-wrap:break-word;word-break:normal}}th{{position:static}}.hero,section{{padding:16px;margin:10px 0}}.quick-stack,.quick-attention{{padding:11px;margin:7px 0}}.quick-stack .section-head h2,.quick-attention .section-head h2{{margin-bottom:3px}}.system-layer{{padding:7px 0}}.layer-copy p{{margin:.1rem 0}}.quick-attention .finding{{padding:9px;margin:6px 0}}.quick-attention .finding p{{margin:.2rem 0}}.evidence{{break-inside:auto}}.evidence pre{{display:none}}.compact-provenance{{break-inside:avoid}}}}
	.change-warning{{margin:14px 0;padding:14px;border:1px solid #b7791f;border-left:5px solid var(--amber);border-radius:12px;background:#2b2115}}.change-warning>span{{display:block;color:var(--amber);font-size:.7rem;font-weight:900;letter-spacing:.09em}}.change-warning pre{{border-color:#765522}}
	</style></head><body><main>{body}<footer class="muted">Generated from passive evidence. Model interpretation is displayed only after deterministic validation; unknowns remain unknown.</footer></main></body></html>"""


def _coverage_table(coverage: list[dict[str, str]]) -> str:
    return _table(
        ["Area", "Coverage", "Snapshot source"],
        [[item["area"], _state_html(item["state"]), item["source"]] for item in coverage],
        raw_columns={1},
    )


def _matrix_table(rows: list[list[str]]) -> str:
    return _table(
        [
            "Role",
            "Physical component",
            "Driver",
            "ROS node",
            "Endpoint",
            "Ownership",
            "Evidence state",
        ],
        rows,
    )


def _flow_table(rows: list[list[str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    return _table(["Publisher", "Topic", "Message type", "Subscriber"], selected)


def _record_table(records: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    return _table(
        [key.replace("_", " ").title() for key in keys],
        [[record.get(key) for key in keys] for record in records],
    )


def _kv_table(values: dict[str, Any]) -> str:
    return _table(["Property", "Value"], [[key, value] for key, value in values.items()])


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


def _cards(values: list[str], *, tone: str) -> str:
    cards = "".join(f'<div class="card {tone}">{_h(value)}</div>' for value in values)
    return f'<div class="cards">{cards}</div>'


def _list(values: list[str], empty: str) -> str:
    return (
        f"<ul>{''.join(f'<li>{_h(value)}</li>' for value in values)}</ul>"
        if values
        else f'<p class="muted">{_h(empty)}</p>'
    )


def _empty_state(message: str) -> str:
    return f'<div class="empty"><p>{_h(message)}</p></div>'


def _ordered(values: list[str]) -> str:
    return (
        f"<ol>{''.join(f'<li>{_h(value)}</li>' for value in values)}</ol>"
        if values
        else '<p class="muted">No approach accepted.</p>'
    )


def _metric(label: str, value: Any, tone: str = "neutral") -> str:
    return f'<div class="metric tone-{_h(tone)}"><span>{_h(label)}</span><strong>{_h(_display(value))}</strong></div>'


def _state_html(state: str) -> str:
    css = state.lower().replace(" ", "-")
    return f'<span class="state state-{_h(css)}">{_h(state)}</span>'


def _focus_badge(value: Any) -> str:
    return f"<span>Focus: {_h(value)}</span>" if value else ""


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
    total = max(0, int(value))
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
    if seconds or not parts:
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


def _middleware(value: Any) -> str:
    return (
        "Provider default (exact RMW not reported)"
        if value in (None, "", "default")
        else str(value)
    )


def _usage_tone(value: Any) -> str:
    return "warning" if isinstance(value, (int, float)) and float(value) >= 90 else "ok"


def _state_tone(value: Any) -> str:
    return "ok" if str(value).upper() == "RUNNING" else "warning"


def _first(value: Any) -> str:
    values = _string_list(value)
    return values[0] if values else "No accepted observation."


def _evidence_id(reference: str) -> str:
    root = reference.split("[", 1)[0].split(".", 1)[0]
    return "evidence-" + re.sub(r"[^a-z0-9_-]+", "-", root.lower()).strip("-")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-") or "unknown"


def _issue_id(issue: dict[str, Any]) -> str:
    return "issue-" + _slug(str(issue.get("code") or issue.get("title") or "unknown"))


def _h(value: Any) -> str:
    return html.escape(_display(value), quote=True)


__all__ = [
    "build_report_context",
    "render_compact_snapshot",
    "render_diagnostic_report",
    "render_system_blueprint",
]
