# Partial Fill Follow-Ups

## Overview

Partial fills occur when an exchange order is matched only in part — e.g., a BUY 0.10 BTC order fills 0.04 BTC and remains open for the rest. The **partial-fill follow-up system** detects these mid-order fills and automatically creates new stealth follow-up orders for each accumulated minimum-size unit, keeping the position working without manual intervention.

This feature is:
- **Opt-in per parent order** (`allow_partial_fills=True`)
- **Restart-safe** (watermark persisted to `partial_fill_progress` table)
- **Concurrency-safe** (per-order lock + monotonic delta checks)
- **Audit-trailed** (every watermark advance emitted to `order_event_stream`)

---

## How It Works — End-to-End

```
1. Order created with allow_partial_fills=True
   └─► insert_order_parent(allow_partial_fills=True)

2. Engine starts / restarts
   └─► start_background_threads()
       ├─► load_parent_child_order_ids()         # reads allow_partial_fills from DB
       └─► _hydrate_partial_fill_state_from_db() # restores watermarks

3. WebSocket OPEN / UPDATE event arrives for the child order
   └─► process_user_order(status=OPEN)
       └─► _handle_partial_fill_if_enabled(client_order_id, order)
           ├─► acquire per-order lock (prevents concurrent duplicate events)
           ├─► read cumulative_quantity from event
           ├─► on first fill: lazy-init watermark entry in _partial_fill_state
           ├─► compute delta = cumulative - last_watermark
           ├─► carry += delta
           ├─► follow_ups_due = int(carry / min_order_size)
           ├─► _create_partial_fill_follow_up() → creates stealth child(ren)
           └─► _save_partial_fill_progress()   → persists new watermark to DB

4. Order reaches terminal status
   └─► process_user_order(status=FILLED|CANCELLED|FAILED)
       └─► _finalize_partial_fill_progress(client_order_id, "FINALIZED"|"CANCELLED")
           ├─► removes from _partial_fill_state (in-memory)
           ├─► marks DB row terminal
           └─► releases per-order lock map entry
```

---

## Enabling Partial Fills on an Order

### Via Dashboard UI (recommended)

Send `allow_partial_fills: true` in the `create_stealth_order` WebSocket message:

```json
{
    "type": "create_stealth_order",
    "order": {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": 0.10,
        "limit_price": 95000.00,
        "reveal_condition": {
            "type": "price",
            "direction": "below",
            "price_threshold": 95000.00,
            "hold_duration_seconds": 5
        },
        "target_movement": 0.002,
        "target_movement_type": "P",
        "max_order_replacements": 10,
        "allow_partial_fills": true
    }
}
```

### Via Python (programmatic)

```python
stealth_order_id = engine.stealth_order_bridge.create_stealth_order(
    product_id="BTC-USDC",
    side="BUY",
    total_size=0.10,
    limit_price=95000.00,
    reveal_condition={
        "type": "price",
        "direction": "below",
        "price_threshold": 95000.00,
        "hold_duration_seconds": 5,
    },
    target_movement=0.002,
    target_movement_type="P",
    max_order_replacements=10,
    allow_partial_fills=True,   # ← opt-in
)
```

### What Happens Next

1. `insert_order_parent(allow_partial_fills=True)` writes `TRUE` to the `order_parent` table.
2. On the first OPEN WebSocket event where `cumulative_quantity > 0`, the engine initialises
   a watermark entry for this order.
3. On every subsequent OPEN/UPDATE event it advances the watermark and creates follow-up
   stealth orders when `carry >= min_order_size`.

---

## Minimum Order Size (`min_order_size`)

The system reads `base_increment` from `orderbook.product[product_id]` at runtime:

```python
def _resolve_min_order_size(self, product_id: str) -> float:
    product_meta = self.orderbook.product.get(product_id, {})
    return safe_float(product_meta.get("base_increment"), default=0.0)
```

If `base_increment` is `0.01`, then a fill of `0.025` accumulates a carry of `0.025`,
spawns **2** follow-ups of `0.01` each, and carries `0.005` forward to the next event.

---

## Carry Accumulator

Sub-minimum fills accumulate in a `carry_remainder_qty` field rather than being discarded.
This ensures no filled quantity is silently lost between follow-up thresholds.

