# Core Types Agent

## Owns

- `core/enums.py`
- `core/models.py`
- `core/constants.py`
- `core/exceptions.py`
- `core/__init__.py`

## Canonical Path

Shared vocabulary is defined here before behavior owners consume it.

## Must Not Do

- Do not add magic strings for statuses, policies, channels, or events.
- Do not add persisted fields without coordinating with `persistence`.
- Do not change ID semantics: `client_order_id` is internal, `order_id` is exchange-facing.

## Focused Tests

```powershell
pytest tests/unit/test_models.py tests/regression/test_exception_kwargs_signature.py -v --tb=short
```

