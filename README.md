# Coinbase Trading Engine

This repository contains a stateful, multithreaded Coinbase Advanced Trade
engine for operator-managed spot and expiring-futures orders. Its primary
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

See [CHANGELOG.md](CHANGELOG.md) for the current `prod` revival history.

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
  and configurable follow-up retreat from the anchor price.

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

The production development environment is Windows 11 with PowerShell. The
commands below assume the repository root is the current directory.

### 1. Prerequisites

- Python 3.13 (the package requires `>=3.13`).
- PostgreSQL reachable from Windows.
- Coinbase Advanced Trade API credentials authorized for the account and
  products you intend to operate.
- An initialized engine database. The runtime applies several additive table
  migrations, but the current checkout does **not** provide a supported,
  non-destructive full-schema bootstrap command for an empty database.
- TCP port `8765` available for the local dashboard WebSocket server.

Do not use `__dangerous_delete_all_tables__.py` as an installation step. It
permanently drops every table in the target database before recreating schema.

### 2. Install the runtime

```powershell
git switch prod
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

The editable install provides the runtime dependencies declared in
`pyproject.toml`, including the Coinbase SDK, PostgreSQL driver, Rich, and the
dashboard WebSocket version used by this branch.

### 3. Configure the process

Set configuration in the same PowerShell session that will launch the engine:

```powershell
$env:COINBASE_API_KEY = "<coinbase-api-key>"
$env:COINBASE_API_SECRET = "<coinbase-api-secret>"

$env:COINBASE_DB_HOST = "127.0.0.1"
$env:COINBASE_DB_PORT = "5432"
$env:COINBASE_DB_NAME = "<initialized-database-name>"
$env:COINBASE_DB_USER = "postgres"
$env:COINBASE_DB_PASSWORD = "<database-password>"

# Optional because PAUSED is already the safe default.
$env:ENGINE_START_PAUSED = "true"
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

```powershell
@'
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
'@ | .\.venv\Scripts\python.exe -
```

### 4. Start the complete engine

```powershell
.\.venv\Scripts\python.exe -m main
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

```powershell
Start-Process .\ui_stealth_orders_manager.html
```

`DISABLE_RECONCILER=1` bypasses both startup and periodic reconciliation. It is
an operational escape hatch, not a normal startup setting; using it removes
the exchange/local drift safety barrier.

### 5. Connect an operator UI

The engine exposes its unauthenticated dashboard protocol on localhost at
`ws://localhost:8765`. Do not expose that port to an untrusted network. Open
one of the local HTML files directly in a browser:

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

```powershell
.\.venv\Scripts\python.exe ui_console.py
```

Use `Ctrl+C` in the engine terminal for the ordinary cooperative drain and
stop. The tracked HTML and console clients do not currently expose the
`admin_shutdown` protocol command.

## Validation

The default repository gate is the complete local non-external suite. It
expects an isolated test PostgreSQL instance at `127.0.0.1:9876` (mapped to
PostgreSQL's container port `5432`) and refuses localhost production port
`5432` for test-shaped processes unless explicitly overridden.

Install the repository's test dependencies, then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests\requirements.txt
.\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

External Coinbase tests are credential-gated and opt-in; they are not part of
the default validation command.

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
and tests remain authoritative when an older design note disagrees.

## Current Operational Boundaries

- A fresh empty database still needs an approved non-destructive schema
  bootstrap workflow.
- `PAUSED` is an origination-admission boundary, not database or exchange
  read-only mode.
- The automatic anchor repricer has a known full-reveal exposure-model
  limitation; ordinary fully revealed resting placements can skip automatic
  cancel/replace. Manual move and reconciliation remain separate paths.
- This checkout has no general cancel/re-entry or "hide a live placement"
  subsystem. Local state must never claim a revealed order is hidden without
  exchange cancellation, fill, replacement, or reconciliation evidence.
- Live exchange validation and external tests require a separately authorized,
  guarded procedure; a passing local suite does not prove live routing.
