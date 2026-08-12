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

    priority = _priority_next_check(actionable, unknowns, coverage)
    ros = _ros_overview(snapshot)
    physical = _physical_peripherals(snapshot)
    return {
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
    """Render a findings-first view that can be understood in under a minute."""

    ros = _mapping(context["ros"])
    memory = _mapping(context["memory"])
    platform = _mapping(context["platform"])
    attention = context["actionable"]
    attention_html = (
        "".join(_compact_issue(issue) for issue in attention[:6])
        if attention
        else '<div class="empty"><strong>No confirmed actionable problem</strong><p>No failure is proven by the collected evidence. This is not a functional test.</p></div>'
    )
    return _page(
        f"Compact snapshot — {_mapping(context['identity']).get('hostname', 'robot')}",
        f"""
<header class="hero tone-{_h(context["tone"])}">
  <p class="eyebrow">SCREWDRIVER · COMPACT AGENTIC SNAPSHOT</p>
  <h1>{_h(context["overall"])}</h1>
  <p class="lede">{_h(context["summary"])}</p>
  <div class="meta"><span>Scan {_h(context["scan_id"])}</span><span>{_h(context["created_at"])}</span><span>Passive · no repairs</span></div>
</header>
<nav class="toc" aria-label="Report sections"><a href="#attention">Attention</a><a href="#stacks">Stacks</a><a href="#working">Working</a><a href="#flow">Data flow</a><a href="#unknowns">Unknowns</a><a href="#coverage">Coverage</a></nav>
{_analysis_notice(context)}
<section class="priority"><p class="eyebrow">HIGHEST-PRIORITY NEXT CHECK</p><h2>{_h(context["priority"])}</h2></section>
<section aria-labelledby="at-glance"><h2 id="at-glance">System at a glance</h2>
  <div class="metric-grid">
    {_metric("Computer", platform.get("product_name") or platform.get("board_name") or "Linux computer")}
    {_metric("ROS graph", str(ros.get("state") or "Not available"), _state_tone(ros.get("state")))}
    {_metric("Nodes / topics", f"{ros.get('nodes', 0)} / {ros.get('topics', 0)}")}
    {_metric("Memory", _percent(memory.get("usage_percent")), _usage_tone(memory.get("usage_percent")))}
    {_metric("Physical peripherals", len(context["physical"]))}
    {_metric("Actionable findings", len(attention), "warning" if attention else "ok")}
  </div>
</section>
<section id="attention"><div class="section-head"><h2>Needs attention</h2><a href="diagnostic-report.html">Open detailed diagnostics →</a></div>{attention_html}</section>
<section id="stacks"><div class="section-head"><h2>Robotics software stacks</h2><a href="system-blueprint.html#software">Open stack architecture →</a></div>{_software_table(context["stacks"], link_to_blueprint=True) if context["stacks"] else _empty_state("No robotics software stack was collected.")}</section>
<section id="working"><h2>What is working in this snapshot</h2>{_cards(context["checks"], tone="ok")}</section>
<section id="flow"><div class="section-head"><h2>Verified ROS relationships</h2><a href="system-blueprint.html#data-flow">Open complete flow →</a></div>{_flow_table(context["flows"], limit=10)}</section>
<section id="unknowns"><h2>Unknowns that must not be mistaken for failures</h2>{_list(context["unknowns"], "No explicit evidence gaps were recorded.")}</section>
<section id="coverage"><h2>Collection coverage</h2>{_coverage_table(context["coverage"])}</section>
{_report_metadata(context)}
""",
    )


def render_system_blueprint(context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Render the detailed system architecture without raw-dump presentation."""

    identity = _mapping(context["identity"])
    os_info = _mapping(context["os"])
    platform = _mapping(context["platform"])
    cpu = _mapping(context["cpu"])
    memory = _mapping(context["memory"])
    ros = _mapping(context["ros"])
    sections: list[str] = []
    sections.append(
        f"""<section id="overview"><h2>1. Engineering overview</h2>
        <div class="status-line tone-{_h(context["tone"])}"><strong>{_h(context["overall"])}</strong><span>{_h(context["priority"])}</span></div>
        <div class="two-col"><div><h3>What is known</h3>{_cards(context["checks"], tone="ok")}</div><div><h3>Evidence gaps</h3>{_list(context["unknowns"], "None recorded.")}</div></div></section>"""
    )
    sections.append(
        f"""<section id="compute"><h2>2. Compute platform</h2>{
            _kv_table(
                {
                    "Hostname": identity.get("hostname"),
                    "Platform": platform.get("product_name") or platform.get("board_name"),
                    "Manufacturer": platform.get("manufacturer"),
                    "CPU": cpu.get("model"),
                    "Logical CPUs": cpu.get("logical_cpus"),
                    "Memory total": _bytes(memory.get("total_bytes")),
                    "Memory used": _percent(memory.get("usage_percent")),
                    "Operating system": os_info.get("distribution"),
                    "Kernel": os_info.get("kernel"),
                    "Architecture": os_info.get("architecture"),
                    "Uptime": _duration(os_info.get("uptime_seconds")),
                }
            )
        }</section>"""
    )
    sections.append(
        f"""<section id="architecture"><h2>3. Component health and ownership matrix</h2>
        <p class="muted">A ROS role is not called physical ownership unless an exact configured path or physical correlation exists.</p>
        {_matrix_table(context["component_matrix"])}</section>"""
    )
    physical = context["physical"]
    sections.append(
        f"""<section id="hardware"><h2>4. Physical hardware inventory</h2>
        <h3>Robot-facing USB peripherals</h3>{_record_table(physical, ("display_name", "usb_id", "device_class_name", "drivers")) if physical else _empty_state("No robot-facing USB peripheral was identified in this snapshot.")}
        <h3>Serial interfaces</h3>{_record_table(_records(snapshot.get("serial_devices")), ("display_name", "port", "transport", "driver", "stable_id_path")) if _records(snapshot.get("serial_devices")) else _empty_state("No serial interface was collected.")}
        <h3>Storage, grouped by function</h3>{_storage_table(_records(snapshot.get("storage_devices"))) if _records(snapshot.get("storage_devices")) else _empty_state("No storage device was collected.")}</section>"""
    )
    sections.append(
        f"""<section id="ros"><h2>5. ROS 2 runtime</h2>{
            _kv_table(
                {
                    "Graph state": ros.get("state"),
                    "Distribution": ros.get("ros_distro"),
                    "Domain ID": ros.get("domain_id"),
                    "DDS middleware": _middleware(ros.get("middleware")),
                    "Discovery": ros.get("discovery_mode"),
                    "Environment recovered": _yes_no(ros.get("environment_recovered")),
                    "Nodes": ros.get("nodes"),
                    "Topics": ros.get("topics"),
                    "Services": ros.get("services"),
                    "Actions": ros.get("actions"),
                }
            )
        }{_ros_graph_summary(snapshot)}</section>"""
    )
    sections.append(
        f"""<section id="data-flow"><h2>6. Active data and command flow</h2>
        <p class="muted">Publisher → topic and message type → subscriber. Endpoint presence proves graph structure, not live message rate or physical function.</p>
        {_flow_table(context["flows"])}</section>"""
    )
    sections.append(
        f"""<section id="network"><h2>7. Network and communications</h2>{_network_table(_mapping(context["network"]))}</section>"""
    )
    software = _records(snapshot.get("software_stack_inventory"))
    sections.append(
        f'<section id="software"><h2>8. Robotics software-stack architecture</h2><p class="muted">Installed does not mean operational. Runtime, connectivity, and integration remain separate evidence states.</p>{_software_table(software, include_anchors=True) if software else _empty_state("No robotics software package record was collected.")}</section>'
    )
    sections.append(
        f"""<section id="interpretation"><h2>9. Agentic interpretation</h2>
        <h3>Architecture observations</h3>{_list(context["observations"], "No additional interpretation was accepted.")}
        <h3>Unknowns and limits</h3>{_list(context["unknowns"], "No explicit unknowns were recorded.")}
        <div class="callout">Sensor streams were not sampled, actuators were not commanded, and endpoint presence was not treated as functional success.</div></section>"""
    )
    sections.append(
        f"""<section id="coverage"><h2>10. Coverage and provenance</h2>{_coverage_table(context["coverage"])}{_report_metadata(context)}</section>"""
    )
    sections.append(_evidence_appendix(snapshot))
    return _page(
        f"System blueprint — {identity.get('hostname', 'robot')}",
        f"""
<header class="hero"><p class="eyebrow">SCREWDRIVER · DETAILED SYSTEM BLUEPRINT</p><h1>System blueprint — {_h(identity.get("hostname", "robot"))}</h1><p class="lede">{_h(context["summary"])}</p><div class="meta"><span>Scan {_h(context["scan_id"])}</span><span>Passive evidence</span>{_focus_badge(context.get("focus"))}</div></header>
<nav class="toc" aria-label="Report sections"><a href="#overview">Overview</a><a href="#compute">Compute</a><a href="#architecture">Matrix</a><a href="#hardware">Hardware</a><a href="#ros">ROS 2</a><a href="#data-flow">Data flow</a><a href="#network">Network</a><a href="#software">Software</a><a href="#coverage">Coverage</a><a href="#evidence">Evidence</a></nav>
{_analysis_notice(context)}
{"".join(sections)}
""",
    )


def render_diagnostic_report(context: dict[str, Any], probes: list[dict[str, Any]]) -> str:
    """Render detailed, classified diagnostics with evidence and command provenance."""

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
<header class="hero tone-{_h(context["tone"])}"><p class="eyebrow">SCREWDRIVER · EVIDENCE-GROUNDED DIAGNOSTICS</p><h1>{_h(context["overall"])}</h1><p class="lede">Problems are separated from advisories and unknowns. No repair was executed.</p><div class="meta"><span>Scan {_h(context["scan_id"])}</span><span>{_h(context["created_at"])}</span><span>No repairs executed</span></div></header>
<nav class="toc" aria-label="Report sections"><a href="#overview">Overview</a><a href="#stack-diagnostics">Stacks</a><a href="#confirmed_failure">Failures</a><a href="#degraded">Degraded</a><a href="#configuration_warning">Warnings</a><a href="#advisory">Advisories</a><a href="#needs_confirmation">Confirm</a><a href="#probes">Probes</a><a href="#verification">Verification</a></nav>
{_analysis_notice(context)}
<section id="overview"><h2>Diagnostic overview</h2><div class="metric-grid">{_metric("Critical", counts["CRITICAL"], "critical" if counts["CRITICAL"] else "neutral")}{_metric("High", counts["HIGH"], "high" if counts["HIGH"] else "neutral")}{_metric("Medium", counts["MEDIUM"], "warning" if counts["MEDIUM"] else "neutral")}{_metric("Low", counts["LOW"])}{_metric("Advisory / confirm", sum(issue.get("classification") in {"ADVISORY", "NEEDS_CONFIRMATION"} for issue in issues))}</div><div class="priority"><p class="eyebrow">NEXT CHECK</p><strong>{_h(context["priority"])}</strong></div>{_coverage_table(context["coverage"])}</section>
<section id="stack-diagnostics"><div class="section-head"><h2>Robotics-stack operational stages</h2><a href="system-blueprint.html#software">Open Blueprint relationships →</a></div>{_software_table(context["stacks"], link_to_blueprint=True) if context["stacks"] else _empty_state("No stack evidence was collected.")}</section>
{"".join(issue_sections)}
{probe_section}
<section id="verification"><h2>Verification workflow</h2><ol><li>Confirm that the affected capability is expected on this robot.</li><li>Run only the displayed read-only checks.</li><li>Apply one human-approved change outside Screwdriver.</li><li>Repeat the original failing check.</li><li>Run a new passive inspection and compare scan IDs.</li></ol></section>
{_report_metadata(context)}
""",
    )


def _compact_issue(issue: dict[str, Any]) -> str:
    target = _issue_id(issue)
    return f"""<article class="finding severity-{_h(str(issue.get("severity", "INFO")).lower())}"><div><span class="pill">{_h(issue.get("classification", "NEEDS_CONFIRMATION"))}</span><h3>{_h(issue.get("title"))}</h3></div><p><strong>Impact:</strong> {_h(issue.get("operational_impact") or "Impact not established.")}</p><p><strong>Observed:</strong> {_h(_first(issue.get("observed")))}</p><a href="diagnostic-report.html#{target}">Open finding evidence and recovery criteria →</a></article>"""


def _detailed_issue(issue: dict[str, Any], index: int) -> str:
    commands = _string_list(issue.get("diagnostic_commands"))
    references = _string_list(issue.get("evidence_references"))
    command_html = (
        "<h4>Validated read-only commands</h4>"
        + "".join(f"<pre><code>{_h(command)}</code></pre>" for command in commands)
        if commands
        else '<p class="muted">No executable command was validated for this finding.</p>'
    )
    refs = (
        " ".join(
            f'<a class="evidence-ref" href="system-blueprint.html#{_evidence_id(ref)}">{_h(ref)}</a>'
            for ref in references
        )
        if references
        else '<span class="muted">No exact evidence reference accepted.</span>'
    )
    return f"""<details id="{_issue_id(issue)}" class="issue severity-{_h(str(issue.get("severity", "INFO")).lower())}" open><summary><span class="issue-number">{index}</span><span><strong>{_h(issue.get("title"))}</strong><small>{_h(issue.get("severity"))} · {_h(issue.get("classification"))} · observation {_h(issue.get("observation_confidence", issue.get("confidence")))}% · diagnosis {_h(issue.get("diagnosis_confidence", issue.get("confidence")))}%</small></span></summary><div class="issue-body"><div class="two-col"><div><h4>Expected</h4><p>{_h(issue.get("expected_state") or "No expected state was supplied.")}</p></div><div><h4>Observed</h4>{_list(_string_list(issue.get("observed")), "No accepted observation.")}</div></div><h4>Operational impact</h4><p>{_h(issue.get("operational_impact") or "Impact has not been established.")}</p><h4>Evidence</h4><p>{refs}</p><p><a href="system-blueprint.html#architecture">Open affected architecture in the Blueprint →</a></p><h4>Probable causes</h4>{_list(_string_list(issue.get("probable_causes")), "Cause not established.")}<h4>Ordered approach</h4>{_ordered(_string_list(issue.get("primary_approach")))}{command_html}<h4>Success criteria</h4>{_list(_string_list(issue.get("success_criteria")), "Repeat inspection no longer reports the condition.")}</div></details>"""


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
                _bytes(item.get("capacity_bytes")),
            ]
        )
    return _table(["Function", "Device", "Path", "Capacity"], rows)


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
                item.get("state"),
                _display(item.get("ipv4_addresses")),
                item.get("speed_mbps"),
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
    ) + _table(["Role", "Interface", "State", "IPv4", "Mb/s", "Driver"], rows)


