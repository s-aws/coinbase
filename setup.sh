#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${project_root}"

select_python() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
            printf 'PYTHON_BIN=%s was not found.\n' "${PYTHON_BIN}" >&2
            exit 1
        }
        "${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))' || {
            printf 'PYTHON_BIN must select Python 3.14: %s\n' "${PYTHON_BIN}" >&2
            exit 1
        }
        printf '%s\n' "${PYTHON_BIN}"
        return
    fi
    for candidate in python3.14; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            if "${candidate}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'; then
                printf '%s\n' "${candidate}"
                return
            fi
        fi
    done
    printf 'Python 3.14 is required.\n' >&2
    exit 1
}

python_bin="$(select_python)"
venv_dir="${VENV_DIR:-${project_root}/.venv}"

if [[ -e "${venv_dir}" && ! -x "${venv_dir}/bin/python3.14" ]]; then
    printf 'Existing virtual environment is not Python 3.14: %s\n' "${venv_dir}" >&2
    printf 'Remove it or choose a new path with VENV_DIR before rerunning setup.\n' >&2
    exit 1
fi

if [[ -x "${venv_dir}/bin/python3.14" ]]; then
    if ! "${venv_dir}/bin/python3.14" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'; then
        printf 'Existing virtual environment does not use Python 3.14: %s\n' "${venv_dir}" >&2
        printf 'Remove it or choose a new path with VENV_DIR before rerunning setup.\n' >&2
        exit 1
    fi
else
    "${python_bin}" -m venv "${venv_dir}"
fi

ln -sfn python3.14 "${venv_dir}/bin/python"
ln -sfn python3.14 "${venv_dir}/bin/python3"

"${venv_dir}/bin/python3.14" -m pip install --upgrade pip
"${venv_dir}/bin/python3.14" -m pip install -e .
"${venv_dir}/bin/python3.14" -m pip install -r tests/requirements.txt

"${project_root}/scripts/test_database.sh" start

COINBASE_DB_HOST="${COINBASE_TEST_DB_HOST:-127.0.0.1}" \
COINBASE_DB_PORT="${COINBASE_TEST_DB_PORT:-9876}" \
COINBASE_DB_NAME="${COINBASE_TEST_DB_NAME:-postgres}" \
COINBASE_DB_USER="${COINBASE_TEST_DB_USER:-postgres}" \
COINBASE_DB_PASSWORD="${COINBASE_TEST_DB_PASSWORD:-postgres}" \
    "${venv_dir}/bin/python3.14" -m database.schema

printf '\nSetup complete.\n'
printf 'Run tests: %s/scripts/run_tests.sh\n' "${project_root}"
printf 'Validate a clean release: %s/scripts/validate_release.sh\n' "${project_root}"
printf 'After setting runtime DB/API variables, deploy paused: %s/scripts/deploy_runtime.sh\n' "${project_root}"
printf 'Database-only preparation: %s/scripts/bootstrap_runtime_database.sh\n' "${project_root}"
