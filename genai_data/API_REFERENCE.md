# API Reference

Reconciled with the `prod` checkout on 2026-10-09. Current surfaces are the
Coinbase wrappers and the local dashboard WebSocket server. This checkout has
no enterprise HTTP Admin API, Spot sweep/campaign CLI, account-condition guard,
cancel/re-entry distance policy, or same-side hidden-order retreat subsystem.
Earlier mixed-branch contracts are retained in
[the historical reference](history/api_reference_mixed_branches.md).

## 1) Coinbase REST Wrapper (`CoinbaseRestClient`)

### Account and portfolio
- `get_account_wallets()`
- `get_transaction_summary(product_type=None, contract_expiry_type=None, product_venue=None)`
- `get_accounts()`
- `get_portfolio(portfolio_id)`
- `list_portfolios()`

#### Transaction-summary fee schedules

`CoinbaseRestClient.get_transaction_summary(...)` wraps the authenticated
Advanced Trade endpoint:

```text
GET /api/v3/brokerage/transaction_summary
```

The wrapper accepts canonical enums and forwards their values using the SDK's
exact query names:

- `product_type`: `SPOT` or `FUTURE`
- `contract_expiry_type`: `EXPIRING` or `PERPETUAL`; applicable to futures
- `product_venue`: project enum currently exposes `CBE` and `FCM` (the
  Coinbase endpoint also documents `INTX`)

With no filters, the wrapper preserves the SDK's unfiltered call. Production
fee refreshes do not use that ambiguous aggregate. `FeeManager` makes two
independent filtered requests:

```text
SPOT   + CBE
FUTURE + EXPIRING + FCM
```

The response is a transaction-summary object, not the historical
`GET /api/v1/fees` shape. Relevant fields are:

- `total_fees`
- `fee_tier.pricing_tier`
- `fee_tier.maker_fee_rate`
- `fee_tier.taker_fee_rate`
- `fee_tier.aop_from` / `fee_tier.aop_to`
- `fee_tier.volume_types_and_range[]`
- `margin_rate` for futures responses
- `advanced_trade_only_volume` / `advanced_trade_only_fees`
- `coinbase_pro_volume` / `coinbase_pro_fees`
- `total_balance`
- `volume_breakdown[]`
- `has_cost_plus_commission`
- optional `has_promo_fee` when supplied by the SDK/API response

`FeeManager` caches one immutable snapshot per canonical product type, not one
snapshot per product id. A product id selects either the shared SPOT/CBE cache
or the shared FUTURE/EXPIRING/FCM cache. A valid explicit `product_type` hint
wins when a profitability caller has no canonical exchange product id; missing
or unknown ids without a valid hint resolve to the conservative SPOT cache.
Each filtered refresh is atomic: one request may succeed while the other
retains its own last-known-good/default snapshot. A futures response is rejected
unless `has_cost_plus_commission` is explicitly `true`.

Public inspection surfaces are
`get_fee_schedule_snapshot(product_id)`,
`get_profit_validation_fee_quote(product_id, post_only, product_type=None)`, and
`get_fee_info(product_id)`. A quote uses the maker rate only when
`post_only=True`; every other order uses the taker rate. Quote telemetry carries
the selected source, pricing tier, cost-plus flag, liquidity assumption,
exchange rate, and validation rate from the same immutable sample.

These percentage schedules are separate from the CDE fixed per-contract cost.
The settlement-confirmed BIP/default fixed cost is `$0.12` per contract side;
the legacy full-size BTI/ETI/SLC/XRL value remains `$0.27` per contract side
pending independent reconciliation. This configuration change requires no
database correction or backfill. Use
`genai_tools/check_live_fee_tier.py` for a read-only live diagnostic of both
filtered responses and the corresponding public FeeManager snapshots/quotes.

`get_account_wallets()` reads one SDK accounts page and filters deleted
accounts. It does not exhaust pagination in this checkout; do not treat its
wallet map as proof of complete account inventory.

### Product metadata
- `get_product(product_id)`
- `get_products(product_ids)`
- `get_product_dict(product_id)`

