# GenAI Data Directory

## Purpose

`genai_data/` is the versioned documentation and agent-context set for this
repository. Versioning makes context changes reviewable and ensures normal Git
reverts restore them together with code.

This repo evolves quickly. Use these files for intended design and navigation,
then verify behavioral claims against the current code, schema, configuration,
and tests. Topical fix/completion documents may describe historical work from
another branch and are not current implementation authority.

The living references were reconciled with the `prod` checkout on 2026-10-09.
Historical summaries and designs are explicitly marked; their line numbers,
code samples, counts, completion claims, and commands are not current contracts.

## Read Order

Follow root `AGENTS.md` and `ai-context.md`: read this overview, ID rules,
and current handoff first, then load only task-relevant living references.
The living reference set is:

- `ARCHITECTURE.md`, `MODULES.md`, `DATA_MODELS.md`
- `CONFIGURATION.md`, `API_REFERENCE.md`
- `ORDER_ID_HANDLING.md`, `ENUM_USAGE_GUIDE.md`, `EXCEPTIONS.md`
- `PARTIAL_FILLS.md`, `MOVE_MECHANISM.md`, `PROFIT_TRACKING_SYSTEM.md`
- `DEBUGGING_STRATEGY.md`, `TESTING_STRATEGY.md`, `COMPREHENSIVE_TEST_SUITE.md`

Agent process files:
- `AGENT_CONSISTENCY_PROTOCOL.md`
- `agent_state.md`
- `AGENT_HANDOFF_TEMPLATE.md`

## System Snapshot

This is a multithreaded Coinbase trading engine with:
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
- Stealth local state must match live exchange reality: hidden/pending/triggered orders have no active Coinbase placement; revealed orders may have one until cancellation, fill, move/reprice, or reconciliation accounts for it. Intentional local CANCELLED is an automation stop and may retain pending exchange exposure.
- Use enums from `core/enums.py`, not ad hoc strings.
- Respect thread-safety boundaries and existing lock ownership.
- Follow the validation gate in root `AGENTS.md`. It controls over any older
  testing guidance retained in historical context files.

## Main Runtime Entry Points

- `main.py` - starts dashboard, stealth bridge, order engine, runtime controller, and reconciler.
- `dashboard_server.py` - WebSocket state hub and operator command surface.
- `core/order_engine.py` - event ingestion, order lifecycle, follow-up logic.
- `core/stealth_order_manager.py` - stealth lifecycle and reveal/reprice/move logic.
- `bridges/stealth_order_bridge.py` - evaluation and DB reconciliation loops.

## UI and Ops Entry Points

- Browser UIs: `ui_stealth_orders_manager.html`, `ui_slide_calibration_chart.html`, `ui_stealth_repricing_chart.html`, `ui_order_span_builder.html`, `ui_hotpoint_manager.html`, `ui_dashboard.html`, `ui_spread_monitor.html`.
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

The living references above describe this checkout. Historical summaries and
unimplemented designs elsewhere are retained for provenance, with a status
notice at the top. Mixed-branch API/architecture and prior agent state live in
`history/`; they do not authorize new work. `genai_tools/` remains an opt-in
toolbox, never implementation authority.

API fixtures in `api_reference/` and `websocket_reference/` are stored samples,
not a guarantee of current Coinbase behavior. The code graph is checked and
rebuilt using `codex_repo_graph/ENTRYPOINT.md`.

---

Last reconciled with checkout: 2026-10-09
