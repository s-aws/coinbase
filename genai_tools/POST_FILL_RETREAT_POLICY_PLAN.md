# Same-Side Post-Fill Retreat Policy Plan

## Intent

Introduce an opt-in hidden-order policy that moves the nearest eligible same-product,
same-side hidden order away from the market after another order on that side fills.

This is not re-hide behavior and is not a general cross-order rules engine. It only
mutates hidden stealth orders that have no active Coinbase placement.

## Terminology

- Feature name: same-side post-fill retreat.
- Per-order policy field: `post_fill_retreat_policy_json`.
- Scope enum: `PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE`.
- Mutation kind: `StealthMutationKind.RETREAT`.
- Audit reason: `PostFillRetreatReason.SAME_SIDE_FILL`.
- Retreat unit: product price tick / `price_increment`.

## Runtime Rules

1. On a stealth fill, inspect in-memory stealth orders.
2. Select only orders matching:
   - same `product_id`
   - same side
   - status `HIDDEN`, `PENDING`, or `TRIGGERED`
   - no active placement client order id
   - no active exchange order id
   - enabled `post_fill_retreat_policy_json`
3. Pick the eligible hidden order closest to the fill reference price.
4. Claim `StealthMutationKind.RETREAT` before mutating it.
5. Move BUY orders lower and SELL orders higher by `retreat_ticks * price_increment`.
6. Move reveal-condition price thresholds with the limit price.
7. Reset trigger timing fields so the order must re-qualify through the normal reveal path.
8. Store cumulative retreat offset in anchor repricing state so later anchor repricing does not erase the retreat.
9. Use the filled placement client id as an idempotency source key so replayed fill handling cannot nudge another order.

## UI Contract

Both `ui_order_span_builder.html` and `ui_stealth_orders_manager.html` expose:

- Enable same-side post-fill retreat.
- Retreat ticks, minimum 1.

Dashboard create/import/export payloads preserve `post_fill_retreat_policy`.

## Persistence Contract

`stealth_orders.post_fill_retreat_policy_json` stores the normalized policy and defaults
to disabled:

```json
{"enabled": false}
```

Follow-up stealth orders inherit the policy only when `inherit_to_follow_ups` is true.

## Test Coverage

Regression coverage must include:

- Policy round trip and disabled defaults.
- Create path persists policy.
- SELL retreat moves higher and updates reveal thresholds.
- BUY retreat moves lower and updates reveal thresholds.
- Duplicate fill processing is idempotent.
- Anchor repricing preserves cumulative retreat offset.
- UI and dashboard payload contract wiring.
