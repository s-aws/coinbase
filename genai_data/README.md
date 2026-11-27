# GenAI Data Directory

## Purpose

`genai_data/` is the versioned documentation and agent-context set for this
repository. Versioning makes context changes reviewable and ensures normal Git
reverts restore them together with code.

This repo evolves quickly. Use these files for intended design and navigation,
then verify behavioral claims against the current code, schema, configuration,
and tests.

The living references were reconciled with the `prod` checkout on 2026-11-26.
The checkout retains current references only.

## Read Order

Follow root `AGENTS.md` and `ai-context.md`: read this overview, ID rules,
and current handoff first, then load only task-relevant living references.
The living reference set is:

- `ARCHITECTURE.md`, `MODULES.md`, `MODULE_DEPENDENCIES.md`, `DATA_MODELS.md`
- `CONFIGURATION.md`, `API_REFERENCE.md`
- `ORDER_ID_HANDLING.md`, `ENUM_USAGE_GUIDE.md`, `EXCEPTIONS.md`
- `PARTIAL_FILLS.md`, `MOVE_MECHANISM.md`, `PROFIT_TRACKING_SYSTEM.md`
- `DEBUGGING_STRATEGY.md`, `TESTING_STRATEGY.md`, `COMPREHENSIVE_TEST_SUITE.md`

Current design work is routed separately through
`design_specs/README.md`. Never bulk-load that directory: read only the spec
named for the active task. A design spec describes intended change and cannot
establish current runtime behavior.

Agent process files:
- `AGENT_CONSISTENCY_PROTOCOL.md`
- `agent_state.md`
- `AGENT_HANDOFF_TEMPLATE.md`

## System Snapshot

This is a multithreaded Coinbase trading engine with:
- Instance-owned authenticated feed sequencing and bounded keyed dispatch
  (`core/user_feed_processor.py`).
- Parent/child order lifecycle management under a strict flat hierarchy.
- Stealth orders with condition-based reveal, anchor repricing/rearm, manual Rehide, intentional Cancel, and move-revealed flows.
- Runtime lifecycle control (`STARTING`, `RUNNING`, transitional `PAUSING`, `PAUSED`, `DRAINING`, `STOPPED`) via `core/runtime_controller.py`.
- Startup and periodic reconciliation against exchange truth (`core/startup_reconciler.py`, `core/periodic_reconciler.py`).
- Fill ledger + cross-source fill reconciliation (`business/fill_ledger.py`, `business/fill_reconciler.py`).
- Dashboard WebSocket server (`dashboard_server.py`) plus browser/terminal consumers.
- Market telemetry for slide calibration and charting (`market_tick`, `market_candle_1m`, `database/*_helpers.py`).
- Optional cross-venue intelligence (`market_intel/*`, `ui_console.py`).

## Stealth Orders in One Paragraph

A stealth order is a local execution plan, not a normal exchange order. It may stay off-exchange until its reveal condition, profitability gate, sizing strategy, and pricing policy allow a placement. Once revealed, the live Coinbase placement is tracked separately from the logical `stealth_order_id`, which allows audited move/reprice/cancel-reentry behavior while preserving the original stealth identity. Confirmed zero-fill rearm returns the same order to hidden evaluation. Intentional Cancel instead stops new triggers and follow-ups while retaining unresolved exposure until confirmation. New-child price retreat is a RepricingPolicy helper; same-side hidden-order retreat and distance-based cancel/re-entry are absent here.

## Non-Negotiable Invariants

- Internal tracking uses `client_order_id`; `order_id` is exchange-facing only.
- Child orders always link to the original parent (flat hierarchy).
- Children are independent execution units, not independent strategy
  definitions; editable strategy authority remains at the flat-chain root.
- Stealth local state must match live exchange reality: hidden/pending/triggered orders have no active Coinbase placement; revealed orders may have one until cancellation, fill, move/reprice, or reconciliation accounts for it. Intentional local CANCELLED is an automation stop and may retain pending exchange exposure.
- Use enums from `core/enums.py`, not ad hoc strings.
- Respect thread-safety boundaries and existing lock ownership.
- Follow the validation gate in root `AGENTS.md`.

