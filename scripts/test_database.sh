#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_db_root="${COINBASE_TEST_DB_ROOT:-${project_root}/.local/test-postgres}"
data_dir="${test_db_root}/data"
log_file="${test_db_root}/postgres.log"

db_host="${COINBASE_TEST_DB_HOST:-127.0.0.1}"
db_port="${COINBASE_TEST_DB_PORT:-9876}"
db_name="${COINBASE_TEST_DB_NAME:-postgres}"
db_user="${COINBASE_TEST_DB_USER:-postgres}"
db_password="${COINBASE_TEST_DB_PASSWORD:-postgres}"
action="${1:-start}"

fail() {
    printf 'test database: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "missing command '$1' (install PostgreSQL server tools)"
}

validate_target() {
    case "${db_host}" in
        127.0.0.1|localhost) ;;
        *) fail "refusing to manage non-loopback host ${db_host}" ;;
    esac
    [[ "${db_port}" =~ ^[0-9]+$ ]] || fail "invalid port ${db_port}"
    [[ "${db_port}" != "5432" ]] || fail "refusing to manage the protected localhost production port 5432"
}

endpoint_is_usable() {
    PGPASSWORD="${db_password}" psql \
        --host "${db_host}" \
        --port "${db_port}" \
        --username "${db_user}" \
        --dbname "${db_name}" \
        --no-password \
        --tuples-only \
        --no-align \
        --command "SELECT 1" 2>/dev/null | grep -qx '1'
}

initialize_cluster() {
    [[ ! -e "${data_dir}/PG_VERSION" ]] || return 0

    mkdir -p "${test_db_root}"
    chmod 700 "${test_db_root}"
    password_file="$(mktemp "${test_db_root}/init-password.XXXXXX")"
    trap 'rm -f "${password_file:-}"' EXIT
    chmod 600 "${password_file}"
    printf '%s\n' "${db_password}" > "${password_file}"

    initdb \
        --pgdata "${data_dir}" \
        --username "${db_user}" \
        --pwfile "${password_file}" \
        --auth-local trust \
        --auth-host scram-sha-256 \
        --encoding UTF8 \
        --locale C >/dev/null

    rm -f "${password_file}"
    trap - EXIT
    printf 'Initialized isolated PostgreSQL cluster at %s\n' "${data_dir}"
}

start_database() {
    require_command initdb
    require_command pg_ctl
    require_command pg_isready
    require_command psql
    validate_target

    if [[ -e "${data_dir}/PG_VERSION" ]] && pg_ctl --pgdata "${data_dir}" status >/dev/null 2>&1; then
        endpoint_is_usable || fail "managed cluster is running but credentials or endpoint verification failed"
        printf 'Test PostgreSQL is already running at %s:%s/%s\n' "${db_host}" "${db_port}" "${db_name}"
        return
    fi

    if pg_isready --host "${db_host}" --port "${db_port}" >/dev/null 2>&1; then
        endpoint_is_usable || fail "port ${db_port} is occupied by an unexpected PostgreSQL instance"
        printf 'Using existing test PostgreSQL at %s:%s/%s\n' "${db_host}" "${db_port}" "${db_name}"
        return
    fi

    initialize_cluster
    mkdir -p "${test_db_root}"
    pg_ctl \
        --pgdata "${data_dir}" \
        --log "${log_file}" \
        --options "-h ${db_host} -p ${db_port} -k ${test_db_root}" \
        --wait \
        start >/dev/null

    endpoint_is_usable || fail "PostgreSQL started but connection verification failed; inspect ${log_file}"
    printf 'Started isolated test PostgreSQL at %s:%s/%s\n' "${db_host}" "${db_port}" "${db_name}"
}

stop_database() {
    validate_target
    [[ -e "${data_dir}/PG_VERSION" ]] || {
        printf 'No managed test PostgreSQL cluster exists.\n'
        return
    }
    if pg_ctl --pgdata "${data_dir}" status >/dev/null 2>&1; then
        pg_ctl --pgdata "${data_dir}" --wait stop >/dev/null
        printf 'Stopped managed test PostgreSQL.\n'
    else
        printf 'Managed test PostgreSQL is already stopped.\n'
    fi
}

status_database() {
    validate_target
    if endpoint_is_usable; then
        printf 'Test PostgreSQL is ready at %s:%s/%s\n' "${db_host}" "${db_port}" "${db_name}"
        return
    fi
    fail "no usable test PostgreSQL at ${db_host}:${db_port}/${db_name}"
}

case "${action}" in
    start) start_database ;;
    stop) stop_database ;;
    status) status_database ;;
    *) fail "usage: $0 {start|stop|status}" ;;
esac
