# agent.md - Project-Specific Rules

This project is built on Windows. CRLF is the standard line ending.
CRTIICAL: For Linux, avoid formatters. Use surgical patches only.
For session entry rules and required reading order see [AGENTS.md](AGENTS.md).
For public agent ownership boundaries see `docs/agents/` and `.agents/ownership.yaml`.
For expanded local engineering context (DRY, single code path, ID discipline) see `genai_data/` when present.

This file documents constraints and references that are specific to this codebase
and not duplicated in global agent instructions.

---

## P0 - Honest Feedback, Not Engagement Optimization

The user has explicitly opted out of yes-man behavior and validation-seeking responses.
Apply to every non-trivial decision, design proposal, business idea, or "what do you think" question:

- **Lead with the disagreement, the risk, or the unflattering numbers.** Do not bury them under three paragraphs of qualifiers.
- **Compare against industry standards, named competitors, or known-better practices** when those exist.
- **Surface what the user did NOT ask** when it materially affects the answer (regulatory burden, hidden costs, distribution problems, second-order effects).
- **Recommend against** when the evidence supports it. "Don't" is a valid first word.
- **No empty validation** ("Great question!", "That's a really interesting idea!"). No softening preambles. No artificial enthusiasm.
- Honesty is **respect**, not rudeness. Stay professional, stay specific, skip the cushioning.

If a recommendation would land softer than the evidence warrants, the recommendation is wrong.

---

## Critical Design Constraint: Flat Parent-Child Hierarchy

Non-negotiable: all child orders MUST link to their original parent, never to another child.

```
Parent Order (root)
|- Child 1
|- Child 2 (created when Child 1 fills)
|- Child 3 (created when Child 2 fills)
`- Child 4

Every child points to Parent Order (root).
No grandchildren. No re-parenting.
```

### Behavior Rules
- Child fills/cancels can create follow-ups, but linkage always stays on the original parent.
- Parent cancels can execute premarked move behavior (`move_on_cancel=TRUE`).
- Cancelled parents cannot create normal children; move flow is the only replacement path after cancel.

### Why this exists
- Prevents recursive nesting and runaway graph growth.
- Keeps move semantics auditable and deterministic.
- Simplifies database and in-memory reconciliation.

### Key enforcement points
- `OrderEngine.resolve_parent_client_order_id`
- `OrderEngine.register_child_order`
- `OrderEngine.handle_cancelled_order`
- `StealthOrderManager.resolve_stealth_chain_root`

When adding order lifecycle behavior, validate flat hierarchy explicitly.

---

## Critical Design Constraint: Stealth State Must Match Exchange Reality

Stealth visibility is not just a UI label.

- `HIDDEN`, `PENDING`, and `TRIGGERED` stealth orders must not have a live resting Coinbase placement.
- `REVEALED` means a placement was submitted to the exchange and may still be live until fills, cancellation, move/reprice replacement, or reconciliation proves otherwise.
- Any feature that makes a revealed order hidden again must first cancel or otherwise account for the active exchange placement. If the exchange cancel fails, do not mark the order hidden.
- Cancel/re-entry policy is not general hide-again behavior. It applies only to no-fill revealed placements, cancels the tracked exchange placement, records `cancelled_by_policy` state, then re-enters through the existing reveal path when thresholds allow.
- The old UI "Hide" duplicate behavior is not the same contract. Do not describe cancel/re-entry or UI Hide as re-hide.

### Cancel/Re-entry / Move / Reprice Extension Checklist
- Use the existing `StealthOrderManager` mutation claim paths; do not add a parallel lifecycle implementation.
- Keep dashboard wiring complete: UI message -> `dashboard_server.py` handler -> `bridges/stealth_order_bridge.py` method -> `StealthOrderManager` method.
- Update `genai_data/API_REFERENCE.md` only for message types that are actually implemented end to end.
- Add regression tests for the real exchange-cancel boundary, bridge method presence, dashboard handler route, UI payload, and zero-fill guard.
- Keep `genai_data/API_REFERENCE.md`, `DATA_MODELS.md`, and `ARCHITECTURE.md` updated in the same change whenever stealth lifecycle behavior changes.

---

## Files Not To Edit Without Deep Understanding

- `database/order.py` - canonical schema and write paths
- `core/stealth_order_manager.py` - stealth lifecycle engine
- `bridges/stealth_order_bridge.py` - reveal/reconcile loops
- `core/order_engine.py` - central event and order lifecycle logic
- `dashboard_server.py` - dashboard message contract and broadcast state

---

## Runtime and Dashboard Surface

Dashboard transport is WebSocket at `ws://localhost:8765` via `dashboard_server.py`.

### Primary UIs and consumers
- `ui_stealth_orders_manager.html`
- `ui_slide_calibration_chart.html`
- `ui_stealth_repricing_chart.html`
- `ui_spread_monitor.html`
- `ui_dashboard.html`
- `ui_console.py` (terminal consumer of dashboard state)

### WebSocket request message types currently handled
- `admin_status`, `admin_pause`, `admin_resume`, `admin_shutdown`
- `place_order`, `cancel_order`
- `request_stealth_orders`, `create_stealth_order`, `cancel_stealth_order`
- `update_stealth_target_movement`, `update_stealth_price_threshold`
- `reprice_now_stealth_order`, `move_revealed_stealth_order`
- `request_slide_calibration_summary`, `request_market_chart_history`
- `export_active_stealth_orders`, `import_stealth_orders`
- `clear_all_stealth_orders`
- `request_parent_orders`, `create_parent_order`, `update_parent_order`, `delete_parent_order`
- `update_parent_target_movement`
- `request_products`, `update_products_list`
- `request_move_history`, `move_order`, `premark_move`
- `request_storyboard_products`, `request_investor_storyboard`
- `ping`

When extending UI behavior, update both dashboard handler logic and the corresponding docs in `genai_data/API_REFERENCE.md`.

---

## Testing Commands (PowerShell)

`pytest tests/regression/ -v --tb=short` must pass before any non-agent-file change is done.
Exception: if changes are limited to agent/context files only (`AGENTS.md`, `agent.md`, `ai-context.md`, `.agents/ownership.yaml`, `docs/agents/*.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

```powershell
# Regression - required for non-agent-file changes
pytest tests/regression/ -v --tb=short

# Full suite - recommended for major or cross-module changes
pytest tests/ -v --tb=short --cov=.

# External (Coinbase REST, sandbox credentials)
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
$env:COINBASE_USE_SANDBOX = "true"
pytest tests/external/ -v -m external

# External websocket smoke (opt-in)
$env:COINBASE_ENABLE_WEBSOCKET_EXTERNAL = "true"
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

---

## genai_tools Workflow

`genai_tools/` is gitignored and intended for temporary debugging utilities.

Use it for:
- DB state inspection scripts
- WebSocket/event trace helpers
- Replay and reconciliation probes
- Scope-creep notes when requests branch beyond immediate deliverable

Workflow:
1. Create `genai_tools/debug_<topic>.py`
2. Use it to gather evidence
3. Capture findings in code comments, commit notes, or handoff docs
4. Leave or delete tool as needed (never productionize directly from `genai_tools/`)

---

## Stack Snapshot

- Python 3.13
- Coinbase Advanced Trade API (REST + WebSocket)
- PostgreSQL (localhost/test-container patterns)
- Rich terminal UI (`ui_console.py`)
- Patterns: Bridge/Orchestrator, Repository, Strategy, Runtime state machine