```
Event 1: fill 0.007  →  carry = 0.007  (below 0.01 min)
Event 2: fill 0.006  →  carry = 0.013  →  1 follow-up (0.01),  carry = 0.003
Event 3: fill 0.009  →  carry = 0.012  →  1 follow-up (0.01),  carry = 0.002
```

---

## Audit Trail

Every watermark advance and terminal transition emits an event to `order_event_stream`:

| `event_type`                         | `source_channel`                   | When                                         |
|--------------------------------------|------------------------------------|----------------------------------------------|
| `partial_fill_detected`              | `order_engine_open_handler`        | First fill for this order                    |
| `partial_fill_progress_updated`      | `order_engine_open_handler`        | Every OPEN/UPDATE with new delta             |
| `partial_fill_follow_up_queued`      | `order_engine_open_handler`        | When ≥1 follow-up is created                 |
| `partial_fill_below_min_accumulated` | `order_engine_open_handler`        | Delta received but carry still below minimum |
| `partial_fill_finalized`             | `order_engine_terminal_handler`    | FILLED or CANCELLED terminal                 |

All types and channels are enum-backed (`EventStreamType`, `EventSourceChannel` in `core/enums.py`).

---

## Restart Safety

The `partial_fill_progress` table acts as a durable watermark store:

```sql
CREATE TABLE partial_fill_progress (
    client_order_id          VARCHAR PRIMARY KEY,
    parent_client_order_id   VARCHAR NOT NULL,
    product_id               VARCHAR NOT NULL,
    side                     VARCHAR NOT NULL,
    original_order_size      NUMERIC NOT NULL,
    min_order_size           NUMERIC NOT NULL,
    last_cumulative_qty_processed NUMERIC NOT NULL DEFAULT 0,
    carry_remainder_qty      NUMERIC NOT NULL DEFAULT 0,
    last_number_of_fills_seen INT NOT NULL DEFAULT 0,
    last_completion_pct_seen NUMERIC NOT NULL DEFAULT 0,
    partial_follow_ups_created INT NOT NULL DEFAULT 0,
    status                   VARCHAR NOT NULL DEFAULT 'ACTIVE',
    created_at               TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at               TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

On restart, `_hydrate_partial_fill_state_from_db()` loads all `ACTIVE` rows into
`_partial_fill_state` so the engine resumes exactly where it left off, without creating
duplicate follow-ups or missing accumulated carry.

---

## Concurrency Safety

### Per-order lock

```python
order_lock = self._get_partial_fill_order_lock(client_order_id)
with order_lock:
    # all partial-fill logic for this order runs here
```

This serialises concurrent duplicate OPEN/UPDATE events for the same order, which the
WebSocket can deliver under high load or reconnect conditions.

### Monotonic delta guard

Even if two events slip through before the lock is acquired (impossible under the lock but
defended against anyway), `resolve_partial_fill_delta()` only returns a positive delta
when `cumulative > last_watermark`. Replayed or out-of-order events produce `delta=0` and
are safely no-op'd.

### FILLED claim gate

When a FILLED event arrives, `_finalize_partial_fill_progress()` is called *before*
`handle_filled_order()`. This removes the in-memory state so any concurrent OPEN/UPDATE
still in flight will find no state and exit cleanly.

---

## Key Invariants

1. **Only root parent orders** can have `allow_partial_fills=True`. Child/follow-up orders
   always have `allow_partial_fills=False` and never spawn further partial-fill chains.

2. **Carry is never negative.** After creating `N` follow-ups the new carry is
   `carry - N * min_order_size`, which is always `[0, min_order_size)`.

3. **Replacement cap is respected.** `_create_partial_fill_follow_up()` calls
   `can_create_follow_up_order()` and caps `units_to_create` at
   `remaining_replacements`. If the cap is exhausted, carry is not consumed and
   the follow-up is silently skipped (logged at INFO level).

4. **Follow-ups are stealth children.** Every partial-fill follow-up is a hidden stealth
   order with `allow_partial_fills=False`, using the same reveal conditions and target
   movement as the original order.

---

## How to Extend Partial Fills

### Change how follow-up size is determined

`_create_partial_fill_follow_up()` in `core/order_engine.py` computes:

```python
follow_up_size = float(units_to_create * min_order_size)
```

To use a different sizing strategy (e.g., fixed dollar value, percentage of remaining
size), override this calculation. The follow-up stealth order is created via
`stealth_manager.create_follow_up_stealth_order(...)`, so any size you compute here
becomes the `total_size` of that child order.

### Change the reveal condition for follow-ups

By default, the follow-up inherits the same reveal condition and flips the price threshold
direction (`FollowUpRevealDirection.OPPOSITE`). To use a different condition:

```python
# In _create_partial_fill_follow_up(), after computing follow_up_reveal_condition:
follow_up_reveal_condition = {
    "type": "time_delay",
    "delay_seconds": 0,  # immediate
}
```

### Add a custom event_type to the audit trail

All event type strings are in `EventStreamType` (`core/enums.py`). Add a new member:

```python
class EventStreamType(str, Enum):
    ...
    PARTIAL_FILL_CUSTOM = "partial_fill_custom"
