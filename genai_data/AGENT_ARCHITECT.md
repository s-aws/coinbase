# Architect Agent

## Role

The Architect Agent owns codebase boundaries, specialist routing, dependency
rules, and cross-agent conflict resolution.

The Architect does not own runtime behavior by default. It assigns behavior to
one specialist owner, verifies that the chosen owner is the canonical path, and
rejects changes that create duplicate implementations.

## Do Not Start Rule

Do not start implementation work when any of these are true:

- The requested behavior cannot be mapped to one primary owner.
- The change would require two competing code paths for the same behavior.
- The change mutates stealth exchange truth without a cancel, move, reprice, or
  reconcile path.
- The change uses `order_id` for internal linkage or ownership where
  `client_order_id` is required.
- The change bypasses an existing lock, claim ledger, bridge, hook registry, or
  dashboard message path.

When blocked, stop and identify the missing owner, invariant, or canonical path.

## Module Map

### Root Entry Points and Shared Files

| Path | Purpose | Primary owner |
| --- | --- | --- |
| `main.py` | Runtime bootstrap and subsystem wiring | Runtime Lifecycle Agent |
| `dashboard_server.py` | Dashboard websocket command surface and state broadcast | Dashboard Contract Agent |
| `configuration.py` | Credentials, product config loading, runtime subscriptions, REST client setup | Configuration Agent |
| `products.json` | Product catalog, increments, min sizes, product type metadata | Configuration Agent |
| `logging_service.py` | Standard logging wrapper and dashboard log backend | Runtime Lifecycle Agent |
| `order.py` | Order span creation helper routed through stealth bridge | Dashboard Contract Agent |
| `ui_*.html`, `ui_console.py`, `engine_console.py` | Browser and terminal operator surfaces | Dashboard Contract Agent |
| root `check_*.py`, `audit_*.py`, `verify_tables.py`, demo/debug scripts | Diagnostics and local operations | Ops and Diagnostics Agent |
| root historical `*.md` | Historical notes unless explicitly refreshed into `genai_data/` | Ops and Diagnostics Agent |

### Python Packages

| Package | Purpose | Primary owner |
| --- | --- | --- |
| `core/` | Engine behavior, runtime state, core models/enums, orderbook, reconciliation | Split by file; see ownership table |
| `bridges/` | Subsystem adapters and loop entrypoints between runtime surfaces | Bridge and Hook Agent |
| `business/` | Business policies, fill handling, strategies, market metrics | Split by file; see ownership table |
| `calculation/` | Pure or mostly-pure sizing, price, fee, product, and profitability helpers | Calculation Agent |
| `database/` | Canonical schema, SQL helpers, analytics DB reads/writes | Persistence Agent |
| `data/` | Repository abstractions and in-memory inventory/state helpers | Persistence Agent |
| `external/` | Coinbase REST/websocket clients and external venue websocket clients | Exchange Integration Agent |
| `integration/` | Hook registries for websocket, fills, order placement, state, stealth lifecycle | Bridge and Hook Agent |
| `market_intel/` | Cross-venue symbol mapping and signal aggregation | Market Analytics Agent |
| `websocket/` | Websocket message normalization and ticker utilities | Exchange Integration Agent |

### Reference and Test Data

| Path | Purpose | Primary owner |
| --- | --- | --- |
| `api_reference/` | Coinbase REST sample payloads | Exchange Integration Agent |
| `websocket_reference/` | Coinbase websocket sample payloads | Exchange Integration Agent |
| `tests/unit/` | Isolated unit coverage | Behavior owner, with Test Agent for infrastructure |
| `tests/integration/` | Multi-module workflow coverage | Behavior owner, with Test Agent for infrastructure |
| `tests/regression/` | Required release gate and invariant coverage | Behavior owner, with Test Agent for infrastructure |
| `tests/e2e/` | Top-level workflow coverage | Dashboard Contract Agent and Test Agent |
| `tests/external/` | Coinbase live/sandbox contract coverage | Exchange Integration Agent and Test Agent |

## Dependency Graph

