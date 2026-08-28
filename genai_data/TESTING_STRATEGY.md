# Testing Strategy

This project uses pytest with one simple default gate: the complete local
non-external suite. Focused selections are opt-in and may be run only when the
user explicitly requests them.

## Non-Negotiable Gate

For every non-agent-file change, run the complete local non-external suite. It
contains the mandatory regression directory and must exit `0` before handoff:

```powershell
pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

Exception (docs/process-only): if changes are limited to agent/context files (`AGENTS.md`, `agent.md`, `ai-context.md`, `docs/agents/*.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

## Milestone Closeout

Run the complete non-external suite sequentially. Tests frequently monkeypatch
process globals and several tests touch shared files or the test database. This
repository does not provide a parallel test runner.

## Current Test Layout

As of 2026-06-21:
- `tests/unit/`: 28 files (`test_*.py`)
- `tests/integration/`: 7 files
- `tests/regression/`: 82 files
- `tests/e2e/`: 4 files
- `tests/external/`: 1 file

## What Each Layer Covers

### Unit
Fast, isolated behavior verification.
Examples:
- orderbook and claim-ledger behavior
- fee/profit/size calculations
- fill reconciler matching logic
- stealth policy normalization
- bridge cleanup retry after bounded scheduler joins or stop exceptions

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
- runtime controller STARTING/readiness, sticky startup-pause, and
  admission/drain behavior
- startup orchestration order and originating-action rejection before readiness
- stop races across fee refresh legs, sampled dashboard status publication,
  websocket ownership, and retryable engine cleanup
- authenticated user-channel topology, connection-generation sequence fencing,
  PATCH/UPDATE pagination and live dispatch, fail-closed malformed/overflow
  handling at both queue boundaries, whole-envelope atomic admission, initial
  snapshot/bootstrap timeout, generation-drain fencing, position isolation,
  keyed per-COID FIFO, and `EXPIRED` cleanup
  (`tests/regression/test_user_channel_patch_dispatch.py`)
- dashboard handler contracts
- missed-fill reconciliation behavior

### E2E
Top-level user-message and workflow tests.

### External
Live/sandbox Coinbase contract tests (opt-in, credential-gated).

## Standard Command Set (PowerShell)

### Default local validation
```powershell
pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

### Focused runs

Do not run a single test file, a name-filtered selection, or a single test case
unless the user explicitly asks for focused validation.

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

1. Relevant new/updated tests stay simple and outcome-oriented.
2. The complete local non-external suite passes.
3. External tests run only with explicit opt-in and safe credentials/routing.
4. No focused selection or flaky retry was used to obtain a pass.

## Debugging Failed Tests

1. Use the complete-suite traceback to verify fixture assumptions and
   enum/string contracts.
2. Check whether failure is deterministic or race-related without narrowing
   the test selection unless the user approves a focused run.
3. For race failures, inspect lock scope and claim/release paths before changing
   business logic.
4. Use `genai_tools/` scripts for DB/event trace inspection when needed.

---

Last updated: 2026-08-28
