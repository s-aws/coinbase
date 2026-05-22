# Stealth Order Reveal & Reprice Audit Trail

This module documents the persistence path that records every reveal-time and
reprice-time placement decision into `stealth_order_reveal_history`, plus the
canonical lookup of `target_movement` used by both the pre-trade profit gate and
child `order_parent` rows.

## Why

Two separate gaps were uncovered while debugging a wasted retracement fill:

1. **Reveal-time profit gate was silently no-op.** The gate read
   `target_movement` from `stealth_orders` (where it is `NULL` for root orders);
   the canonical value lives on `order_parent`.
2. **Anchor reprices left no audit row.** Revealed reprices placed new exchange
   orders, but `_record_reveal_event` was never called and the new placement
   `client_order_id` was not inserted into `order_parent` (FK violation risk on
   any incoming WS event for that uuid).

The fix elevates `RevealExecutionPlan` to be the single source of truth for
profitability inputs and extends `_record_reveal_event` to capture the full
reprice context (placement uuid, anchor target, reference price source, etc.).

## Canonical `target_movement` resolution

Defined in
`StealthOrderManager._resolve_target_movement_for_plan(stealth_order_id, order)`.

Lookup precedence:

1. `order_parent` row (canonical) keyed by `stealth_order_id`.
2. In-memory stealth `order` dict (rarely populated for root orders).
3. `unavailable` — caller decides whether to skip the gate.

Returns `(target_movement: Optional[float], target_movement_type: Optional[str],
source: str)`. The `source` value (`"order_parent"`, `"stealth_order"`,
`"unavailable"`) is recorded on `RevealExecutionPlan.target_movement_source` for
audit so silent skips of the gate are traceable.

Used by:

- `build_reveal_execution_plan` — populates `plan.target_movement(_type)`.
- `_validate_reveal_profitability` — reads from the plan and logs an explicit
  skip line when `target_movement_source == "unavailable"`.
- `reveal_order_slice` — propagates the canonical value to the child placement
  `order_parent` row so post-fill follow-up calculations see the inherited
  target instead of `0.0`.
- `_apply_revealed_anchor_reprice` — same propagation when a reprice creates a
  new child placement uuid.

## Reveal history schema additions

Additive columns (all nullable, backwards-compatible). Migration is idempotent
via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in
`create_stealth_order_reveal_history_table()`.

| Column                     | Type           | Purpose                                                    |
| -------------------------- | -------------- | ---------------------------------------------------------- |
| `placement_client_order_id`| `UUID`         | The placement uuid sent to the exchange.                   |
| `placement_status`         | `VARCHAR(32)`  | `placed` / `failed` / `repriced`.                          |
| `placement_success`        | `BOOLEAN`      | True if REST submission succeeded.                         |
| `cancelled_for_reprice`    | `BOOLEAN`      | True when this row was superseded by a later reprice.      |
| `reprice_reason`           | `VARCHAR(64)`  | `reference_price_updated`, `outside_max_boundary`, ...     |
| `reveal_event_type`        | `VARCHAR(32)`  | `reveal` / `reprice` / `reveal_blocked` (filter helper).   |
| `anchor_target_price`      | `DECIMAL(16,2)`| Anchor target price at reveal/reprice time.                |
| `anchor_max_price`         | `DECIMAL(16,2)`| Anchor max boundary at reveal/reprice time.                |
| `reference_price_source`   | `VARCHAR(64)`  | E.g. `ticker_midpoint`, `ticker_best_bid`.                 |
| `reference_price`          | `DECIMAL(16,2)`| Numeric reference price used by the policy.                |
| `reference_bid`            | `DECIMAL(16,2)`| Bid sample at the reference moment.                        |
| `reference_ask`            | `DECIMAL(16,2)`| Ask sample at the reference moment.                        |
| `market_source`            | `VARCHAR(32)`  | `ticker` / `snapshot` / `unavailable`.                     |

## Trigger reason

`_format_reveal_trigger_reason(order, reveal_event)` replaces the previous
`"Price below unknown"` placeholder. It reads the live `reveal_condition_json`
(direction, threshold) and falls back to the configured limit when no explicit
threshold is set. Reprice rows render as `"Anchor reprice: <reason>"`.

## Structured logging

The following INFO events are emitted via `log_callback`:

- `stealth_anchor_reprice_hidden_applied` — limit price moved while order is
  hidden/triggered.
- `stealth_anchor_reprice_revealed_applied` — exchange order cancelled and
  re-placed at a new price; new placement uuid included.
- `stealth_anchor_reprice_blocked_unprofitable` — pre-trade gate blocked the
  reprice; `last_profitability_block_reason` mirrored on the persisted state.
- `stealth_order_profitability_validation_failed` — reveal blocked by the
  pre-trade gate.

## Querying the audit trail

```sql
-- Full lifecycle for a single stealth order, including reprices
SELECT reveal_number, reveal_event_type, placement_status,
       placement_price, reprice_reason,
       reference_price_source, reference_price,
       market_bid, market_ask, anchor_target_price, anchor_max_price,
       created_at
FROM stealth_order_reveal_history
WHERE stealth_order_id = :stealth_order_id
ORDER BY created_at;
```