This is the observed internal package graph from a repository import scan. Root
diagnostic scripts and root-level legacy tests are intentionally excluded from
the ownership model unless they are explicitly in scope.

```text
main
  -> bridges
  -> configuration
  -> core
  -> dashboard_server
  -> database
  -> logging_service

dashboard_server
  -> business
  -> calculation
  -> configuration
  -> core
  -> database
  -> logging_service
  -> order

order
  -> calculation
  -> configuration
  -> core

core
  -> bridges
  -> business
  -> calculation
  -> configuration
  -> dashboard_server
  -> database
  -> external
  -> integration
  -> logging_service

bridges
  -> business
  -> calculation
  -> configuration
  -> core
  -> logging_service

business
  -> calculation
  -> configuration
  -> core
  -> database
  -> logging_service

calculation
  -> configuration
  -> core

database
  -> configuration
  -> core
  -> logging_service

data
  -> configuration
  -> core
  -> database
  -> integration
  -> logging_service

external
  -> core
  -> market_intel

integration
  -> bridges
  -> core
  -> logging_service

ui_console
  -> core
  -> external
  -> market_intel
```

### Dependency Rules

- New shared state, statuses, event names, and policies belong in
  `core/enums.py` and typed models before callers use them.
- Bridges may coordinate loops and route calls, but domain rules belong in the
  domain owner module.
- Dashboard handlers may call bridge/domain APIs, but they must not implement
  stealth, order lifecycle, fill, or reconciliation behavior locally.
- Database modules own schema and SQL helpers, but they must not become a second
  business-rule engine.
- External clients wrap exchange APIs and payload translation. They must not
  decide local ownership, parent linkage, stealth state, or fill truth.
- The existing `core` <-> `bridges` and `core` -> `dashboard_server` coupling is
  historical. Do not expand it without an explicit refactor plan and tests.

## Ownership Areas

Each non-test file has one primary owner. A specialist may edit another owner's
file only when the change is explicitly coordinated and remains part of one
canonical behavior path.

### 1. Architect Agent

Owns:
- `genai_data/AGENT_ARCHITECT.md`
- Boundary and ownership routing decisions
- Cross-agent conflict resolution

Responsibilities:
- Assign one primary owner for each requested behavior.
- Keep boundaries small, logical, and enforceable.
- Reject duplicate implementations, speculative docs, and stale routing.
- Decide when a change needs co-review from another specialist.

Does not own:
- Runtime code behavior.
- Domain-specific tests except boundary validation.

### 2. Core Types Agent

Owns:
- `core/enums.py`
- `core/models.py`
- `core/constants.py`
- `core/exceptions.py`
- `core/__init__.py`

Responsibilities:
- Shared enums, dataclasses, constants, exceptions, and domain vocabulary.
- `client_order_id` and `order_id` vocabulary consistency.
- Cross-module model compatibility.

Must coordinate with:
- Any behavior owner that consumes a new enum, model field, or exception.
- Persistence Agent when new fields become stored schema.

### 3. Runtime Lifecycle Agent

Owns:
- `main.py`
- `core/runtime_controller.py`
- `core/startup_reconciler.py`
- `core/periodic_reconciler.py`
- `logging_service.py`

Responsibilities:
- Process bootstrap and shutdown.
- Runtime states: `RUNNING`, `PAUSING`, `PAUSED`, `DRAINING`, `STOPPED`.
- Admission gates and inflight drain tracking.
- Startup/periodic reconciliation orchestration.
- Logging infrastructure.

Must coordinate with:
- Order Lifecycle Agent for fill/order processing inflight categories.
- Stealth Lifecycle Agent for reveal/cancel/move/reprice inflight categories.
- Persistence Agent for reconciliation query changes.

### 4. Order Lifecycle Agent

Owns:
- `core/order_engine.py`
- `core/orderbook.py`
- `business/order_progress.py`
- `business/move_manager.py`

Responsibilities:
- User websocket order event ingestion after bridge dedup.
- Parent/child lifecycle and flat hierarchy enforcement.
- Follow-up order creation and replacement-slot claims.
- Partial-fill progress and per-COID serialization.
- Parent move and premark behavior.

