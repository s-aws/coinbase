# Configuration Reference

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

Test suite guard (`tests/conftest.py`) sets these to test defaults (`port 9876`) and blocks accidental prod DB use unless `ALLOW_PROD_DB=1`. `database/database.py` also blocks direct test-shaped processes (`pytest`, root-level `test_*.py`) from connecting to localhost production port `5432` unless the same override is set.

Expected local Docker layout:
- `coinbase-stage-postgres`: host `127.0.0.1:5432` -> container `5432`
- `coinbase-dev-postgres`: host `127.0.0.1:9876` -> container `5432`

The host `9876` mapping must point to container port `5432`. Mapping `9876->9876` creates a TCP listener that is not a working Postgres endpoint because the stock Postgres image listens on `5432`.

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

- `ACTION_CONDITION_GUARDS_JSON`
  - optional JSON object for stealth planning, reveal, and replacement
    account-condition guards.
  - direct dashboard `place_order` also evaluates this policy before REST
    placement.
  - overrides top-level `products.json::action_condition_guards` when set.
  - supported keys: `wallet_available`, `known_inventory_available`, and
    `limits`.
  - see [Action Condition Guards](../README.action-condition-guards.md).

- `PRODUCT_CAPABILITIES_JSON`
  - optional JSON object for product capability overrides.
  - overrides top-level `products.json::product_capabilities` when set.
  - supports `product_type` and `product_id` maps.
  - default spot policy enables direct placement, stealth planning, and stealth
    reveal, while disabling spot move/reprice replacement, cancel/re-entry, and
    hotpoint auto-placement by default. If move/reprice is explicitly enabled,
    the replacement action guard credits the active same-currency Coinbase hold
    and checks only the net new wallet requirement before cancel-and-replace.

- `SPOT_FOLLOW_UP_POLICY_JSON`
  - optional JSON object for spot follow-up intent policy.
  - overrides top-level `products.json::spot_follow_up_policy` when set.
  - default spot policy allows `exit` follow-ups and blocks `rebuy` and
    `same_side_replacement` until explicitly enabled.

- `SPOT_INVENTORY_BASELINES_JSON`
  - optional JSON list for imported spot inventory lots.
  - overrides top-level `products.json::spot_inventory_baselines` when set.
  - each entry should include `product_id`, `quantity`, and optional
    `entry_price`, `fees`, `entry_timestamp`, `source_id`, and
    `cost_basis_status`.
  - entries without positive known `entry_price` are treated as unknown cost
    basis and cannot satisfy `known_inventory_available`.

### External test toggles
- `COINBASE_USE_SANDBOX` (expected `true` for external tests)
- `COINBASE_ENABLE_WEBSOCKET_EXTERNAL` (opt-in live websocket smoke)
- `COINBASE_SANDBOX_URL` (external test override)

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
- `action_condition_guards`: optional file-backed default for stealth planning,
  reveal, and replacement action guards. `ACTION_CONDITION_GUARDS_JSON`
  overrides it.
- `product_capabilities`: optional file-backed default for product capability
  overrides. `PRODUCT_CAPABILITIES_JSON` overrides it.
- `spot_follow_up_policy`: optional file-backed default for spot follow-up
  intent policy. `SPOT_FOLLOW_UP_POLICY_JSON` overrides it.
- `spot_inventory_baselines`: optional file-backed imported spot inventory
  lots. `SPOT_INVENTORY_BASELINES_JSON` overrides it.

Loaded by `configuration.py` into:
- `SPOT_PRODUCT_IDS`
- `DERIVATIVES_PRODUCT_IDS`
- `PRODUCT_METADATA`
- `TICKER_TO_TRADING`
- `ACTION_CONDITION_GUARDS`
- `PRODUCT_CAPABILITIES`
- `SPOT_FOLLOW_UP_POLICY`
- `SPOT_INVENTORY_BASELINES`

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
- `cancel_reentry_policy_json`
- `cancel_reentry_state_json`
- `post_fill_retreat_policy_json`

`cancel_reentry_policy_json` is per-order configuration for no-fill revealed placements. It cancels the live exchange placement when the market gets too close to the limit and re-enters only after a wider distance, optional cooldown, and optional max re-entry count. It is not a global bot setting.

`post_fill_retreat_policy_json` is per-order configuration for hidden-order response to fills elsewhere on the same product/side. It uses product `price_increment` ticks, stores cumulative runtime offset in `anchor_repricing_state_json`, and does not mutate live revealed placements.

### Stealth order config (in-memory dict only — NOT persisted)
- `reveal_pricing_policy`
- `follow_up_reveal_direction`

> These two fields live on the in-memory order dict and are passed
> through `StealthOrderManager.create_stealth_order` / follow-up
> creation, but the rolled-back `stealth_orders` schema has no
> column for them. They reset to defaults on process restart.
> If persistence is needed, add an `ALTER TABLE` and update
> `_save_stealth_order_to_db` / `_load_stealth_order_from_db`.

Do not introduce duplicate global settings when a per-order canonical field already exists.

## 6) Product Precision and Size Rules

- Price increment enforcement uses `calculation/formatter.py::quantize_to_increment`.
- Size validation uses `calculation/size_validation.py::validate_and_quantize_size`.
- Product increments/min sizes come from `PRODUCT_METADATA` (from `products.json`).
- Spot ticker/trading mappings must only point to live tradable products. The
  default BTC spot path keeps `BTC-USD` as both ticker and trading product.

## 7) Operational Commands (PowerShell)

```powershell
# Full regression gate for durable milestone closeout or explicit request
pytest tests/regression/ -v

# Full suite (major changes)
pytest tests/ -v --tb=short --cov=.

# Disable reconcilers for local troubleshooting
$env:DISABLE_RECONCILER = "1"
py main.py

# Use fibonacci metrics windows (optional)
$env:MARKET_METRICS_WINDOWS = "fibonacci"
py main.py

# Verify the test database endpoint
python -c "import psycopg2; psycopg2.connect(host='127.0.0.1', port=9876, dbname='postgres', user='postgres', password='postgres').close(); print('ok')"

# Read-only live fee diagnostic: raw filtered summaries + public cache/quotes
.\.venv\Scripts\python.exe genai_tools\check_live_fee_tier.py
```

## 8) Configuration Anti-Patterns

- Do not hard-code product ids or precision in strategy code.
- Do not duplicate enums/constant values as plain strings in new paths.
- Do not add parallel fallback config paths that diverge from `products.json` + canonical constants.

---

Last updated: 2026-08-26
