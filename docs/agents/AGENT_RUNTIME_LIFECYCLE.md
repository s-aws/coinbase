# Runtime Lifecycle Agent

## Owns

- `main.py`
- `core/runtime_controller.py`
- `core/startup_reconciler.py`
- `core/periodic_reconciler.py`
- `logging_service.py`

## Canonical Path

Runtime state flows through `RuntimeController`. Startup and periodic exchange
truth audits flow through the reconciler modules.

## Must Not Do

- Do not admit originating work while paused, draining, or stopped.
- Do not bypass `track_inflight` for critical REST, DB, fill, or stealth work.
- Do not classify exchange ownership without submission evidence.

## Focused Tests

```powershell
pytest tests/regression/test_runtime_controller.py tests/regression/test_cross_source_reconciliation.py -v --tb=short
```

