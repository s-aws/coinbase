# System Architecture

Reconciled with the `prod` checkout on 2026-11-28. Current source and tests
remain the evidence for runtime behavior.

## Overview

The runtime is centered on a single `OrderEngine` instance (`core/order_engine.py`) with supporting subsystems:

- `core/user_feed_processor.py`: authenticated connection-generation state,
  ordered envelope reduction, bounded keyed dispatch, and feed metrics.
- `dashboard_server.py` + `operator_api/`: versioned operator JSON-RPC
  transport, schema validation, explicit dispatch, and state notifications.
- `bridges/stealth_order_bridge.py` +
  `bridges/stealth_event_deadline_scheduler.py`: ordered stealth condition
  evaluation, deadline scheduling, and reveal orchestration.
- `core/runtime_controller.py`: lifecycle admission gate and inflight drain coordinator.
- `core/execution_core.py`: typed in-process application boundary for runtime
  administration, detached execution queries, and atomic operator-originated
  strategy commands.
- `core/startup_reconciler.py` + `core/periodic_reconciler.py`: exchange-vs-local drift audits.
- `calculation/fee_manager.py`: dynamic maker/taker fee telemetry and adaptive factors.

`main.py` is the sole process composition root. `main()` loads the environment
and product-file settings; `build_application_runtime()` constructs one REST
adapter, one shared `OrderBook`, the manager/bridge/engine graph, and the
Execution Core, dashboard, persistence, and reconciliation adapters. It
resolves the four
existing hook registries once and injects the same placement and lifecycle
instances wherever they are consumed. It also installs one synchronous
dashboard projection sink in `OrderEngine`. Consumer modules receive narrow
REST, metadata, product-resolution, position, hook, projection, fill-ledger, or
event-audit persistence capabilities
instead of importing concrete adapters or live objects from configuration. The
composition root also installs graceful shutdown hooks. It assumes the database-only
`scripts/bootstrap_runtime_database.sh` step (normally composed by
`scripts/deploy_runtime.sh`) has already run the additive `database.schema`
implementation successfully and does not run full schema DDL during process
startup.

Execution Core exposes typed runtime status, pause, and resume operations plus
enum-filtered deep snapshots of active stealth state. Snapshot callers cannot
mutate authoritative nested order data through their result, but the snapshot
is not a transactionally coherent multi-order database view. Its six
originating methods cover single create, span, import, Rehide, manual reprice,
and revealed-order move. Each uses one atomic
`INFLIGHT_APPLICATION_COMMAND` admission/in-flight registration; the embedded
dashboard is an adapter over those methods. Cancellation, queries, and wind-down
remain available under their existing non-originating contracts. Lifecycle and
persistence mutations remain owned by the bridge, manager, and engine.

`core/execution_ports.py` owns the structural contracts for fill-ledger and
event-stream persistence, order/position/status/log/ticker/spread projections,
and WebSocket, fill, placement, and stealth-lifecycle hooks. `OrderEngine` and
`StealthOrderManager` default to explicit stateless no-ops for projection and
hook capabilities only when constructed outside the canonical runtime. The
fill-ledger and event-stream persistence capabilities are required explicitly.
`main.py` supplies one production database adapter for both ports plus the
dashboard and registry adapters. The
default fill logger is registered before the event-stream subscriber, retaining
the established callback order. Hook exception semantics remain owned by the
existing registries, including best-effort stealth lifecycle auditing.

## Runtime Layers

1. **Ingress Layer**
- Public Coinbase ticker/heartbeat envelopes flow through
  `OrderEngine.on_message`; authenticated user/futures-balance/heartbeat
  envelopes enter through `OrderEngine.on_user_message` on a separate
  `WSUserClient` connection and are owned by its `UserFeedProcessor`.
- Operator JSON-RPC requests flow through `operator_api.protocol` validation
  into the explicit `dashboard_server.handle_client_message` dispatcher.
- A newly registered operator socket is excluded from notification fanout until
  its validated bootstrap response is sent. It then receives fresh targeted
  runtime and stealth catch-up projections; direct correlated reads, including
  deployment health, do not require notification eligibility.
- After dispatch, handler success payloads flow back through the originating
  method's closed result schema before serialization. A producer-contract
  mismatch fails closed as one correlated indeterminate internal error; it is
  never treated as retry permission for a possibly completed mutation. After
  that error is sent, each projection requested by the completed handler is
  attempted independently so authoritative state can still reveal the outcome;
  projection failures are logged and cannot rewrite the terminal response.
2. **Domain Layer**
- `OrderEngine` handles flat parent/child cache hydration, placement-to-execution
  status projection, follow-up creation, partial-fill state, and ownership
  classification. Runtime/operator publication goes through its injected
  projection sink rather than a reverse import of `dashboard_server.py`.
