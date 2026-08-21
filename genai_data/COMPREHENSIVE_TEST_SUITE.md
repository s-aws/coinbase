# Comprehensive Test Suite

## Overview

This repository maintains a layered pytest suite with focused phase gates and a
strict full-regression closeout gate. The suite is designed to protect
concurrency safety, ID discipline, and stealth/follow-up lifecycle behavior
while allowing rapid iteration.

## Current Inventory (2026-05-16)

- Unit test files: 28
- Integration test files: 7
- Regression test files: 58
- E2E test files: 2
- External test files: 1

## Directory Map

- `tests/unit/`
- `tests/integration/`
- `tests/regression/`
- `tests/e2e/`
- `tests/external/`

## Required Execution Policy

For ordinary non-agent-file changes, run focused tests and validators covering
the changed behavior. For durable milestone closeout, public/release-candidate
handoff, or explicit user request, run the full regression closeout gate:

```powershell
python tools/run_parallel_regression.py --workers 4
```

The helper runs non-serial regression tests with pytest-xdist process workers
and runs tests marked `serial` in a separate sequential lane. Do not use Python
threads to parallelize the regression suite.

## Suite Coverage Focus

### Unit coverage highlights
- orderbook v2 behavior and claim ledgers
- fee regime adaptation and profit validation
- size validation and increment quantization
- fill ledger append + reconciler matching logic
- condition evaluators and stealth manager helpers

### Integration coverage highlights
- stealth order workflow and bridge interactions
- anchor repricing integration (phase and regression boundaries)
- engine ID workflow and order processing interactions

### Regression coverage highlights
- flat hierarchy guarantees
- order id/client order id discipline
- follow-up dedupe and replacement-slot race prevention
- partial-fill atomic claim behavior
- runtime controller pause/resume/drain correctness
- cross-source reconciliation and ownership partitioning
- DB cursor thread-safety guarantees
- DB production-guard behavior for pytest and direct test-shaped scripts
- stealth cancel/re-entry policy, same-side post-fill retreat, UI payloads, and active-placement safety

### E2E coverage highlights
- top-level trading workflow traces
- user-message order flow traces

### External coverage highlights
- sandbox Coinbase REST contract checks
- optional live websocket smoke (opt-in marker path)

## Command Reference

### Full regression closeout gate
```powershell
python tools/run_parallel_regression.py --workers 4
```

### Full suite
```powershell
pytest tests/ -v --tb=short --cov=.
```

### Examples of focused runs
```powershell
pytest tests/unit/test_orderbook_v2.py -v --tb=short
pytest tests/integration/test_stealth_order_workflow.py -v --tb=short
pytest tests/regression/test_runtime_controller.py -v --tb=short
```

### External sandbox
```powershell
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
$env:COINBASE_USE_SANDBOX = "true"
pytest tests/external/ -v -m external
```

## Reliability and Safety Features

- strict marker enforcement (`tests/pytest.ini`)
- short traceback mode for fast triage (`--tb=short`)
- test DB safety guard in `tests/conftest.py` to prevent accidental prod DB writes
- direct test-process DB guard in `database/database.py`
- deterministic behavior checks for race-condition fixes

## Adding New Coverage

When adding code:
1. Add unit tests for pure logic.
2. Add integration tests for multi-module flows.
3. Add regression tests for bug classes or invariants that could recur.
4. Update this file if a new test domain or major category is introduced.

## Operational Checklist Before Merge

1. Focused tests and validators for the changed behavior pass.
2. Full regression passes when the change is a durable milestone closeout,
   public/release-candidate handoff, deployment approval/closeout,
   release-hardening closeout, Admin API/backend association closeout, or
   explicit user request.
3. New tests cover the changed behavior and failure mode.
4. No unexplained flaky failures.
5. External tests run when live/sandbox exchange-facing behavior changed and
   the run was explicitly enabled.

---

Last updated: 2026-05-16
