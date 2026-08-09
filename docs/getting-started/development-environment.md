# Development Environment

This guide explains how to create and use a reproducible development environment for Screwdriver.

## Overview

Screwdriver keeps its development environment isolated from the system Python installation.

The environment is built from four committed files:

| File | Responsibility |
|---|---|
| `.python-version` | Selects the development Python version |
| `pyproject.toml` | Defines the project and allowed dependency ranges |
| `uv.lock` | Records the exact resolved dependency versions |
| `scripts/bootstrap.sh` | Reconstructs the complete environment |

Generated directories such as `.tools/` and `.venv/` are not committed.

## Prerequisites

The host computer requires:

- Linux
- Git
- `curl`
- Internet access during the initial setup

Python and `uv` do not need to be installed globally.

## Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/screwdriver.git
cd screwdriver
```

Replace `YOUR_USERNAME` with the repository owner.

## Create the environment

Run the bootstrap script:

```bash
./scripts/bootstrap.sh
```

The script performs the following operations:

1. Installs the pinned `uv` version inside `.tools/bin/`.
2. Installs the Python version specified by `.python-version`.
3. Verifies that `uv.lock` matches `pyproject.toml`.
4. Creates the isolated `.venv`.
5. Installs the exact locked dependencies.
6. Connects the local Screwdriver source package to the environment.
7. Verifies the Python and pytest installations.

No packages are installed into the system Python environment.

## Run commands without activation

The recommended approach is to run commands through the project-local `uv`:

```bash
.tools/bin/uv run --locked screwdriver
.tools/bin/uv run --locked pytest
.tools/bin/uv run --locked ruff check .
.tools/bin/uv run --locked mypy src
```

This explicitly runs every command inside Screwdriver's managed environment.

## Activate the virtual environment

Manual activation is optional:

```bash
source .venv/bin/activate
```

After activation, commands can be run directly:

```bash
screwdriver
pytest
ruff check .
mypy src
```

Leave the environment with:

```bash
deactivate
```

## Verify the environment

Check the Python version:

```bash
.tools/bin/uv run --locked python --version
```

Check the active Python executable:

```bash
.tools/bin/uv run --locked python -c \
'import sys; print(sys.executable)'
```

It should point to:

```text
screwdriver/.venv/bin/python
```

Check where Screwdriver is imported from:

```bash
.tools/bin/uv run --locked python -c \
'import screwdriver; print(screwdriver.__file__)'
```

It should point to the local `src/screwdriver/` directory.

## Rebuild the environment

The `.tools/` and `.venv/` directories are generated and disposable.

To reconstruct everything from the committed blueprint:

```bash
rm -rf .tools .venv
./scripts/bootstrap.sh
```

Do not delete these blueprint files:

```text
.python-version
pyproject.toml
uv.lock
scripts/bootstrap.sh
```

## Update dependencies

When intentionally adding or changing a dependency:

1. Edit `pyproject.toml`.
2. regenerate the lockfile:

```bash
.tools/bin/uv lock
```

3. Synchronize the environment:

```bash
.tools/bin/uv sync --locked --group dev
```

4. Run the project checks:

```bash
.tools/bin/uv run --locked pytest
.tools/bin/uv run --locked ruff check .
.tools/bin/uv run --locked mypy src
```

5. Commit both files:

```text
pyproject.toml
uv.lock
```

The lockfile must be committed whenever dependency resolution changes.

## Troubleshooting

### Bootstrap script is not executable

```bash
chmod +x scripts/bootstrap.sh
```

Then run it again:

```bash
./scripts/bootstrap.sh
```

### Lockfile does not match the project

If `pyproject.toml` was intentionally changed, regenerate the lockfile:

```bash
.tools/bin/uv lock
```

Do not regenerate it merely to bypass an unexpected error. First confirm why the project requirements changed.

### Environment appears corrupted

Reconstruct the generated environment:

```bash
rm -rf .venv
./scripts/bootstrap.sh
```