- `StealthOrderManager` handles stealth creation, condition checks, reveal, repricing/rearm, manual Rehide, intentional cancellation, and move-revealed execution.

3. **Persistence Layer**
- `database/order.py` owns canonical table definitions, forward migrations,
  and the trading write/read API.
- Database-backed order records are the durable authority. `OrderEngine` and
  `StealthOrderManager` hold working execution state; dashboard payloads,
  event-stream rows, and lifecycle audit markers are projections and must not
  be used as competing sources of order truth.
- `database/schema.py` is the single ordered additive bootstrap plus
  fresh-state/required-table verifier, shared by deployment, test provisioning,
  and destructive reset recreation.
- `scripts/bootstrap_runtime_database.sh` is the database-only deployment
  boundary: mandatory explicit variables, read-only database/user/fresh-state
  validation, bootstrap, and required-table verification.
- `scripts/deploy_runtime.sh` composes the clean release gate, database
  bootstrap, canonical paused runtime, and dashboard health proof while
  remaining foreground-owned for an external supervisor.
- `database/database.py::PostgresDB` serializes cursor/transaction access with an RLock.

4. **Audit/Reconciliation Layer**
- Startup and periodic diff against exchange open orders.
- Historical fills audit against `fill_ledger` and `order_event_stream` ownership evidence.
- Stealth lifecycle callbacks run synchronously but fail soft. Their event,
  history, snapshot, and latest-marker writes are currently best effort and
  non-atomic; durable delivery is deferred to the process-boundary/outbox work.

5. **Presentation Layer**
- Named runtime, stealth-order, ticker, and spread JSON-RPC notifications for
  the two retained HTML consumers.
- Supported stealth strategy commands and admin lifecycle control.

## Enforced In-Process Boundaries

The directory names above are navigation aids, not enforceable layers:
`core/`, in particular, contains both shared domain vocabulary and high-level
runtime orchestration. `module_boundaries.toml` therefore assigns each
supported runtime module to an explicit composition, operator, execution,
reconciliation, market-data, persistence, exchange, integration, domain, or
logging zone. `tests/regression/test_module_boundaries.py` rejects undeclared
modules, new reverse-zone imports, new import cycles, new broad/untyped
constructor capability surfaces, and new reflection mechanisms that can hide
those surfaces.

The contract records 11 reverse-zone import edges, no strongly connected
runtime import component, 31 broad constructor capability surfaces, and seven
reflection/namespace escape signatures. Item 4 retired the configuration edges
and former import cycle; the supported operator-surface cleanup retired six
more import-debt edges and one reflection signature. Execution Core stage 5.3
then retired seven execution-to-dashboard/integration imports and one broad
manager hook capability by introducing narrow injected ports. Stage 5.4A
retired the unused parallel conditional lifecycle, its database reverse import,
and its broad database-client capability. Stage 5.4B.1 restores the active
fill-ledger query contract and moves its SQL access behind a narrow structural
port and canonical database adapter. Stage 5.4B.2 moves event-stream and
best-effort lifecycle-audit writes behind a second narrow protocol implemented
by that same adapter, without combining their transactions or failure paths.
Stage 5.4B.3 moves the bridge's deterministic span parent-row lookup behind
`SpanParentOrderReader`, also implemented by the same adapter. The read remains
inside the existing all-rung action-lock scope and retains fail-closed preflight
behavior without moving SQL or transaction ownership. Stage 5.4B.4 moves the
cancelled-parent workflow behind `CancelledOrderMovePersistence`; `MoveManager`
contains no database import, `OrderEngine` uses one construction path, and the
same adapter delegates to canonical helpers without combining their existing
transactions or changing their failure policy.
Remaining exact debt is assigned to
modular-monolith checklist items 5-8 and is not a package-wide permission for
additional coupling.

Static inspection cannot prove arbitrary Python aliasing, monkeypatching,
returned objects, or runtime dispatch. Full component isolation requires the
narrow protocols/facades and explicit composition planned by later checklist
items. See `MODULE_DEPENDENCIES.md` for the dependency matrix, debt policy, and
maintenance procedure.

Projection dispatch remains synchronous. Order, position, and lifecycle status
publication can occur inside existing engine critical sections, and ticker and
spread publication occurs under `ticker_lock`. The dashboard sink therefore
delegates only to bounded in-memory mutation or event-loop scheduling; future
adapters must not add blocking network or database work at these call sites.

## Threading Model

`OrderEngine.start_background_threads()` starts:
- `websocket_thread_maximum` redundant public `WSClient` connections for
  configured public channels and exactly one `WSUserClient` connection when
  private payload channels are configured
- one worker per subscribed channel (user, ticker, heartbeats, futures_balance_summary)
- periodic parent/child reconciliation loop
- dedup bucket rotation loop
- dashboard status monitor loop
- fee manager refresh loop (hourly)
- market tick retention sweeper (if recorder initialized)

