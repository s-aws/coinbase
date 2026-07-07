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
  explicit user request. The canonical policy lives in
  `docs/REGRESSION_PROCESS.md`.
- Do not parallelize the regression suite with threads. Use process workers
  through `tools/run_parallel_regression.py`, and mark shared-state tests
  `serial`.

## Focused Tests

```powershell
pytest tests/regression/test_db_prod_guard.py -v --tb=short
```

## Milestone Closeout Acceleration

See `docs/REGRESSION_PROCESS.md` for the canonical regression policy.

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

The runner rejects `--workers auto` and values above `4` to keep peak memory
bounded. Raise that cap only after measuring peak memory on the target host and
updating the runner, tests, and `docs/REGRESSION_PROCESS.md`. Tests that create
fixed database tables, touch fixed files, or depend on process-global state
must carry the `serial` marker. Regression files importing the full FastAPI app
factory must also stay in the serial lane because the route-model graph is
memory-heavy. The runner validates this classification before invoking pytest.
To run only the fast classification preflight:

The runner uses short tracebacks and a Windows memory-pressure guard by default.
It samples every 5 seconds and aborts on high commit pressure, high
physical-memory pressure, or low available physical memory. Preserve the
summary JSON because it includes per-lane peak memory samples and top-process
`process_memory_snapshots` captured at each lane's observed peak. If the
summary status is `memory_guard_aborted`, the closeout gate failed. Run the
stale-process checker, preserve the evidence, and reduce or split the offending
regression file before retrying. The checker also reports matched repo-owned
test workers above the default high-memory threshold before they reach the
normal stale age threshold. Do not disable the guard for normal milestone
closeout.

```powershell
python3.13 tools/run_parallel_regression.py --check-serial-classification-only
```

Use `# parallel-regression: serial-safe: <reason>` only when the static
classifier reports a false positive and the file is safe for the process
parallel lane.

