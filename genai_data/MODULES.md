# Modules Reference

Reconciled with the `prod` checkout on 2026-11-27. Current source and tests
remain the evidence for runtime behavior.

This file maps current code ownership by module.
Use it to find the single canonical behavior path before editing.

## Quick Lookup by Task

- Engine lifecycle and order processing: `core/order_engine.py`
- Authenticated feed sequencing and dispatch: `core/user_feed_processor.py`
- Stealth order lifecycle/repricing/rearm/Rehide/cancel/move: `core/stealth_order_manager.py`
- Runtime pause/resume/drain state: `core/runtime_controller.py`
- Exchange-vs-local reconciliation: `core/startup_reconciler.py`, `core/periodic_reconciler.py`
- Parent/child and stealth DB definitions/persistence: `database/order.py`
- Automated release/runtime deployment entry points:
  `scripts/validate_release.sh`, `scripts/deploy_runtime.sh`
- Guarded database-only deployment entry point:
  `scripts/bootstrap_runtime_database.sh`
- Runtime schema/fresh-state/reset orchestration: `database/schema.py`
- Dashboard request handlers/state broadcast: `dashboard_server.py`
- Execution projection and hook capability contracts: `core/execution_ports.py`
- Fill ledger + reconciliation: `business/fill_ledger.py`, `business/fill_reconciler.py`
- Per-snapshot fill progress deltas: `business/order_progress.py`
- Size/profit/price calculation helpers: `calculation/*`
- Cross-venue signal aggregation: `market_intel/*`
- Enforced module zones and architectural debt budget:
  `module_boundaries.toml`, explained by `genai_data/MODULE_DEPENDENCIES.md`

## Dependency Ownership Contract

`module_boundaries.toml` is the executable ownership map for supported runtime
modules. It classifies individual modules rather than treating directories as
layers, because `core/` and `business/` currently mix multiple architectural
roles. The regression contract freezes reverse-zone import edges, actual import
cycles, broad/untyped injected capability surfaces, and dependency-obscuring
reflection. Later modular-monolith work must reduce those exact debt sets while
preserving one behavior path and the current lifecycle owner.

The checker does not import application modules. `configuration.py` is now
passive as well, but source-only inspection keeps the architecture gate
independent of environment, database, and exchange availability. The checker
does not claim to prove arbitrary runtime aliases or callbacks; new
cross-component collaboration must use a narrow annotated protocol or facade.
See `MODULE_DEPENDENCIES.md` for the zone matrix and limits.

## Root Entry Points

### `main.py`
Bootstraps:
- one immutable settings snapshot and authenticated REST adapter
- one shared `core.orderbook.OrderBook` product/position/runtime-state owner
- explicit REST, metadata, product-resolution, and position readers for
  execution, dashboard, and reconciliation consumers
- one dashboard execution projection sink and the shared WebSocket, fill,
  placement, and stealth-lifecycle hook registries
- initial non-admitting runtime state and default-on startup-pause latch
- stealth bridge
- order engine
- ordered runtime stop hooks and lock-free signal intent before hydration
- passive stealth hydration before dashboard exposure
- dashboard server while admission remains `STARTING`
- startup reconciliation
- periodic reconciler
- post-worker readiness publication

It deliberately does not create or migrate the full database schema. Normal
deployment enters through `scripts/deploy_runtime.sh`, which validates the
release, bootstraps a fresh trading database, launches this module paused, and
verifies dashboard health while remaining attached to the process.

### `dashboard_server.py`
WebSocket adapter for correlated operator JSON-RPC commands and named state
notifications. It owns explicit method dispatch for the two supported browser
UIs and the deployment healthcheck; framing and schema validation live in
`operator_api/`. Every handler result is validated against its originating
method after JSON normalization and before success emission; a contract defect
becomes one correlated indeterminate internal error rather than an untyped
success. Once that error is sent, the adapter still attempts each projection
requested by the completed handler; those attempts are independent and best
effort.
New connections remain outside all notification fanout until their bootstrap
success is on the wire, then receive targeted runtime and stealth catch-up
projections. Correlated administrative reads remain available while barred.
It is an embedded transport, not a process composition root: `main.py`
installs the shared `OrderBook`, publish interval, `ExecutionCore`, and stealth
bridge. Six originating methods are parsed into typed facade commands;
the transport does not perform its former check-then-act admission precheck.
`DashboardExecutionProjectionSink` also adapts the six established order,
position, engine-status, log, ticker, and spread publishers to the narrow
execution port; it adds no second projection path.
Direct
script execution exits with canonical
entrypoint guidance. `main()` owns environment resolution and passes the host
and port explicitly; direct `run_websocket_server()` defaults remain
`localhost:8765`. See `CONFIGURATION.md` for listener and independent client
endpoint settings.

