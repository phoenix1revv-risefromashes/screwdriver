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

Collects the same system evidence, then uses AI to organize, filter, and present the information most relevant to the user.

```bash
screwdriver inspect --agentic --focus "camera and ROS 2"
```

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