### Orders
- `get_open_orders()`
- `place_limit_order(product_id, side, limit_price, base_size|quote_size, client_order_id, post_only, time_in_force)`
- `create_order(...)` (pass-through/flexible order configuration)
- `list_orders(order_status=None, cursor=None)`
- `get_order(order_id)`
- `cancel_order(client_order_id)`
- `cancel_orders(order_ids)`
- `limit_order_gtc(...)`

### Fills and candles
- `list_fills(*, order_id=None, product_id=None, start_date=None, end_date=None, cursor=None, limit=100)`
- `get_candles(product_id, start, end, granularity="ONE_MINUTE")`

### Futures
- `get_futures_positions()`
- `list_futures_positions()`

### Notes
- `place_limit_order` delegates to GTC regardless of its legacy
  `time_in_force` argument, and returns the SDK response dictionary. Placement
  callers must classify acceptance with `classify_placement_response`.
- `list_fills` maps user-facing params to SDK keys (`order_ids`, `product_ids`, `start_sequence_timestamp`, `end_sequence_timestamp`).
- `list_orders` exposes the SDK continuation `cursor`; callers
  that require a complete exchange snapshot must walk every page and honor the
  response's `has_next`/`cursor` contract.
- `get_order(order_id)` performs an exact lookup by Coinbase's
  exchange-assigned `order_id`; internal correlation continues to use
  `client_order_id`.
- The legacy `cancel_order(client_order_id)` wrapper checks only whether the
  returned collection is nonempty. That boolean does not validate per-order
  success or prove exchange closure. Managed stealth cancellation uses the
  persisted intent and exact confirmation path described below.

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

The wrapper accepts either Coinbase SDK `WSClient` or `WSUserClient`. Runtime
ownership is split in `OrderEngine`: redundant `WSClient` instances subscribe
only to public channels; exactly one `WSUserClient` subscribes to user order
data, futures balance summary, and its heartbeat. Authenticated messages retain
their entire envelope, share one connection-generation sequence watermark, and
traverse one ordered reducer queue; they do not use the public payload-hash
dedup path. Public ingress accepts only the configured public role channels.

Authenticated user order wire kinds are `snapshot`, `update`, and compatibility
`patch`; each row's `status` remains its independent lifecycle status. Initial
open orders are accumulated in pages of 50 until the first shorter page, then
drift-checked/hydrated without DB or order-lifecycle side effects. Only later
complete live rows enter bounded, keyed canonical `process_user_order`
dispatch; failed admission desynchronizes and reconnects.

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

`place_order` currently generates a `client_order_id`, normalizes a supplied
limit price through `normalize_price_for_product`, quantizes a supplied base
size through `validate_and_quantize_size`, and then calls
`REST_CLIENT.create_order`. It does not pre-insert an `order_parent` row. A
successful response returns the Coinbase `order_id`; error responses include
the generated `client_order_id` when available. Market and quote-sized shapes
are not categorically rejected by this handler, although only supplied base
size and limit-price fields pass through those two validators.

`cancel_order` resolves a managed logical or placement `client_order_id` to its
stealth identity and uses the same bridge cancellation path as
`cancel_stealth_order`. Its `cancel_response` includes `accepted`,
`exchange_cancel_pending`, and the authoritative `order` for managed requests;
success acknowledges a persisted automation stop, not exchange confirmation.
Unmapped orders retain the legacy direct REST compatibility path, which passes
the supplied client ID in `order_ids=[...]` to `REST_CLIENT.cancel_orders`.

Stealth views/actions:
- `request_stealth_orders`
- `create_stealth_order`
- `cancel_stealth_order`
- `rehide_stealth_order`
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

Hotpoint manager:
- `request_hotpoint_state`
- `set_hotpoint_kill_switch`
- `place_hotpoint_test_order`

`place_hotpoint_test_order` submits a live GTC limit order with
`enable_hotpoint_replication=True`. Send `order` containing `product_id`,
`side`, `price`, and `size`. The handler validates positive price/size and side,
normalizes the price, pre-inserts a PENDING parent with zero normal replacement
budget, and calls `REST_CLIENT.limit_order_gtc(post_only=False)`. Acceptance is
classified explicitly. It has no Admin API command-service, capability-policy,
or account-condition guard in this checkout. Its initial dashboard admission
check is separate from its REST call; it does not use atomic admitted-inflight
registration. This is an operator live-test surface, not an isolated test.

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

