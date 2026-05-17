# Bridge and Hook Agent

## Owns

- `bridges/*`
- `integration/*`
- `business/event_processor.py`

## Canonical Path

Bridges coordinate loops and adapters. Hook registries fan out lifecycle events.
Domain behavior remains in its owner module.

## Must Not Do

- Do not recreate deleted pass-through orchestrator/facade layers.
- Do not dispatch hooks inside lock-critical sections unless the existing module
  already documents that ordering.
- Do not add bridge methods that are not exercised by a real caller or test.

## Focused Tests

```powershell
pytest tests/integration/test_bridges.py tests/regression/test_dashboard_move_revealed_handler.py -v --tb=short
```

