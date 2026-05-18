# Persistence Agent

## Owns

- `database/*`
- `data/*`

## Canonical Path

Schema and SQL helpers live in `database/order.py`; DB access is serialized by
`PostgresDB._cursor_lock`; repository abstractions live under `data/`.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not add business decisions to SQL helper code when an engine, manager, or
  policy module owns the behavior.
- Do not bypass `PostgresDB._cursor_lock`.
- Do not add persisted enum/status strings without `core_types`.

## Focused Tests

```powershell
pytest tests/regression/test_db_cursor_thread_safety.py tests/regression/test_db_prod_guard.py tests/regression/test_reconciler_schema.py -v --tb=short
```