Must coordinate with:
- Core Types Agent for statuses, directions, ownership scopes, and events.
- Persistence Agent for `order_parent`, `partial_fill_progress`, and move tables.
- Fill and Audit Agent for fill ledger and order event stream writes.
- Dashboard Contract Agent for message handlers that create, cancel, or move parent orders.

Hard boundary:
- Do not implement stealth reveal, stealth hide/cancel/re-entry, or active
  placement mutation here. That belongs to the Stealth Lifecycle Agent.

### 5. Stealth Lifecycle Agent

Owns:
- `core/stealth_order_manager.py`
- `business/stealth_condition_evaluator.py`
- `business/stealth_reveal_strategy.py`
- `business/cancel_reentry_policy.py`

Responsibilities:
- Stealth order state machine and exchange-truth invariants.
- Reveal condition evaluation and reveal execution plans.
- Anchor repricing, cancel/re-entry, move-revealed planning/execution.
- Active placement pointer truth in `anchor_repricing_state_json`.
- Follow-up stealth order creation.

Must coordinate with:
- Bridge and Hook Agent for `bridges/stealth_order_bridge.py` loop and method wiring.
- Dashboard Contract Agent for stealth websocket requests and UI payloads.
- Persistence Agent for `stealth_orders`, snapshots, reveal history, lifecycle history, and moves.
- Calculation Agent for size, price, fee, and profitability helpers.

Hard boundary:
- A revealed stealth order cannot become hidden or cancelled by local mutation
  alone. The live exchange placement must be cancelled, replaced, filled, moved,
  or reconciled closed first.

### 6. Bridge and Hook Agent

Owns:
- `bridges/event_bridge.py`
- `bridges/stealth_order_bridge.py`
- `integration/websocket_hooks.py`
- `integration/fill_event_hooks.py`
- `integration/order_placement_hooks.py`
- `integration/order_state_hooks.py`
- `integration/stealth_lifecycle_hooks.py`
- `integration/__init__.py`
- `business/event_processor.py`

Responsibilities:
- Event dedup and claim-and-mark behavior at ingress.
- Bridge loop ownership and explicit bridge method contracts.
- Hook registry APIs and dispatch ordering.
- Avoiding deadlocks by keeping hook dispatch out of lock-critical sections
  where required.

Must coordinate with:
- Order Lifecycle Agent for websocket order event processing.
- Stealth Lifecycle Agent for stealth evaluation, DB reconciliation, cancel/re-entry, and repricing loop semantics.
- Fill and Audit Agent for fill hook payloads.

Hard boundary:
- Do not recreate deleted bridge/orchestrator pass-through layers.

### 7. Dashboard Contract Agent

Owns:
- `dashboard_server.py`
- `order.py`
- `ui_*.html`
- `ui_console.py`
- `engine_console.py`
- `docs/` files that describe operator workflows
- Dashboard sections of `genai_data/API_REFERENCE.md` when explicitly in scope

Responsibilities:
- WebSocket request/response contracts.
- Operator UI payloads and state rendering.
- UI -> `dashboard_server.py` -> bridge/domain method wiring.
- JSON-safe serialization for dashboard state.
- Product-list and chart/storyboard request surfaces.

Must coordinate with:
- Stealth Lifecycle Agent for stealth message behavior.
- Order Lifecycle Agent for parent order CRUD, cancel, move, and placement behavior.
- Market Analytics Agent for chart, calibration, spread, and storyboard payloads.
- Configuration Agent for product-list update behavior.

Hard boundary:
- Dashboard code must not be the canonical implementation of trading behavior.
  It validates/routes requests and serializes responses.

### 8. Persistence Agent

Owns:
- `database/database.py`
- `database/order.py`
- `database/order_dashboard_helpers.py`
- `database/market_chart_helpers.py`
- `database/market_candle_store.py`
- `database/slide_calibration_helpers.py`
- `data/state_manager.py`
- `data/order_inventory.py`
- `data/repositories/*`