During process startup, originating dashboard requests receive
`admission_rejected` with `engine_state="STARTING"`. `admin_status_response`,
`admin_pause_response`, and `admin_resume_response` expose
`startup_pause_pending`. A startup pause leaves state `STARTING` until runtime
readiness; resume cannot open admission during that interval.

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
- `stealth_order_rehide_result`
- `stealth_order_updated`
- `stealth_order_cancel_result`
- `stealth_order_moved`
- `stealth_threshold_updated`
- `reprice_now_result`
- `export_active_stealth_orders_response`
- `import_stealth_orders_response`
- `stealth_orders_imported`
- `stealth_orders_cleared`
- `stealth_orders_clear_result`

Move/product/analytics responses:
- `move_history_list`
- `order_moved`
- `order_premarked`
- `products_list`
- `products_list_updated`
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
- The stealth-manager table displays a parent group when the parent or any child is `HIDDEN`, `PENDING`, `TRIGGERED`, `REVEALED`, or awaiting exchange confirmation of an operator cancellation. Terminal parents remain visible as containers for active children; all children in a displayed group remain available through the existing expansion control. A settled terminal-only group is omitted.
- `request_stealth_orders` and `stealth_orders_snapshot` already include revealed orders; the visibility rule is browser-side and does not change the WebSocket payload or backend lifecycle.
- The UI `Rehide` action sends `rehide_stealth_order` for the existing stealth identity; it never creates a duplicate. It disables conflicting row actions while exchange withdrawal is pending and disables Rehide for known executed quantity. Terminal Cancel remains available to supersede a pending rehide.

### Operator cancellation and guarded deletion

`cancel_stealth_order` returns `stealth_order_cancel_result` with
`stealth_order_id`, `accepted`, `exchange_cancel_pending`, authoritative `order`,
and `message` (plus `error` on failure). Local automation stops durably before
exchange cancellation is requested. An accepted request may still await exchange
confirmation; even a failed request can expose a retained, stopped order needing
reconciliation. The browser never infers exchange cancellation from acceptance.
Cancellation is available while paused/draining and for REVEALED orders.

Clear All first requests canonical cancellations. If any cancellation fails or
remains unresolved, `stealth_orders_clear_result` reports `cleared=false` and
retains all memory, database rows, and recovery history. The operator can retry
after confirmation; there is no deferred-delete job. Database deletion is
transactionally guarded against active status, pending intent, live placement
identifiers, and unaccounted revealed exposure. Parent deletion similarly refuses
to remove a logical root or placement row needed by unresolved stealth activity.
Import remains creation-only and rejects an existing identity rather than
overwriting pending cancellation evidence.

### `rehide_stealth_order`

Request: `{"type": "rehide_stealth_order", "stealth_order_id": "<existing stealth id>"}`.

This is a manual `REVEALED` to `HIDDEN` operation on the same zero-fill stealth
order, not restoration of an already-cancelled order. It preserves the configured
price, reveal/sizing/repricing policies, and parent linkage. Repricing need not be
enabled. The existing revealed-order rearm lifecycle durably records the intent,
withdraws the live placement, and waits for authoritative zero-fill cancellation
confirmation before resetting the hidden cycle. The existing reveal policy then
resumes; a satisfied condition may reveal the order again immediately, subject to
its configured hold/delay. A fill discovered during cancellation prevents rehide.

Response: `stealth_order_rehide_result` with `stealth_order_id`, `accepted`, and
`message`; failures also include `error`. `accepted: true` acknowledges durable
intent, **not** confirmed withdrawal or a `HIDDEN` state. Initial exchange rejection
or timeout can leave this request pending reconciliation. The browser refreshes
`request_stealth_orders` and renders authoritative state without marking the order
hidden itself. Repeat pending requests must not create another order or placement.

The command originates a new reveal cycle, so it requires `RUNNING` admission and
bridge readiness. The dashboard's initial admission gate returns
`admission_rejected` during startup/pause/drain; validation, readiness, persistence,
or a later admission-race rejection returns `stealth_order_rehide_result` with
`accepted: false`. Ordinary cancellation remains independently available under
its existing contract.

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

`target_movement_type` is independent of every policy-level `distance_type`.
`P` interprets `target_movement` as a decimal fraction (`0.003` = `0.3%`);
`A` interprets it as an absolute quote-unit price movement (`300` = `$300` for
USD-quoted products). The stealth-manager and span-builder UIs expose this as a
separate Profit Target Type selector.