### `operator_api/`
Transport-only JSON-RPC framing. `protocol.py` validates canonical caller UUID
IDs, method-specific object params and results, one-request envelopes, and
serializes success, structured error, and server-notification envelopes.
Notification validators support regression and future client-boundary checks
without running on every Python ticker publication. `schema.json` is the
committed Draft 2020-12 contract consumed by Python and prepared for future
generated TypeScript bindings. It owns no lifecycle, persistence, exchange, or
admission behavior.

### `configuration.py`
Passive configuration model and loader. Importing it performs no environment,
file, network, or runtime-object construction. `load_runtime_settings()` reads
the environment and `products.json` only when called by `main()`. It also owns
the immutable `RuntimeSettings`, `ProductConfiguration`, and `Subscription`
snapshots plus atomic product-cache serialization.

### `external/runtime.py`
Composition adapters for constructing the Coinbase REST wrapper and fetching
startup product/position snapshots. It owns exchange response validation but
does not retain process-global runtime state.

## `core/` (Engine and Domain State)

### `core/order_engine.py`
Primary runtime engine.
Responsibilities:
- separate public `WSClient` fan-out and single-owner private `WSUserClient`
  topology; authenticated payloads are delegated to `UserFeedProcessor` and
  remain isolated from public payload deduplication
- bounded ticker-ingress recovery with newest-envelope retention, inherited
  per-product continuity-loss counts, and Coinbase envelope-time forwarding
- one-query flat parent/child hydration with disjoint root/child maps, direct-root
  validation, and last-known-good retention on invalid snapshots
- atomic exact-placement plus durable execution-owner status projection, with
  lineage/self-ownership guards and accepted-index cross-checking; failed guards
  pause and suppress origination without suppressing factual fill/audit ingest
- follow-up creation (filled/cancelled and partial-fill paths)
- fill progress delta ingestion and persistence fan-out
- ownership classification (`local`, `external`, `unknown`)
- order/position/status/log/ticker/spread publication through an injected
  projection sink
- atomic RuntimeController admission for worker-originated hotpoint placement
- one-shot DB/REST preparation outside the lifecycle lock, bounded worker
  publication serialized against cooperative stop, and partial-start cleanup
  before readiness
- lifecycle-consistent dashboard status publication and per-worker websocket
  disconnect ownership
- explicit `EXPIRED` terminal cleanup without filled/cancelled replacement
  handlers, plus order/position failure isolation inside mixed user events
- startup-conditional early drain quiesce, preserving fully started fill/event
  workers until stealth bridge shutdown precedes full engine cleanup

The engine receives WebSocket, fill, placement, and stealth-lifecycle hook
capabilities explicitly. A deliberately isolated constructor gets stateless
no-ops; the supported `main.py` runtime injects the existing shared registries.
The engine no longer imports the dashboard or integration registry modules.

### `core/execution_ports.py`
Consumer-owned structural protocols for the projection sink and four hook
capabilities used by execution owners. It also provides stateless no-op
implementations for headless tests or deliberately isolated embedding. These
ports define only the member surface and do not change callback ordering,
locking, persistence, or exception policy.

### `core/user_feed_processor.py`
Instance-owned authenticated WebSocket pipeline.
Responsibilities:
- connection-generation and sequence fencing with fail-closed reconnect
- paginated snapshot accumulation and ordered private-envelope reduction
- old-generation lifecycle draining and stale-generation rejection
- atomic bounded admission to per-`client_order_id` FIFO lanes
- coherent feed, queue, dispatcher, bootstrap, and inflight metrics

The processor calls `OrderEngine` for order/position lifecycle behavior; it
does not own trading policy, persistence, or exchange placement.

### `core/stealth_order_manager.py`
Stealth order state machine.
Responsibilities:
- create/load/update stealth orders
- condition evaluation and reveal gating
- reveal execution plan generation and profitability checks
- anchor repricing policy/state normalization and application
- same-order zero-fill rearm for revealed repricing and manual Rehide
- durable operator stop and exchange withdrawal confirmation
- move-revealed cancel-and-replace flow
- lifecycle hook dispatch through an injected best-effort capability and audit
  writes owned by the existing subscriber
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
- one `application_command` category for atomic facade admission and drain
  accounting
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
Sole thread-safe runtime `OrderBook` implementation. It owns the installed
product catalog, ticker-to-trading mapping, positions, parent/child caches,
claim ledgers, and the retained legacy property surface. Product metadata and
symbol resolution are instance readers injected into consumers; there is no
`configuration.OrderBook` shim or process-global metadata authority.

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
- accepted-placement ownership indexing before fallible local finalization and
  restoration from persisted accepted reveal events during hydration
