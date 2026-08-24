# Screwdriver

Screwdriver passively inspects Linux-based robotics computers from the host and hardware layers up through networking, device interfaces, ROS 2, and robotics software. It keeps deterministic evidence exhaustive while presenting human reports as curated engineering views.

## Core commands

```bash
screwdriver inspect
screwdriver inspect --find-issues
screwdriver inspect --agentic
screwdriver inspect --find-issues --agentic
```

Run Screwdriver as the normal robot user. Do not run the whole application with `sudo`. If a specific diagnostic check needs elevated access, the diagnostic report may recommend a narrowly scoped `sudo` command only after its target and required value are established from evidence.

`--no-open` saves the generated HTML without launching a browser.

## Reports

### Deterministic local inspection

```bash
screwdriver inspect
```

Produces the exhaustive passive snapshot plus the local text and HTML inspection reports. The local HTML is organized into exactly seven top-level sections: Core System Specs, Connectivity, Hardware Inventory, ROS 2, Robotics Software Stacks, Diagnostics, and Report & Provenance. Raw evidence remains exhaustive in `snapshot.json`, while the human report curates host/kernel noise. Unverified onboard UART candidates such as ttyTHS/ttyAMA remain in raw evidence unless the collector establishes that they are real robot-facing hardware.

### Agentic reports

```bash
screwdriver inspect --agentic
```

Agentic mode always runs and saves the normal deterministic local inspection first. It then analyzes that exact local evidence and writes **exactly two files** in the matching `reports/agentic/<scan-id>/` directory:

```text
agentic-system-blueprint-report.html
agentic-system-diagnostic-report.html
```

No compact snapshot, structured-analysis JSON, manifest, or intermediate reasoning artifact is written into the agentic run directory. The normal local artifacts remain unchanged under `reports/local/<scan-id>/`.

`--find-issues --agentic` still generates the same two agentic reports; it changes terminal emphasis and selects the Diagnostic report for auto-open. Plain `--agentic` selects the Blueprint for auto-open.

#### Agentic System Blueprint Report

The Blueprint reconstructs the machine rather than repeating inventory. Its five locked top-level sections are:

1. Whole System Summary
2. Core System Specs
3. Hardware Components Status
4. Software & Runtime Status
5. Verified Integration Chains

The Whole System Summary states the probable system purpose and role, established operational capabilities, important cross-layer architecture observations, and evidence boundaries. The integration model is:

```text
physical component
→ interface / driver
→ OS interface
→ runtime owner
→ endpoint / consumer
→ robot capability
```

A link is marked VERIFIED only when the meaningful chain is established by evidence. PARTIAL preserves missing links. INFERRED is used only when evidence supports the relationship without directly proving it. Detection or installation alone is never promoted to operation, integration, or capability proof.

#### Agentic System Diagnostic Report

The Diagnostic report is organized around problems, evidence, root cause, correction, and proof of recovery:

1. Diagnostic Summary
2. Prioritized Findings
3. Root-Cause Analysis
4. Verification Summary
5. Unresolved Evidence, only when needed

Each RCA keeps these details together: expected state, observed state, affected components/software/capability, operational impact, observed evidence, evidence trace, observation confidence, diagnosis confidence, probable causes, root-cause chain, likely root cause, passive investigation commands, expected command results, correction/remediation, expected outcome, verification, measurable recovery criteria, and rollback/recovery. Severity and diagnosis certainty are separate concepts.

The report must preserve uncertainty. ABSENT, UNINSPECTED, PERMISSION BLOCKED, COLLECTOR FAILURE, UNKNOWN, INSTALLED, RUNNING, CONNECTED, INTEGRATED, INFERRED, and VERIFIED are not interchangeable states. In particular, a ROS environment unavailable to the inspection shell does not by itself prove that the deployed robot ROS graph is down.

Both agentic reports share the same scan identity and include Scan ID, generated time, target, report mode, Screwdriver version, probe safety, provider, model, effort, scan duration, and agentic status. Agent/provider interpretation is accepted only when it can be reconciled with deterministic evidence; unresolved relationships remain unresolved.

## Agent providers

Agentic reporting supports `anthropic`, `openai`, and `none`.

```bash
screwdriver inspect --agentic --provider anthropic --effort high
screwdriver inspect --agentic --provider openai --effort high
screwdriver inspect --agentic --provider none
```

Provider/model reasoning is validated against deterministic evidence. Provider failure falls back to deterministic analysis instead of fabricating missing evidence.

## Read-only investigation

```bash
screwdriver inspect --find-issues --agentic --investigate
```

`--investigate` allows only a bounded catalog of additional read-only probes. Screwdriver does not execute repairs, actuate hardware, publish robot commands, edit configuration, restart services, change permissions, or install packages.

## Report opening

On a direct graphical Linux session, the generated human HTML report opens automatically after successful completion. Use `--no-open` to disable this.

A normal remote SSH process cannot open the browser on the SSH client. Use the client-side wrapper instead:

```bash
screwdriver-ssh phoenix@192.168.4.68 --cwd ~/pro_projects/screwdriver inspect
screwdriver-ssh phoenix@192.168.4.68 --cwd ~/pro_projects/screwdriver inspect --agentic
screwdriver-ssh phoenix@192.168.4.68 --cwd ~/pro_projects/screwdriver inspect --find-issues --agentic
```

The wrapper runs the scan remotely with `--no-open`, copies the selected HTML report to the client, and opens that local copy.

## Validation

Before release:

```bash
.venv/bin/ruff format src tests
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
.venv/bin/mypy src
git diff --check
```
