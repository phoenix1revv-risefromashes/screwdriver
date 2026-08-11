# Screwdriver

[![CI](https://github.com/phoenix1revv-risefromashes/screwdriver/actions/workflows/ci.yml/badge.svg)](https://github.com/phoenix1revv-risefromashes/screwdriver/actions/workflows/ci.yml)


Screwdriver is a read-only Linux inspection and AI-assisted diagnostic tool for robotic systems.

It inspects hardware, drivers, software, networking, devices, and robotics runtimes, then helps identify bugs, misconfigurations, likely root causes, and recommended fixes.

> Screwdriver is currently under active development.

## Core commands

### Local inspection

```bash
screwdriver inspect --local
```

Creates a complete offline snapshot of the system without using AI.

### Agentic inspection

```bash
screwdriver inspect --agentic
```

Collects the same system evidence, then generates:

* `compact_snapshot.html` — a findings-first, one-minute operational view
* `system-blueprint.html` — a detailed, organized map of the robotic system
* `diagnostic-report.html` — failures, likely causes, and step-by-step solutions
* `agent-analysis.json` — validated structured evidence behind all three reports

Every run is isolated and never overwrites an older report:

```text
report/
├── local/<date_timestamp>/
│   ├── snapshot.json
│   ├── report.txt
│   ├── report.html
│   ├── inspection.log
│   └── report-manifest.json
└── agentic/<same_date_timestamp>/
    ├── compact_snapshot.html
    ├── system-blueprint.html
    ├── diagnostic-report.html
    ├── agent-analysis.json
    └── report-manifest.json
```

By default, Screwdriver uses Anthropic Claude Sonnet 5 and falls back to deterministic
reporting if the API is unavailable. Provider API keys are read only from environment
variables and are never written to reports.

```bash
export ANTHROPIC_API_KEY="your-new-key"
screwdriver inspect --agentic
```

Choose Anthropic or OpenAI explicitly:

```bash
export ANTHROPIC_API_KEY="your-key"
screwdriver inspect --agentic --provider anthropic --model claude-sonnet-5

export OPENAI_API_KEY="your-key"
screwdriver inspect --agentic --provider openai --model gpt-5.6-terra
```

These are the optimized defaults, so `--model` can be omitted after selecting a
provider. Any other text model that supports the provider's structured-output
request can still be supplied with `--model`.

Control the quality, latency, and token tradeoff with the same public vocabulary
for both providers:

```bash
screwdriver inspect --agentic \
  --provider anthropic \
  --model claude-sonnet-5 \
  --effort medium

screwdriver inspect --agentic \
  --provider openai \
  --model gpt-5.6-terra \
  --effort medium
```

Accepted effort values are `light`, `medium`, and `high`. `light` is translated
to the providers' API value `low`. If another otherwise-compatible model rejects
the effort setting, Screwdriver retries once without that setting and uses the
model's native default.

```bash
screwdriver inspect --agentic --focus "camera and ROS 2"
```

Allow the agent to request a bounded set of additional read-only checks:

```bash
screwdriver inspect --agentic --investigate
```

The investigation catalog contains validated metadata-only checks such as `ros2 node info`,
`ros2 topic info --verbose`, `udevadm info`, `lsof`, and recent kernel logs. It
does not accept arbitrary commands. Rejected requests, exit codes, stdout, stderr,
duration, and truncation state remain visible in the diagnostic evidence.

### Analyze

```bash
screwdriver analyze snapshot.json
```

Analyzes an inspection snapshot to:

* Detect bugs and misconfigurations
* Correlate failures across system layers
* Identify likely root causes
* Prioritize findings
* Recommend safe troubleshooting steps

Screwdriver recommends fixes but never applies them automatically.

Run without a model:

```bash
screwdriver analyze snapshot.json --provider none
```

Use Claude Sonnet 5 explicitly:

```bash
screwdriver analyze snapshot.json \
  --provider anthropic \
  --model claude-sonnet-5 \
  --effort medium
```

## Inspection areas

* Operating system, kernel, CPU, memory, storage, and GPU
* PCI and USB devices
* Drivers, kernel modules, and device nodes
* Network interfaces, addresses, and routes
* Cameras, audio, serial, and CAN devices
* Installed software and system services
* ROS 2 installations, nodes, topics, and configuration

## Quick start

```bash
git clone https://github.com/phoenix1revv-risefromashes/screwdriver.git
cd screwdriver
./scripts/bootstrap.sh
```

Run Screwdriver:

```bash
.tools/bin/uv run --locked screwdriver inspect --local
```

Run development checks:

```bash
.tools/bin/uv run --locked pytest
.tools/bin/uv run --locked ruff check .
.tools/bin/uv run --locked mypy src
```

## Safety

Screwdriver operates in read-only mode. It does not modify configuration, restart services, change permissions, install packages, flash firmware, or execute AI-recommended fixes.

## Documentation

* [Documentation index](docs/README.md)
* [Development environment](docs/getting-started/development-environment.md)
* [CLI reference](docs/reference/cli.md)

## License

License information will be added before the first public release.