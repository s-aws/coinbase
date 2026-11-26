#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VENV_DIR:-${project_root}/.venv}/bin/python3.14"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/bootstrap_runtime_database.sh \
    --confirm-target HOST:PORT/DATABASE

Required environment variables:
  COINBASE_DB_HOST
  COINBASE_DB_PORT
  COINBASE_DB_NAME
  COINBASE_DB_USER
  COINBASE_DB_PASSWORD

The confirmation value must exactly match the configured host, port, and
database. The script verifies the connected database identity read-only,
applies the canonical additive schema bootstrap, and verifies every required
runtime table. It does not start the trading engine.
EOF
}

fail() {
    printf 'runtime database bootstrap: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

[[ "$#" -eq 2 && "$1" == "--confirm-target" ]] || {
    usage >&2
    fail "an exact --confirm-target value is required"
}

required_variables=(
    COINBASE_DB_HOST
    COINBASE_DB_PORT
    COINBASE_DB_NAME
    COINBASE_DB_USER
    COINBASE_DB_PASSWORD
)
for variable_name in "${required_variables[@]}"; do
    [[ -n "${!variable_name:-}" ]] || {
        fail "${variable_name} must be set explicitly and cannot be empty"
    }
done

[[ "${COINBASE_DB_PORT}" =~ ^[0-9]+$ ]] || {
    fail "COINBASE_DB_PORT must be an integer"
}
db_port_decimal=$((10#${COINBASE_DB_PORT}))
((db_port_decimal >= 1 && db_port_decimal <= 65535)) || {
    fail "COINBASE_DB_PORT must be between 1 and 65535"
}

[[ -x "${python_bin}" ]] || {
    fail "Python 3.14 environment not found; run ./setup.sh first"
}
"${python_bin}" -c \
    'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))' || {
    fail "${python_bin} must use Python 3.14"
}

configured_target="${COINBASE_DB_HOST}:${COINBASE_DB_PORT}/${COINBASE_DB_NAME}"
confirmed_target="$2"
[[ "${confirmed_target}" == "${configured_target}" ]] || {
    fail "target confirmation mismatch; configured target is ${configured_target}"
}

printf 'Configured runtime database: %s (user=%s)\n' \
    "${configured_target}" "${COINBASE_DB_USER}"
printf 'Verifying connected database identity read-only...\n'

"${python_bin}" - <<'PY'
import os

from database.database import PostgresDB

db = PostgresDB()
try:
    rows = db.execute_query(
        """
        SELECT current_database() AS database,
               current_user AS database_user,
               inet_server_addr()::text AS server_address,
               inet_server_port() AS server_port
        """
    )
    if len(rows) != 1:
        raise RuntimeError("database identity query did not return exactly one row")
    identity = rows[0]
    expected_database = os.environ["COINBASE_DB_NAME"]
    expected_user = os.environ["COINBASE_DB_USER"]
    if identity["database"] != expected_database:
        raise RuntimeError(
            "connected database mismatch: "
            f"expected {expected_database!r}, got {identity['database']!r}"
        )
    if identity["database_user"] != expected_user:
        raise RuntimeError(
            "connected database user mismatch: "
            f"expected {expected_user!r}, got {identity['database_user']!r}"
        )
    server_address = identity["server_address"] or "local-socket"
    print(
        "Connected database identity: "
        f"database={identity['database']} "
        f"user={identity['database_user']} "
        f"server={server_address}:{identity['server_port']}"
    )
finally:
    db.disconnect()
PY

printf 'Applying canonical additive runtime schema...\n'
"${python_bin}" -m database.schema
printf 'Runtime database schema bootstrap complete for %s.\n' \
    "${configured_target}"