Parent/child reconciliation reads the flat `order_parent` table once per cycle.
It builds roots and linked rows in two passes, validates that every link points
directly to a retained root, and atomically replaces both disjoint maps only
after the complete snapshot succeeds. Lazy hydration uses the same row
classifier and root-entry shape. Neither path queries `stealth_orders` per root
or recalculates persisted replacement counters from lineage size.

`RuntimeController` is constructed in non-admitting `STARTING`. Stop hooks and
the default-on `ENGINE_START_PAUSED` latch are installed before any operator
surface is exposed; an explicit false value opts into automatic readiness as
`RUNNING`. `StealthOrderBridge.start()` then performs strict database
hydration and starts only the stealth DB reconciliation loop (`30s` cadence);
this passive hydration now precedes dashboard startup and does not enable
reveal decisions. The dashboard may answer queries/admin commands while
startup continues, but every configured originating message is rejected as
`STARTING`.

After startup exchange/local reconciliation succeeds,
`activate_decisions()` builds every active order's derived schedule and starts
one event/deadline worker. An incomplete hydration or failed schedule build
always blocks engine startup. Unavailable startup reconciliation also blocks
it unless the operator explicitly set `DISABLE_RECONCILER`; that flag bypasses
reconciliation only. Periodic reconciliation starts next, followed by
`OrderEngine.start_background_threads()`. Only after that method returns does
the `run_forever()` readiness callback call `RuntimeController.complete_startup()`
and publish `PAUSED` by default, or `RUNNING` when startup pause was explicitly
disabled. This boundary proves that every required, non-fail-soft
`Thread.start()` call and
the synchronous initial fee-refresh attempt returned. It does not prove that
the fail-soft market-tick/hotpoint workers started, that parent/child or
partial-fill hydration completed without a swallowed error, that either
filtered fee request succeeded, that websocket connection/subscription
completed, that a first Coinbase snapshot arrived, or that metrics warm-load
finished.

Periodic reconciler hook registration plus thread start is one bounded atomic
startup action. Bridge hydration and schedule construction, plus OrderEngine
DB/REST preparation, run outside component lifecycle locks. Sticky stop
checkpoints surround those potentially blocking stages; only bounded
callback/thread/scheduler publication is serialized with `stop()`. A stopped
component therefore cannot publish or revive a worker, and a partial
worker-start exception forces cooperative cleanup before readiness.

An already-started Coinbase REST call is not force-cancelled and has no
project-configured request timeout. Stop can return while that call is still
blocked, but its post-call checkpoint prevents subsequent websocket launch or
runtime readiness. Each websocket worker owns and closes its wrapper in a
`finally` block once connection was attempted; a connection call that never
returns cannot reach that cleanup until the SDK call unwinds.

Runtime drain has one owner; concurrent callers receive the same terminal
result, and a hook registered while the effective state is `DRAINING` is
invoked immediately and counted until it returns, instead of being stranded
behind an earlier hook snapshot. A hook registered after `STOPPED` is also
invoked immediately, but necessarily runs outside the already-published
terminal result. `STOPPED` is the logical admission/accounting terminal state.
Bounded component joins or a drain timeout may still leave cooperative daemon
work exiting; the guarantee is no new component activation or readiness
revival, not that every OS thread has already terminated.

Fill handling remains allowed during `STARTING`, including persistence of
local hidden follow-up plans for existing exposure. Their exchange reveal is
still admission-gated. Worker-originated hotpoint placement is separately
wrapped in atomic admission/inflight registration, so it can retain detector
history but cannot submit while `STARTING`. A trigger emitted during startup is
skipped, not queued for readiness replay; a later qualifying fill is required
to produce another placement attempt.

The decision scheduler owns one `Condition`, an ordered bounded market-event
FIFO, and one monotonic generational deadline heap. It has no DB, REST, or
lifecycle authority. Market-event overflow is explicit and fail-closed:
one bounded aggregate boundary carries exact loss counts for every discarded
product and, when applicable, the single retained newest snapshot. An
intrinsic event field distinguishes snapshots from control-only resets; payload
shape is not semantic. If the worker stops unexpectedly or an authoritative
runtime schedule cannot be rebuilt, the bridge clears readiness, terminally
stops the scheduler, emits one diagnostic, and pauses originating work. A
later operator resume is paused again on the next rejected publication;
restart plus hydration/reconciliation is required. Due
deadlines are dispatched before queued market events, and the worker handles
at most one market event before checking the heap again, so a hot ticker
backlog cannot starve time/admission/anchor wakes.

`OrderEngine` also treats its upstream bounded ticker queue as an explicit
continuity boundary. On overflow it serializes producers, retains the newest
envelope, carries forward any earlier recovery counts, and records exact loss
counts per product. The ticker worker publishes those reset markers before the
retained snapshot reaches the stealth scheduler. Coinbase's top-level message
timestamp travels with that envelope; it is not expected on each ticker row.
The local monotonic receipt time is sampled at `on_message` entry, attached only
after deduplication, and retained with the selected overflow envelope.

