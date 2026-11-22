# Coinbase Trading Engine

This repository contains a stateful, multithreaded Coinbase Advanced Trade
engine for operator-managed spot and futures orders, including configured perpetual products. Its primary
workflow is local **stealth orders**: an order remains under local control until
its configured market condition is satisfied, then the engine submits and
tracks the corresponding Coinbase placement.

> [!CAUTION]
> `python -m main` uses the normal Coinbase SDK endpoints and can place or
> cancel live orders after the engine enters `RUNNING`. Startup defaults to
> `PAUSED`, but that pause blocks new originating work only; reconciliation,
> fill handling, cancellations, database writes, and authenticated market or
> account reads can continue.
> `COINBASE_USE_SANDBOX` is an external-test setting and does not turn the main
> runtime into a sandbox.

## Major Features

### Stealth execution

- Local lifecycle states from `HIDDEN` through `PENDING`, `TRIGGERED`,
  `REVEALED`, and terminal outcomes. A stealth order is identified by local
  ownership, not by whether it is temporarily visible on Coinbase.
- Price, spread, and time-based reveal scheduling using ordered ticker evidence
  and monotonic deadlines. Price and spread holds may be zero seconds or require
  a continuous true interval; false, unusable, lost, or temporally disordered
  evidence resets the hold safely.
- Compatibility evaluators for cumulative volume, product ratio, and composite
  conditions.
- Configured-limit, top-of-book, and midpoint reveal pricing. Top-of-book and
  midpoint are post-only; the persisted pricing policy survives restart.
- Fixed, staged tranche/iceberg, and volume-adaptive reveal sizing.
- Audited manual movement of revealed orders, anchor-based repricing policy,
  confirmed same-order Rehide, and configurable new-child price retreat.
- Reveal threshold offsets follow the configured limit independently for each
  composite condition path. Manual threshold edits reset the corresponding
  saved map; hold-duration edits preserve it.

### Order lifecycle and follow-ups

- Parent/child tracking keyed internally by `client_order_id`; Coinbase
  `order_id` values remain exchange-facing evidence.
- Fill-, cancellation-, and partial-fill-driven follow-ups with atomic
  deduplication and replacement-cap claims.
- A strict flat hierarchy: every child links to the original root parent, never
  to another child.
- Per-order target movement, maximum replacement count, partial-fill policy,
  and optional hotpoint replication.

### Exchange correctness and profitability

- One canonical tick-normalization path for exchange-bound limit prices. The
  normalized effective price is the value persisted, tracked, and submitted.
- Product-aware size quantization and minimum-size validation from
  `products.json` metadata.
- Fail-closed placement classification: only explicit Coinbase success with a
  usable exchange order ID is accepted; rejected or indeterminate responses
  become visible errors instead of passive success.
- Separate Coinbase fee schedules for spot and expiring FCM futures, maker fees
  only for `post_only=true`, taker fees otherwise, and round-trip profitability
  checks that include fixed derivatives costs.

### WebSocket processing and runtime safety

- Redundant public ticker/heartbeat sockets with atomic fan-out deduplication.
- Exactly one authenticated private socket for user, futures-balance, and
  private-heartbeat events.
- Connection-global private sequence validation, paginated snapshot bootstrap,
  bounded queues, and keyed FIFO completion per `client_order_id`. Sequence
  corruption, malformed known payloads, overflow, or snapshot timeout fails
  closed and reconnects rather than processing partial truth.
- Runtime states `STARTING`, `RUNNING`, `PAUSING`, `PAUSED`, `DRAINING`, and
  `STOPPED`, with atomic admission/in-flight accounting and bounded graceful
  shutdown.
- Startup hydration and exchange/local reconciliation before decision
  activation, followed by periodic drift and missed-fill audits. Exchange-only
  orders are reported as `unknown_to_local`; they are not reconstructed as
  stealth orders.

### Persistence, audit, and operator surfaces

- PostgreSQL persistence for parent/child state, stealth lifecycle, reveal and
  move history, fill ledger, event stream, partial-fill progress, and market
  telemetry.
- Browser tools for stealth management, order-span creation, repricing,
  calibration, spread monitoring, hotpoint control, and general dashboard
  state, plus a Rich terminal console.
- Optional hotpoint auto-replication with per-order opt-in, rate limiting,
  decay cleanup, and a runtime kill switch.
- Optional fail-soft cross-venue market intelligence for terminal display; it
  does not mutate trading state.

## Getting Started

The development environment is Linux. Commands below use Bash and assume the
repository root is the current directory.

### 1. Prerequisites

- Python 3.13 or newer (the package requires `>=3.13`).
- PostgreSQL server/client tools (`initdb`, `pg_ctl`, `pg_isready`, `psql`).
- Coinbase Advanced Trade API credentials authorized for the account and
  products you intend to operate.