Responsibilities:
- Schema creation/migration guards and canonical SQL helpers.
- `PostgresDB._cursor_lock` and transaction safety.
- Repository interfaces and persistence adapters.
- JSONB serialization/deserialization at DB boundaries.
- Dashboard and analytics DB read helpers.

Must coordinate with:
- Core Types Agent for enum/model fields persisted to DB.
- Order Lifecycle Agent for `order_parent` and partial-fill write paths.
- Stealth Lifecycle Agent for stealth tables and active placement fields.
- Fill and Audit Agent for fill ledger, match audit, and event stream tables.

Hard boundary:
- Do not add business decisions in SQL helper code when the behavior belongs
  in an engine, manager, policy, or reconciler.

### 9. Fill and Audit Agent

Owns:
- `business/fill_ledger.py`
- `business/fill_reconciler.py`
- `business/order_event_stream.py`
- `business/post_fill_hook.py`

Responsibilities:
- Append-only fill ledger semantics.
- WS-derived vs REST-authoritative fill reconciliation.
- `derived_trade_key`, `exchange_trade_id`, and `exchange_entry_id` handling.
- Order event stream publishing and hook integration.
- Fill/audit payload shape for downstream consumers.

Must coordinate with:
- Runtime Lifecycle Agent for missed-fill audit paths in reconcilers.
- Order Lifecycle Agent for per-snapshot fill deltas.
- Persistence Agent for fill and event-stream schema.
- Bridge and Hook Agent for fill event hooks.

Hard boundary:
- Do not use exchange `order_id` as internal ownership proof. Resolve ownership
  through submission evidence and `client_order_id`.

### 10. Calculation Agent

Owns:
- `calculation/*`

Responsibilities:
- Product type resolution.
- Size validation and quantization.
- Price formatting and increment rounding.
- Fee manager and fee multiplier logic.
- Profitability checks.
- Price camouflage helpers.

Must coordinate with:
- Configuration Agent for product metadata and fee configuration.
- Stealth Lifecycle Agent for reveal/reprice profitability behavior.
- Order Lifecycle Agent for follow-up price/size decisions.

Hard boundary:
- Calculation helpers should remain pure or mostly pure. They should not place
  orders, mutate DB state, or emit dashboard responses.

### 11. Configuration Agent

Owns:
- `configuration.py`
- `products.json`
- `pyproject.toml`

Responsibilities:
- Environment variable loading and runtime subscription configuration.
- Product metadata, product ids, ticker/trading mappings.
- Package inclusion metadata.
- Local installation guidance when package layout changes.

Must coordinate with:
- Exchange Integration Agent for REST client initialization.
- Calculation Agent for precision/min-size metadata.
- Dashboard Contract Agent for product update requests.

Hard boundary:
- Do not introduce parallel product catalogs or duplicate global knobs when a
  per-order or `products.json` field is canonical.

### 12. Exchange Integration Agent

Owns:
- `external/coinbase_client.py`
- `external/coinbase_websocket.py`
- `external/binance_perp_ws.py`
- `external/bybit_perp_ws.py`
- `external/okx_swap_ws.py`
- `websocket/ticker.py`
- `websocket/on_message/user.py`
- `api_reference/`
- `websocket_reference/`

Responsibilities:
- Coinbase REST and websocket wrapper contracts.
- Exchange payload translation.
- External venue websocket feed clients.
- REST/websocket reference payloads used by tests.

Must coordinate with:
- Order Lifecycle Agent for user-channel order payload handling.
- Runtime Lifecycle Agent for connection startup/shutdown behavior.
- Market Analytics Agent for cross-venue feed consumers.

Hard boundary:
- Exchange clients do not own local lifecycle semantics, parent linkage,
  stealth status, or fill ownership classification.

### 13. Market Analytics Agent

Owns:
- `market_intel/*`
- `business/market_tick_recorder.py`
- `business/market_metrics.py`
- market/chart/slide helper behavior in `database/*` with Persistence Agent co-review
- `ui_slide_calibration.html`
- `ui_slide_calibration_chart.html`
- `ui_stealth_repricing_chart.html`
- `ui_spread_monitor.html`
- `ui_investor_storyboard.html`
- storyboard/spread dashboard artifacts

