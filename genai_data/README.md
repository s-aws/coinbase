# GenAI Data Directory

## Purpose

`genai_data/` is the canonical documentation set for this repository.
Use it as the source of truth when implementing, debugging, or reviewing changes.

This repo evolves quickly; these docs are aligned to the codebase as of 2026-05-16.

## Read Order

1. `README.md` (this file)
2. `ARCHITECTURE.md`
3. `ORDER_ID_HANDLING.md`
4. `MODULES.md`
5. `DATA_MODELS.md`
6. `CONFIGURATION.md`
7. `API_REFERENCE.md`
8. `DEBUGGING_STRATEGY.md`
9. `TESTING_STRATEGY.md`
10. `COMPREHENSIVE_TEST_SUITE.md`

Agent process files:
- `AGENT_CONSISTENCY_PROTOCOL.md`
- `agent_state.md`
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
  contract at `openapi/coinbase-admin-api.yaml`. Mutating HTTP routes currently
  return HTTP `501` / `not_implemented` and do not call Coinbase.
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
  milestone closeout, public/release-candidate handoff, or explicit user
  request. Prefer `python tools/run_parallel_regression.py --workers 4` for the
  full closeout gate.

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

The files listed above are living docs and should stay synchronized with current code.
Root-level one-off incident notes and postmortems are historical artifacts unless explicitly updated.

---

Last updated: 2026-05-16
