# Data Models Reference

This document is a navigation reference and may contain historical model
descriptions. `core/models.py`, `core/enums.py`, and `database/order.py` are the
evidence for the current runtime and persistence surface.

## Core Typed Models (`core/models.py`)

### `Order`
Represents a tracked order in memory.

Key fields:
- `client_order_id` (internal primary identifier)
- `product_id`
- `order_side` (`OrderSide`)
- `status` (`OrderStatus`)
- `size`, `price`, `filled_size`
- `order_id` (exchange identifier, optional)
- `product_type` (`ProductType`)
- `custom_metadata`

### `Product`
Product metadata used for precision, min size, and product type behavior.

### `Position`
Futures position snapshot (`product_id`, `side`, `number_of_contracts`, etc.).

### `Wallet`
Account wallet balance snapshot.

### `FollowUpOrderTemplate`
Canonical structure used for follow-up order generation.

### `RevealExecutionPlan`
Resolved reveal execution intent for a stealth order.
Includes submitted price, source, policy, market context, target movement source, and post-only flag.

### `StealthMovePlan` / `StealthMoveResult`
Planning and execution result structures for move-revealed flow.

### `RepricingPolicy`
Strongly-typed anchor repricing policy with normalization and helper methods.
Serialized into `stealth_orders.anchor_repricing_policy_json`.

### `CancelReentryPolicy` / `CancelReentryRuntimeState`
Pure cancel/re-entry policy and mutable runtime state in `business/cancel_reentry_policy.py`.
Serialized into `stealth_orders.cancel_reentry_policy_json` and `stealth_orders.cancel_reentry_state_json`.

### `PostFillRetreatPolicy`
Opt-in same-side hidden-order retreat policy in `business/post_fill_retreat_policy.py`.
Serialized into `stealth_orders.post_fill_retreat_policy_json`.

### TypedDicts
- `MarketData`: current market snapshot for stealth evaluation/repricing.
- `RepricingState`: mutable per-stealth runtime state persisted in JSONB.

## Canonical Enums (`core/enums.py`)

High-impact enums:
- `OrderSide`, `OrderStatus`, `StealthOrderStatus`
- `ProductType`, `TargetMovementType`
- `RevealPricingPolicy`, `RevealPriceSource`, `RevealConditionType`
- `RepricingReferenceSource`, `RepricingDistanceType`, `RepricingUpdateMode`
- `PostFillRetreatScope`, `PostFillRetreatReason`
- `CancelReentryState`, `CancelReentryDecision`
- `FollowUpKind`, `StealthMutationKind`, `StealthMoveReason`
- `OrderStateEvent`, `StealthLifecycleEvent`
- `EventStreamType`, `EventSourceChannel`
- `EngineState`, `WebSocketEventType`, `UserFeedPhase`

Use enums instead of string literals in new behavior.

`WebSocketEventType` is the authenticated wire kind (`snapshot`, `update`, or
`patch`) and must not be substituted for the lifecycle `OrderStatus` carried
inside an order row. `UserFeedPhase` is connection-generation state only:
`AWAITING_SNAPSHOT`, `BOOTSTRAPPING`, `LIVE`, or `DESYNCHRONIZED`.

`EngineState.STARTING` is the initial fail-closed runtime state. It permits
cancellation, fill handling, and DB completion but rejects originating work.
`RuntimeController.complete_startup()` is its sole admission-opening exit;
startup pause requests cause that exit to publish `PAUSED` instead of
`RUNNING`. Startup component registration/start and component-local publication
locks prevent new worker activation or readiness revival after stop wins;
concurrent drain callers share one terminal result. `STOPPED` is a logical
admission/accounting boundary: bounded joins and drain timeouts can leave
cooperative daemon work finishing afterward.

### Stealth Status Semantics

- `HIDDEN`, `PENDING`, and `TRIGGERED`: no active exchange placement should exist.
- `REVEALED`: one or more placements have been submitted; the latest active placement may be tracked in `anchor_repricing_state_json`.
- `ERROR`: an exchange placement was rejected or could not be proven accepted.
  It is terminal and is not automatically retried.
- `EXECUTED` and `CANCELLED`: terminal local states, but reconciliation still matters if exchange evidence later contradicts local assumptions.

Cancel/re-entry uses status plus runtime state:
- `REVEALED` + policy enabled + no executed size: eligible for policy cancellation when the distance threshold is crossed.
- `HIDDEN` + `cancel_reentry_state_json.state = "cancelled_by_policy"`: not a normal hidden order; it is waiting for re-entry distance/cooldown/count checks.
- `REVEALED` with any executed size must not be policy-hidden.

Do not add a new stealth status unless the transition is backed by persistence, dashboard display, lifecycle/audit events, and regression tests.

## In-Memory Runtime Structures

### `UserStreamEnvelope` (`core/order_engine.py`)

Immutable private WebSocket transport record containing `channel`, connection
`generation`, connection-global `sequence_num`, Coinbase `timestamp`, and the
complete event tuple. It remains intact in user, futures-balance, and
private-heartbeat traffic while all three sources traverse one ordered private
reducer queue, so stale generations can be rejected before state mutation.

### `OrderBook` (`core/orderbook.py`)
Primary mutable structures:
- orders map (`client_order_id -> order payload`)
- parent map (`root_client_order_id -> parent entry`)
- child-to-parent map
- position map
- follow-up claim ledger

### `OrderProgressTracker` (`business/order_progress.py`)
Per-`client_order_id` watermark records for:
- cumulative quantity processed
- fee/value counters
- carry remainder for partial-fill follow-ups
- snapshot sequence and derived trade key generation