def _software_table(
    records: list[dict[str, Any]],
    *,
    include_anchors: bool = False,
    link_to_blueprint: bool = False,
) -> str:
    rows = []
    for item in records:
        details = _mapping(item.get("details"))
        name = str(item.get("name") or "Unnamed stack")
        display_name = (
            f'<a href="system-blueprint.html#stack-{_slug(name)}">{_h(name)}</a>'
            if link_to_blueprint
            else _h(name)
        )
        rows.append(
            [
                display_name,
                details.get("stack_category") or item.get("category"),
                details.get("version") or details.get("detected_packages"),
                _yes_no(details.get("installed")),
                _yes_no(details.get("configured")),
                _yes_no(details.get("running")),
                _yes_no(details.get("connected")),
                _yes_no(details.get("integrated")),
                details.get("capability"),
                details.get("capability_state"),
                details.get("state") or item.get("status"),
            ]
        )
    return _software_grid(rows, include_anchors=include_anchors, raw_name=True)


def _software_grid(rows: list[list[Any]], *, include_anchors: bool, raw_name: bool) -> str:
    headers = [
        "Stack",
        "Category",
        "Version / packages",
        "Installed",
        "Configured",
        "Running",
        "Connected",
        "Integrated",
        "Capability",
        "Capability state",
        "Operational stage",
    ]
    head = "".join(f"<th>{_h(value)}</th>" for value in headers)
    body: list[str] = []
    for row in rows:
        name_text = re.sub(r"<[^>]+>", "", str(row[0]))
        row_id = f' id="stack-{_slug(name_text)}"' if include_anchors else ""
        cells = "".join(
            f"<td>{value if raw_name and index == 0 else _h(_display(value))}</td>"
            for index, value in enumerate(row)
        )
        body.append(f"<tr{row_id}>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


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
