# Configuration Reference

Reconciled with the `prod` checkout on 2026-10-09. Current source and tests
remain the evidence for runtime behavior.

This document describes active configuration sources in the current codebase.

## 1) Environment Variables

### Coinbase credentials
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`

Loaded in `configuration.py` and used to initialize `REST_CLIENT`.

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

### Dashboard WebSocket listener (`dashboard_server.py`)

`main.py` and the standalone dashboard/demo call `start_dashboard_server()`
without arguments. Its defaults are captured at module import:

| Setting | Resolution | Notes |
| --- | --- | --- |
| Host | `DASHBOARD_SERVER_HOST` -> `HOSTNAME` -> `localhost` | Fallback applies only when a variable is absent, not when it is blank. `HOSTNAME` is an environment value, not a system-hostname lookup. |
| Port | `int(DASHBOARD_SERVER_PORT)`; `8765` if absent | Blank or non-integer values raise `ValueError` during import. No explicit port-range validation is performed; binding can reject invalid values. |
| State publish interval | `float(DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS)`; `0.25` if absent | Full latest-state snapshots are emitted at most once per interval during bursts. Values below `0.01` are clamped to `0.01`; invalid values raise `ValueError` during import. Ticker messages use their separate latest-value publisher. |

Set these variables before launching the process; changing them after import
does not update function defaults. Explicit `start_dashboard_server(host=...,
port=...)` arguments override the captured defaults and are forwarded to
`run_websocket_server`. Calling `run_websocket_server()` directly without
arguments still uses its own literal `localhost:8765` defaults. Startup logs
show the supplied host and port; a wildcard bind address is not a usable
browser destination, and port `0` does not report its OS-assigned port.

The listener uses plain `ws` and has no application authentication. A
`HOSTNAME` fallback may select a non-loopback interface; use an explicit
`DASHBOARD_SERVER_HOST=localhost` for local-only operation. A remote bind must
resolve to a local interface, and clients must use a reachable server address.
Keep this operator API off untrusted networks.

Client endpoint selection is independent of server environment variables:

- `ui_console.py`: `--host` and `--port`, defaulting to `localhost` and `8765`.
- `ui_dashboard.html`: fixed `ws://localhost:8765`.
- `ui_stealth_orders_manager.html` and `ui_hotpoint_manager.html`: page hostname
  or `localhost`, fixed port `8765`, plain `ws`.
- Chart, spread, calibration, repricing, and `ui_codex.html` pages: page
  hostname or `localhost`, fixed port `8765`; HTTPS pages select `wss`.
- `ui_order_span_builder.html` and `ui_investor_storyboard.html`: page host/port
  and matching `ws`/`wss` when served, otherwise `ws://localhost:8765`.

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
  - an invalid nonempty value aborts before the dashboard is exposed.

- `DISABLE_RECONCILER`
  - values like `1`, `true`, `yes`, `on` disable both startup and periodic reconciliation in `main.py`.

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
  API-style `type`; `configuration.py` normalizes this into canonical
  `product_type` values for runtime consumers.
Loaded by `configuration.py` into:
- `SPOT_PRODUCT_IDS`
- `DERIVATIVES_PRODUCT_IDS`
- `PRODUCT_METADATA`
- `TICKER_TO_TRADING`

### `pyproject.toml`
Project/package metadata and package inclusion list.

## 3) Runtime Subscription Configuration

Defined in `configuration.py::Subscription`:
- `product_ids = DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS`
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

`follow_up_reveal_direction` remains an in-memory creation option and resets
on hydration; it is not a persisted column. Distance-based cancel/re-entry and
same-side hidden-order retreat policies are absent from this checkout.

Do not introduce duplicate global settings when a per-order canonical field already exists.

## 6) Product Precision and Size Rules

- Exchange-bound price enforcement uses
  `calculation/price_validation.py::normalize_price_for_product`; it uses
  `calculation/formatter.py::quantize_to_increment` internally.
- Size validation uses `calculation/size_validation.py::validate_and_quantize_size`.
- Product increments/min sizes come from `PRODUCT_METADATA` (from `products.json`).
- Spot ticker/trading mappings must only point to live tradable products. The
  default BTC spot path keeps `BTC-USD` as both ticker and trading product.

## 7) Operational Commands (Linux/Bash)

```bash
# Required complete local non-external gate for every non-agent-file change
./scripts/run_tests.sh

# Disable reconcilers for local troubleshooting
export DISABLE_RECONCILER=1
./.venv/bin/python -m main

# Choose the dashboard listener before process startup (loopback, custom port)
export DASHBOARD_SERVER_HOST=localhost
export DASHBOARD_SERVER_PORT=9000
./.venv/bin/python -m main
# In another terminal, point the console at the same endpoint
./.venv/bin/python ui_console.py --host localhost --port 9000

# Use fibonacci metrics windows (optional)
export MARKET_METRICS_WINDOWS=fibonacci
./.venv/bin/python -m main

# Provision and verify the isolated test database endpoint and schema
./scripts/test_database.sh start
COINBASE_DB_HOST=127.0.0.1 COINBASE_DB_PORT=9876 \
COINBASE_DB_NAME=postgres COINBASE_DB_USER=postgres \
COINBASE_DB_PASSWORD=postgres ./.venv/bin/python -m database.schema
./scripts/test_database.sh status

# Read-only live fee diagnostic: raw filtered summaries + public cache/quotes
./.venv/bin/python genai_tools/check_live_fee_tier.py
```

## 8) Configuration Anti-Patterns

- Do not hard-code product ids or precision in strategy code.
- Do not duplicate enums/constant values as plain strings in new paths.
- Do not add parallel fallback config paths that diverge from `products.json` + canonical constants.

---

Last reconciled with checkout: 2026-10-09
Dashboard listener and client endpoint reference updated: 2026-11-04
