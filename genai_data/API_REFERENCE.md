# API Reference

This file covers active API surfaces in the codebase:
- Coinbase REST wrapper (`external/coinbase_client.py`)
- Coinbase WebSocket wrapper (`external/coinbase_websocket.py`)
- Dashboard WebSocket message contract (`dashboard_server.py`)

## 1) Coinbase REST Wrapper (`CoinbaseRestClient`)

### Account and portfolio
- `get_account_wallets()`
- `get_transaction_summary()`
- `get_accounts()`
- `get_portfolio(portfolio_id)`
- `list_portfolios()`

`get_account_wallets()` follows Coinbase `get_accounts` pagination before
building the currency-to-wallet map. Do not replace it with a single
`get_accounts()` call at guard boundaries.

### Product metadata
- `get_product(product_id)`
- `get_products(product_ids)`
- `get_product_dict(product_id)`

### Orders
- `get_open_orders()`
- `place_limit_order(product_id, side, limit_price, base_size|quote_size, client_order_id, post_only, time_in_force)`
- `create_order(...)` (pass-through/flexible order configuration)
- `list_orders(order_status=None)`
- `cancel_order(client_order_id)`
- `cancel_orders(order_ids)`
- `limit_order_gtc(...)`

### Fills and candles
- `list_fills(order_id=None, product_id=None, start_date=None, end_date=None, cursor=None, limit=100)`
- `get_candles(product_id, start, end, granularity="ONE_MINUTE")`

### Futures
- `get_futures_positions()`
- `list_futures_positions()`

### Notes
- `place_limit_order` returns raw SDK response dict (do not coerce to `Order`).
- `list_fills` maps user-facing params to SDK keys (`order_ids`, `product_ids`, `start_sequence_timestamp`, `end_sequence_timestamp`).

## 2) Coinbase WebSocket Wrapper (`CoinbaseWebSocketClient`)

Connection lifecycle:
- `connect()`
- `disconnect()`
- `is_connected()`

Subscription and callbacks:
- `subscribe(products, channels, on_message=None, on_error=None)`
- `unsubscribe(products=None, channels=None)`
- `on_message(callback)`
- `on_error(callback)`
- `on_open(callback)`
- `on_close(callback)`

Utility:
- `sleep_with_exception_check(duration)`
- `get_sdk_client()`

## 3) Dashboard WebSocket Contract (`ws://localhost:8765`)

### Client request message types

Runtime/admin:
- `admin_status`
- `admin_pause`
- `admin_resume`
- `admin_shutdown`

General order actions:
- `place_order`
- `cancel_order`

Parent order views and CRUD:
- `request_parent_orders`
- `create_parent_order`
- `update_parent_order`
- `delete_parent_order`
- `update_parent_target_movement`

`create_parent_order` is local dashboard/database CRUD only. It creates an
`order_parent` row and does not submit a Coinbase order. Live dashboard
submission uses `place_order`.

`place_order` submits a live Coinbase order when REST is available and the
product capability, size validator, and action-condition guard admit the
request. On success, `order_response` includes both the internal
`client_order_id` and Coinbase `order_id` so dashboard submissions can be
correlated with websocket, reconciliation, and fill-ledger evidence. The
handler also writes an `order_submitted` event with source channel
`rest_submit` to `order_event_stream` when the local event stream is available.
The handler normalizes SDK objects, `to_dict()` responses, and nested
`success_response.order_id` payloads before building that audit response.
Base-sized orders are validated through `validate_and_quantize_size`.
Quote-sized market BUYs validate `quote_size` directly against product
`quote_increment` and `quote_min_size`. The direct dashboard handler does not
pre-insert `order_parent` or opt the order into automated follow-up policy
state before submission. It is an immediate manual order surface; websocket
lifecycle and reconciliation own later local evidence rows.

Stealth views/actions:
- `request_stealth_orders`
- `create_stealth_order`
- `cancel_stealth_order`
- `update_stealth_target_movement`
- `update_stealth_price_threshold`
- `reprice_now_stealth_order`
- `move_revealed_stealth_order`
- `clear_all_stealth_orders`
- `export_active_stealth_orders`
- `import_stealth_orders`

Move and product utilities:
- `request_move_history`
- `move_order`
- `premark_move`
- `request_products`
- `update_products_list`
- `request_spot_readiness`
- `request_spot_sweep_status`
- `request_spot_sweep_pnl`
- `request_spot_cost_basis_status`
- `request_spot_campaign_status`

Hotpoint manager:
- `request_hotpoint_state`
- `set_hotpoint_kill_switch`
- `place_hotpoint_test_order`

