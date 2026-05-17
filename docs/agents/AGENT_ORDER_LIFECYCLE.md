# Order Lifecycle Agent

## Owns

- `core/order_engine.py`
- `core/orderbook.py`
- `business/order_progress.py`
- `business/move_manager.py`

## Canonical Path

User-channel order events enter `OrderEngine`, mutate orderbook state under the
existing locks, persist deltas, and create follow-ups through the single
follow-up path.

## Must Not Do

- Do not create grandchildren. Every child points to the original root parent.
- Do not use `order_id` as an internal parent key.
- Do not implement stealth reveal, hide, reprice, or cancel/re-entry behavior.

## Focused Tests

```powershell
pytest tests/regression/test_order_id_regression.py tests/regression/test_parent_row_before_ws_delta.py tests/regression/test_replacement_slot_atomic_claim.py -v --tb=short
```

