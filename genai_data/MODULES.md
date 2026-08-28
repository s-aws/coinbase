# Modules Reference

This file maps current code ownership by module.
Use it to find the single canonical behavior path before editing.

## Quick Lookup by Task

- Engine lifecycle and event processing: `core/order_engine.py`
- Stealth order lifecycle/repricing/cancel-reentry/move: `core/stealth_order_manager.py`
- Runtime pause/resume/drain state: `core/runtime_controller.py`
- Exchange-vs-local reconciliation: `core/startup_reconciler.py`, `core/periodic_reconciler.py`
- Parent/child and stealth DB schema: `database/order.py`
- Dashboard request handlers/state broadcast: `dashboard_server.py`
- Fill ledger + reconciliation: `business/fill_ledger.py`, `business/fill_reconciler.py`
- Per-snapshot fill progress deltas: `business/order_progress.py`
- Size/profit/price calculation helpers: `calculation/*`
- Cross-venue signal aggregation: `market_intel/*`

## Root Entry Points

### `main.py`
Bootstraps:
- initial non-admitting runtime state and optional startup-pause latch
- stealth bridge
- order engine
- ordered runtime stop hooks and lock-free signal intent before hydration
- passive stealth hydration before dashboard exposure
- dashboard server while admission remains `STARTING`
- startup reconciliation
- periodic reconciler
- post-worker readiness publication

### `dashboard_server.py`
WebSocket server for operator commands and state broadcasts.
Owns message contract for browser and terminal UIs.

### `ui_console.py`
Terminal dashboard consumer of `state_update` broadcast.
Can display cross-venue metrics using `market_intel` and external ws feeds.

## `core/` (Engine and Domain State)

### `core/order_engine.py`
Primary runtime engine.
Responsibilities:
- websocket event fan-out and dedup integration
- bounded ticker-ingress recovery with newest-envelope retention, inherited
  per-product continuity-loss counts, and Coinbase envelope-time forwarding
- parent/child lifecycle updates
- follow-up creation (filled/cancelled and partial-fill paths)
- fill progress delta ingestion and persistence fan-out
- ownership classification (`local`, `external`, `unknown`)
- dashboard status/ticker/log broadcasts
- atomic RuntimeController admission for worker-originated hotpoint placement
- one-shot DB/REST preparation outside the lifecycle lock, bounded worker
  publication serialized against cooperative stop, and partial-start cleanup
  before readiness
- lifecycle-consistent dashboard status publication and per-worker websocket
  disconnect ownership
- startup-conditional early drain quiesce, preserving fully started fill/event
  workers until stealth bridge shutdown precedes full engine cleanup

### `core/stealth_order_manager.py`
Stealth order state machine.
Responsibilities:
- create/load/update stealth orders
- condition evaluation and reveal gating
- reveal execution plan generation and profitability checks
- anchor repricing policy/state normalization and application
- cancel/re-entry policy application for revealed no-fill placements
- same-side post-fill retreat for opted-in hidden orders
- move-revealed cancel-and-replace flow
- lifecycle hook dispatch and audit writes
- authoritative condition state transitions, including continuous price/spread
  hold reset and every condition type's `PENDING`/`TRIGGERED` commitment, with
  rollback/pause before lifecycle publication if a transition cannot be
  persisted
- thread-safe defensive market snapshots and post-persistence schedule
  invalidation notifications

Boundary rule: this module owns stealth lifecycle truth. Any change that makes a revealed stealth order no longer revealed must account for the live exchange placement through the existing cancel/move/reprice/reconcile paths before changing local state.

### `core/runtime_controller.py`
Runtime lifecycle gate.
Responsibilities:
- state transitions (`STARTING`, `RUNNING`, transitional `PAUSING`, `PAUSED`,
  `DRAINING`, `STOPPED`)
- sticky pause requests during startup and sole readiness completion
- admission checks for originating work
- inflight tracking for graceful drain
- atomic admission plus inflight registration for scheduler-owned reveal and
  anchor work
- atomic register/start for bounded startup components
- lock-free signal shutdown intent and shared terminal state/inflight boundary
- single-owner subsystem stop-hook orchestration and tracked immediate
  late-hook stop before terminal publication

### `core/startup_reconciler.py`
Exchange truth diff and missed-fill audit.
Responsibilities:
- open-order drift classification
- optional safe auto-heal (`RECONCILED_CLOSED`)
- historical fill audit vs local ledger
- ownership partition using `order_event_stream` submission evidence
- distinguish an explicit empty exchange order list from unavailable/malformed
  REST data, exhaust cursor pagination, and propagate failed local reads as an
  unavailable reconciliation