`PeriodicReconciler.start()` starts:
- deep exchange-vs-local audit loop (`15m` default)

### Locking and Concurrency

Primary lock boundaries:
- `OrderEngine.orderbook_lock`: guards in-memory order/parent/child mutations.
- `OrderEngine._coid_handler_locks[client_order_id]`: serializes ensure-parent-row,
  guarded status projection, and delta processing per COID.
- `PostgresDB._cursor_lock`: serializes cursor/commit/rollback on shared connection.
- `RuntimeController` state lock + inflight lock: lifecycle state and drain accounting.
- `OrderEngine._ticker_ingress_lock`: serialized ticker enqueue and explicit
  full-queue recovery across concurrent websocket producers.
- `UserFeedProcessor._user_reducer_lock`: serializes private-envelope reduction
  against connection-generation changes; `_user_feed_lock` protects only the
  authenticated stream phase, generation, connection sequence, and bootstrap
  accumulator state. A per-generation in-flight condition prevents a new
  generation from hydrating while an admitted old-generation lifecycle is
  still executing.
- `UserFeedProcessor`'s keyed dispatcher: FIFO completion for the full
  live lifecycle of one `client_order_id`, while unrelated COIDs may execute
  concurrently. All live rows in one Coinbase envelope are admitted atomically;
  pending work is bounded by `queue_maxsize`, and admission failure
  desynchronizes the private generation instead of partially accepting it.
  The narrower `_coid_handler_locks` remain limited to parent assurance plus
  delta ingestion and are not the lifecycle ordering boundary.

`OrderEngine` retains thin private-name delegates for existing integrations,
but the processor is the only implementation and state owner. Its
`snapshot_metrics()` result is exposed through `OrderEngine.get_user_feed_metrics()`
and included under dashboard `engine_status.user_feed`.
- `StealthOrderManager._orders_cache_lock`: short structural snapshots and
  insert/clear operations for the local stealth cache; it is separate from the
  database creation lock.
- `StealthOrderManager._market_cache_lock`: atomic ticker snapshot replacement.
- `StealthEventDeadlineScheduler` condition: market FIFO, deadline heap, and
  per-`stealth_order_id`/purpose generations, including transient
  worker-captured deadline ownership.
- `StealthOrderBridge` per-order action locks: serialize schedule publication,
  complete root/follow-up creation, reveal/reprice/cancel, continuity reset,
  price-condition edits, websocket exchange-ID enrichment, and terminal
  execution updates for one logical stealth order.

Concurrency safety mechanisms:
- Dedup buckets via `EventBridge`.
- Follow-up claim ledgers (filled/cancelled namespaces) to prevent duplicate child creation.
- Replacement-slot claim accounting to enforce `max_order_replacement` under race.
- Stealth mutation claims (`move`, `reprice`, `rehide`) prevent conflicting concurrent mutation.

## Lifecycle State Machine

`RuntimeController` states:
- `STARTING`: initial fail-closed state; originating work is rejected while
  hydration/reconciliation/scheduler/worker startup completes.
- `RUNNING`: full admission.
- `PAUSING` -> `PAUSED`: no new originating work; cancels/fill handling continue.
- `DRAINING`: shutdown requested; no new originating work.
- `STOPPED`: terminal state.

`request_pause()` during `STARTING` latches a pause without changing state, so
`resume()` cannot open admission early. `complete_startup()` consumes that
latch and publishes `PAUSED`; otherwise it publishes `RUNNING`. A shutdown
that reaches `DRAINING` or `STOPPED` cannot be resurrected by late readiness.
Dashboard shutdown changes state to `DRAINING` and starts its non-daemon drain
worker before awaiting the acknowledgment, so a disconnected UI cannot orphan
cleanup. Python signal handlers first publish a lock-free sticky shutdown
intent, then delegate lock-taking drain work to the sole drain worker to avoid
re-entering a lifecycle transition on the interrupted main thread.

Dashboard `engine_status.engine_state` samples RuntimeController at each engine
status publication. Its `running` field is true only after OrderEngine worker
launch has completed and the controller is admitting; STARTING, PAUSED,
DRAINING, and STOPPED would each have `running=false` when sampled. Monitor and
stop publications share the engine's short lifecycle commit boundary, so a
status snapshot prepared before stop cannot overwrite the stop hook's false
value. That hook normally publishes DRAINING; the later logical STOPPED
transition is immediately visible through `v1.runtime.status` but is not
republished by OrderEngine. The stealth-manager UI additionally uses the
bootstrap/runtime-status result to render the exact
authoritative state and enables its confirmed Resume control only in PAUSED.
Other consumers may still collapse `running=false` into a stopped label.