Responsibilities:
- Market tick retention and chart history.
- Market metrics windows and snapshots.
- Slide calibration summaries.
- Cross-venue premium/lead indicators.
- Analytics dashboard payloads.

Must coordinate with:
- Dashboard Contract Agent for websocket request/response surfaces.
- Exchange Integration Agent for external venue feeds.
- Persistence Agent for analytics tables and query helpers.

### 14. Profit, Lot, Hotpoint, and Conditional Strategy Agent

Owns:
- `business/position_lot.py`
- `business/lot_builder.py`
- `business/lot_config.py`
- `business/profit_threshold_engine.py`
- `business/order_interception_layer.py`
- `business/conditional_execution.py`
- `business/hotpoint_detector.py`
- `business/hotpoint_rate_limiter.py`
- `business/hotpoint_placer.py`
- `business/hotpoint_decay_sweeper.py`

Responsibilities:
- Lot tracking and profit-aware strategy helpers.
- Conditional execution wrappers.
- Hotpoint detection, rate limiting, placement, and decay behavior.
- Strategy modules that are adjacent to, but not canonical replacements for,
  order and stealth lifecycle paths.

Must coordinate with:
- Order Lifecycle Agent before any strategy places, cancels, or mutates parent orders.
- Persistence Agent for conditional and hotpoint DB fields.
- Core Types Agent for shared strategy enums.

Hard boundary:
- Strategies may decide intent, but live order lifecycle still goes through the
  canonical order/stealth paths.

### 15. Test and Quality Agent

Owns:
- `tests/conftest.py`
- `tests/pytest.ini`
- `tests/fixtures/`
- `tests/README.md`
- `tests/TEST_*.md`
- cross-suite structure and test infrastructure

Responsibilities:
- Test safety guards and DB test environment.
- Test markers and suite organization.
- Shared fixtures and test infrastructure.
- Coordinating broad validation strategy.

Notes:
- Domain-specific test files are owned by the behavior owner for that domain.
- The Test and Quality Agent can require additional tests but should not own
  production behavior.

### 16. Ops and Diagnostics Agent

Owns:
- `genai_tools/*`
- root diagnostic scripts such as `check_*.py`, `audit_*.py`, `verify_tables.py`, `debug_storyboard.py`
- destructive operational scripts such as `__dangerous_delete_all_tables__.py`
- root historical incident notes unless promoted into canonical `genai_data/`

Responsibilities:
- Temporary probes, DB inspections, replay helpers, and operational notes.
- Keeping diagnostics out of production modules.
- Marking destructive scripts clearly and requiring explicit approval before use.

Hard boundary:
- Do not productionize `genai_tools/` or diagnostic scripts directly. Extract the
  proven behavior into the proper specialist-owned module.

## Test Commands

### Required Gate

Run focused tests and validators that cover the changed behavior before
ordinary phase completion. Run the full regression gate before durable
milestone closeout, public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or explicit full-gate request:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

Regression may be skipped when the change set is limited to agent
instruction/context files and no runtime behavior changed:

```text
AGENTS.md
agent.md
ai-context.md
.agents/ownership.yaml
docs/agents/*.md
genai_data/AGENT_*.md
genai_data/agent_state.md
```

### Full Suite

Use for broad or cross-boundary changes:

```powershell
pytest tests/ -v --tb=short --cov=.
```

### Focused Commands By Area

Focused commands are the normal validation path for ordinary phase work. They
do not replace full regression when marking a durable milestone complete,
preparing public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or handling
an explicit full-gate request.