### `core/periodic_reconciler.py`
Background deep audit loop wrapper around startup reconciler behavior.

### `core/orderbook.py`
Thread-safe in-memory orderbook v2 with claim ledgers and legacy compatibility surface.

### `core/models.py`
Typed models and planning dataclasses.
Includes:
- `Order`, `Product`, `Position`, `Wallet`
- `RevealExecutionPlan`, `StealthMovePlan`, `StealthMoveResult`
- `RepricingPolicy`
- typed dicts (`MarketData`, `RepricingState`)

### `core/enums.py`
Canonical enum source for statuses, policies, lifecycle events, channels, and runtime states.

### `core/constants.py`
Shared constants and fee helpers (`get_derivatives_per_side_fee`,
`DEFAULT_MAX_ORDER_REPLACEMENT`, etc.). The fee helper is the canonical fixed
CDE per-contract-side resolver: settlement-confirmed BIP/default `$0.12`, with
the legacy full-size BTI/ETI/SLC/XRL `$0.27` behavior explicitly unchanged.

### `core/exceptions.py`
Custom exception hierarchy across order, stealth, DB, WS, and API domains.

## `bridges/` (Subsystem Adapters)

### `bridges/event_bridge.py`
WebSocket event dedup with atomic claim-and-mark; used by `OrderEngine.on_message`.

### `bridges/stealth_order_bridge.py`
Coordinates `StealthOrderManager` with `OrderEngine`.
Responsibilities:
- strict hydration followed by separately gated decision activation after
  startup reconciliation
- product-scoped ordered ticker-event evaluation and per-order deadline routing
- continuous-hold confirmation only from ordered websocket evidence, including
  reset-on-evaluation-error and terminal latching if reset persistence fails
- committed reveal admission retries and compatibility-only condition rechecks
  at 100ms where required
- stealth DB reconciliation loop (~30s)
- market data forwarding at the front of ticker handling
- UTC-normalized Coinbase ticker event-time preservation with host-time fallback
- ingress-monotonic anchor eligibility retained through ticker queue recovery
- anchor deadline handoff to the next live ticker, with generation claims before
  invoking the canonical manager reprice path; active and worker-captured
  deadlines use the same atomic claim, with per-SID admission rechecks, atomic
  RuntimeController admission/inflight registration, and due-work retention or
  rebuilding across pause/drain
- per-SID action ownership across complete root/follow-up creation, scheduling,
  reveal/reprice/cancel, condition reset/edit, websocket exchange-ID
  enrichment, and terminal execution updates
- terminal fail-closed scheduler stop/readiness clear on worker or schedule
  failure; one diagnostic is logged and an unsafe later resume is paused again
- reveal event recording

Dashboard handlers that route through the bridge must have an explicit bridge method. Do not call manager methods from `dashboard_server.py` through a bridge method that does not exist.

### `bridges/stealth_event_deadline_scheduler.py`
Manager/DB/REST-independent scheduling primitive. Owns one condition-protected
bounded market FIFO and one monotonic deadline heap keyed by
`(stealth_order_id, StealthWakePurpose, generation)`. Reschedule/invalidate
advances the generation; captured stale work must recheck ownership before it
can act. Due deadlines have priority over the bounded one-event-at-a-time
market dispatch. A live ticker may atomically claim a due active or
worker-captured anchor wake from this same heap; this is not a parallel timer.
Overflow recovery remains within the configured queue bound by using one
aggregate continuity boundary with exact per-product loss counts. The event's
intrinsic snapshot flag, not its opaque payload, identifies a retained ticker.
The heap is disposable derived state, never lifecycle truth.

> **Removed 2026-05-04:** `bridges/engine_orchestrator.py`
> (`OrderEngineOrchestrator`), `bridges/calculator_bridge.py`,
> `bridges/processor_bridge.py`. Strangler-fig scaffolding from the v2
> `OrderEngine` refactor; the migration was complete and the wrappers
> were unused (orchestrator was a 250-line pass-through facade with one
> live one-line method). `main.py` now owns reconciliation and readiness,
> then calls `engine.run_forever()` with the readiness callback.
> `business.OrderCalculator` and `business.OrderProcessor`
> were also removed later the same day after audit confirmed they had
> zero production callers once the bridges were gone.
> `business.EventProcessor` survives — it backs the live `EventBridge`.

## `business/` (Business Logic)

### Fill and Reconciliation
- `business/order_progress.py`: per-order cumulative watermark and delta derivation.
- `business/fill_ledger.py`: append-only fill ledger repository.
- `business/fill_reconciler.py`: WS-derived vs REST fill matching and status stamping.

