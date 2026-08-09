# Command-Line Interface

Screwdriver provides two primary commands:

```text
inspect → Understand what the robotic system contains
analyze → Determine what is wrong and recommend fixes
```

All inspection operations are read-only.

## `screwdriver inspect`

Collects hardware, software, configuration, network, driver, device, and robotics-runtime evidence.

### Local inspection

```bash
screwdriver inspect --local
```

This mode:

- Works completely offline
- Collects the complete system snapshot
- Uses no AI service
- Preserves detailed technical evidence
- Does not diagnose problems
- Does not change the system

Generated files:

```text
snapshot.json
snapshot.html
```

Running `inspect` without a mode defaults to local:

```bash
screwdriver inspect
```

Equivalent to:

```bash
screwdriver inspect --local
```

### Agentic inspection

```bash
screwdriver inspect --agentic
```

This mode:

1. Performs the complete inspection locally.
2. Stores the full raw snapshot locally.
3. Redacts sensitive information.
4. Allows the AI agent to retrieve relevant evidence through controlled tools.
5. Creates an organized, filtered system overview.

Generated files:

```text
snapshot.json
agentic-snapshot.html
```

The complete `snapshot.json` remains local. Only selected and redacted evidence may be sent to the configured AI provider.

A focused inspection can be requested with:

```bash
screwdriver inspect --agentic \
  --focus "camera, networking, and ROS 2"
```

The agentic inspection explains what is installed and how components relate. It does not diagnose faults or recommend fixes.

### Options

| Option | Purpose |
|---|---|
| `--local` | Perform a complete offline inspection |
| `--agentic` | Produce an AI-organized inspection |
| `--focus TEXT` | Focus agentic inspection on selected areas |
| `--output PATH` | Select the output directory |
| `--format FORMAT` | Select `json`, `html`, or `all` |
| `--no-redact` | Disable redaction for local output only |
| `--verbose` | Display detailed inspection progress |

`--local` and `--agentic` are mutually exclusive.

## `screwdriver analyze`

Analyzes an existing inspection snapshot:

```bash
screwdriver analyze snapshot.json
```

The command:

- Validates the snapshot
- Runs deterministic diagnostic rules
- Detects bugs and misconfigurations
- Correlates evidence across system layers
- Uses agentic AI for root-cause investigation
- Assigns severity and confidence
- Explains every finding
- Recommends safe fixes
- Never executes the recommended fixes

Generated files:

```text
analysis-report.json
analysis-report.html
```

Example:

```bash
screwdriver analyze snapshot.json \
  --output reports/analysis
```

## Command boundaries

| Command | Complete snapshot | AI organization | Diagnosis | Fix recommendations | Modifies system |
|---|---:|---:|---:|---:|---:|
| `inspect --local` | Yes | No | No | No | No |
| `inspect --agentic` | Yes | Yes | No | No | No |
| `analyze` | Uses existing snapshot | Yes | Yes | Yes | No |

## Safety

Screwdriver must never automatically:

- Modify system configuration
- Install or remove packages
- Restart services
- Change network settings
- Alter device permissions
- Load or unload kernel modules
- Flash firmware
- Execute AI-generated repair commands

Every recommendation remains under human control.