`place_hotpoint_test_order` is a live Coinbase submission surface used by
`ui_hotpoint_manager.html` to seed the hotpoint detector with a normal limit
order whose `order_parent` row has `enable_hotpoint_replication=TRUE`. It is
not a generic spot bypass. The handler is runtime-admission gated, requires
`ProductCapability.HOTPOINT_AUTO_PLACEMENT`, validates size, runs the
planning-phase `ActionConditionGuard`, pre-inserts the parent row, calls
`REST_CLIENT.limit_order_gtc`, and writes `order_submitted` / `rest_submit`
evidence when the local event stream is available. Spot products are blocked by
default unless the hotpoint capability is explicitly enabled in product
capability policy.

Analytics/storyboard:
- `request_slide_calibration_summary`
- `request_market_chart_history`
- `request_storyboard_products`
- `request_investor_storyboard`

Connectivity:
- `ping`

### Server response message types

Administrative:
- `admin_status_response`
- `admin_pause_response`
- `admin_resume_response`
- `admin_shutdown_response`
- `admission_rejected`

Order/parent responses:
- `order_response`
- `cancel_response`
- `parent_orders_list`
- `parent_order_created`
- `parent_order_updated`
- `parent_order_deleted`
- `parent_target_movement_updated`

Stealth responses:
- `stealth_orders_snapshot`
- `stealth_order_created`
- `stealth_order_cancelled`
- `stealth_order_updated`
- `stealth_order_moved`
- `stealth_threshold_updated`
- `reprice_now_result`
- `export_active_stealth_orders_response`
- `import_stealth_orders_response`
- `stealth_orders_imported`
- `stealth_orders_cleared`

Move/product/analytics responses:
- `move_history_list`
- `order_moved`
- `order_premarked`
- `products_list`
- `products_list_updated`
- `spot_readiness`
- `spot_sweep_status`
- `spot_sweep_pnl`
- `spot_cost_basis_status`
- `spot_campaign_status`
- `hotpoint_state`
- `hotpoint_kill_switch_response`
- `place_hotpoint_test_order_response`
- `slide_calibration_summary`
- `market_chart_history`
- `storyboard_products`
- `spread_snapshot`

Common/global:
- `state_update`
- `update_success`
- `error`
- `pong`
- `ticker`

### Stealth message contract rules

- A dashboard request type is considered active only when it is implemented end to end: browser/terminal caller, `dashboard_server.py` handler, bridge method if the handler routes through `StealthOrderBridge`, manager/domain method, and regression coverage.
- Do not document speculative message types as active. If a design is not implemented, keep it in design notes, not in the request/response tables above.
- Cancel/re-entry is active as a policy carried by `create_stealth_order` and import/export payloads, not as a separate WebSocket request type.
- Cancel/re-entry is not general hide-again behavior. It cancels a live no-fill placement, marks the stealth order hidden with `cancelled_by_policy` state, then re-enters through the normal reveal path when thresholds allow.
- Same-side post-fill retreat is active as a policy carried by `create_stealth_order` and import/export payloads, not as a separate WebSocket request type. It only mutates opted-in hidden orders with no live exchange placement.
- The old UI "Hide" action must not be described as re-hide either.

### `create_stealth_order` high-impact fields

Core fields:
- `product_id`
- `side`
- `total_size`
- `limit_price`
- `reveal_condition`
- `sizing_strategy`
- `target_movement`
- `target_movement_type`

Policy fields:
- `anchor_repricing_policy`
- `cancel_reentry_policy`
- `post_fill_retreat_policy`
- `reveal_pricing_policy`
- `follow_up_reveal_direction`

`cancel_reentry_policy` shape:
- `enabled`
- `reference_price_source`: `last_trade`, `midpoint`, or `top_of_book`
- `distance_type`: `A` absolute or `P` percent
- `cancel_distance`
- `reentry_distance`
- `cooldown_seconds`
- `max_reentry_count`
- `inherit_to_follow_ups`

Validation contract:
- `cancel_distance` must be greater than `0`.
- `reentry_distance` must be greater than `cancel_distance`.
- The policy only cancels revealed orders with no executed size.
- If exchange cancel fails, the order remains `REVEALED` and active placement pointers stay intact.

`post_fill_retreat_policy` shape:
- `enabled`
- `scope`: `same_product_same_side`
- `retreat_ticks`
- `inherit_to_follow_ups`

Runtime contract:
- Triggered by a filled same-product/same-side stealth placement.
- Selects one nearest eligible hidden order that opted in.
- Moves BUY lower and SELL higher by `retreat_ticks * product.price_increment`.
- Updates `limit_price`, absolute reveal-condition price fields, trigger timestamps, and cumulative anchor offset in `anchor_repricing_state_json`.
- Does not cancel/move/reprice any live `REVEALED` exchange placement.

Import/export contract:
- Active-stealth export stores persisted field names such as `cancel_reentry_policy_json`.
- Import maps those names back to request names such as `cancel_reentry_policy` and `post_fill_retreat_policy`.
- `ui_order_span_builder.html` and `ui_stealth_orders_manager.html` both send `cancel_reentry_policy` and `post_fill_retreat_policy` when configured.

