# Cancel/Re-Entry Policy Plan

Date: 2026-05-16

## Intent

Introduce an optional policy that cancels a resting visible order when the market moves too close to its limit, then re-enters the order when the market moves safely away again.

Example for a SELL limit at 100:

- mid = 90: distance = 10, order rests
- mid = 91: distance = 9, order rests
- mid = 92: distance = 8, policy cancels
- mid = 93: still cancelled
- mid = 92: still cancelled
- mid = 91: distance = 9, policy re-enters

BUY orders reverse the distance formula.

## Terminology

Use the implementation name `cancel_reentry_policy`.

This is not a new order type. It is a lifecycle policy attached to an order.

## Policy Shape

```json
{
  "enabled": true,
  "reference_price_source": "midpoint",
  "cancel_distance": 8.0,
  "reentry_distance": 9.0,
  "distance_type": "A",
  "cooldown_seconds": 5,
  "max_reentry_count": 3,
  "inherit_to_follow_ups": true
}
```

Initial implementation should support midpoint, last trade, and top-of-book references. `distance_type` uses the existing enum values: `A` for absolute amount and `P` for percentage.

`reentry_distance` must be greater than `cancel_distance` to create hysteresis. Without hysteresis the order can flap on adjacent ticks.

## State Shape

Persist mutable runtime state with the order:

```json
{
  "state": "resting",
  "last_cancel_at": null,
  "last_reentry_at": null,
  "reentry_count": 0,
  "cancelled_placement_client_order_id": null,
  "cancelled_exchange_order_id": null,
  "last_reason": null
}
```

Expected states:

- `resting`
- `cancelled_by_policy`

Avoid adding broad new `OrderStatus` / `StealthOrderStatus` values unless the code needs them. The policy state is separate from order status.

## Distance Formulas

For SELL:

```text
distance = limit_price - midprice
cancel when distance <= cancel_distance
re-enter when distance >= reentry_distance
```

For BUY:

```text
distance = midprice - limit_price
cancel when distance <= cancel_distance
re-enter when distance >= reentry_distance
```

If midprice, side, or limit price is unavailable, do nothing and log/debug reason only where useful.

## Lifecycle Rules

- Fill/executed wins. Do not policy-cancel or re-enter an order that has any fill.
- Manual cancel wins. Do not re-enter manual/user-cancelled orders.
- Exchange cancel failure keeps the order revealed/resting with active placement pointers intact.
- Policy cancel must use existing exchange cancel path and mutation claims.
- Re-entry must go through the existing reveal placement path, not a new REST placement path.
- Parent/child hierarchy remains flat. Re-entry must not create a child/grandchild.
- Anchor reprice and policy cancel must not mutate the same revealed placement concurrently.

## First Implementation Scope

Implement for stealth orders because the active order-span and stealth-manager UIs create stealth orders, and stealth has the existing reveal/reprice/move machinery needed for safe cancel/re-entry.

Add the evaluator as a reusable business module so normal-order support can be added later without duplicating the policy math.

## Integration Points

- `business/cancel_reentry_policy.py`: pure policy normalization and decision logic.
- `core/stealth_order_manager.py`: persist config/state, cancel active revealed placement, re-enter through `reveal_order_slice`.
- `bridges/stealth_order_bridge.py`: evaluate policy for active orders after reveal/reprice processing.
- `database/order.py`: JSONB columns for policy and state.
- `dashboard_server.py`: pass config through `create_stealth_order` / import/export.
- `ui_order_span_builder.html`: configure policy for span-created orders.
- `ui_stealth_orders_manager.html`: configure and display policy for direct stealth orders.
- `tests/regression/`: policy evaluator tests plus stealth lifecycle wiring tests.

## Stop/Reevaluate Conditions

Reevaluate before continuing if implementation requires:

- changing how fills are reconciled;
- adding a new global order status;
- changing parent/child linkage semantics;
- re-entering by creating a child order;
- ignoring exchange cancel failure;
- separate logic paths for span orders vs stealth-manager orders.
