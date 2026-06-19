# Testing Strategy

This project uses pytest with focused phase gates and full regression at
durable milestone closeout.

## Non-Negotiable Gate

For ordinary phase work, run focused tests and validators that cover the
changed behavior. For durable milestone closeout, public/release-candidate
handoff, or explicit user request, run the full regression gate:

```powershell
pytest tests/regression/ -v --tb=short
```

Must exit `0` before the milestone or release handoff is considered complete.

Exception (docs/process-only): if changes are limited to agent/context files (`AGENTS.md`, `agent.md`, `ai-context.md`, `docs/agents/*.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

## Current Test Layout

As of 2026-05-16:
- `tests/unit/`: 28 files (`test_*.py`)
- `tests/integration/`: 7 files
- `tests/regression/`: 58 files
- `tests/e2e/`: 2 files
- `tests/external/`: 1 file

## What Each Layer Covers

### Unit
Fast, isolated behavior verification.
Examples:
- orderbook and claim-ledger behavior
- fee/profit/size calculations
- fill reconciler matching logic
- stealth policy normalization

### Integration
Cross-module workflows with realistic collaboration boundaries.
Examples:
- stealth workflow integration
- anchor repricing integration
- bridge wiring and engine id workflow

### Regression (release gate)
High-risk bug prevention and invariants.
Examples include:
- ID discipline and flat hierarchy
- follow-up claim and replacement-slot race prevention
- stealth cancel/re-entry and move/reprice active-placement safety
- same-side post-fill retreat hidden-order selection, idempotency, reveal-threshold tracking, and anchor-offset persistence
- runtime controller admission/drain behavior
- dashboard handler contracts
- missed-fill reconciliation behavior

### E2E
Top-level user-message and workflow tests.

### External
Live/sandbox Coinbase contract tests (opt-in, credential-gated).

## Standard Command Set (PowerShell)

### Full regression gate
```powershell
pytest tests/regression/ -v --tb=short
```

### Full validation
```powershell
pytest tests/ -v --tb=short --cov=.
```

### Focused runs
```powershell
# Single test file
pytest tests/regression/test_cross_source_reconciliation.py -v --tb=short

# Name filter
pytest tests/regression/ -k "reprice or stealth_move" -v --tb=short
```

### External sandbox runs
```powershell
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
$env:COINBASE_USE_SANDBOX = "true"
pytest tests/external/ -v -m external
```

### External websocket smoke (explicit opt-in)
```powershell
$env:COINBASE_ENABLE_WEBSOCKET_EXTERNAL = "true"
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

## Test Environment Safeguards

`tests/conftest.py` enforces DB safety:
- defaults DB env vars to test instance (`COINBASE_DB_PORT=9876`)
- refuses localhost:5432 connections unless `ALLOW_PROD_DB=1`

`database/database.py` also refuses test-shaped direct script processes from connecting to localhost `5432` unless `ALLOW_PROD_DB=1`. This covers root-level scripts such as `test_*.py` that do not load `tests/conftest.py`.

Expected Docker mapping:
- stage/prod-like DB: `coinbase-stage-postgres` on host `127.0.0.1:5432`
- test/dev DB: `coinbase-dev-postgres` on host `127.0.0.1:9876` mapped to container port `5432`

This guard exists to prevent accidental writes to production-like local DB instances during tests. It does not make destructive SQL safe; still inspect target host/port before any reset or restore.

## When to Add Tests

- Bug fix: add a regression test that fails pre-fix and passes post-fix.
- New behavior: add unit + integration coverage.
- Message contract change: add/update regression tests for request/response payload behavior.
- Schema or persistence change: add regression coverage around migration/compatibility and lock safety.
- Stealth lifecycle change: add regression coverage for exchange-facing side effects, active placement state, mutation claims, bridge/dashboard wiring, and zero-fill/terminal-state guards.

## Stealth Lifecycle Test Checklist

For features that cancel, move, reprice, hide, cancel/re-enter, or otherwise mutate a `REVEALED` stealth order, tests should prove:
- the live exchange placement is cancelled/replaced/reconciled before local state stops being `REVEALED`;
- failed exchange cancel does not mark the order hidden or clear the active exchange pointer as if the placement were gone;
- no-fill guards prevent cancel/re-entry from hiding partially filled revealed orders;
- cancel/re-entry state blocks normal reveal until re-entry criteria are met;
- dashboard request handling calls an existing bridge/domain method;
- UI payloads and dashboard handler kwargs carry new config end to end;
- reload from `stealth_orders` restores the config/state needed after restart.

For same-side post-fill retreat, tests should prove:
- only opted-in hidden/PENDING/TRIGGERED orders with no active exchange placement can be moved;
- one nearest same-product/same-side hidden order is selected;
- BUY retreats lower and SELL retreats higher by product price ticks;
- reveal-condition price fields and pending trigger timestamps are reset with the limit;
- the filled placement id cannot apply a second retreat on retry/replay;
- cumulative `post_fill_retreat_offset` is applied to future anchor target bands.

## Pre-Merge Checklist

1. Relevant new/updated tests added.
2. `pytest tests/regression/ -v --tb=short` passes.
3. For broad changes, full suite run completed or explicitly deferred with rationale.
4. No flaky retries required to pass.

## Debugging Failed Tests

1. Re-run only the failing test with `-v --tb=short`.
2. Verify fixture assumptions and enum/string contracts.
3. Check whether failure is deterministic or race-related.
4. For race failures, inspect lock scope and claim/release paths before changing business logic.
5. Use `genai_tools/` scripts for DB/event trace inspection when needed.

---

Last updated: 2026-05-16