- A PostgreSQL database for the engine. It may be empty; the supported schema
  bootstrap below creates or forward-migrates the required tables.
- The configured dashboard TCP port available (`8765` by default).

Do not use `__dangerous_delete_all_tables__.py` as an installation step. It
permanently drops every table in the target database before recreating schema.

### 2. Install the runtime

```bash
git switch prod
./setup.sh
```

`setup.sh` creates the virtual environment, installs runtime and test
dependencies, and provisions the isolated test PostgreSQL at
`127.0.0.1:9876`, including its complete test schema. The editable install
provides the runtime dependencies declared in `pyproject.toml`, including the
Coinbase SDK, PostgreSQL driver, Rich, and the dashboard WebSocket version used
by this branch.

### 3. Configure the process

Set configuration in the same shell that will launch the engine:

```bash
export COINBASE_API_KEY="<coinbase-api-key>"
export COINBASE_API_SECRET="<coinbase-api-secret>"

export COINBASE_DB_HOST="127.0.0.1"
export COINBASE_DB_PORT="5432"
export COINBASE_DB_NAME="<initialized-database-name>"
export COINBASE_DB_USER="postgres"
export COINBASE_DB_PASSWORD="<database-password>"

# Pin the dashboard to loopback; otherwise HOSTNAME may select another interface.
export DASHBOARD_SERVER_HOST="localhost"
export DASHBOARD_SERVER_PORT="8765"

# Optional because PAUSED is already the safe default.
export ENGINE_START_PAUSED="true"
```

Do not commit credentials. Product scope, ticker mappings, increments, minimum
sizes, and product-level policy are loaded from `products.json`; startup tries
to refresh product metadata from Coinbase and falls back to that validated
local catalog when the remote catalog is unavailable. A successful dashboard
startup refresh rewrites the tracked `products.json` file and may leave the
working tree dirty.

The database defaults are `127.0.0.1:5432/postgres` with user/password
`postgres`/`postgres`, so production setup should always set every database
variable explicitly. Verify the resolved target and server identity read-only
before stateful startup:

```bash
./.venv/bin/python - <<'PY'
from database.database import PostgresDB

db = PostgresDB()
print(f"configured={db.host}:{db.port}/{db.database} user={db.user}")
try:
    print(db.execute_query(
        "SELECT current_database() AS database, "
        "inet_server_addr()::text AS server_address, "
        "inet_server_port() AS server_port"
    )[0])
finally:
    db.disconnect()
PY
```

After verifying the target, bootstrap or forward-migrate the runtime schema.
The command is additive and does not delete rows or tables:

```bash
./.venv/bin/python -m database.schema
```

### 4. Start the complete engine

```bash
./.venv/bin/python -m main
```

Use `main`, not `dashboard_server.py`, for trading. `main` owns the required
ordering: passive database hydration, startup reconciliation, stealth decision
activation, background workers, and readiness publication. Running
`dashboard_server.py` directly starts only its standalone dashboard/demo path.

Expected state progression is:

1. `STARTING` while local state is hydrated, reconciled, and workers start.
2. `PAUSED` after readiness, unless `ENGINE_START_PAUSED=false` was explicitly
   set before launch.
3. `RUNNING` only after an operator resumes the engine.

Wait for `Trading engine startup complete (PAUSED)` before opening the primary
operator page:

```bash
xdg-open ./ui_stealth_orders_manager.html
```

`DISABLE_RECONCILER=1` bypasses both startup and periodic reconciliation. It is
an operational escape hatch, not a normal startup setting; using it removes
the exchange/local drift safety barrier.

### 5. Connect an operator UI

