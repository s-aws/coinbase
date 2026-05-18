# Strategy Agent

## Owns

- `business/position_lot.py`
- `business/lot_builder.py`
- `business/lot_config.py`
- `business/profit_threshold_engine.py`
- `business/order_interception_layer.py`
- `business/conditional_execution.py`
- `business/hotpoint_detector.py`
- `business/hotpoint_rate_limiter.py`
- `business/hotpoint_placer.py`
- `business/hotpoint_decay_sweeper.py`

## Canonical Path

Strategy modules decide intent. Live order placement, cancellation, and lifecycle
mutation still flow through the canonical order/stealth paths.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not create a competing order lifecycle.
- Do not let auto-placed hotpoint orders cascade into new hotpoint triggers.
- Do not bypass rate limits or kill switches.

## Focused Tests

```powershell
pytest tests/regression/test_hotpoint_detector.py tests/regression/test_hotpoint_rate_limiter.py tests/regression/test_hotpoint_placer.py -v --tb=short
```

