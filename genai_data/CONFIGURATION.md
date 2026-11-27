# Configuration Reference

Reconciled with the `prod` checkout on 2026-11-26. Current source and tests
remain the evidence for runtime behavior.

This document describes active configuration sources in the current codebase.

## 1) Environment Variables

### Coinbase credentials
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`

Read by `configuration.load_runtime_settings()` when `main()` starts. The
composition root passes them to `external.runtime.build_rest_client()`; importing
configuration does not read credentials or construct a client.

### Database connection (`database/database.py`)
- `COINBASE_DB_HOST` (default `127.0.0.1`)
- `COINBASE_DB_PORT` (default `5432`)
- `COINBASE_DB_NAME` (default `postgres`)
- `COINBASE_DB_USER` (default `postgres`)
- `COINBASE_DB_PASSWORD` (default `postgres`)

The test suite ignores runtime `COINBASE_DB_*` values and maps the dedicated
`COINBASE_TEST_DB_HOST`, `COINBASE_TEST_DB_PORT`, `COINBASE_TEST_DB_NAME`,
`COINBASE_TEST_DB_USER`, and `COINBASE_TEST_DB_PASSWORD` values into the
process instead. Defaults are `127.0.0.1:9876/postgres` and
`postgres`/`postgres`. `tests/conftest.py` starts the user-owned Linux cluster
through `scripts/test_database.sh` unless `COINBASE_TEST_DB_AUTOSTART=0`, then
runs the non-destructive `database.schema` bootstrap before test collection.
Both test guards block accidental localhost production-port use unless
`ALLOW_PROD_DB=1`.

#### Runtime schema deployment contract

Set every runtime `COINBASE_DB_*` variable explicitly. The guarded database
entry point derives its target only from those variables, verifies connected
database/user identity and fresh trading state read-only, then applies the
canonical schema:

```bash
./scripts/bootstrap_runtime_database.sh
```

`scripts/bootstrap_runtime_database.sh` requires all five runtime database
variables and accepts no duplicate target-confirmation argument. Required
runtime tables may be absent or already provisioned for a retry, but every
existing required table must be empty. Only `market_candle_1m` and
`market_tick` may coexist as additional public tables; their telemetry data is
allowed. Unknown tables or trading rows fail closed. `database/schema.py` owns
the ordered, idempotent implementation and fresh-state verifier shared by
deployment, test provisioning, and reset recreation. Direct `python -m main`
startup deliberately performs no full schema bootstrap.

The complete safe deployment path is:

```bash
./scripts/deploy_runtime.sh
```

It first runs `scripts/validate_release.sh`, invokes the guarded database
bootstrap, forces `ENGINE_START_PAUSED=true`, starts the canonical `python -m
main` entry point, and waits for live `admin_status` proof of stable `PAUSED`
health with admission closed and zero in-flight work. It rejects a true
`DISABLE_RECONCILER`, an already responding engine, and overlapping deployment
launchers. The script remains in the foreground; a service/container
supervisor must own it for durable operation.

`__dangerous_delete_all_tables__.py` is not an alternate migration command. It
irreversibly drops the target's public tables before invoking the canonical
bootstrap and must be run only as an explicitly intended manual reset. The
`market_tick` and `market_candle_1m` analytics tables remain owned by their
lazy telemetry paths. After required schema recreation, direct reset-script
execution preserves the existing best-effort Coinbase candle backfill;
per-product failures are logged and may leave optional history incomplete.

### Dashboard WebSocket listener (`dashboard_server.py`)

The supported `python -m main` path resolves listener settings while loading
`RuntimeSettings`, then passes them explicitly to the embedded dashboard
transport. `dashboard_server.py` does not read the environment or construct a
standalone runtime. `main.py` also installs the one composed `ExecutionCore`;
originating handlers fail closed if that dependency is absent:

| Setting | Resolution | Notes |
| --- | --- | --- |
| Host | `DASHBOARD_SERVER_HOST` -> `HOSTNAME` -> `localhost` | Fallback applies only when a variable is absent, not when it is blank. `HOSTNAME` is an environment value, not a system-hostname lookup. |
| Port | `int(DASHBOARD_SERVER_PORT)`; `8765` if absent | Blank or non-integer values raise `ValueError` while `main()` loads settings. No explicit port-range validation is performed; binding can reject invalid values. |
| State publish interval | `float(DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS)`; `0.25` if absent | Full latest-state snapshots are emitted at most once per interval during bursts. Values below `0.01` are clamped to `0.01`; invalid values raise `ValueError` while loading settings. Ticker messages use their separate latest-value publisher. |

Set these variables before launching the process. A `RuntimeSettings` snapshot
does not change after loading. `main()` forwards its host and port to
`start_dashboard_server()`, which forwards them to `run_websocket_server`.
Calling `run_websocket_server()` directly without arguments still uses its own
literal `localhost:8765` defaults, but this is not a supported trading-process
entrypoint. Startup logs show the supplied host and port; a wildcard bind
address is not a usable browser destination, and port `0` does not report its
OS-assigned port.

The listener uses plain `ws` and has no application authentication. A
`HOSTNAME` fallback may select a non-loopback interface; use an explicit
`DASHBOARD_SERVER_HOST=localhost` for local-only operation. A remote bind must
resolve to a local interface, and clients must use a reachable server address.
Keep this operator API off untrusted networks.

Client endpoint selection is independent of server environment variables:

- `ui_stealth_orders_manager.html`: page hostname or `localhost`, fixed port
  `8765`, plain `ws`.
- `ui_order_span_builder.html`: page host/port and matching `ws`/`wss` when
  served, otherwise `ws://localhost:8765`.