With the configuration above, the engine exposes its unauthenticated dashboard
protocol at `ws://localhost:8765`. The server reads `DASHBOARD_SERVER_HOST`,
falling back to `HOSTNAME`, then `localhost`; `DASHBOARD_SERVER_PORT` defaults
to `8765`. These values are captured when `dashboard_server.py` is imported,
so set them before launch. Do not expose this operator port to an untrusted
network. See [dashboard configuration](genai_data/CONFIGURATION.md#dashboard-websocket-listener-dashboard_serverpy)
for parsing rules and Python overrides.

Clients select their endpoints independently; changing the server environment
does not update browser URLs or console defaults. Most browser pages use the
page hostname (or `localhost` for local files) and fixed port `8765`;
`ui_dashboard.html` always uses `ws://localhost:8765`. The span builder and
investor storyboard instead use the page host/port when served over HTTP(S).
For a custom listener, match the client URL to a reachable server address and
port, or configure a proxy for the page's expected endpoint. A wildcard bind
such as `0.0.0.0` is not a client destination. The server provides plain `ws`,
so pages choosing `wss` under HTTPS need TLS termination in front of it.

Open one of the local HTML files directly in a browser:

- `ui_stealth_orders_manager.html` — create/manage stealth orders and display
  authoritative engine state. Its **Resume Engine** button is enabled only
  while connected and exactly `PAUSED`, and requires confirmation.
- `ui_order_span_builder.html` — create a ladder/span of stealth orders with a
  fixed 200 ms batch-send cadence and a configurable price-hold duration,
  including zero seconds. Open it only after the engine reports `RUNNING`.
- `ui_dashboard.html` — general engine state and order activity.
- `ui_stealth_repricing_chart.html`, `ui_slide_calibration_chart.html`, and
  `ui_spread_monitor.html` — focused market and strategy views.

For a terminal client, run:

```bash
./.venv/bin/python ui_console.py

# Match a custom server address/port (the console defaults remain localhost:8765).
./.venv/bin/python ui_console.py --host <reachable-server-address> --port 9000
```

Use `Ctrl+C` in the engine terminal for the ordinary cooperative drain and
stop. The tracked HTML and console clients do not currently expose the
`admin_shutdown` protocol command.

## Validation

The default repository gate is the complete local non-external suite. It uses
an isolated, user-owned PostgreSQL cluster at `127.0.0.1:9876`, stored under
`.local/test-postgres`, and refuses localhost production port `5432` for
test-shaped processes unless explicitly overridden.

Install the repository's test dependencies, then run:

```bash
./scripts/run_tests.sh
```

Pytest also starts the isolated database on demand. Manage it directly with
`./scripts/test_database.sh start|status|stop`. Runtime `COINBASE_DB_*`
settings are ignored by tests; use `COINBASE_TEST_DB_*` only for an alternate
isolated test endpoint.

External Coinbase tests are credential-gated and opt-in; they are not part of
the default validation command.

For a repeatable Linux resource check of the dashboard cancellation hot path:

```bash
./scripts/run_cancel_stress.sh
```

The default workload publishes 20 batches of 1,000 synthetic cancellations
and fails on retained tasks, threads, file descriptors, publisher work, or
configured CPU/memory limits. It does not contact Coinbase or replace the full
test suite.

For the stronger authenticated-envelope → engine → test-database → dashboard
path:

```bash
./scripts/run_cancel_pipeline_stress.sh
```

This exchange-free test defaults to three batches of 100 cancellations,
requires the isolated port-9876 PostgreSQL instance, verifies that all durable
rows were written, and fails if per-order locks, claims, progress records,
parent entries, queues, tasks, or publishers remain active afterward. It also
enforces the dashboard publication rate and a default 32 KiB transmitted-byte
budget per measured cancellation.

For repeated private-feed generation loss followed by a database-backed
process restart:

```bash
./scripts/run_user_recovery_stress.sh
```

This exchange-free harness rejects stale-generation messages, repeatedly
returns the private feed to `LIVE`, persists active external orders, replaces
the engine process state, rehydrates from PostgreSQL plus a venue snapshot,
and verifies terminal cleanup without retained per-order state.

## Project Map

| Path | Responsibility |
| --- | --- |
| `main.py` | Production startup, readiness, reconciliation, and shutdown ordering |
| `core/order_engine.py` | WebSocket ingestion and parent/child/fill lifecycle |
| `core/stealth_order_manager.py` | Canonical stealth lifecycle and exchange mutation logic |
| `bridges/stealth_order_bridge.py` | Stealth hydration, scheduling, and engine integration |
| `bridges/stealth_event_deadline_scheduler.py` | Ordered market-event FIFO and derived deadline heap |
| `calculation/` | Price, size, fee, and profitability calculations |
| `database/order.py` | Canonical trading schema and persistence helpers |
| `dashboard_server.py` | Operator WebSocket command and state contract |

Deeper architecture, configuration, and message-contract references are
indexed by [ai-context.md](ai-context.md). Current code, schema, configuration,
and tests remain authoritative for current behavior.

## Current Operational Boundaries

- `PAUSED` is an origination-admission boundary, not database or exchange
  read-only mode.
- Automatic revealed repricing and manual **Rehide** use one persisted
  cancellation/rearm path for a single fully accounted zero-fill placement.
  Only exact cancellation confirmation returns it to `HIDDEN`; its existing
  reveal condition then owns the next placement. Multi-live exposure layouts
  and partially filled placements are not eligible for this rearm.
- Project **Cancel** persists an automation stop before requesting exchange
  withdrawal. Pending exposure remains visible and protected from deletion;
  racing fills are accounted without enabling new follow-ups. External
  cancellation retains the configured replacement behavior.
- This checkout has no distance-based cancel/re-entry or same-side hidden-order
  retreat policy, enterprise HTTP Admin API, or Spot sweep/campaign service.
- Live exchange validation and external tests require a separately authorized,
  guarded procedure; a passing local suite does not prove live routing.
