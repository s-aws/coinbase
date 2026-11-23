#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VENV_DIR:-${project_root}/.venv}/bin/python3.14"

[[ -x "${python_bin}" ]] || {
    printf 'Virtual environment not found. Run ./setup.sh first.\n' >&2
    exit 1
}

"${python_bin}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))' || {
    printf 'Python 3.14 is required.\n' >&2
    exit 1
}

"${project_root}/scripts/test_database.sh" start
exec "${python_bin}" "${project_root}/scripts/stress_cancel_pipeline.py" "$@"