Custom server bindings require matching client URLs or proxy routing. There
is no shared browser endpoint setting or server-provided HTML hosting. HTTPS
pages selecting `wss` require TLS termination outside this plain listener.

### Runtime toggles
- `ENGINE_START_PAUSED`
  - defaults to paused when unset or blank.
  - strict boolean values are `1`, `true`, `yes`, `on`, `0`, `false`, `no`,
    or `off` (case-insensitive).
  - a true value latches the same startup pause used by `admin_pause`; the
    process still completes hydration, reconciliation, scheduler activation,
    and worker startup, then publishes `PAUSED` instead of `RUNNING`.
  - set an explicit false value to opt into entering `RUNNING` automatically
    after startup readiness completes.
  - `scripts/deploy_runtime.sh` rejects an explicit false value; supported
    deployment always reaches stable `PAUSED` before operator review.
  - an invalid nonempty value aborts before the dashboard is exposed.

- `DISABLE_RECONCILER`
  - values like `1`, `true`, `yes`, `on` disable both startup and periodic reconciliation in `main.py`.
  - `scripts/deploy_runtime.sh` rejects this bypass; deployment reconciliation
    cannot be disabled.

- `DEPLOYMENT_HEALTHCHECK_URL`
  - dashboard WebSocket URL used only by deployment automation.
  - defaults to `ws://127.0.0.1:${DASHBOARD_SERVER_PORT:-8765}`.

- `DEPLOYMENT_HEALTH_TIMEOUT_SECONDS`
  - finite positive time allowed for startup to reach stable `PAUSED` health.
  - defaults to `60`.

- `MARKET_METRICS_WINDOWS`
  - controls metrics window preset in `business/market_metrics.py`.
  - supported: `standard` (default), `fibonacci`.

### External test toggles
- `COINBASE_USE_SANDBOX` (external-test opt-in assertion; does not change
  production runtime routing or configure the test SDK base URL)
- `COINBASE_ENABLE_WEBSOCKET_EXTERNAL` (opt-in live websocket smoke)
- `COINBASE_SANDBOX_URL` (recorded in external fixtures but not passed to the
  current RESTClient constructor; it is not proof of sandbox routing)

## 2) File-Based Configuration

### `products.json`
Primary product catalog and metadata source.

Contains:
- `spot`: spot product ids
- `derivatives`: derivatives product ids
- `ticker_to_trading`: ticker product id to trading product id mapping
- `metadata`: per-product increments/min sizes/type data. Metadata may carry
  API-style `type`; `ProductConfiguration.local_products()` normalizes this
  into canonical `product_type` values for cached-startup consumers.

`load_product_configuration()` copies these fields into one immutable
`ProductConfiguration`. `main.py` prefers a validated live catalog, falls back
to `ProductConfiguration.local_products()`, and installs one complete snapshot
in the shared `core.orderbook.OrderBook`. Validators and strategy consumers
receive its `get_product_metadata()` reader. A successful manual dashboard
refresh atomically persists `products.json` before replacing the live snapshot;
a cache-write failure leaves the runtime catalog unchanged.

### `pyproject.toml`
Project/package metadata and package inclusion list.

## 3) Runtime Subscription Configuration

Defined in `configuration.py::Subscription` and built from the immutable
`ProductConfiguration`:
- `product_ids = derivatives_product_ids + spot_product_ids`
- `public_channels = [heartbeats, ticker]`
- `private_channels = [heartbeats, user, futures_balance_summary]`
- `channels`: deduplicated union derived from the two role lists for local
  queue/worker ownership

The role lists are authoritative for production transport ownership:
`websocket_thread_maximum` applies only to public connections, while all
private channels share exactly one `WSUserClient` and one ordered reducer
queue. Legacy/custom subscription objects exposing only `channels` are
partitioned by `OrderEngine` for backward compatibility.

## 4) Core Constants and Defaults

### `core/constants.py`
Key values:
- `DEFAULT_MAX_ORDER_REPLACEMENT = 1`
- order side/position mappings (`ORDER_SIDE_SWITCH`, `ORDER_POSITION_SIDE`, `ORDER_DIRECTION`)
- derivatives fee constants and helper:
  - `get_derivatives_per_side_fee(product_id)`
  - BIP/default all-in fixed cost: `$0.12` per contract side (`$0.10`
    venue + `$0.01` clearing + one `$0.01` regulatory/NFA charge)
  - full-size BTI/ETI/SLC/XRL: unchanged legacy `$0.27` per contract side,
    explicitly isolated from the BIP/default component calculation

