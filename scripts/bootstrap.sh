#!/usr/bin/env bash

set -euo pipefail

readonly UV_VERSION="0.12.3"
readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly UV_DIRECTORY="${PROJECT_ROOT}/.tools/bin"
readonly UV_BINARY="${UV_DIRECTORY}/uv"

cd "${PROJECT_ROOT}"

install_uv() {
    if ! command -v curl >/dev/null 2>&1; then
        echo "Error: curl is required to install uv." >&2
        exit 1
    fi

    echo "Installing uv ${UV_VERSION} locally..."

    mkdir -p "${UV_DIRECTORY}"

    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" |
        env UV_UNMANAGED_INSTALL="${UV_DIRECTORY}" sh
}

if [[ ! -x "${UV_BINARY}" ]]; then
    install_uv
fi

case "$("${UV_BINARY}" --version)" in
    "uv ${UV_VERSION}"*)
        ;;
    *)
        echo "Replacing the local uv installation with version ${UV_VERSION}..."
        install_uv
        ;;
esac

echo "Installing the Python version from .python-version..."
"${UV_BINARY}" python install

echo "Verifying uv.lock..."
"${UV_BINARY}" lock --check

echo "Creating and synchronizing .venv..."
"${UV_BINARY}" sync --locked --group dev

echo
echo "Screwdriver development environment is ready."
"${UV_BINARY}" run --locked python --version
"${UV_BINARY}" run --locked pytest --version
echo "Python executable:"
"${UV_BINARY}" run --locked python -c 'import sys; print(sys.executable)'