Admission is enforced at dashboard and engine-originated entry points. The
main-owned shutdown order first runs OrderEngine's startup-quiesce/status hook.
That hook sets the local stop event only while background startup is incomplete;
for a fully started engine it publishes `DRAINING/running=false` while preserving
fill/event workers. The bridge stops next, then full OrderEngine cleanup sets
the local stop event; the periodic reconciler hook is registered later during
startup. Inflight critical sections (`track_inflight`) are allowed to finish
within the drain timeout.
Scheduler-owned reveal and anchor actions use `track_admitted_inflight` so the
admission decision and inflight registration share one state-lock boundary:
pause either wins first or the already-admitted action drains as existing work.

## Core Data Flows

### 1. User Order Event Flow

1. The sole private `WSUserClient` receives a complete authenticated envelope.
   Generation, connection-global sequence number, timestamp, channel, and
   events remain attached through one bounded ordered reducer queue. Subscription
   acknowledgements, heartbeats, user orders, and futures-balance messages all
   advance the one sequence watermark for that connection generation.
2. The user reducer moves through `AWAITING_SNAPSHOT -> BOOTSTRAPPING -> LIVE`.
   Initial order pages (`snapshot` plus compatibility `patch`/`update` pages)
   accumulate by `client_order_id`; the first page below 50 completes the
   venue set. Ten seconds without the initial order snapshot or without a short
   terminating page, a sequence discontinuity, channel or dispatcher queue
   overflow, conflicting duplicate, or malformed known payload moves the
   generation to `DESYNCHRONIZED` and requests reconnect.
3. A completed bootstrap performs exactly one drift comparison and one
   in-memory hydration. Bootstrap rows never enter DB/fill/follow-up lifecycle
   processing. Positions are reduced independently and cannot change the order
   bootstrap phase when no `orders` member is present.
4. Post-bootstrap `update` and `patch` rows are validated as complete canonical
   lifecycle snapshots, then all rows from the complete envelope are admitted
   atomically, keyed by `client_order_id`, and routed exactly once through
   `process_user_order`.
5. `process_user_order` normalizes payload and resolves ownership. Parent-row
   existence is ensured before delta persistence paths.
6. `OrderProgressTracker` computes per-snapshot deltas. Delta fan-out:
- `fill_ledger` append (`WS_DERIVED` rows) through the injected persistence port
- `order_match_audit` append
- partial-fill follow-up evaluation
7. `FILLED`/`CANCELLED` use their canonical handlers. `EXPIRED` is terminal
   cleanup only: exact status persistence/dashboard publication, progress
   finalization, and in-memory eviction without filled/cancelled replacement
   handling.
8. Dashboard state/log broadcast updates.

### 2. Stealth Lifecycle Flow

1. Declarative spans are planned server-side before any write. The planner
   validates and product-normalizes every rung, apportions the effective total
   size in base increments, derives deterministic `client_order_id` values from
   `span_id`, and materializes flat Parent+Children linkage or independent
   roots. The bridge acquires every new-SID action lock in deterministic order
   and then delegates each rung to the existing single-order creation path.
   Span persistence is resumable, not atomic: validation failure writes
   nothing; a runtime failure stops later rungs and returns an explicit partial
   result; retry verifies matching durable rows and creates only missing rungs.
2. The bridge reserves the new `stealth_order_id` and owns its per-order lock
   across the manager's complete creation transaction. `create_stealth_order`
   persists root order and in-memory state, emits `CREATED`, and publishes the
   schedule before a ticker can evaluate that SID. The same ownership covers
   follow-up post-create metadata persistence.
3. The ticker worker publishes a defensive normalized snapshot to the bridge
   before dashboard/metrics work. The scheduler preserves websocket arrival
   order and evaluates only active orders for that product. Coinbase's ticker
   event time is preserved (UTC-normalized; host UTC is only the fallback), so
   an engine queue delay does not silently lengthen a configured hold. A
   detected upstream queue loss or out-of-order timestamp breaks continuous
   evidence before a retained/newer ticker can start a new hold.
4. Fixed time conditions use stable wall-clock deadlines. Price and spread
   conditions use continuous-hold deadlines: a true event starts `PENDING`, any
   later false, unusable, or failed-to-evaluate ordered event emits
   `CONDITION_RESET` and returns to `HIDDEN`, and elapsed time alone cannot
   trigger. If that reset cannot be persisted, decision readiness is
   terminally latched off until restart. A true ordered event at or after the
   deadline commits `TRIGGERED`. Zero hold commits on the first true event.
   Every condition type uses the same fail-closed persistence boundary for
   `PENDING` and `TRIGGERED`: a failed write restores the prior in-memory
   state, requests a runtime pause, and raises before logging success,
   lifecycle publication, schedule invalidation, or reveal.
   Jitter, volume, ratio, and composite conditions retain the compatibility
   recheck path; they were not redefined by this scheduler change. Activation
   rejects malformed configurations that would fail on every recheck while
   retaining their existing fallback semantics.