The fixed fee is runtime calculation configuration, not persisted fee truth.
Changing it requires a process restart to rebuild OrderBook price offsets; it
does not require or authorize a database correction/backfill. Historical fill
fees remain the exchange-reported values already stored by the fill pipeline.

### `calculation/fee_manager.py`
Adaptive fee telemetry defaults:
- conservative default maker/taker rates before first refresh
- product-type multipliers
- volume and margin regime factor clamps
- hourly refresh cadence
- separate immutable caches for filtered `SPOT/CBE` and
  `FUTURE/EXPIRING/FCM` transaction summaries
- partial refresh isolation: a failed product-type request retains only that
  cache's last-known-good/default snapshot
- public inspection through `get_fee_schedule_snapshot(product_id)`,
  `get_profit_validation_fee_quote(product_id, post_only, product_type=None)`, and
  `get_fee_info(product_id)`

The live source endpoint is
`GET /api/v3/brokerage/transaction_summary`. Futures snapshots require
`has_cost_plus_commission=true`. Maker pricing is selected only for
`post_only=True`; all other orders are modeled as taker. Fee quotes report the
selected source, pricing tier, cost-plus flag, and exchange/validation rates
from one atomic snapshot. A valid explicit product-type hint takes precedence
when a profitability check has no canonical exchange product id.

### `business/market_metrics.py`
Window presets:
- `STANDARD_WINDOWS_MINUTES`
- `FIBONACCI_WINDOWS_MINUTES`

## 5) Per-Order Configuration Payloads

Many important behaviors are configured per order, not globally.

### Parent order config (`order_parent` row)
- `target_movement`
- `target_movement_type`
- `max_order_replacement`
- `allow_partial_fills`

### Stealth order config (`stealth_orders` row)
- `reveal_condition_json`
- `sizing_strategy_json`
- `anchor_repricing_policy_json`
- `anchor_repricing_state_json` (placement/rearm/intent state; not operator policy)
- `reveal_pricing_policy` (persisted column, default `configured_limit`)
- `follow_up_reveal_direction` (persisted column, default `opposite`)

Distance-based cancel/re-entry and same-side hidden-order retreat policies are
absent from this checkout.

Do not introduce duplicate global settings when a per-order canonical field already exists.

## 6) Product Precision and Size Rules

- Exchange-bound price enforcement uses
  `calculation/price_validation.py::normalize_price_for_product`; it uses
  `calculation/formatter.py::quantize_to_increment` internally.
- Size validation uses `calculation/size_validation.py::validate_and_quantize_size`.
- Product increments/min sizes come from the shared `OrderBook` catalog: live
  Coinbase metadata when startup/refresh succeeds, otherwise the cached
  `products.json` snapshot.
- Spot ticker/trading mappings must only point to live tradable products. The
  default BTC spot path keeps `BTC-USD` as both ticker and trading product.

## 7) Operational Commands (Linux/Bash)

```bash
# Required complete local non-external gate for every non-agent-file change
./scripts/run_tests.sh

# Automated clean-worktree release gate
./scripts/validate_release.sh

# Database-only preparation after setting all COINBASE_DB_* values
./scripts/bootstrap_runtime_database.sh

# Complete foreground deployment after setting DB/API variables
./scripts/deploy_runtime.sh

# Disable reconcilers for local troubleshooting
export DISABLE_RECONCILER=1
./.venv/bin/python3.14 -m main

# Choose the dashboard listener before process startup (loopback, custom port)
export DASHBOARD_SERVER_HOST=localhost
export DASHBOARD_SERVER_PORT=9000
./.venv/bin/python3.14 -m main
# Serve/proxy the retained browser page so its endpoint rule reaches this port.

# Use fibonacci metrics windows (optional)
export MARKET_METRICS_WINDOWS=fibonacci
./.venv/bin/python3.14 -m main

# Provision and verify the isolated test database endpoint and schema
./scripts/test_database.sh start
COINBASE_DB_HOST=127.0.0.1 COINBASE_DB_PORT=9876 \
COINBASE_DB_NAME=postgres COINBASE_DB_USER=postgres \
COINBASE_DB_PASSWORD=postgres ./.venv/bin/python3.14 -m database.schema
./scripts/test_database.sh status

# Read-only live fee diagnostic: raw filtered summaries + public cache/quotes
./.venv/bin/python3.14 genai_tools/check_live_fee_tier.py
```

## 8) Configuration Anti-Patterns

- Do not hard-code product ids or precision in strategy code.
- Do not duplicate enums/constant values as plain strings in new paths.
- Do not add parallel fallback config paths that diverge from `products.json` + canonical constants.

---

Last reconciled with checkout: 2026-11-26
Dashboard listener and client endpoint reference updated: 2026-11-04
