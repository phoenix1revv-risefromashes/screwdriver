# Screwdriver
[![CI](https://github.com/phoenix1revv-risefromashes/screwdriver/actions/workflows/ci.yml/badge.svg)](https://github.com/phoenix1revv-risefromashes/screwdriver/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)



Screwdriver is a read-only Linux inspection and AI-assisted agentic-diagnostic tool for robotic systems.

It inspects hardware, drivers, software, networking, devices, and robotics runtimes, then prepares the comprehensive system architecture blueprint, identify bugs, misconfigurations, likely root causes, and recommended fixes -- running locally or agentic assistant [OPENAI, ANTHROPIC CLAUDE]


## Getting started

### Requirements

- A Linux robotics computer or Linux development host
- Git and `curl`
- Internet access for initial setup
- An API key only when Anthropic or OpenAI analysis is desired

### Install

```bash
git clone https://github.com/phoenix1revv-risefromashes/screwdriver.git
cd screwdriver
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

The bootstrap script installs the pinned `uv` and Python versions locally, verifies
`uv.lock`, creates `.venv`, and installs the locked dependencies.

Run without activating the environment:

```bash
.tools/bin/uv run --locked screwdriver --help
```

Or activate it correctly AND run CLI:

```bash
source .venv/bin/activate
screwdriver --help
```


### First local inspection

```bash
.tools/bin/uv run --locked screwdriver inspect --local
```

Open `reports/local/latest/report.html`.



## Complete command reference

The examples below omit `.tools/bin/uv run --locked` for readability. Prefix it when
the environment is not activated.

### Help

```bash
screwdriver
screwdriver --help
screwdriver inspect --help
screwdriver analyze --help
```

### `screwdriver inspect`

Collect a new passive snapshot from the current Linux computer:

```bash
screwdriver inspect [--local | --agentic] [OPTIONS]
```

| Option | Values | Default | Meaning |
|---|---|---|---|
| `--local` | Flag | Used when no mode is supplied | Generate local deterministic reports |
| `--agentic` | Flag | Off | Collect locally, then generate all three analysis reports |
| `--output` | Path | `reports` | Root containing `local/` and `agentic/` |
| `--provider` | `anthropic`, `openai`, `none` | `anthropic` | Analysis provider used with `--agentic` |
| `--model` | Model ID | Provider default | Override the provider's default model |
| `--effort` | `light`, `medium`, `high` | `medium` | Requested reasoning effort |
| `--focus` | Text | Complete system | Emphasize a subsystem while retaining complete evidence; requires `--agentic` |
| `--investigate` | Flag | Off | Permit up to four validated read-only probes; requires `--agentic` |
| `-h`, `--help` | Flag | — | Show command help |

`--local` and `--agentic` are mutually exclusive. Provider options do nothing during
a local-only inspection.

```bash
# Local modes
screwdriver inspect
screwdriver inspect --local
screwdriver inspect --local --output /path/to/reports

# Default agentic mode: Anthropic, Claude Sonnet 5, medium effort
screwdriver inspect --agentic

# Explicit Anthropic
screwdriver inspect --agentic \
  --provider anthropic --model claude-sonnet-5 --effort medium

# Explicit OpenAI
screwdriver inspect --agentic \
  --provider openai --model gpt-5.6-terra --effort medium

# No remote model
screwdriver inspect --agentic --provider none

# Focused interpretation
screwdriver inspect --agentic \
  --focus "ROS 2, Nav2, SLAM, and device ownership"

# Bounded read-only investigation
screwdriver inspect --agentic --investigate

# Fully customized run
screwdriver inspect --agentic \
  --provider openai \
  --model gpt-5.6-terra \
  --effort high \
  --focus "localization and navigation" \
  --investigate \
  --output /path/to/reports
```

### `screwdriver analyze`

Generate analysis reports from an existing `snapshot.json` without collecting the
computer again:

```bash
screwdriver analyze SNAPSHOT [OPTIONS]
```

| Argument or option | Values | Default | Meaning |
|---|---|---|---|
| `SNAPSHOT` | Path | Required | Existing `snapshot.json` to analyze |
| `--output` | Path | `reports` | Root containing the new agentic run |
| `--provider` | `anthropic`, `openai`, `none` | `anthropic` | Remote or deterministic analysis |
| `--model` | Model ID | Provider default | Override the provider model |
| `--effort` | `light`, `medium`, `high` | `medium` | Requested reasoning effort |
| `--focus` | Text | Complete system | Emphasize one subsystem while retaining complete evidence |
| `--investigate` | Flag | Off | Permit validated probes when the snapshot belongs to this host |
| `-h`, `--help` | Flag | — | Show command help |

```bash
# Default Anthropic analysis
screwdriver analyze reports/local/latest/snapshot.json

# Deterministic analysis
screwdriver analyze reports/local/latest/snapshot.json --provider none

# Explicit Anthropic
screwdriver analyze reports/local/latest/snapshot.json \
  --provider anthropic --model claude-sonnet-5 --effort high

# OpenAI with focused investigation
screwdriver analyze reports/local/latest/snapshot.json \
  --provider openai \
  --model gpt-5.6-terra \
  --effort high \
  --focus "serial controller and ROS ownership" \
  --investigate

# Custom report root
screwdriver analyze /path/to/snapshot.json \
  --provider none --output /path/to/reports
```

## Provider, model, and effort chart

| Provider | CLI value | Default verified model | Compatible models | API key | Efforts |
|---|---|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-5` | Anthropic Messages API models supporting JSON-schema structured output; custom model IDs are accepted | `ANTHROPIC_API_KEY` | `light`, `medium`, `high` |
| OpenAI | `openai` | `gpt-5.6-terra` | OpenAI Responses API models supporting strict JSON-schema text output; custom model IDs are accepted | `OPENAI_API_KEY` | `light`, `medium`, `high` |
| Deterministic | `none` | No model | Not applicable | None | Accepted by the CLI, but no remote reasoning occurs |

The named defaults are the tested v1 configurations. Custom model availability and
structured-output support depend on the provider account and API. Screwdriver accepts
custom IDs, and the provider validates their capabilities at request time.

| Screwdriver effort | Provider API value | Intended use |
|---|---|---|
| `light` | `low` | Faster, lower-cost organization of straightforward evidence |
| `medium` | `medium` | Balanced default for complete system analysis |
| `high` | `high` | Deeper correlation for complex bring-up and diagnostics |

If a compatible model rejects the effort field, Screwdriver retries once without it
and records that the model's native default was used. If a remote provider is missing
its key or unavailable, deterministic fallback reports are still generated and clearly
labeled.


### Uisng Agentic-assistance (API keys)
First export the API_KEY to the terminal environemt:

```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

```bash
export OPENAI_API_KEY="your-openai-api-key"
```


Then ssimply follow the CLI protocol explained before:

screwdriver inspect --agentic \
  --provider anthropic --model claude-sonnet-5 --effort medium

# Explicit OpenAI
screwdriver inspect --agentic \
  --provider openai --model gpt-5.6-terra --effort medium


Keys are read from the environment and are never written to snapshots or reports.

## Output layout

Runs use America/Los_Angeles report time and non-overwriting directory names in the
form `YYYY-MM-DD_HH:MM:SS`. A numeric suffix handles timestamp collisions. The
`latest` symlink is updated atomically after completion.

```text
reports/
├── local/
│   ├── YYYY-MM-DD_HH:MM:SS/
│   │   ├── snapshot.json
│   │   ├── report.txt
│   │   ├── report.html
│   │   ├── inspection.log
│   │   └── report-manifest.json
│   └── latest -> YYYY-MM-DD_HH:MM:SS
└── agentic/
    ├── YYYY-MM-DD_HH:MM:SS/
    │   ├── compact_snapshot.html
    │   ├── system-blueprint.html
    │   ├── diagnostic-report.html
    │   ├── agent-analysis.json
    │   └── report-manifest.json
    └── latest -> YYYY-MM-DD_HH:MM:SS
```

An agentic inspection creates matching local and agentic scan IDs. Existing runs are
never overwritten.

## Inspection coverage

Screwdriver passively collects and correlates:

- Linux, kernel, architecture, platform, firmware, CPU, memory, GPU, storage, power,
  thermals, processes, and services
- USB topology, PCI evidence, serial/UART, stable device identities, permissions,
  kernel modules, drivers, and device paths
- Network interfaces, IP configuration, routes, DNS, link state, CAN, and virtual links
- Sensors, actuators, cameras, audio devices, LiDAR, MCU/debug interfaces, and containers
- ROS installations, sourced environment, workspaces, RMW/DDS, domain ID, and discovery
- ROS nodes, topics, services, actions, data flow, and hardware ownership evidence

### Robotics software-stack coverage

| Domain | Tracked stacks and capabilities |
|---|---|
| Navigation and localization | Navigation2, AMCL, Robot Localization |
| SLAM and mapping | SLAM Toolbox, Cartographer, RTAB-Map |
| Motion and control | `ros2_control`, hardware interfaces, controllers |
| Manipulation | MoveIt, planning scenes, trajectories, execution paths |
| Perception and AI | Camera drivers, LiDAR drivers, GPU-accelerated perception |
| Speech and interaction | Audio capture/playback, STT, TTS |
| MCU and embedded bridges | micro-ROS and observable serial, UDP, or CAN bridges |
| Simulation and visualization | Gazebo, Isaac ROS, Webots, RViz, Robot State Publisher |
| Teleoperation | Keyboard, joystick, and remote command paths |
| Recording and telemetry | Rosbag, diagnostics, monitoring, and health aggregation |

For every recognized stack, Screwdriver separates:

```text
installation → configuration → runtime → connectivity → integration → capability
```

An absent optional stack is not a fault unless evidence establishes that the deployed
robot requires it. Older snapshots receive explicit **not recorded in snapshot** states
instead of misleading `NOT_INSTALLED` claims.

## Evidence guarantees

- Raw `snapshot.json` remains on the inspected host.
- Provider evidence is bounded, deduplicated, and redacted.
- Machine IDs, serial numbers, MAC addresses, and gateway identifiers are removed from
  the provider evidence view.
- Truncated or omitted paths are disclosed.
- Remote output must match a strict schema.
- New model findings are accepted only when evidence references resolve to the snapshot.
- Observation confidence and diagnosis confidence are separate.
- Provider, model, effort, token usage when available, request ID, duration, fallback
  state, scan ID, and snapshot hash are preserved.
- Unknown evidence remains unknown.

## Read-only investigation

`--investigate` permits at most four provider-requested checks:

| Probe | Command family |
|---|---|
| ROS node metadata | `ros2 node info` |
| ROS topic metadata | `ros2 topic info --verbose` |
| ROS parameter names | `ros2 param list` |
| Device metadata | `udevadm info` |
| Device owner | `lsof` |
| Service status | `systemctl status` |
| Recent kernel messages | `journalctl -k` |
| Network link metadata | `ip -details link show` |

Targets are validated, commands execute without a shell, time and output are bounded,
and rejected requests remain visible. Probes run only when the snapshot hostname
matches the current computer.

## Safety

Screwdriver does **not** automatically:

- Activate actuators or publish robot commands
- Modify configuration or network settings
- Install, upgrade, or remove packages
- Restart services or containers
- Change users, groups, ownership, or device permissions
- Load or unload kernel modules
- Flash firmware
- Execute model-generated repair commands

The Diagnostic Report may display clearly labeled system-changing command examples for
human review. It never executes them.

## Development

```bash
./scripts/bootstrap.sh

.tools/bin/uv run --locked ruff format --check .
.tools/bin/uv run --locked ruff check .
.tools/bin/uv run --locked mypy src
.tools/bin/uv run --locked pytest
```

After an intentional `pyproject.toml` dependency change:

```bash
.tools/bin/uv lock
.tools/bin/uv sync --locked --group dev
```

Commit `pyproject.toml` and `uv.lock` together. Do not regenerate the lockfile merely to
hide an unexpected mismatch.



### Provider key is missing

Deterministic fallback is automatic. To request it explicitly:

```bash
screwdriver inspect --agentic --provider none
```

### ROS 2 is installed but the graph is empty

Run Screwdriver from the same sourced underlay, overlay, domain, and middleware context
used by the robot application. Installed ROS, a sourced shell, and a discoverable graph
are separate evidence states.

## License

Screwdriver is released under the [MIT License](LICENSE). Copyright © 2026 Phoenix Bogati.


## Sample reports

- [Quick System Snapshot](assets/samples/compact_snapshot.html)
- [Complete System Blueprint](assets/samples/system-blueprint.html)
- [Engineering Diagnostic Report](assets/samples/diagnostic-report.html)