## Main Runtime Entry Points

- `main.py` - sole process composition root; loads settings and explicitly
  wires the REST adapter, shared orderbook, dashboard transport, stealth
  bridge/manager, Execution Core facade, order engine, runtime controller, and
  reconcilers.
- `scripts/validate_release.sh` - clean-worktree full-suite, graph, and diff
  gate with no live/runtime mutation.
- `scripts/deploy_runtime.sh` - foreground deployment owner that validates the
  release, bootstraps a fresh trading database, launches `main` paused, and
  proves dashboard health before waiting on the engine.
- `scripts/bootstrap_runtime_database.sh` - guarded operator entry point for
  read-only runtime identity/fresh-state validation and database-only schema
  deployment before `main.py`; market telemetry may remain.
- `database/schema.py` - canonical additive runtime-schema implementation and
  fresh-state/required-table verification shared by deployment, test
  provisioning, and destructive reset recreation.
- `dashboard_server.py` - embedded WebSocket state hub and operator command
  transport; it receives runtime dependencies from `main.py` and is not a
  standalone process entrypoint.
- `core/order_engine.py` - event ingestion, order lifecycle, follow-up logic.
- `core/execution_core.py` - transport-neutral application shell. Its current
  stage exposes typed runtime status/pause/resume and detached active stealth
  queries; originating commands remain unavailable until atomic admission is
  implemented in a separately approved stage.
- `core/user_feed_processor.py` - private-feed generations, reduction,
  backpressure, per-order FIFO dispatch, and runtime metrics.
- `core/stealth_order_manager.py` - stealth lifecycle and reveal/reprice/move logic.
- `bridges/stealth_order_bridge.py` - evaluation and DB reconciliation loops.

## UI and Ops Entry Points

- Browser UIs: `ui_stealth_orders_manager.html`, `ui_slide_calibration_chart.html`, `ui_stealth_repricing_chart.html`, `ui_order_span_builder.html`, `ui_hotpoint_manager.html`, `ui_spread_monitor.html`.
- Terminal UI: `ui_console.py`.
- Risk utility script: `__dangerous_delete_all_tables__.py` (destructive manual
  reset only). Its recreation phase delegates to `database/schema.py`; it does
  preserve the existing best-effort Coinbase candle backfill afterward, whose
  failures may leave optional history incomplete.

## Quick Troubleshooting Pointers

- Order ownership or linkage confusion: see `ORDER_ID_HANDLING.md`.
- Runtime pause/drain behavior: see `ARCHITECTURE.md` and `API_REFERENCE.md` admin messages.
- Fill mismatches or missed fills: see `ARCHITECTURE.md` reconciliation section and `DEBUGGING_STRATEGY.md`.
- Dashboard request/response mismatch: see `API_REFERENCE.md` message contract tables.
- Stealth behavior summary: see `ARCHITECTURE.md`, `DATA_MODELS.md`, and `API_REFERENCE.md`.
- Test triage and required commands: see `TESTING_STRATEGY.md`.
- Module ownership, allowed dependency direction, and frozen architectural
  debt: see `MODULE_DEPENDENCIES.md`.

## Documentation Scope

The living references above describe this checkout. Current design specs may
describe proposed or partially implemented work when their status and authority
are explicit. A `DRAFT` authorizes no implementation; an `ACCEPTED` spec records
operator-approved intent but still does not prove current behavior. Remove
rejected or superseded specs, superseded notes, completed handoffs, and incident
reports from the active tree rather than retaining a second archive; Git history
preserves them. `genai_tools/` remains an opt-in toolbox, never implementation
authority.

API fixtures in `api_reference/` and `websocket_reference/` are stored samples,
not a guarantee of current Coinbase behavior. The code graph is checked and
rebuilt using `codex_repo_graph/ENTRYPOINT.md`.

---

Last reconciled with checkout: 2026-11-26