### Dashboard State (`dashboard_server.py`)
`engine_state` includes:
- orders
- positions
- stealth_orders
- engine_status
- logs
- market_metrics

## Database Schema (Canonical: `database/order.py`)

### `order_parent`
Stores both parent and child placement rows under flat hierarchy.

Key columns:
- `client_order_id` (unique)
- `parent_order_id` (root parent link for children)
- `product_id`, `side`, `size`, `price`, `status`
- `target_movement`, `target_movement_type`
- `max_order_replacement`, `current_order_replacement`
- `allow_partial_fills`

### `stealth_orders`
Primary stealth order state table.

Key columns:
- `stealth_order_id` (unique)
- `parent_order_id` (stealth follow-up linkage)
- size and status fields (`total_size`, `revealed_size`, `remaining_size`, `executed_size`, `status`)
- condition fields (`reveal_condition_type`, `reveal_condition_json`, hold timestamps)
- reveal execution policy (`reveal_pricing_policy`; defaults to `configured_limit`)
- policy/state JSONB (`anchor_repricing_policy_json`, `anchor_repricing_state_json`, `sizing_strategy_json`, `cancel_reentry_policy_json`, `cancel_reentry_state_json`, `post_fill_retreat_policy_json`)
- lifecycle fields (`last_lifecycle_event`, `failure_reason`)

`anchor_repricing_state_json` is also the active-placement pointer for revealed stealth orders. Important keys include:
- `active_placement_client_order_id`
- `active_exchange_order_id`
- `active_exchange_price`
- `current_logical_limit_price`
- cancel/re-entry audit hints such as `cancel_reentry_last_reference_price` and `cancel_reentry_last_distance`
- post-fill retreat state such as `post_fill_retreat_offset`, `post_fill_retreat_count`, `post_fill_retreat_source_order_ids`, and `last_post_fill_retreat_*`

`cancel_reentry_policy_json` keys:
- `enabled`
- `reference_price_source` (`last_trade`, `midpoint`, `top_of_book`)
- `distance_type` (`A` absolute or `P` percent)
- `cancel_distance`
- `reentry_distance` (must be greater than cancel distance)
- `cooldown_seconds`
- `max_reentry_count` (`0` means unlimited)
- `inherit_to_follow_ups`

`cancel_reentry_state_json` keys:
- `state` (`resting` or `cancelled_by_policy`)
- `last_cancel_at`
- `last_reentry_at`
- `reentry_count`
- `cancelled_placement_client_order_id`
- `cancelled_exchange_order_id`
- `last_reason`

`post_fill_retreat_policy_json` keys:
- `enabled`
- `scope` (`same_product_same_side`; only implemented scope)
- `retreat_ticks` (integer count of product price ticks)
- `inherit_to_follow_ups`

Same-side post-fill retreat state is stored in `anchor_repricing_state_json`, not a separate active-placement pointer. The cumulative `post_fill_retreat_offset` is added to future anchor target bands so anchor repricing does not undo the retreat.

> Note: `reveal_pricing_policy` is a first-class `stealth_orders` column and
> is restored during both startup and lazy hydration.
> `follow_up_reveal_direction` remains an **in-memory dict key only** and is
> not a column on `stealth_orders`.

### `stealth_order_snapshots`
Lifecycle/event snapshots with market context.

### `stealth_order_reveal_history`
One row per reveal/reprice placement event.
Contains placement IDs, exchange IDs, trigger context, and reference-price audit data.

### `stealth_order_lifecycle_history`
Immutable lifecycle transition history rows for stealth state machine events.

### `order_moves`
Parent-order move/premark audit table.

### `stealth_order_moves`
Move-revealed audit table for stealth orders.

### `fill_ledger`
Append-only fill ledger.

Key id columns:
- `derived_trade_key` (unique WS-derived idempotency key)
- `exchange_trade_id`, `exchange_entry_id` (REST-authoritative ids)
- `reconciliation_status` (`WS_DERIVED`, `RECONCILED`, `MISMATCH`)

### `order_match_audit`
Per-snapshot derived-counter audit rows for websocket order progress.

### `order_event_stream`
Normalized event timeline across placement, status changes, triggers, and hooks.

### `conditional_orders`
Conditional order persistence for condition-based execution wrappers.

### `partial_fill_progress`
Restart-safe per-order watermark state for partial-fill follow-up flow.

## Analytics Support Tables

### `market_tick`
Downsampled ticker persistence (typically <= 1 row/sec/product).

### `market_candle_1m`
1-minute OHLC fallback table used for chart backfill.

## API Payload Shapes in Active Use

### Coinbase create order response (wrapped)
`CoinbaseRestClient.place_limit_order` returns SDK response dict with:
- `success`
- `success_response` (`order_id`, `client_order_id`, `product_id`, `side`)
- optional `failure_reason` / `error_response`

### Dashboard state broadcast
`state_update` payload:
- `type: "state_update"`
- `data: engine_state`
- `timestamp`

### Slide calibration summary
`slide_calibration_summary` payload includes:
- window metadata
- per-product fill + stealth + reprice metrics
- totals and target progress values

### Stealth create/import payload
`create_stealth_order` and active-stealth import payloads can include:
- `anchor_repricing_policy`
- `cancel_reentry_policy`
- `post_fill_retreat_policy`
- `sizing_strategy`

Dashboard exports map persisted JSONB names back to request names, for example `cancel_reentry_policy_json` -> `cancel_reentry_policy`.

## ID Model Summary

- Internal key: `client_order_id`
- Exchange key: `order_id`
- Fill idempotency key: `derived_trade_key`

See `ORDER_ID_HANDLING.md` for strict usage rules.

---

Last updated: 2026-05-16
