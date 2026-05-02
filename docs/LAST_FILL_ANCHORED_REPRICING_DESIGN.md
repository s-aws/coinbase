> Documentation status (2026-05-02): **Supplemental (non-canonical active reference)**
> This file is useful operational context but is not the canonical source of truth.
> Canonical living docs remain under genai_data/.
# Ticker-Anchored Repricing Design

## Goal

Add an optional order-creation feature that keeps an order a configured percentage or fixed amount away from a market reference price from the ticker feed.

Desired behavior:

- The feature is selected at order creation time.
- It works for both hidden and revealed orders.
- The order is re-evaluated on a fixed cadence (`60`, `120`, `300`) or an adaptive cadence.
- The order aims for a target distance from the anchor price.
- If the order drifts too far from that anchor beyond a configured max distance, it reverses course and moves back toward the anchor until it is inside the allowed band again.

This document is intentionally anchored to the current codebase instead of proposing a parallel subsystem.

## Existing Anchors In The Codebase

### 1. Single order-creation path already exists

Current creation flow:

- `order.py:create_limit_order_span()`
- `dashboard_server.py:create_stealth_order` WebSocket handler
- `bridges/stealth_order_bridge.py:create_stealth_order()`
- `core/stealth_order_manager.py:create_stealth_order()`

This is the correct insertion point for the feature because the system already expects all orders to enter through the stealth-order model, even for immediate reveal.

### 2. There is already a single background controller

`bridges/stealth_order_bridge.py` owns the evaluation loop.

That loop already decides when hidden orders change lifecycle state. It should also own the new ticker-anchored repricing checks so we do not introduce a second scheduler.

### 3. The codebase already has the right pricing pattern

`core/order_engine.py:resolve_parent_target_movement()` and `configuration.py:calculate_new_order_move_from_snapshot()` already model “derive a new order price from a reference price plus a movement rule”.

That pricing model should be reused for this feature instead of creating new pricing math somewhere else.

### 4. Current move logic is not the right primitive

`business/move_manager.py` is built for replacing a cancelled parent with a new parent order.

That is not the right abstraction here because this feature is about continuously managing one logical order around a market reference price, not about breaking and recreating the parent/child chain.

### 5. Current revealed-order ID usage must be generalized

Today `core/stealth_order_manager.py:reveal_order_slice()` uses `stealth_order_id` as the submitted `client_order_id` for the exchange placement.

That works for a one-time reveal, but it is not sufficient for repeated cancel/replace behavior. A repriced logical order needs:

- one stable logical order ID for internal tracking: `stealth_order_id`
- one new placement `client_order_id` for each exchange submission attempt
- one exchange `order_id` for cancellation

This is the main architectural constraint for implementing the feature safely.

## Proposed Concept

Introduce an optional policy on stealth orders called `anchor_repricing_policy`.

This policy tells the system:

- what market price to anchor to
- how far from that price the order should sit
- how far is too far
- how often to check
- whether a revealed exchange order may be cancel/replaced automatically

This keeps the feature as a policy on the existing order object, not as a new order type.

## Scope

### In scope for V1

- New order-creation option for anchored repricing
- Hidden-order price refresh before reveal
- Revealed open-order cancel/replace management
- Percentage and absolute distance modes
- Fixed and adaptive update cadence
- Max-distance guardrail
- Audit trail for anchor changes and reprices

### Out of scope for V1

- Anchoring to the user's own historical fills
- Managing multiple live exchange placements for one logical order at the same time
- Reusing `move_manager` semantics for this feature
- Retroactively migrating all historical orders into anchored mode

## Anchor Semantics

The anchor should be explicit, not implicit.

Recommended V1 anchor source:

- `ticker_last_trade`

Recommended production-ready source hierarchy:

1. `ticker_midpoint` for passive quote management when best bid/ask are available
2. `ticker_last_trade` if the intended behavior is explicitly “away from the last traded market price”
3. `ticker_same_side_top_of_book` for side-aware passive placement constraints

Meaning:

- `ticker_last_trade`: use the market last-traded price from the ticker stream
- `ticker_midpoint`: use $(bid + ask) / 2$
- `ticker_same_side_top_of_book`: BUY anchors from best bid, SELL anchors from best ask

This avoids the original problem of anchoring to internal fills, and it aligns with standard automated quoting practice where order placement tracks market data, not account trade history.

## Standard Trading Automation Recommendation

If the product goal is literally “stay X% or $Y away from the ticker's last traded price,” then `ticker_last_trade` is correct.

If the product goal is “maintain a passive quote around the live market,” standard practice is usually not last trade. It is typically one of:

- midpoint for neutral reference pricing
- best bid or best ask for side-aware quoting
- a protected reference such as midpoint with spread/tick guards

Reason:

- last trade can be stale in thin markets
- last trade can jump on isolated prints
- midpoint or top-of-book generally tracks quoteable liquidity better for passive automation

Recommended product design:

- expose `reference_price_source` as a creation-time option
- support `last_trade`, `midpoint`, and `top_of_book`
- default to `last_trade` only if you specifically want “distance from ticker last price” behavior
- otherwise default to `midpoint` for standard passive automation

## Price Semantics

For a given reference price `R`:

- SELL target price = `R + distance`
- BUY target price = `R - distance`

Where `distance` is:

- percentage mode: `R * target_distance`
- absolute mode: `target_distance`

And the max boundary is:

- SELL max price = `R + max_distance`
- BUY min price = `R - max_distance`

This aligns with the existing follow-up spacing model already used by the engine.

## Operational Band

The policy defines two distances from the anchor:

- `target_distance`: where the order prefers to rest relative to the market reference price
- `max_distance`: farthest allowed distance from the market reference price

Behavior:

1. If current order price is near the target band, do nothing.
2. If current order price is between target and max, optionally leave it until the next scheduled correction.
3. If current order price moves outside max, reprice toward the anchor immediately enough to return inside the allowed band.

Recommended correction rule:

- if outside max, move to the max boundary first
- if still enabled on later cycles, converge back toward the target boundary

That matches the user requirement that the order “reverse course and move closer until it is closer than the max” without forcing every correction to jump straight back to the ideal target.

## Update Cadence Model

Support both fixed cadence and adaptive cadence.

### Fixed cadence

- `60`
- `120`
- `300`

### Adaptive cadence

Adaptive mode should schedule the next evaluation based on how far the current order is from the target band.

Recommended initial rule:

- severe drift or outside max: check again in `60s`
- moderately outside target: `120s`
- comfortably far from needing action: `300s`

Even though the user described “further away updates more slowly”, the guardrail case should override that rule. Once the order is beyond `max_distance`, the system should switch to the shortest cadence until it is back inside the allowed band.

Standard automation note:

- if you are using live ticker anchoring for a truly competitive passive quote, `60/120/300s` is slow by market-making standards
- that cadence is acceptable for low-frequency repositioning logic
- for more standard quote maintenance, use event-driven ticker updates plus throttle and cooldown guards rather than minute-scale polling alone

That gives the feature predictable safety behavior.

## Hidden Vs Revealed Behavior

### Hidden order

If the order has not yet been revealed:

- recompute the configured `limit_price` from the latest market reference price
- persist the updated logical price on the stealth order record
- do not touch the exchange because there is no live placement yet

### Revealed open order

If the order is live on exchange and still open:

- compute the desired correction price from the current market reference state
- compare against the active live placement price
- if outside tolerance, cancel the active exchange order using exchange `order_id`
- submit a replacement exchange order with a new placement `client_order_id`
- update the active placement reference on the logical stealth order

This keeps one logical order strategy while allowing multiple sequential exchange placements.

## Required Data Model Changes

### Stealth order logical policy

Add `anchor_repricing_policy_json` to `stealth_orders`.

Suggested structure:

```json
{
  "enabled": true,
  "reference_price_source": "last_trade",
  "distance_type": "P",
  "target_distance": 0.01,
  "max_distance": 0.05,
  "update_mode": "adaptive",
  "fixed_interval_seconds": null,
  "allow_revealed_reprice": true,
  "min_price_change": 0.01,
  "hysteresis_bps": 5,
  "min_reprice_interval_seconds": 30,
  "max_reprices_per_hour": 20,
  "post_only_required": true,
  "converge_to_target": true,
  "inherit_to_follow_ups": true
}
```

### Stealth order runtime state

Add `anchor_repricing_state_json` to `stealth_orders`.

Suggested fields:

```json
{
  "last_reference_source": "ticker_last_trade",
  "last_reference_price": 100.0,
  "last_reference_bid": 99.9,
  "last_reference_ask": 100.1,
  "last_reference_at": "2026-04-25T12:00:00Z",
  "current_logical_limit_price": 101.0,
  "active_placement_client_order_id": "placement-client-id",
  "active_exchange_order_id": "exchange-order-id",
  "active_exchange_price": 101.0,
  "last_reprice_at": "2026-04-25T12:01:00Z",
  "next_reprice_at": "2026-04-25T12:03:00Z",
  "reprice_reason": "outside_max_boundary"
}
```

### Placement history

Extend `revealed_orders` event objects to include:

- `placement_client_order_id`
- `exchange_order_id`
- `placement_status`
- `cancelled_for_reprice`
- `reference_price_source`
- `reference_price`
- `reference_bid`
- `reference_ask`
- `anchor_target_price`
- `anchor_max_price`
- `reprice_reason`

## Critical ID Handling

This feature must preserve the existing order ID rules:

- use `client_order_id` for internal tracking
- use exchange `order_id` for cancellations

For anchored repricing, the system must stop assuming that `stealth_order_id == live placement client_order_id`.

Recommended model:

- `stealth_order_id`: stable logical strategy ID
- `placement_client_order_id`: new UUID for each live exchange placement
- `exchange_order_id`: Coinbase ID from the successful placement response

Then maintain two lookups in memory:

- `placement_client_order_id -> stealth_order_id`
- `stealth_order_id -> active placement metadata`

This lets fill and cancel events still resolve back to the logical order while supporting repeated replacements.

## Proposed Runtime Flow

### 1. Order creation

Order is created through the existing `create_stealth_order()` path with optional `anchor_repricing_policy`.

Validation at creation time:

- `target_distance > 0`
- `max_distance >= target_distance`
- `distance_type in {'P', 'A'}`
- if anchored mode is enabled, an anchor source must be resolvable

### 2. Ticker updates refresh reference state

When `OrderEngine` or `StealthOrderBridge` receives ticker updates for the product:

- normalize the product ID as it already does for ticker processing
- update the order's latest reference price state from the configured source
- schedule repricing evaluation if the market moved materially

This is the correct place to ingest anchor updates because the feature is explicitly driven by market data, not account trade events.

### 3. Bridge evaluation loop handles repricing

Extend the existing `StealthOrderBridge` evaluation loop to do two checks for each eligible stealth order:

- reveal-condition evaluation for hidden orders
- anchor repricing evaluation for anchored orders

This keeps one scheduler and one lifecycle surface.

### 4. Hidden order repricing

If hidden and anchored:

- compute target logical price from current reference price state
- update `limit_price` and runtime state
- persist to database

### 5. Revealed order repricing

If revealed, open, and anchored:

- read active placement metadata
- compute current band from current reference price
- determine whether to hold, correct to max boundary, or converge to target
- cancel current exchange order by `exchange_order_id`
- place replacement with new `placement_client_order_id`
- update state and audit trail

## Recommended Components

### A. New policy model

Add enum(s) in `core/enums.py`:

- `ReferencePriceSource`
- `AnchorRepricingUpdateMode`
- `AnchorRepricingAction`

Add dataclass(es) in `core/models.py`:

- `AnchorRepricingPolicy`
- `AnchorRepricingState`
- `AnchorRepricingDecision`

This matches the repo’s existing pattern of formalizing execution decisions in models and enums.

### B. Manager methods in `core/stealth_order_manager.py`

Recommended methods:

- `_normalize_anchor_repricing_policy(...)`
- `build_anchor_repricing_state(...)`
- `compute_reference_target_prices(...)`
- `decide_anchor_reprice_action(...)`
- `apply_hidden_anchor_reprice(...)`
- `apply_revealed_anchor_reprice(...)`

These should be used from the existing manager and bridge flow, not from a separate service tree.

### C. Engine integration in `core/order_engine.py`

Recommended method:

- `notify_reference_price_update(...)`

Responsibility:

- publish market reference price updates to the stealth manager when a relevant ticker arrives

### D. Dashboard and API integration

Update the create-order payload handled by `dashboard_server.py` to accept:

- `anchor_repricing_policy`

UI changes in `ui_order_manager.html`:

- enable toggle
- distance type selector: `%` or fixed amount
- target distance input
- max distance input
- cadence selector: `60`, `120`, `300`, `adaptive`
- optional inheritance toggle for follow-ups

## Decision Algorithm

Recommended decision output:

```python
{
    "action": "hold|update_hidden|replace_live",
    "reason": "within_band|outside_max_boundary|converge_to_target|reference_price_updated",
    "target_price": 101.00,
    "max_boundary_price": 105.00,
    "replacement_price": 105.00,
    "next_check_seconds": 60,
}
```

Recommended logic:

1. Resolve latest market reference price.
2. Compute target and max boundary prices.
3. Compare current logical/live price against those thresholds.
4. If beyond max, choose `replace_live` or `update_hidden` toward max boundary.
5. If within band but materially stale versus target, optionally converge.
6. Otherwise hold and schedule next check.

Additional standard-practice gates:

7. Do not reprice if `min_price_change` is not met.
8. Do not reprice if `min_reprice_interval_seconds` has not elapsed.
9. Do not reprice if hourly churn limit is exceeded.
10. For passive orders, skip replacements that would cross the spread when `post_only_required` is enabled.

## Why This Should Live In The Existing Bridge Loop

Reasons:

- the bridge already evaluates order lifecycle continuously
- it already has market cache and stealth-order access
- it avoids a new thread with overlapping ownership of the same order state
- it preserves the repo’s “single path” rule

Recommended implementation detail:

- keep the `100ms` bridge loop
- gate anchor repricing by per-order `next_reprice_at`
- do not run repricing logic on every pass