5. `TRIGGERED` is a committed snapshot. Runtime pause can defer placement, but
   later market events do not roll it back; reveal admission and inflight
   registration are atomic. Closed admission leaves no recurring trigger retry;
   the admission-open hook schedules one immediate retry per eligible order.
   Running retries use the existing 100 ms cadence with one successor owner.
6. Anchor deadlines only mark a logical order due. The next live ticker for its
   product claims that deadline generation and invokes the existing manager
   repricing path; stale generations are no-ops and anchor repricing REST/DB work
   does not run on the decision worker. The ticker may atomically claim either
   an active heap deadline or a wake already captured by the worker, so the
   first eligible post-deadline ticker cannot miss the handoff window. Anchor
   eligibility uses that ticker's ingress monotonic time, not the later time at
   which dashboard/metrics work finishes. Batch processing rechecks admission
   per SID, atomically registers admitted anchor work with `RuntimeController`,
   and retains or rebuilds unstarted due work if pause/drain or decision
   readiness loss begins.
7. Reveal plan resolves submitted price (`configured_limit`, `top_of_book`, or `midpoint`) and post-only policy.
8. Placement happens via REST. For placement client order IDs that differ from
   the owning logical `stealth_order_id`, `StealthOrderManager.reveal_order_slice`
   pre-inserts an `order_parent` row linked to the original strategy root before
   the REST attempt and records that SID in
   `execution_owner_client_order_id`, so a racing WS user-channel event has
   durable ownership before the accepted-placement index exists. If REST raises
   or Coinbase returns a
   rejected placement, the reveal path records a failed reveal event but
   leaves revealed size, remaining size, and active placement pointers
   unchanged.
9. Reveal events and lifecycle transitions persist to audit/history tables.
10. Anchor repricing of a revealed order uses the accepted reveal event as live-placement truth, persists a `pending_rearm` cancel intent, and requests cancellation without placing a replacement. The default `return_to_hidden=true` mode keeps the order `REVEALED` until the matching authenticated `CANCELLED` event returns that placement's size to hidden inventory. The same intent may be superseded with `return_to_hidden=false` when terminal local state must win (for example, an operator cancel during an in-flight rearm); this reuses the acknowledgement path rather than adding another cancel protocol. A fill aborts the rearm, and every non-terminal/ambiguous cancel outcome leaves the intent pending. The existing condition evaluator and reveal path own all later re-entry. Repricing fails closed when one tracked cancellation cannot account for all revealed exposure; multi-live sizing layouts are intentionally unsupported by this minimal path.
11. The operator Move-revealed flow remains a distinct direct cancel-and-replace action with audit row insertion; it is not the automatic cancel-to-hidden rearm path.
12. Manual Rehide enters the same persisted rearm/confirmation path without requiring anchor repricing or a price change. It preserves the configured price, condition configuration, sizing, and flat linkage; only one fully accounted zero-fill placement is eligible. The bridge requires startup readiness and atomically admitted runtime work under its existing per-order action lock. A request acknowledgement means pending exchange confirmation, never an optimistic `HIDDEN` status. Confirmation restarts the existing reveal policy; a satisfied condition may reveal again subject to its normal hold/delay and admission rules. Manual rehide does not increment repricing history or reset anchor pacing.

### Stealth State and Exchange Truth

Stealth status is operational state, not display-only metadata:
- Exchange `OrderStatus.CANCELLED` and logical `StealthOrderStatus.CANCELLED` are different facts. Rehide/reprice consumes a confirmed zero-fill cancellation into `HIDDEN`; an external cancellation keeps the configured replacement behavior. Intentional project cancellation instead persists the logical stop and `operator_cancel_requested_at` before requesting withdrawal, superseding any rehide with `pending_rearm.return_to_hidden=false`. It retains live identifiers until authenticated terminal truth, using the same restart/reconciliation path.
- Follow-up admission is serialized with intentional cancellation under the source SID action lock, followed by the existing new-SID creation lock. The shared stop predicate also guards hotpoint origination; fill ledger/progress/execution recording continues. A fill can change the factual outcome to `EXECUTED` without removing the durable stop. Existing children are not retroactively cancelled. The first committed action wins the cancellation/creation race.
- `HIDDEN`, `PENDING`, and `TRIGGERED` mean no live Coinbase placement should exist for that stealth order.
- `REVEALED` means a placement was submitted and may still be resting on the exchange. The active placement is tracked in `anchor_repricing_state_json.active_placement_client_order_id` and `active_exchange_order_id` when known.
- Every logical stealth `order_parent` row owns itself through
  `execution_owner_client_order_id`; each distinct reveal/move placement names
  its logical SID. External/unowned compatibility rows may leave it NULL.
  User-order status projection resolves this durable relation and updates the
  exact placement plus its validated owner in one database statement. The owner
  must exist, own itself, share the same flat strategy root, and agree with the
  accepted-placement index when that runtime evidence is available. A missing
  index does not block a pre-REST race. A failed guard retains exact placement
  truth where possible, pauses the runtime, and suppresses normal, partial-fill,
  and hotpoint origination while factual fill/audit ingestion continues. Rearm
  uses the same operation with distinct placement/logical statuses.