- self-ownership persistence for every logical stealth row and SID ownership on
  each distinct reveal/move placement before its REST attempt
- declarative span coordination: deterministic all-SID lock acquisition,
  idempotent existing-rung verification, stop-on-first-failure materialization,
  and explicit success/partial/error results through the canonical single-order
  creation path
- terminal fail-closed scheduler stop/readiness clear on worker or schedule
  failure; one diagnostic is logged and an unsafe later resume is paused again
- reveal event recording

Dashboard handlers that route through the bridge must have an explicit bridge method. Do not call manager methods from `dashboard_server.py` through a bridge method that does not exist.
Manual move now follows that rule through
`StealthOrderBridge.move_revealed_stealth_order`; Rehide readiness and
per-order locking remain in the bridge while application admission is owned by
`ExecutionCore`.

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

## `business/` (Business Logic)

- `business/stealth_order_span.py`: side-effect-free declarative span planning,
  product-grid normalization, exact rung allocation, deterministic
  `client_order_id` derivation, flat hierarchy construction, and per-rung
  reveal/anchor policy materialization.

### Fill and Reconciliation
- `business/order_progress.py`: per-order cumulative watermark and delta derivation.
- `business/fill_ledger.py`: append-only fill ledger repository.
- `business/fill_reconciler.py`: WS-derived vs REST fill matching and status stamping.

### Order Lifecycle and Strategy
- `business/event_processor.py`
- `business/move_manager.py`

The unused parallel `ConditionalExecutionWrapper` and its
`OrderInterceptionLayer` were retired in Execution Core stage 5.4A. Active
conditional behavior is expressed by managed stealth reveal conditions rather
than a second order lifecycle.

### Stealth and Profitability
- `business/stealth_condition_evaluator.py`
- `business/stealth_reveal_strategy.py`
- `business/profit_threshold_engine.py`
- `business/post_fill_hook.py`

Follow-up price retreat is a `RepricingPolicy` helper applied to new children.
It is distinct from moving existing hidden orders after a same-side fill; the
latter subsystem and cancel/re-entry distance policy are absent here.

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

## `database/` (Schema and SQL Helpers)

### `database/database.py`
`PostgresDB` connection manager with serialized cursor access.

### `database/order.py`
Canonical table definitions, idempotent forward migrations, and write/read
functions for core trading tables.

### `database/schema.py`
Single ordered additive bootstrap for all required runtime trading tables.
It also owns fresh-deployment and required-table verification. Guarded
deployment, isolated test provisioning, and destructive reset recreation use
this path so initializer coverage cannot drift between entry points.

### `scripts/validate_release.sh`
Read-only release gate for a clean worktree. Runs the complete local
non-external suite, graph check, and final Git/diff checks without contacting
Coinbase or the runtime database.

### `scripts/deploy_runtime.sh`
Foreground runtime deployment owner. Rejects disabled reconciliation and an
existing dashboard, runs release validation and database bootstrap, forces
paused startup through `python -m main`, verifies stable `PAUSED` admin status,
then waits on the engine for an external supervisor.

### `scripts/bootstrap_runtime_database.sh`
Operator-facing runtime schema deployment entry point. Requires explicit
`COINBASE_DB_*` values, validates connected database/user identity and fresh
trading state read-only, permits only existing candle/tick telemetry, delegates
schema work to `database.schema`, and never starts the trading engine.

### `scripts/runtime_healthcheck.py`
Correlated `v1.runtime.status` poller used by deployment. A healthy result requires
`PAUSED`, admission closed, no stop transition, and zero in-flight work.

### Dashboard and market-data persistence helpers
- `database/order_dashboard_helpers.py`
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

## `integration/` (Runtime Adapters and Hook Registries)

- `integration/websocket_hooks.py`
- `integration/fill_event_hooks.py`
- `integration/order_placement_hooks.py`
- `integration/stealth_lifecycle_hooks.py`: synchronous, fail-soft delivery to
  the best-effort stealth lifecycle audit subscriber. It is not an order store
  or a general execution-interception framework.

`main.py` is the only production lookup point for these process-global
registries. It injects their narrow capabilities into the manager and engine;
execution modules do not resolve the singletons themselves.

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

Last reconciled with checkout: 2026-11-26
