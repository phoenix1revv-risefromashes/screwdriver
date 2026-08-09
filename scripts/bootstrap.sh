#!/usr/bin/env bash

set -euo pipefail

readonly UV_VERSION="0.12.3"
readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly TOOL_DIRECTORY="${PROJECT_ROOT}/.tools/bin"
readonly UV_BINARY="${TOOL_DIRECTORY}/uv"

update_lock=false

case "${1:-}" in
    "")
        ;;
    --update-lock)
        update_lock=true
        ;;
    *)
        printf 'Usage: %s [--update-lock]\n' "$0" >&2
        exit 64
        ;;
esac

install_uv() {
    mkdir -p "${TOOL_DIRECTORY}"

    printf 'Installing uv %s locally...\n' "${UV_VERSION}"

    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" |
            env \
                UV_INSTALL_DIR="${TOOL_DIRECTORY}" \
                UV_NO_MODIFY_PATH=1 \
                sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "https://astral.sh/uv/${UV_VERSION}/install.sh" |
            env \
                UV_INSTALL_DIR="${TOOL_DIRECTORY}" \
                UV_NO_MODIFY_PATH=1 \
                sh
    else
        printf 'Error: bootstrap requires curl or wget.\n' >&2
        exit 69
    fi
}

if [[ ! -x "${UV_BINARY}" ]]; then
    install_uv
fi

if [[ "$("${UV_BINARY}" --version)" != "uv ${UV_VERSION}" ]]; then
    printf 'The local uv installation is not version %s; reinstalling.\n' "${UV_VERSION}"
    install_uv
fi

cd "${PROJECT_ROOT}"

"${UV_BINARY}" python install

if [[ "${update_lock}" == true ]]; then
    "${UV_BINARY}" lock
elif [[ ! -f uv.lock ]]; then
    printf 'Error: uv.lock is missing.\n' >&2
    printf 'Maintainers may create it with: ./scripts/bootstrap.sh --update-lock\n' >&2
    exit 66
fi

"${UV_BINARY}" sync --locked --group dev

printf '\nScrewdriver development environment is ready.\n'
printf 'Virtual environment: %s/.venv\n' "${PROJECT_ROOT}"
printf 'Run commands with: .tools/bin/uv run --locked <command>\n'