| Area | Useful focused command |
| --- | --- |
| Core order lifecycle | `pytest tests/regression/test_order_id_regression.py tests/regression/test_parent_row_before_ws_delta.py tests/regression/test_replacement_slot_atomic_claim.py -v --tb=short` |
| Stealth lifecycle | `pytest tests/regression/test_stealth_cancel_reentry.py tests/regression/test_stealth_move_revealed.py tests/regression/test_repricing_policy.py -v --tb=short` |
| Dashboard contract | `pytest tests/regression/test_dashboard_move_revealed_handler.py tests/regression/test_order_span_builder_ui.py -v --tb=short` |
| Persistence and DB safety | `pytest tests/regression/test_db_cursor_thread_safety.py tests/regression/test_db_prod_guard.py tests/regression/test_reconciler_schema.py -v --tb=short` |
| Fill/reconciliation | `pytest tests/regression/test_cross_source_reconciliation.py tests/unit/test_fill_reconciler.py tests/unit/test_fill_ledger_append_derived.py -v --tb=short` |
| Calculation | `pytest tests/regression/test_size_validation.py tests/regression/test_quantize_to_increment.py tests/regression/test_maker_taker_fee_selection.py -v --tb=short` |
| Market analytics | `pytest tests/regression/test_market_tick_recorder.py tests/regression/test_market_metrics_tracker.py tests/regression/test_market_chart_data.py -v --tb=short` |
| Hotpoint strategy | `pytest tests/regression/test_hotpoint_detector.py tests/regression/test_hotpoint_rate_limiter.py tests/regression/test_hotpoint_placer.py -v --tb=short` |
| External wrappers | `pytest tests/external/test_coinbase_api.py -v --tb=short` |

## Coding Conventions

- Use `client_order_id` for internal tracking, DB linkage, parent/child maps,
  follow-up claims, dashboard references, and reconciliation ownership.
- Use `order_id` only for exchange-facing operations and exchange-native
  evidence.
- Use enums from `core/enums.py` for statuses, policies, event names, channels,
  runtime states, and shared strategy values.
- Keep one code path per behavior. Do not add pass-through facades, fallback
  implementations, or local dashboard-only versions of domain behavior.
- Respect lock ownership:
  - `OrderEngine.orderbook_lock` guards in-memory order/parent/child mutations.
  - Per-COID handler locks serialize order-event processing.
  - `PostgresDB._cursor_lock` serializes DB cursor/transaction access.
  - `RuntimeController` locks guard state and inflight counters.
  - Hook dispatch must follow the existing lock-order guidance.
- For dashboard actions, keep the end-to-end path complete:
  UI payload -> `dashboard_server.py` handler -> explicit bridge/domain method
  -> manager/engine behavior -> response/state update -> regression coverage.
- Do not document a WebSocket message type as active unless it is implemented
  end to end.
- Do not hard-code product ids, increments, min sizes, or product types in
  strategy code. Use `products.json`, `configuration.py`, and calculation
  helpers.
- Use structured parsers and existing helpers at DB/API boundaries. Avoid ad hoc
  string parsing when a typed model, enum, or helper already exists.
- Keep temporary investigation code in `genai_tools/`. Do not promote it
  directly into production modules.
- This is a Windows 11 project. Prefer PowerShell-compatible commands in docs
  and handoffs.

## Cross-Boundary Change Rules

- Enum/model change: Core Types Agent owns first; behavior owners update callers
  after the shared vocabulary exists.
- Schema change: Persistence Agent owns table/helper changes; behavior owner
  proves the runtime path and regression coverage.
- Dashboard message change: Dashboard Contract Agent owns payload and handler;
  behavior owner owns the domain method.
- Stealth lifecycle change: Stealth Lifecycle Agent owns state semantics;
  Persistence, Dashboard, Bridge, and Calculation Agents co-review as needed.
- Exchange API change: Exchange Integration Agent owns wrapper behavior;
  lifecycle owners decide how local state reacts.
- Reconciliation/fill ownership change: Fill and Audit Agent plus Runtime
  Lifecycle Agent must agree on source-of-truth rules.

## Architect Handoff Checklist

When assigning work to a specialist, state:

1. Primary owner.
2. Files in scope.
3. Files explicitly out of scope.
4. Required coordinating owners.
5. Canonical behavior path.
6. Required focused tests.
7. Whether the full regression gate is required.

If those seven fields cannot be stated clearly, the boundary is not ready for
implementation.

---

Last updated: 2026-05-17
