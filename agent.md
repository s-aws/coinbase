# agent.md - Project-Specific Rules

For session entry rules and required reading order see [AGENTS.md](AGENTS.md).
For canonical engineering principles (DRY, single code path, ID discipline) see `genai_data/`.

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

## Files Not To Edit Without Deep Understanding

- `database/order.py` - canonical schema and write paths
- `core/stealth_order_manager.py` - stealth lifecycle engine
- `bridges/stealth_order_bridge.py` - reveal/reconcile loops
- `core/order_engine.py` - central event and order lifecycle logic
- `dashboard_server.py` - dashboard message contract and broadcast state

---

## Runtime and Dashboard Surface

Dashboard transport is plain WebSocket via `dashboard_server.py`.
The supported process entrypoint is `python -m main`; `dashboard_server.py`
does not construct or run a partial standalone runtime. `main()` loads
`DASHBOARD_SERVER_HOST` (fallback `HOSTNAME`, then `localhost`) and integer
`DASHBOARD_SERVER_PORT` (default `8765`) and passes them explicitly to
`start_dashboard_server()`.
`run_websocket_server()` called directly still defaults to `localhost:8765`.
Client URLs are selected separately. See `genai_data/CONFIGURATION.md` for
listener precedence and browser endpoint limits. The operator API is
unauthenticated, so bind explicitly to loopback for local-only access.

### Primary UIs and consumers
- `ui_stealth_orders_manager.html`
- `ui_order_span_builder.html`

### Operator protocol

The transport accepts only the versioned JSON-RPC methods in
`core.enums.OperatorRpcMethod`, validated against
`operator_api/schema.json`. Every client request supplies a canonical UUID
correlation ID and receives one terminal response. Server projections use
`OperatorNotificationMethod`; legacy ad-hoc `type` messages, batches, and
client notifications are unsupported. Current clients must complete
`v1.session.bootstrap` before mutations. See `genai_data/API_REFERENCE.md`.

Hotpoint replication is enabled only by the per-strategy
`enable_hotpoint_replication` field in the two creation UIs. There is no
global Hotpoint kill switch or separate manager page.

When extending UI behavior, update both dashboard handler logic and the corresponding docs in `genai_data/API_REFERENCE.md`.

---

## Testing Commands (Linux/Bash)

The complete local non-external suite is the default validation for every
non-agent-file change; it includes the mandatory regression gate. Focused test
files, name filters, and single-test selections must not be run unless the user
explicitly requests them.
Exception: if changes are limited to agent/context files only (`AGENTS.md`, `agent.md`, `ai-context.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

```bash
# Default local validation (includes regression; excludes opt-in external tests)
./scripts/run_tests.sh

# External (Coinbase REST, sandbox credentials)
export COINBASE_API_KEY="..."
export COINBASE_API_SECRET="..."
export COINBASE_USE_SANDBOX="true"
./.venv/bin/python3.14 -m pytest tests/external/ -v -m external

# External websocket smoke (opt-in)
export COINBASE_ENABLE_WEBSOCKET_EXTERNAL="true"
./.venv/bin/python3.14 -m pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

---

## genai_tools Workflow

Human-authored source in `genai_tools/` is versioned so diagnostic methods are
reviewable and revertible. Generated output, database/schema dumps, browser
profiles, test-temporary directories, captured account data, and credential
helpers remain ignored.

The directory is an opt-in toolbox, not required reading or implementation
authority. A tracked script may be historical, stale, destructive, or capable
of live exchange/database mutation. Inspect the named file and obtain any
required operator authorization before running it; presence in Git is not
approval to execute it.

Use it for:
- DB state inspection scripts
- WebSocket/event trace helpers
- Replay and reconciliation probes
- Scope-creep notes when requests branch beyond immediate deliverable

Workflow:
1. Create `genai_tools/debug_<topic>.py`
2. Use it to gather evidence
3. Capture findings in code comments, commit notes, or handoff docs
4. Keep and version it only when it is reusable and reviewed; otherwise delete it
5. Never productionize directly from `genai_tools/`

---

## Stack Snapshot

- Python 3.14
- Coinbase Advanced Trade API (REST + WebSocket)
- PostgreSQL (localhost/test-container patterns)
- Browser operator UIs (plain HTML/JavaScript)
- Patterns: Bridge/Orchestrator, Repository, Strategy, Runtime state machine
