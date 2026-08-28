# Comprehensive Test Suite

## Overview

This repository maintains a layered pytest suite with one complete local
non-external validation gate. The suite is designed to protect
concurrency safety, ID discipline, and stealth/follow-up lifecycle behavior
with a simple, repeatable execution policy.

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

For every non-agent-file change, run the complete local non-external suite. It
includes the mandatory regression tests and must exit `0` before handoff:

```powershell
pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

Run this suite sequentially. This repository does not provide a
parallel test runner. Do not run focused test files, name filters, or individual
test cases unless the user explicitly requests them.

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
- runtime controller STARTING/readiness, sticky startup-pause, pause/resume,
  and drain correctness
- startup admission rejection across dashboard, stealth reveal, and hotpoint
  placement origins
- stop-dominant initial fee refresh, coherent sampled dashboard status with
  stop-dominant publication, websocket disconnect ownership, and retryable
  engine cleanup
- cross-source reconciliation and ownership partitioning
- DB cursor thread-safety guarantees
- DB production-guard behavior for pytest and direct test-shaped scripts
- stealth cancel/re-entry policy, same-side post-fill retreat, UI payloads, and active-placement safety

### E2E coverage highlights
- top-level trading workflow traces
- user-message order flow traces

### Unit coverage highlights
- bridge cleanup retry after bounded scheduler joins or stop exceptions

### External coverage highlights
- sandbox Coinbase REST contract checks
- optional live websocket smoke (opt-in marker path)

## Command Reference

### Default local validation
```powershell
pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

### Focused runs

Focused selections require an explicit user request.

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

1. The complete local non-external suite passes.
2. New tests remain simple and cover the changed behavior and failure mode.
3. No focused selection or unexplained flaky retry was used to obtain a pass.
4. External tests run when live/sandbox exchange-facing behavior changed and
   the run was explicitly enabled.

---

Last updated: 2026-08-28
