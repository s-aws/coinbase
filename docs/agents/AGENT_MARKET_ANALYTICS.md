# Market Analytics Agent

## Owns

- `market_intel/*`
- `business/market_tick_recorder.py`
- `business/market_metrics.py`

## Canonical Path

Market telemetry is read-only or analytics-oriented. It may inform dashboards
and metrics, but it does not own order mutation.

Dashboard chart surfaces are owned by `dashboard_contract`. Analytics SQL
helpers are owned by `persistence`. Coordinate with those owners for UI or DB
shape changes.

## Must Not Do

- Do not mutate trading state from cross-venue or chart signals.
- Do not crash engine loops when analytics data is missing.
- Do not bypass persistence owner for analytics table changes.

## Focused Tests

```powershell
pytest tests/regression/test_market_tick_recorder.py tests/regression/test_market_metrics_tracker.py tests/regression/test_market_chart_data.py -v --tb=short
```