### Order Lifecycle and Strategy
- `business/event_processor.py`
- `business/move_manager.py`
- `business/conditional_execution.py`

### Stealth and Profitability
- `business/stealth_condition_evaluator.py`
- `business/stealth_reveal_strategy.py`
- `business/cancel_reentry_policy.py`
- `business/profit_threshold_engine.py`
- `business/post_fill_hook.py`

`business/cancel_reentry_policy.py` is intentionally pure: it returns `hold`, `cancel`, or `reenter`. Exchange cancel/place side effects remain in `StealthOrderManager`.

### Telemetry and Metrics
- `business/market_tick_recorder.py`
- `business/market_metrics.py`

### Lot/Position Models
- `business/position_lot.py`, `business/lot_builder.py`, `business/lot_config.py`

## `calculation/` (Pure or Mostly-Pure Calculation Helpers)

- `calculation/resolver.py`: normalize product type, resolve sizes/sides/counters.
- `calculation/formatter.py`: `safe_float`, increment quantization/formatting.
- `calculation/size_validation.py`: size quantize + minimum checks.
- `calculation/profit_validator.py`: profitability checks with product-type and fee context.
- `calculation/fee_manager.py`: owns separate immutable SPOT/CBE and
  FUTURE/EXPIRING/FCM transaction-summary caches, atomic public fee quotes,
  maker selection only for `post_only=True`, taker selection otherwise, and
  adaptive regime multipliers that cannot discount the selected exchange rate.
  Explicit product-type hints and canonical product-id resolution select the
  same schedule and multiplier within each quote.
- `calculation/price_camouflage.py`: deterministic round-number price nudging.

## `data/` (State and Repository Abstractions)

- `data/state_manager.py`: DI-oriented state manager abstraction.
- `data/order_inventory.py`: aggregate order/stealth inventory with lifecycle hook integration.
- `data/repositories/order_repository.py`: repository interface.
- `data/repositories/postgres_order_repository.py`: PostgreSQL repository implementation.

## `database/` (Schema and SQL Helpers)

### `database/database.py`
`PostgresDB` connection manager with serialized cursor access.

### `database/order.py`
Canonical schema and write/read functions for core trading tables.

### Dashboard and Analytics helpers
- `database/order_dashboard_helpers.py`
- `database/slide_calibration_helpers.py`
- `database/market_chart_helpers.py`
- `database/market_candle_store.py`

## `external/` (Exchange and External Feed Clients)

- `external/coinbase_client.py`: Coinbase REST wrapper. Its
  `get_transaction_summary(product_type, contract_expiry_type, product_venue)`
  maps canonical enums to the real
  `/api/v3/brokerage/transaction_summary` query parameters.
- `external/coinbase_websocket.py`: Coinbase websocket wrapper.
- `external/binance_perp_ws.py`, `external/bybit_perp_ws.py`, `external/okx_swap_ws.py`: external venue feed clients.

## `genai_tools/` (Reviewed Operator Diagnostics)

- `genai_tools/check_live_fee_tier.py`: read-only one-shot comparison of raw
  filtered SPOT/CBE and FUTURE/EXPIRING/FCM summaries with FeeManager's public
  snapshots and post-only maker/non-post-only taker quotes. It displays source,
  pricing tier, cost-plus state, and fixed CDE fee scope without reading private
  cache globals or modifying the database.

## `integration/` (Hook Registries)

- `integration/websocket_hooks.py`
- `integration/fill_event_hooks.py`
- `integration/order_placement_hooks.py`
- `integration/order_state_hooks.py`
- `integration/stealth_lifecycle_hooks.py`

> **Removed 2026-05-04:** `integration/engine_integration.py` and the
> bridge shims (`integration/calculator_bridge.py`,
> `integration/processor_bridge.py`, `integration/event_bridge.py`).
> They were duplicates of the `bridges/` package classes; only the dead
> integration-side `EventBridge` had any real code. See
> `integration/__init__.py` for full incident notes.

## `market_intel/` (Cross-Venue Intelligence)

- `market_intel/venues.py`: venue enum and product-symbol mapping.
- `market_intel/cross_venue_aggregator.py`: thread-safe ring-buffered signal aggregation.

## `websocket/`

- `websocket/on_message/user.py`: user websocket message processing helpers.
- `websocket/ticker.py`: ticker channel utilities.

## Tests by Domain

- Unit: `tests/unit/`
- Integration: `tests/integration/`
- Regression (release gate): `tests/regression/`
- End-to-end: `tests/e2e/`
- External API: `tests/external/`

---

Last updated: 2026-08-27