- `anchor_repricing_state_json.pending_rearm` identifies one persisted cancellation awaiting authenticated exchange truth. It records both the internal placement `client_order_id` and source exchange `order_id`; `return_to_hidden` selects rearm (`true`, also the legacy default when absent) versus terminal cancellation (`false`). The matching placement `client_order_id` on an authenticated terminal event is the idempotency boundary.
- `ERROR` means exchange placement was rejected or acceptance could not be
  proven. It is terminal, excluded from active evaluation, and is never
  automatically resubmitted.
- A revealed order cannot become hidden again by local status mutation alone. The live exchange order must be cancelled, filled, moved/replaced, or reconciled closed before local state claims it is hidden. Intentional local CANCELLED may
  precede withdrawal, but must preserve exposure identifiers and pending intent.
- If an exchange cancel fails, keep the local state conservative and surface operator action. Do not clear the active exchange pointer and mark the order hidden as if the order were gone.
- A confirmed rearm sets `reveal_armed_at` only on the `REVEALED` to `HIDDEN` transition. Hidden anchor-price maintenance does not restart time-delay reveal policy.
- Once `reveal_armed_at` exists, each new reveal uses a fresh placement `client_order_id`, including orders with repricing disabled. The logical stealth ID and original root linkage stay unchanged; retired exchange client IDs are never reused after rehide.
- Hydrated or dropped-event rearm intents are recovered by the existing stealth reconciliation loop using an exact authenticated exchange-order lookup. `OPEN` reissues cancellation of that same exchange order; `CANCELLED` and `FILLED` return through the canonical order-event path. This completion path remains active when the broad startup/periodic drift auditor is disabled because it finishes a previously persisted exchange mutation rather than discovering unrelated drift.

### 3. Reconciliation Flow

Startup (and periodic deep audit):
- Pull every page of exchange open orders via REST; malformed pagination,
  missing order IDs, and repeated cursors make the reconciliation unavailable.
- Pull local open view from `order_parent` (excluding terminal and pre-reveal stealth statuses).
- Diff into `unknown_to_local`, `open_on_exchange_terminal_locally`, `closed_on_exchange_open_locally`, `in_sync`.
- Optional safe auto-heal marks local-open/exchange-closed rows as `RECONCILED_CLOSED`.
- Startup accepts only an explicit Coinbase `orders` list plus successful local
  queries. Missing/malformed REST data or failed local reads produce no
  authoritative report and therefore cannot activate stealth decisions or the
  engine loop. An explicit empty `orders: []` is valid exchange truth.

Missed-fill audit:
- Page REST historical fills.
- Compare against `fill_ledger.exchange_entry_id`.
- Suppress false positives for pending WS-derived rows.
- Partition owned vs unowned fills via `order_event_stream` `order_submitted` + `rest_submit` evidence.

## Persistence Architecture

Canonical required-table definitions live in `database/order.py`:
- `order_parent`
- `stealth_orders`
- `stealth_order_snapshots`
- `stealth_order_reveal_history`
- `stealth_order_lifecycle_history`
- `order_moves`
- `stealth_order_moves`
- `fill_ledger`
- `order_match_audit`
- `order_event_stream`
- `partial_fill_progress`

The canonical set contains 11 required tables. The retired parallel
`ConditionalExecutionWrapper` and its exclusive `conditional_orders` table are
not part of the managed stealth reveal-condition lifecycle.

`database/schema.py::initialize_database_schema()` invokes those definitions
in dependency order, `verify_database_schema()` checks the required set,
`verify_fresh_runtime_database()` rejects unknown public tables or existing
trading rows, and `REQUIRED_TABLES` exposes canonical names. Fresh deployment
enters through foreground `scripts/deploy_runtime.sh`: clean release validation,
database-only bootstrap, canonical paused `main` launch, and live dashboard
health proof. `scripts/bootstrap_runtime_database.sh` remains the database-only
entry point. The destructive reset uses the same initialization and required
table verification after dropping public tables, but is never called by
deployment automation. Direct reset-script execution then preserves its
existing best-effort candle backfill.

Analytics support tables are created lazily by their telemetry paths rather
than included in the required runtime bootstrap:
- `market_tick` (live recorder)
- `market_candle_1m` (historical candle fallback)

Those two tables are the only non-runtime public tables allowed by the fresh
deployment guard, and their existing rows do not make a trading target stale.

## Dashboard and Operator Interface

