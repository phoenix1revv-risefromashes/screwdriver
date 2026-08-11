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
report/local/<date_timestamp>/snapshot.json
report/local/<date_timestamp>/report.txt
report/local/<date_timestamp>/report.html
report/local/<date_timestamp>/inspection.log
report/local/<date_timestamp>/report-manifest.json
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
report/local/<date_timestamp>/snapshot.json
report/local/<date_timestamp>/report.txt
report/local/<date_timestamp>/report.html
report/local/<date_timestamp>/inspection.log
report/agentic/<same_date_timestamp>/compact_snapshot.html
report/agentic/<same_date_timestamp>/system-blueprint.html
report/agentic/<same_date_timestamp>/diagnostic-report.html
report/agentic/<same_date_timestamp>/agent-analysis.json
```

The compact snapshot contains only the operationally useful overview: evidence
state, working checks, actionable findings, unknowns, next check, data flow, and
coverage. The blueprint and diagnostic report retain the detailed engineering
evidence. Provider availability is report-generation metadata, not robot health.

The complete `snapshot.json` remains local. Agentic analysis supports Anthropic and
OpenAI. API keys are read from `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and are never
stored in a report. The evidence view removes machine IDs, serial numbers, MAC
addresses, and the default gateway before model analysis.

A focused inspection can be requested with:

```bash
screwdriver inspect --agentic \
  --focus "camera, networking, and ROS 2"
```

The system blueprint explains what is installed and how components relate. The
diagnostic report separately explains observed problems, likely causes, ordered
solution approaches, diagnostic commands, and measurable success criteria.

### Options

| Option | Purpose |
|---|---|
| `--local` | Perform a complete offline inspection |
| `--agentic` | Produce an AI-organized inspection |
| `--focus TEXT` | Focus agentic inspection on selected areas |
| `--output PATH` | Select the report root containing `local/` and `agentic/` |
| `--provider anthropic\|openai\|none` | Select Anthropic, OpenAI, or deterministic analysis |
| `--model MODEL` | Select a provider model (defaults: `claude-sonnet-5` or `gpt-5.6-terra`) |
| `--effort light\|medium\|high` | Balance provider reasoning and token use (default `medium`) |
| `--investigate` | Permit the closed catalog of extra read-only probes |

`--local` and `--agentic` are mutually exclusive.

`light` maps to each provider's API value `low`. Claude Sonnet 5 and GPT-5.6
Terra accept all three exposed levels. Other compatible structured-output models
remain selectable. If one rejects the effort parameter, Screwdriver retries the
request once without effort and records that the model's native default was used.

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
report/agentic/<date_timestamp>/compact_snapshot.html
report/agentic/<date_timestamp>/system-blueprint.html
report/agentic/<date_timestamp>/diagnostic-report.html
report/agentic/<date_timestamp>/agent-analysis.json
```

Example:

```bash
screwdriver analyze snapshot.json \
  --output report
```

`--investigate` authorizes at most four additional probes chosen from a closed
catalog. Probe arguments are validated, commands run without a shell, output and
execution time are bounded, and probes only run when the snapshot hostname
matches the current computer. Invalid probe requests are recorded as rejected
instead of silently disappearing.

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