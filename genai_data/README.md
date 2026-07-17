# GenAI Data Directory

## Purpose

`genai_data/` contains expanded engineering references and historical analyses.
Current work authority is `AGENT_MVP_REBUILD_GOAL.md`, goal id
`futures_preview_acceptance_recovery_r12`,
paired with the frontend canonical goal
at `/home/developer/coinbase/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. An
individual analysis or implementation note does not become current work merely
because it lives in this directory.

Goal `futures_preview_acceptance_recovery_r12` is
`prepared_release_disabled` with alignment
`r12_separate_eligibility_and_single_use_attempt_v1`. Its source-bound
`R12_RELEASE_READY` gate remains `False`. Current work is limited to no-live
focused validation, local deployment validation, independent safety audit, and
blind contextless audit. Cycle 1 used nine authorized GETs and failed closed
before claim; the current preparation creates no additional eligibility read,
R12 claim, idempotency key, or Preview attempt. R12 remains unconsumed with nine
eligibility cycles available.

The prepared workflow separates at most ten durably counted non-attempt
eligibility refreshes from the single-use attempt. A complete refresh permits
only nine authenticated GETs across six fixed categories, excludes Futures
sweeps, and retains the exact V3 pair, `AVP-20DEC30-CDE`, one contract, and
strict `<100 / <150 / <300 USDC` caps. Only a fresh exact-V3 success plus all
validation and audits can reach one durable claim and at most one Preview.
Retries, fallbacks, redirects, submissions, and exchange mutations remain zero.
See `../docs/FUTURES_SLICE_2R12_PREPARATION.md`.

Historical goal `futures_preview_acceptance_recovery_r11` is complete with
alignment
`r11_terminal_pre_preview_v3_operator_policy_rejection` and slice status
`complete_terminal_no_retry`. R11 is terminally consumed. Its one workflow
claim stopped at `remaining_margin_validation` with fixed reason
`futures_preview_margin_windows_ambiguous`: the documented token for policy row
`1` / `retail_intraday_margin_1` was classified
`margin_window_type_documented_but_operator_rejected` under the unchanged V3
operator policy. Preview attempts: `0`. Exchange submission attempts: `0`.
All retry, fallback, redirect, Create, Cancel, Close, Reduce, and other exchange
mutation counters are zero. The terminal artifact file SHA-256 is
`effb4bd037b853e06da14a0327d71eb8104e2b7edb2f56970b4c47ef855b6061` and
its evidence SHA-256 is
`548bbb02709c70dc320219bc15520b40ed948309ad09ec0f8af8f812d63bedea`.
R11 itself grants no retry, independent successor authority, or Slice 3,
Slice 4, or Slice 5 activation. Its historical default action was
`stop_and_await_operator_direction`. R12 now exists only under the separate
prepared, source-disabled boundary above; it grants no Slice 3/4/5 activation.

Historically, goal
`futures_post_r10_preview_compatibility_and_direction_selection` completed the
prospective separation of Coinbase's official Preview wire schema from the
project's stricter V3 acceptance policy without reinterpreting immutable R10
evidence. R8 content/hash remain inaccessible. That checkpoint granted no
successor or live authority. See
`../docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md` for the source mapping,
ranked direction, and no-live closeout.

## Read Order

1. `README.md` (this file)
2. `AGENT_MVP_REBUILD_GOAL.md`
3. `ARCHITECTURE.md`
4. `ORDER_ID_HANDLING.md`
5. `MODULES.md`
6. `DATA_MODELS.md`
7. `CONFIGURATION.md`
8. `API_REFERENCE.md`
9. `DEBUGGING_STRATEGY.md`
10. `TESTING_STRATEGY.md`
11. `COMPREHENSIVE_TEST_SUITE.md`

Agent process files:
- `AGENT_CONSISTENCY_PROTOCOL.md`
- `agent_state.md` (historical M57 snapshot, not current authority)
- `AGENT_HANDOFF_TEMPLATE.md`

## System Snapshot

This is a multithreaded Coinbase trading engine with:
- Parent/child order lifecycle management under a strict flat hierarchy.
- Stealth orders with condition-based reveal, anchor repricing, cancel/re-entry, same-side post-fill retreat, and move-revealed flows.
- Runtime lifecycle control (`RUNNING`, `PAUSED`, `DRAINING`, `STOPPED`) via `core/runtime_controller.py`.
- Startup and periodic reconciliation against exchange truth (`core/startup_reconciler.py`, `core/periodic_reconciler.py`).
- Fill ledger + cross-source fill reconciliation (`business/fill_ledger.py`, `business/fill_reconciler.py`).
- Dashboard WebSocket server (`dashboard_server.py`) plus browser/terminal consumers.
- Enterprise Admin API (`api/v1/app.py`) with fail-closed auth/RBAC, durable
  idempotency/audit stores, read-only spot routes, and a generated OpenAPI
  contract at `openapi/coinbase-admin-api.yaml`. Command posture is
  route-specific: manual Spot placement can reach the shared live service only
  after exact backend admission; HTTP Spot cancel, Futures, Stealth,
  movement/reprice, campaign, and sweep command routes remain no-live or
  local-evidence boundaries. The guarded fill-follow-up trigger is a no-live local-state
  compatibility exception that can return accepted parent/child readback
  evidence after exact proof refs while Coinbase submit/cancel and live exchange
  mutation remain disallowed.
- Market telemetry for slide calibration and charting (`market_tick`, `market_candle_1m`, `database/*_helpers.py`).
- Optional cross-venue intelligence (`market_intel/*`, `ui_console.py`).

## Stealth Orders in One Paragraph

A stealth order is a local execution plan, not a normal exchange order. It may stay off-exchange until its reveal condition, profitability gate, sizing strategy, and pricing policy allow a placement. Once revealed, the live Coinbase placement is tracked separately from the logical `stealth_order_id`, which allows audited move/reprice/cancel-reentry behavior while preserving the original stealth identity. Same-side post-fill retreat is a hidden-order policy only; it moves opted-in hidden orders and must not be confused with re-hide or live-placement mutation.

## Non-Negotiable Invariants

- Internal tracking uses `client_order_id`; `order_id` is exchange-facing only.
- Child orders always link to the original parent (flat hierarchy).
- Stealth local state must match live exchange reality: hidden/pending/triggered orders have no active Coinbase placement; revealed orders may have one until cancellation, fill, move/reprice, or reconciliation accounts for it.
- Use enums from `core/enums.py`, not ad hoc strings.
- Respect thread-safety boundaries and existing lock ownership.
- For ordinary non-agent-file changes, run focused tests and validators that
  cover the changed behavior. Full `tests/regression/` is reserved for durable
  milestone closeout, public/release-candidate handoff, deployment
  approval/closeout, release-hardening closeout, Admin API/backend association
  closeout, or explicit user request. Prefer
  `python3.13 tools/run_parallel_regression.py --workers 4` for the full closeout
  gate.

## Main Runtime Entry Points

- `main.py` - starts dashboard, stealth bridge, order engine, runtime controller, and reconciler.
- `dashboard_server.py` - WebSocket state hub and operator command surface.
- `api/v1/app.py` - FastAPI Admin API app factory.
- `application/admin_api/` - shared command service, auth/RBAC, idempotency,
  approval, audit, read-service, and route-inventory modules for enterprise API
  work.
- `core/order_engine.py` - event ingestion, order lifecycle, follow-up logic.
- `core/stealth_order_manager.py` - stealth lifecycle and reveal/reprice/move logic.
- `bridges/stealth_order_bridge.py` - evaluation and DB reconciliation loops.

## UI and Ops Entry Points

- Browser UIs: `ui_stealth_orders_manager.html`, `ui_slide_calibration_chart.html`, `ui_stealth_repricing_chart.html`, `ui_dashboard.html`, `ui_spread_monitor.html`.
- Terminal UI: `ui_console.py`.
- Risk utility script: `__dangerous_delete_all_tables__.py` (destructive; use carefully).

## Quick Troubleshooting Pointers

- Order ownership or linkage confusion: see `ORDER_ID_HANDLING.md`.
- Runtime pause/drain behavior: see `ARCHITECTURE.md` and `API_REFERENCE.md` admin messages.
- Fill mismatches or missed fills: see `ARCHITECTURE.md` reconciliation section and `DEBUGGING_STRATEGY.md`.
- Dashboard request/response mismatch: see `API_REFERENCE.md` message contract tables.
- Stealth behavior summary: see `ARCHITECTURE.md`, `DATA_MODELS.md`, and `API_REFERENCE.md`.
- Test triage and required commands: see `TESTING_STRATEGY.md`.

## Documentation Scope

The read-order files above are living references and should stay synchronized
with current code. One-off analyses such as deadlock findings, enum migration
notes, prior follow-up implementation summaries, and target-movement rollout
notes are historical unless a current goal or living reference explicitly
adopts them. Broken source links inside `docs/archive/` or those historical
notes are archival evidence, not current implementation instructions.

---

Last updated: 2026-07-16
