# Test and Quality Agent

## Owns

- `tests/conftest.py`
- `tests/pytest.ini`
- `tests/fixtures/*`
- test documentation and shared infrastructure

## Canonical Path

Behavior-specific tests are owned by the behavior owner. Test infrastructure and
safety guards are owned here.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not weaken DB safety guards to make a test pass.
- Do not make external/live tests part of the normal regression gate.
- Do not skip regression for non-agent-file changes.

## Focused Tests

```powershell
pytest tests/regression/test_db_prod_guard.py -v --tb=short
```

