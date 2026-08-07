# Screwdriver

Screwdriver is an agentic inspection and diagnostics tool for Linux robotics systems.

Its goal is to identify the host computer, connected hardware, drivers, Linux interfaces and ROS 2 architecture—then investigate failures using verified system evidence.

## Current milestone

`v0.1.0` — Agentic host-system identification.

The first release will identify:

- Linux distribution and kernel
- Computer or development-board model
- CPU, GPU, memory and storage
- Jetson, Raspberry Pi, x86 or generic Linux platform
- Available system commands and interfaces
- ROS 2 environment
- JetPack, L4T and CUDA on Jetson systems

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Initial commands

```bash
screwdriver --version
screwdriver inspect
python -m screwdriver inspect
```

## Development checks

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m build
```

## Safety principles

Screwdriver begins as a strictly read-only tool.

It does not:

- Use `sudo`
- Modify system configuration
- Move actuators
- Communicate with hardware unnecessarily
- Execute arbitrary AI-generated shell commands

The agent may select only registered, read-only scanners.

## License

Released under the MIT License.