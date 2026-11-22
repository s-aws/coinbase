#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VENV_DIR:-${project_root}/.venv}/bin/python"

[[ -x "${python_bin}" ]] || {
    printf 'Virtual environment not found. Run ./setup.sh first.\n' >&2
    exit 1
}

"${project_root}/scripts/test_database.sh" start
exec "${python_bin}" -m pytest \
    -c "${project_root}/tests/pytest.ini" \
    "${project_root}/tests" \
    -m "not external" \
    -v \
    --tb=short
