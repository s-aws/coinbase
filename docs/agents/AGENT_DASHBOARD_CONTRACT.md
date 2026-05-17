# Dashboard Contract Agent

## Owns

- `dashboard_server.py`
- `order.py`
- `ui_*.html`
- `ui_console.py`
- `engine_console.py`
- dashboard contract docs

## Canonical Path

Dashboard behavior is UI payload -> `dashboard_server.py` handler -> explicit
bridge/domain method -> response/state update -> regression coverage.

## Must Not Do

- Do not implement trading lifecycle behavior in dashboard handlers.
- Do not document speculative WebSocket message types as active.
- Do not route to a bridge method that does not exist.

## Focused Tests

```powershell
pytest tests/regression/test_dashboard_move_revealed_handler.py tests/regression/test_order_span_builder_ui.py -v --tb=short
```