### `request_spot_readiness`

Request shape:

```json
{"type": "request_spot_readiness"}
```

Optional product filter:

```json
{
  "type": "request_spot_readiness",
  "params": {"product_ids": ["BTC-USD"]}
}
```

Response shape:

```json
{
  "type": "spot_readiness",
  "status": "success",
  "generated_at": "2026-06-08T00:00:00",
  "products": [
    {
      "product_id": "BTC-USD",
      "product_type": "SPOT",
      "base_currency": "BTC",
      "quote_currency": "USD",
      "capabilities": {
        "direct_placement": {"mode": "enabled", "reason": "allowed by policy"}
      },
      "inventory": {
        "imported_baselines": {
          "configured": true,
          "known_quantity": 0.25,
          "unknown_cost_basis_quantity": 0.1,
          "lots": [
            {
              "source_id": "manual-baseline",
              "cost_basis_status": "known",
              "remaining_quantity": 0.25,
              "entry_price": 90000.0,
              "min_profitable_exit_price": 90450.0
            }
          ]
        }
      }
    }
  ],
  "planned_budget": {"USD": 125.5},
  "wallet_snapshot": {
    "available": true,
    "age_seconds": 0.0,
    "currencies": {"USD": {"available_balance": 1000.0}}
  },
  "action_guards": {
    "wallet_available": {"enabled": true},
    "known_inventory_available": {"enabled": true}
  },
  "action_guard_summary": [
    {
      "condition": "planned_budget_available",
      "label": "planned spot budget",
      "mode": "enabled",
      "phases": ["planning", "reveal"],
      "reason": "spot wallet availability is reduced by local hidden, pending, and triggered spot commitments"
    }
  ]
}
```

Operator contract:
- The dashboard may render `capabilities`, `action_guard_summary`, wallet
  snapshot data, planned budget, and imported baseline inventory directly.
- `inventory.imported_baselines` is an operator summary, not a replacement for
  the lot-authority guard. Concrete spot `SELL` admission still requires a size
  and price and is decided by the shared action-condition guard.
- Structured `error` payloads may include `guard` or `capability` dictionaries
  when a planning boundary rejects an action.

### `request_spot_sweep_status`

Request shape:

```json
{"type": "request_spot_sweep_status"}
```

Optional sweep ledger override:

```json
{
  "type": "request_spot_sweep_status",
  "params": {"state_file": "runtime_state/spot_portfolio_sweeps.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_sweep_status",
  "status": "success",
  "state_file": "runtime_state/spot_portfolio_sweeps.jsonl",
  "operator_status": {
    "config_count": 1,
    "run_count": 1,
    "submitted_order_count": 385,
    "blocked_or_error_count": 0,
    "total_submitted_notional_usdc": "385",
    "total_executed_notional_usdc": "381.4362450472677185",
    "configs": [
      {
        "config_id": "spot-sweep-example",
        "latest_run": {
          "status": "completed",
          "recorded_status": "partial",
          "execution": {
            "submitted_order_count": 385,
            "skipped_order_count": 2
          }
        }
      }
    ]
  }
}
```

Operator contract:
- This request reads the local sweep ledger only. It does not call Coinbase and
  does not submit orders.
- Planned skips, such as below-minimum quote-notional rows, remain visible in
  order details but are not counted as Coinbase submission failures.
- Live sweep placement still requires
  `tools/run_spot_portfolio_sweep_live.py --approved-live-orders`.
- Live sweep order reports include UUID `client_order_id` values and
  `submission_event_recorded`. When the local event stream is available,
  accepted placements publish `order_submitted` / `rest_submit` evidence to
  `order_event_stream`; the JSONL sweep ledger remains the run-level audit
  record.

### `request_spot_sweep_pnl`

Request shape:

```json
{"type": "request_spot_sweep_pnl"}
```

Optional filters:

```json
{
  "type": "request_spot_sweep_pnl",
  "params": {
    "product_ids": ["BTC-USDC"],
    "include_coinbase_average_cost": false
  }
}
```

Response shape:

```json
{
  "type": "spot_sweep_pnl",
  "status": "success",
  "read_only_coinbase_requests": ["get_public_products"],
  "pnl_report": {
    "product_count": 1,
    "portfolio": {"total_unrealized_pnl_usdc": "0"},
    "since_last_purchase": {"total_unrealized_pnl_usdc": "0"}
  }
}
```

Operator contract:
- This request reads public product marks and local fill-ledger evidence. If
  `include_coinbase_average_cost` is true, it may also read Coinbase portfolio
  average-cost data.
- The response is operational P/L, not tax accounting.
- It never submits Coinbase orders.

### `request_spot_cost_basis_status`

Request shape:

```json
{"type": "request_spot_cost_basis_status"}
```

Optional snapshot ledger override:

```json
{
  "type": "request_spot_cost_basis_status",
  "params": {"state_file": "runtime_state/spot_cost_basis_snapshots.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_cost_basis_status",
  "status": "success",
  "state_file": "runtime_state/spot_cost_basis_snapshots.jsonl",
  "operator_status": {
    "snapshot_count": 1,
    "latest_snapshot": {
      "record_type": "spot_cost_basis_snapshot",
      "status": "available",
      "baseline": {"record_count": 376, "baseline_count": 376},
      "inventory_coverage": {"wallet_only_product_count": 8},
      "drift_audit": {"status_counts": {"stale": 1}},
      "gap_triage": {"product_count": 381}
    }
  }
}
```

Operator contract:
- This request reads the local cost-basis snapshot ledger only. It does not
  call Coinbase and does not submit orders.
- Generate or refresh snapshots with
  `tools/run_spot_portfolio_sweep_live.py --cost-basis-triage --record-cost-basis-snapshot`.

### `request_spot_campaign_status`

Request shape:

```json
{"type": "request_spot_campaign_status"}
```

Optional campaign ledger override:

```json
{
  "type": "request_spot_campaign_status",
  "params": {"state_file": "runtime_state/spot_campaigns.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_campaign_status",
  "status": "success",
  "state_file": "runtime_state/spot_campaigns.jsonl",
  "operator_status": {
    "campaign_count": 1,
    "snapshot_count": 2,
    "total_submitted_notional_usdc": "0",
    "total_executed_notional_usdc": "0",
    "operator_summary": {
      "readiness_status": "ready",
      "ready": true,
      "blocked": false,
      "gate_status": "passed",
      "automation_decision": "due",
      "next_run_at": "2026-01-01T06:00:00+00:00",
      "operation_lock_status": "released",
      "operation_lock_exists": false,
      "operation_lock_stale": false,
      "recovery_status": "passed",
      "planned_reconciliation_run_count": 0,
      "planned_backfill_order_count": 0,
      "planned_order_count": 10,
      "planned_skip_count": 0,
      "safety_decision": "allowed",
      "latest_live_run_id": "spot-sweep-example",
      "total_submitted_notional_usdc": "10",
      "total_executed_notional_usdc": "9.95",
      "portfolio_total_pnl": "0.12"
    },
    "latest_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "campaign_id": "spot-campaign-example",
      "mode": "release_gate",
      "status": "ready",
      "dry_run": {
        "plan": {"planned_count": 10, "skipped_count": 0},
        "safety_evaluation": {"decision": "allowed"}
      },
      "release_gate": {
        "gate_status": "passed",
        "failures": [],
        "warnings": []
      }
    },
    "latest_readiness_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "mode": "release_gate",
      "status": "ready"
    },
    "latest_live_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "mode": "live_canary",
      "sweep_summary": {"run_id": "spot-sweep-example"}
    }
  }
}
```

Operator contract:
- This request reads the local campaign snapshot ledger only. It does not call
  Coinbase and does not submit orders.
- `latest_snapshot` is the newest campaign ledger record. It can be a live
  canary record with no dry-run/release-gate details.
- `latest_readiness_snapshot` is the newest dry-run or release-gate record with
  readiness data. `latest_live_snapshot` is the newest live-canary record.
- `operator_summary` is the dashboard-ready read-only summary for readiness,
  due state, lock state, recovery state, planned skips, notional, and P/L.
- Generate or refresh snapshots with
  `tools/run_spot_campaign.py --config-file <path> --dry-run-matrix --record-snapshot`
  or `tools/run_spot_campaign.py --config-file <path> --release-gate --record-snapshot`.
- Live campaign canaries use a rendered sweep config and
  `tools/run_spot_portfolio_sweep_live.py --approved-live-orders`.

## 4) Internal Runtime Control API

`core/runtime_controller.py` exposes:
- `get_runtime_controller()` singleton accessor
- `check_admission(category)` gate
- `track_inflight(category)` context manager
- `request_pause()`, `resume()`, `request_shutdown()`
- `drain_and_stop(timeout_seconds)`
- `register_stop_hook(name, hook)`

Inflight categories used by callers include:
- `INFLIGHT_REST_PLACE`
- `INFLIGHT_REST_CANCEL`
- `INFLIGHT_FILL_PROCESSING`
- `INFLIGHT_STEALTH_REVEAL`
- `INFLIGHT_DB_WRITE`

## 5) Error-Handling Guidance

- Use domain-specific exceptions from `core/exceptions.py`.
- WebSocket handlers should return structured `error` payloads, not raw tracebacks.
- Reconciliation and analytics helpers are fail-soft by design; log and degrade rather than crash engine loops.

---

Last updated: 2026-06-09