`dashboard_server.py` runs a plain, unauthenticated WebSocket listener in a
daemon thread inside the canonical process. `main()` reads
`DASHBOARD_SERVER_HOST` (falling back to `HOSTNAME`, then `localhost`) and
integer `DASHBOARD_SERVER_PORT` (default `8765`) and passes both explicitly to
`start_dashboard_server()`. The transport imports passively and receives the
shared `OrderBook`, state-publish interval, `ExecutionCore`, and stealth bridge from the
composition root; direct script execution exits with `python -m main`
guidance. Browser clients choose their own endpoints; changing the listener
does not reconfigure clients or serve HTML. See
`CONFIGURATION.md` for the endpoint matrix and local-only binding guidance.

`dashboard_server.py` accepts only the methods declared by
`OperatorRpcMethod` and `operator_api/schema.json`. One explicit dispatch map
covers bootstrap, runtime control, single/span creation, managed
cancel/Rehide/move/reprice, import/export, price/target/parent updates,
active-order reads, and guarded cleanup. Caller UUIDs correlate exactly one
terminal response; they do not provide generic idempotent replay. The adapter
passes the originating method to `operator_api.protocol` so only a
method-schema-valid handler result can be emitted as success. Notification
builders are regression-checked against their method-specific schemas without
adding validation work to the live ticker path.

The only supported browser clients are `ui_stealth_orders_manager.html` and
`ui_order_span_builder.html`. Hotpoint replication is an off-by-default
per-strategy field; there is no independent global kill switch or manager UI.
Their approved replacement is the not-yet-implemented unified TypeScript/Vite
console in `design_specs/OPERATOR_CONSOLE.md`.

Publication model:
- shared in-memory `engine_state`;
- `v1.projection.runtime` and `v1.projection.stealth_orders` notifications;
- `v1.market.ticker` and `v1.market.spread_snapshot` notifications; and
- JSON-safe serialization for Decimal/datetime payloads.

Client registration sends no uncorrelated fragments. The required
`v1.session.bootstrap` response supplies initial runtime, products,
capabilities, dashboard state, and enriched stealth projection before clients
enable mutations. Batches and client notifications are unsupported. The API
remains unauthenticated and loopback-only in supported deployment.

## Optional Cross-Venue Intelligence

`market_intel/` introduces external-venue signal aggregation:
- Venue mappings in `market_intel/venues.py`
- Ring-buffered aggregator in `market_intel/cross_venue_aggregator.py`

Current scope is intentionally narrow and fail-soft:
- no mutation of trading state
- consumers treat missing intel as no-signal fallback
- no supported operator client currently consumes these libraries

## Known implementation boundaries

- A pre-reveal intentional stop persists the stealth row but still leaves the
  same-SID order_parent projection PENDING and omits the CANCELLED lifecycle
  event. This is a durable audit/projection gap, not an active reveal plan;
  startup reconciliation does not repair it.
- Pending rearm requires one fully accounted zero-fill placement. Multi-live
  exposure fails closed rather than treating hidden remaining_size as exposure.
- Span creation uses the existing per-order persistence transaction for each
  rung. It is resumable through deterministic IDs but is not one cross-rung
  database transaction; a runtime persistence failure can return `partial`.
- Cumulative-volume compatibility evaluation expects trade-volume fields that
  the ticker bridge does not supply and retains evaluator-lifetime limitations.
  Its presence in the factory is not evidence of correct live accumulation.

## Key Architectural Invariants

- `client_order_id` is the internal primary key across memory, DB, hooks, and logs.
- `order_id` is exchange-assigned and used for exchange-side lookup/reporting
  and raw endpoints that require it. The project Coinbase wrapper
  `cancel_order(client_order_id)` is the single-order cancellation exception
  because Coinbase accepts our client id there. That wrapper accepts only
  explicit `success: true` cancel evidence as success.
- Parent-child hierarchy is flat.
- Stealth state must not lie about live exchange placement.
- Cancel/re-entry, move, and repricing must share the same active-placement truth (`anchor_repricing_state_json`) instead of inventing a second exchange pointer.
- Single behavior path per concern (no duplicated parallel implementations).
- Hooks dispatch outside lock-critical sections where required to avoid lock-order deadlocks.

## Extension Rules

When adding a feature:
- choose one canonical write path and one canonical read path.
- follow `module_boundaries.toml`; do not add a reverse-zone import, broad
  injected capability, or reflection exception without architecture review.
- register new enums in `core/enums.py` instead of adding new literals.
- update dashboard request/response contracts in `API_REFERENCE.md`.
- verify UI -> dashboard handler -> bridge -> manager wiring exists for every new dashboard action.
- for stealth lifecycle changes, test both local state transition and the exchange-facing cancel/place/reconcile boundary.
- add/extend regression tests before shipping.

---

Last reconciled with checkout: 2026-11-26