Policy fields:
- `anchor_repricing_policy`
- `reveal_pricing_policy`
- `follow_up_reveal_direction`

`anchor_repricing_policy` is optional. Omitting it or sending
`{"enabled": false}` preserves normal order behavior. When enabled, the current
stealth-manager and span-builder UIs emit:

- `enabled`
- `reference_price_source`: `last_trade`, `midpoint`, or `top_of_book`
- `distance_type`: `A` absolute or `P` percent
- `target_distance`
- `max_distance`
- `update_mode`: `adaptive` or `fixed`
- `fixed_interval_seconds`
- `min_price_change`
- `hysteresis_bps`
- `min_reprice_interval_seconds`
- `max_reprices_per_hour`
- `post_only_required`
- `slide_mode`
- `max_step_per_reprice`
- `follow_up_retreat_distance`
- `follow_up_retreat_jitter`

The span builder sends a separate policy for every emitted order. For zero-based
span index `i`, it adds the same nonnegative offset to `target_distance` and
`max_distance`: `i * price_step` for `A`, or
`i * (price_step / start_price)` for `P`. The backend remains responsible for
applying BUY/SELL direction. Percentage spacing therefore scales with the live
reference price; use `A` for fixed quote-unit spacing.

## 4) Internal Runtime Control API

`core/runtime_controller.py` exposes:
- `get_runtime_controller()` singleton accessor
- `check_admission(category)` gate
- `track_inflight(category)` context manager
- `track_admitted_inflight(category)` atomic admission/accounting context
- `complete_startup()` sole `STARTING` readiness transition
- `startup_pause_pending()` startup-latch inspection
- `lifecycle_snapshot()` coherent `(state, is_admitting, is_stopping)` status
- `request_pause()`, `resume()`, `request_shutdown()`
- `request_shutdown_from_signal()` lock-free sticky signal-handler handoff
- `drain_and_stop(timeout_seconds)`
- `register_stop_hook(name, hook)` returns `True` when queued; while effective
  state is `DRAINING` it invokes and tracks the hook immediately, and after
  `STOPPED` it invokes outside the already-published terminal result
- `register_admission_open_hook(name, hook)` / `unregister_admission_open_hook(name)`
  publish RUNNING-transition callbacks outside controller locks; registration
  while RUNNING is level-triggered
- `start_startup_component(name, start, stop)` atomically registers then starts
  one bounded component only while state is `STARTING`

`drain_and_stop()` is single-owner. Concurrent callers do not execute hooks a
second time; they receive the owning drain's terminal `DrainResult`. Timeout
values must be finite, non-negative, and within the platform wait limit.

Dashboard `engine_status` includes the RuntimeController `engine_state` sampled
when OrderEngine publishes status. `running` means background startup completed
and RuntimeController currently admits originating work; it would be false in
a sample taken during STARTING, PAUSED, DRAINING, or STOPPED.
`admin_status_response` is the live state authority after the engine stop
hook's final DRAINING sample.

`OrderEngine.prepare_for_global_drain()` is the early ordered hook. It sets the
local stop event only when background startup is incomplete; for a fully
started engine it publishes the non-running DRAINING sample while preserving
fill/event workers until the stealth bridge has stopped. The later
`OrderEngine.stop()` hook sets the event unconditionally and performs component
cleanup.

Inflight categories used by callers include:
- `INFLIGHT_REST_PLACE`
- `INFLIGHT_REST_CANCEL`
- `INFLIGHT_FILL_PROCESSING`
- `INFLIGHT_STEALTH_REVEAL`
- `INFLIGHT_DB_WRITE`
- `INFLIGHT_STOP_HOOK` (reported only when a DRAINING-time late stop hook
  exceeds the drain wait)

## 5) Error-Handling Guidance

- Use domain-specific exceptions from `core/exceptions.py`.
- WebSocket handlers should return structured `error` payloads, not raw tracebacks.
- Analytics may degrade with structured errors. Startup reconciliation and
  scheduler integrity are fail-closed readiness boundaries; do not describe
  them as universally fail-soft.

---

Last reconciled with checkout: 2026-10-09
