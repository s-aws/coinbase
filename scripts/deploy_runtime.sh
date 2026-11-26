#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VENV_DIR:-${project_root}/.venv}/bin/python3.14"
healthcheck_script="${project_root}/scripts/runtime_healthcheck.py"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy_runtime.sh

Validates a clean release, verifies and bootstraps a fresh runtime database,
starts the canonical `python -m main` entry point with admission paused, and
waits for the dashboard authority to report stable PAUSED health.

The launcher remains in the foreground after health succeeds. Run it under a
service/container supervisor for a durable deployment. It never resets data,
resumes trading, places orders, pushes Git commits, or daemonizes itself.
EOF
}

fail() {
    printf 'runtime deployment: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

[[ "$#" -eq 0 ]] || {
    usage >&2
    fail "this command does not accept arguments"
}

cd "${project_root}"

[[ -x "${python_bin}" ]] || {
    fail "Python 3.14 environment not found; run ./setup.sh first"
}

for variable_name in COINBASE_API_KEY COINBASE_API_SECRET; do
    [[ -n "${!variable_name:-}" ]] || {
        fail "${variable_name} must be set explicitly and cannot be empty"
    }
done

case "${DISABLE_RECONCILER:-}" in
    ""|0|false|FALSE|False|no|NO|No|off|OFF|Off)
        ;;
    *)
        fail "DISABLE_RECONCILER must be unset or explicitly false for deployment"
        ;;
esac

case "${ENGINE_START_PAUSED:-}" in
    ""|1|true|TRUE|True|yes|YES|Yes|on|ON|On)
        export ENGINE_START_PAUSED=true
        ;;
    0|false|FALSE|False|no|NO|No|off|OFF|Off)
        fail "deployment must start paused; remove the false ENGINE_START_PAUSED value"
        ;;
    *)
        fail "ENGINE_START_PAUSED has an invalid boolean value"
        ;;
esac

if [[ -z "${DASHBOARD_SERVER_HOST:-}" ]]; then
    export DASHBOARD_SERVER_HOST=127.0.0.1
fi

dashboard_port="${DASHBOARD_SERVER_PORT:-8765}"
healthcheck_url="${DEPLOYMENT_HEALTHCHECK_URL:-ws://127.0.0.1:${dashboard_port}}"
health_timeout="${DEPLOYMENT_HEALTH_TIMEOUT_SECONDS:-60}"
case "${healthcheck_url}" in
    ws://*|wss://*)
        ;;
    *)
        fail "DEPLOYMENT_HEALTHCHECK_URL must use ws:// or wss://"
        ;;
esac
"${python_bin}" -c \
    'import math, sys; value = float(sys.argv[1]); raise SystemExit(not math.isfinite(value) or value <= 0)' \
    "${health_timeout}" || {
    fail "DEPLOYMENT_HEALTH_TIMEOUT_SECONDS must be finite and greater than zero"
}

command -v flock >/dev/null 2>&1 || {
    fail "flock is required to prevent overlapping deployment launchers"
}
runtime_directory="${XDG_RUNTIME_DIR:-/tmp}"
[[ -d "${runtime_directory}" && -w "${runtime_directory}" ]] || {
    fail "runtime lock directory is unavailable: ${runtime_directory}"
}
lock_file="${runtime_directory}/coinbase-engine-deployment-${UID}.lock"
exec 9>"${lock_file}"
flock -n 9 || {
    fail "another runtime deployment launcher holds ${lock_file}"
}

assert_no_running_dashboard() {
    if "${python_bin}" "${healthcheck_script}" \
        --url "${healthcheck_url}" \
        --timeout-seconds 1 \
        --probe >/dev/null 2>&1; then
        fail "an engine dashboard already responds at ${healthcheck_url}"
    fi
}

assert_no_running_dashboard
"${project_root}/scripts/validate_release.sh"
assert_no_running_dashboard
"${project_root}/scripts/bootstrap_runtime_database.sh"

engine_pid=""
cleanup_child() {
    exit_status=$?
    trap - EXIT INT TERM
    if [[ -n "${engine_pid}" ]] && kill -0 "${engine_pid}" 2>/dev/null; then
        printf 'Stopping engine process %s after launcher exit...\n' "${engine_pid}" >&2
        kill -TERM "${engine_pid}" 2>/dev/null || true
        set +e
        wait "${engine_pid}"
        set -e
    fi
    exit "${exit_status}"
}
trap cleanup_child EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Starting canonical runtime paused...\n'
"${python_bin}" -m main &
engine_pid=$!

if ! "${python_bin}" "${healthcheck_script}" \
    --url "${healthcheck_url}" \
    --timeout-seconds "${health_timeout}"; then
    fail "engine did not reach stable PAUSED health"
fi

printf 'Runtime is healthy and PAUSED (pid=%s, health=%s).\n' \
    "${engine_pid}" "${healthcheck_url}"
printf 'Launcher remains attached; supervise this foreground process for durability.\n'

set +e
wait "${engine_pid}"
engine_status=$?
set -e
trap - EXIT INT TERM
exit "${engine_status}"