```

Then call `self.event_stream_publisher.publish_event(...)` with the new value in
`_handle_partial_fill_if_enabled()` where appropriate.

### Add a per-order threshold (minimum fill % before follow-ups start)

Add a `partial_fill_threshold_pct` field to the parent order record and persist it
alongside `allow_partial_fills`. In `_handle_partial_fill_if_enabled()`, after reading
`completion_pct`, add a guard:

```python
threshold = state.get("partial_fill_threshold_pct", 0.0)
if completion_pct < threshold:
    return  # not enough of the order has filled yet
```

### Store extra context in the watermark

`_save_partial_fill_progress()` is the single write path for all watermark advances. Add
new columns to `partial_fill_progress` in `database/order.py`, add them to
`upsert_partial_fill_progress()`, and update `_hydrate_partial_fill_state_from_db()` to
restore the new fields on startup.

### Observe partial-fill events from outside the engine

Register a post-OPEN hook via `WebSocketHookRegistry`:

```python
def on_partial_fill(order: dict) -> None:
    # Called for every OPEN/UPDATE event
    cumulative = float(order.get("cumulative_quantity") or 0)
    if cumulative > 0:
        # custom logic here
        pass

engine.websocket_hooks.register_post_order_status("OPEN", on_partial_fill)
engine.websocket_hooks.register_post_order_status("UPDATE", on_partial_fill)
```

Or subscribe to the `order_event_stream` table directly — all partial-fill events are
written there with `trigger_type`, `source_channel`, `client_order_id`, and full payload.

---

## Relevant Files

| File | Role |
|------|------|
| `core/order_engine.py` | `_handle_partial_fill_if_enabled`, `_create_partial_fill_follow_up`, `_save_partial_fill_progress`, `_finalize_partial_fill_progress`, `_hydrate_partial_fill_state_from_db`, `_get_partial_fill_order_lock`, `_resolve_min_order_size`, `_get_parent_allow_partial_fills` |
| `core/stealth_order_manager.py` | `create_stealth_order(allow_partial_fills=...)`, `create_follow_up_stealth_order(...)` |
| `database/order.py` | `create_partial_fill_progress_table`, `upsert_partial_fill_progress`, `get_all_active_partial_fill_progress`, `get_partial_fill_progress`, `finalize_partial_fill_progress`, `insert_order_parent(allow_partial_fills=...)` |
| `calculation/resolver.py` | `resolve_cumulative_filled`, `resolve_remaining_size`, `resolve_partial_fill_delta` |
| `core/enums.py` | `EventStreamType` (partial-fill event types), `EventSourceChannel` (source channel names) |
| `business/order_event_stream.py` | Table initialisation (`create_partial_fill_progress_table` called in `_initialize_table`) |
| `bridges/stealth_order_bridge.py` | Passes `allow_partial_fills` through via `**kwargs` |
| `dashboard_server.py` | `create_stealth_order` handler reads `allow_partial_fills` from WebSocket payload |
| `tests/unit/test_partial_fill_followups.py` | Unit tests — carry math, follow-up creation, replacement cap |
| `tests/unit/test_filled_followup_dedup.py` | Concurrency dedup tests |

---

## Testing

Run partial-fill specific tests:

```powershell
python -m pytest tests/unit/test_partial_fill_followups.py -v
python -m pytest tests/unit/test_filled_followup_dedup.py -v
```

Run full suite to confirm no regressions:

```powershell
python -m pytest tests/ -q --ignore=tests\test_lot_tracking_integration.py
```
