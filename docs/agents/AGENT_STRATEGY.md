# Strategy Agent

## Owns

- `business/position_lot.py`
- `business/lot_builder.py`
- `business/lot_config.py`
- `business/spot_campaign.py`
- `business/spot_cost_basis.py`
- `business/spot_fill_ledger_health.py`
- `business/spot_inventory_authority.py`
- `business/spot_portfolio_sweep.py`
- `business/profit_threshold_engine.py`
- `business/order_interception_layer.py`
- `business/conditional_execution.py`
- `business/hotpoint_detector.py`
- `business/hotpoint_rate_limiter.py`
- `business/hotpoint_placer.py`
- `business/hotpoint_decay_sweeper.py`

## Canonical Path

Strategy modules decide intent. They do not grant exchange authority. The sole
Controlled-live surface is authenticated Admin API manual Spot LIMIT/GTC
place/cancel under its backend admission chain.

Spot campaign and portfolio sweep modules may plan, gate, explain, and record
USDC spot strategy intent. Their mutation modes are source-disabled and cannot
submit Coinbase orders; do not create a second spot placement engine.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not create a competing order lifecycle.
- Do not let auto-placed hotpoint orders cascade into new hotpoint triggers.
- Do not bypass rate limits or kill switches.

## Focused Tests

```powershell
pytest tests/regression/test_hotpoint_detector.py tests/regression/test_hotpoint_rate_limiter.py tests/regression/test_hotpoint_placer.py -v --tb=short
```
