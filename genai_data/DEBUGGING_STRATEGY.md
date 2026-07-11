# Debugging Strategy

This is the practical debugging workflow for the current engine.

## Core Principles

1. Reproduce first, then patch.
2. Confirm the canonical path before editing (avoid parallel fixes).
3. Preserve ID discipline (`client_order_id` internal, `order_id` exchange).
4. Treat concurrency bugs as lock/ordering bugs until proven otherwise.
5. Validate with focused tests that cover the failure before considering the
   fix complete. Reserve full regression for durable milestone closeout,
   public/release-candidate handoff, or explicit request.

## Recommended Workflow

### Step 1: Classify the incident

Common buckets:
- Parent/child linkage or replacement-slot drift
- Stealth reveal/reprice/move anomalies
- Dashboard request/response mismatch
- Fill reconciliation mismatch
- DB transaction/locking errors
- Runtime lifecycle gate behavior (pause/drain/stop)

### Step 2: Identify the canonical source of truth

- Parent/child + statuses: `order_parent` and in-memory orderbook maps
- Stealth state: `stealth_orders` + lifecycle/reveal history tables
- Fill truth: `fill_ledger` + REST historical fills
- Ownership evidence: `order_event_stream` submission rows
- Runtime state: `RuntimeController`

Do not patch using duplicated side channels.

### Step 3: Gather evidence with minimal blast radius

Use read-only probes first.

Suggested commands/scripts:
- focused SQL queries via `database/database.py`
- `genai_tools/debug_<topic>.py` scripts for controlled inspection
- dashboard websocket replay payloads from `websocket_reference/`
- targeted log context from engine payload builders

### Step 4: Verify lock and ordering assumptions

Check:
- which lock guards each mutable structure
- whether hook dispatch is inside or outside lock scope
- whether per-COID serialization is required for the path
- whether claim ledger state (`processing`/`done`) can block retries

Concurrency regressions often come from valid local code that violates global lock order.

### Step 5: Patch only the canonical path

Examples:
- Follow-up dedupe issue: patch claim/replacement logic in `OrderEngine`, not UI handler logic.
- Stealth move/reprice race: patch mutation claim/release flow in `StealthOrderManager`.
- Missed-fill false positives: patch ownership partitioning in reconciler path, not ad hoc filters.

### Step 6: Add or update regression coverage

Target the exact failure mode.
Prefer extending existing focused tests in:
- `tests/regression/`
- `tests/integration/`

### Step 7: Run required validation

Run the focused tests that cover the patched failure mode. For durable
milestone closeout, public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or explicit request, run the full regression gate:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

For broad changes:
```powershell
pytest tests/ -v --tb=short --cov=.
```

## High-Value Debug Anchors

- `core/order_engine.py`
  - `process_user_order`
  - `_ensure_order_parent_row_exists`
  - follow-up creation/claim paths
  - partial-fill delta and carry handling

- `core/stealth_order_manager.py`
  - `build_reveal_execution_plan`
  - `reveal_order_slice`
  - `process_anchor_repricing_for_product`
  - `build_stealth_move_plan` / `execute_stealth_move`

- `core/startup_reconciler.py`
  - drift classification
  - missed-fill audit ownership partition

- `database/order.py`
  - schema and canonical writes

- `dashboard_server.py`
  - message handlers and response payloads

## Common Failure Patterns and Fast Checks

### Symptom: duplicate follow-up children
Check:
- follow-up claim ledger usage
- replacement slot claim/release balance
- per-COID serialization in user order path

### Symptom: stealth root appears as external parent
Check:
- pre-registration callback from stealth manager/bridge to order engine
- root linkage resolution (`resolve_stealth_chain_root`)

### Symptom: missed-fill warnings that are not real
Check:
- whether fills are unowned (no `order_submitted/rest_submit` mapping)
- whether WS-derived pending rows exist but are not yet REST-stamped

### Symptom: pause/drain still admits new work
Check:
- request message is in originating-msg gate set
- `check_admission` is called before work begins
- category used in inflight tracking

## Using `genai_tools/` Safely

- Place temporary scripts under `genai_tools/`.
- Keep scripts focused and disposable.
- Never promote temporary scripts directly into production modules.
- Document findings in commit notes or updated docs.

## What Not To Do

- Do not fix symptoms in multiple modules for the same behavior.
- Do not bypass existing lock/claim mechanisms "just for this path".
- Do not replace enum usage with free-form strings.
- Do not change ID semantics to make one test pass.

---

Last updated: 2026-05-02
