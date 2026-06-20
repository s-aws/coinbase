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
- Do not run full regression by default for ordinary phases. Use focused tests
  for changed behavior and reserve full regression for durable milestone
  closeout, public/release-candidate handoff, deployment approval/closeout,
  release-hardening closeout, Admin API/backend association closeout, or
  explicit user request.
- Do not parallelize the regression suite with threads. Use process workers
  through `tools/run_parallel_regression.py`, and mark shared-state tests
  `serial`.

## Focused Tests

```powershell
pytest tests/regression/test_db_prod_guard.py -v --tb=short
```

## Milestone Closeout Acceleration

```powershell
python tools/run_parallel_regression.py --workers 4
```

Increase workers only after the split lane has passed locally. Tests that
create fixed database tables, touch fixed files, or depend on process-global
state must carry the `serial` marker.

