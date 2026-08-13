#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "Usage: $0 path/to/screwdriver_robotics-*.whl" >&2
    exit 2
fi

readonly WHEEL_PATH="$(realpath -- "$1")"

if [[ ! -f "${WHEEL_PATH}" || "${WHEEL_PATH}" != *.whl ]]; then
    echo "Error: expected one existing wheel file, received: ${WHEEL_PATH}" >&2
    exit 2
fi

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SMOKE_ROOT="$(mktemp -d)"
readonly SMOKE_ENV="${SMOKE_ROOT}/venv"
readonly REPORT_ROOT="${SMOKE_ROOT}/reports"
readonly PROJECT_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

UV_BINARY=""
if command -v uv >/dev/null 2>&1; then
    UV_BINARY="$(command -v uv)"
elif [[ -x "${PROJECT_ROOT}/.tools/bin/uv" ]]; then
    UV_BINARY="${PROJECT_ROOT}/.tools/bin/uv"
else
    echo "Error: uv is missing; run ./scripts/bootstrap.sh first." >&2
    exit 1
fi
readonly UV_BINARY

cleanup() {
    rm -rf -- "${SMOKE_ROOT}"
}
trap cleanup EXIT

cd "${PROJECT_ROOT}"

if [[ ! -x "${PROJECT_PYTHON}" ]]; then
    echo "Error: project environment is missing; run uv sync --locked --all-groups first." >&2
    exit 1
fi

echo "Creating isolated smoke-test environment..."
"${UV_BINARY}" venv --python "${PROJECT_PYTHON}" "${SMOKE_ENV}"

echo "Installing built wheel..."
"${UV_BINARY}" pip install --python "${SMOKE_ENV}/bin/python" "${WHEEL_PATH}"

echo "Verifying installed package metadata..."
"${SMOKE_ENV}/bin/python" - <<'PY'
from importlib.metadata import version

import screwdriver

distribution_version = version("screwdriver-robotics")
assert distribution_version == screwdriver.__version__, (
    f"distribution version {distribution_version!r} does not match "
    f"package version {screwdriver.__version__!r}"
)
print(f"Installed screwdriver-robotics {distribution_version}")
PY

echo "Verifying installed CLI surfaces..."
"${SMOKE_ENV}/bin/screwdriver" --help >/dev/null
"${SMOKE_ENV}/bin/screwdriver" inspect --help >/dev/null
"${SMOKE_ENV}/bin/screwdriver" analyze --help >/dev/null

echo "Running passive inspection through the installed wheel..."
"${SMOKE_ENV}/bin/screwdriver" inspect --local --output "${REPORT_ROOT}" \
    >"${SMOKE_ROOT}/inspection.stdout"

for artifact in snapshot.json report.txt report.html inspection.log report-manifest.json; do
    if [[ ! -f "${REPORT_ROOT}/local/latest/${artifact}" ]]; then
        echo "Error: installed-wheel inspection did not create ${artifact}" >&2
        exit 1
    fi
done

echo "Release wheel smoke test passed."