This keeps responsiveness without creating unnecessary churn.

## Risk Areas

### 1. Placement ID reuse

This is the biggest functional risk. Without decoupling logical order ID from per-placement `client_order_id`, repeated reprice submissions will be brittle or fail outright.

### 2. Cancellation race conditions

An order may fill while a reprice cancellation is in flight.

Required behavior:

- treat fill as authoritative
- ignore replacement if cancellation reports already-filled
- avoid double follow-up creation by preserving current fill-claim protections in `OrderEngine`

### 3. State persistence gaps

Current `StealthOrderManager` DB persistence only stores a subset of runtime fields. V1 should explicitly persist the new repricing policy and runtime state; otherwise restart behavior will be inconsistent.

### 4. Hidden/revealed lifecycle transitions

If market reference state changes just before reveal, the reveal path must use the latest logical limit price. The repricing policy should therefore be evaluated before reveal submission, not after.

### 5. Quote churn and exchange throttling

Ticker-driven repricing can create excessive cancel/replace churn.

Required behavior:

- enforce hysteresis and minimum price change
- enforce minimum time between reprices
- enforce per-order replacement caps over a rolling window
- prefer event-driven scheduling with throttle instead of unconditional replacement on every tick

## Implementation Plan

### Phase 1: Formalize the policy and IDs

1. Add enums and dataclasses for anchored repricing.
2. Decouple logical `stealth_order_id` from per-placement `placement_client_order_id`.
3. Extend in-memory indexes so placement events resolve back to a stealth order.

Deliverable:

- no behavior change yet, but the model supports repeated placements safely.

### Phase 2: Persist policy and state

1. Add `anchor_repricing_policy_json` and `anchor_repricing_state_json` to `stealth_orders`.
2. Update `create_stealth_order()`, `_save_stealth_order_to_db()`, `_update_stealth_order()`, and load methods.
3. Add helper functions for updating market reference state and active placement state.

Deliverable:

- anchored orders survive restart with correct configuration and active state.

### Phase 3: Add creation-time API and UI

1. Extend dashboard WebSocket create payload.
2. Add UI inputs in `ui_order_manager.html`.
3. Validate `max_distance >= target_distance` and anchor-source compatibility.

Deliverable:

- users can create anchored orders from the existing order form.

### Phase 4: Hidden-order repricing

1. Add reference price ingestion from ticker events.
2. Extend bridge evaluation to update hidden order logical prices.
3. Log every hidden repricing decision with reference-price context.

Deliverable:

- hidden orders track the configured market reference price before reveal.

### Phase 5: Revealed-order cancel/replace

1. Store active exchange placement metadata on successful reveal.
2. Add decision logic for hold vs replace.
3. Cancel by exchange `order_id`, then place a new exchange order with a fresh `placement_client_order_id`.
4. Update placement history and active state.

Deliverable:

- live orders maintain the configured band relative to the latest market reference price.

### Phase 6: Follow-up inheritance

1. If enabled, pass anchored repricing policy through follow-up creation.
2. Rebind the same reference-price source on the follow-up order.
3. Ensure the flat parent-child hierarchy stays intact.

Deliverable:

- the feature works consistently across order chains without changing the existing hierarchy model.

### Phase 7: Test coverage

Add focused tests for:

1. policy validation
2. percentage and absolute price derivation
3. hidden-order logical repricing
4. live-order replacement when outside max
5. no replacement while inside tolerance band
6. correct use of `exchange order_id` for cancel and placement `client_order_id` for internal tracking
7. restart reload preserving reference-price state
8. race where fill arrives during cancel/replace
9. no reprice when ticker movement is below hysteresis threshold
10. no reprice when post-only guard would cross the book

Recommended test locations:

- `tests/unit/` for pricing and decision logic
- `tests/integration/` for bridge + engine flow

## Review Recommendation

If approved, the first implementation step should not be UI work.

The first implementation step should be the placement-ID refactor plus policy model introduction, because the rest of the feature depends on that foundation.

## Open Questions

1. Should V1 expose only `last_trade`, or also `midpoint` and `top_of_book` as reference-price options?
2. When an order is inside the `[target, max]` band, should it hold position or gradually converge back toward the target every cycle?
3. Should follow-up orders inherit the anchored repricing policy by default, or only when explicitly enabled?
4. Should the adaptive scheduler prioritize “farther away updates more slowly” in all cases, or should the max-boundary breach always force the fastest cadence?

My recommendation:

- V1 should support a reference-price source field and default it to `last_trade` only if that matches the intended product behavior
- if you want standard passive automation behavior, the default should be `midpoint`
- V1 should correct to max boundary first, then optionally converge later
- follow-up inheritance should be explicit but default-on for advanced strategy users
- max-boundary breach should always force the fastest cadence

