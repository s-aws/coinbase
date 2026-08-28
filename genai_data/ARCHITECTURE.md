# System Architecture

> Verification status: this document contains architecture retained from more
> than one branch. A component named here is active only if it exists in the
> current checkout. Verify behavior against code and tests before changing it.

## Overview

The runtime is centered on a single `OrderEngine` instance (`core/order_engine.py`) with supporting subsystems:

- `dashboard_server.py`: operator command surface and state broadcast over WebSocket.
- `api/v1/app.py`: enterprise Admin API contract app and OpenAPI source.
- `application/admin_api/`: shared command-service boundary for FastAPI and
  dashboard compatibility adapters.
- `bridges/stealth_order_bridge.py` +
  `bridges/stealth_event_deadline_scheduler.py`: ordered stealth condition
  evaluation, deadline scheduling, and reveal orchestration.
- `core/runtime_controller.py`: lifecycle admission gate and inflight drain coordinator.
- `core/startup_reconciler.py` + `core/periodic_reconciler.py`: exchange-vs-local drift audits.
- `calculation/fee_manager.py`: dynamic maker/taker fee telemetry and adaptive factors.

`main.py` wires these together and installs graceful shutdown hooks.

## Runtime Layers

1. **Ingress Layer**
- Coinbase user/ticker websocket events flow into `OrderEngine.on_message`.
- Dashboard websocket commands flow into `dashboard_server.handle_client_message`.
- Enterprise Admin API routes flow through `api/v1/routes/*` into
  `application.admin_api.command_service.AdminApiCommandService`. HTTP
  mutating routes are no-live by default. Manual Spot order and cancel are
  route-scoped configured exceptions that may reach the shared backend live
  branch only after exact backend auth/RBAC, idempotency, approval,
  admission-audit, cap/guard, reconciliation, manual acknowledgement,
  live-service, REST-client, and event-stream gates pass; other mutating HTTP
  routes remain live-disabled/fail-closed and do not call Coinbase.

2. **Domain Layer**
- `OrderEngine` handles parent/child lifecycle, follow-up creation, partial-fill state, and ownership classification.
- `StealthOrderManager` handles stealth creation, condition checks, reveal, repricing, cancel/re-entry, same-side post-fill retreat, and move-revealed execution.

3. **Persistence Layer**
- `database/order.py` is canonical schema + write/read API.
- `database/database.py::PostgresDB` serializes cursor/transaction access with an RLock.

4. **Audit/Reconciliation Layer**
- Startup and periodic diff against exchange open orders.
- Historical fills audit against `fill_ledger` and `order_event_stream` ownership evidence.

5. **Presentation Layer**
- Dashboard state broadcast (`state_update`) for HTML and terminal consumers.
- Analytics endpoints for slide calibration and market chart views.

## Threading Model

`OrderEngine.start_background_threads()` starts:
- websocket connection threads (`websocket_thread_maximum`)
- one worker per subscribed channel (user, ticker, heartbeats, futures_balance_summary)
- periodic parent/child reconciliation loop
- dedup bucket rotation loop
- dashboard status monitor loop
- fee manager refresh loop (hourly)
- market tick retention sweeper (if recorder initialized)

`RuntimeController` is constructed in non-admitting `STARTING`. Stop hooks and
the optional `ENGINE_START_PAUSED` latch are installed before any operator
surface is exposed. `StealthOrderBridge.start()` then performs strict database
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
and publish `RUNNING`, or `PAUSED` when a startup pause was latched. This
boundary proves that every required, non-fail-soft `Thread.start()` call and
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
- `OrderEngine._coid_handler_locks[client_order_id]`: serializes ensure-parent-row + delta processing per COID.
- `PostgresDB._cursor_lock`: serializes cursor/commit/rollback on shared connection.
- `RuntimeController` state lock + inflight lock: lifecycle state and drain accounting.
- `OrderEngine._ticker_ingress_lock`: serialized ticker enqueue and explicit
  full-queue recovery across concurrent websocket producers.
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
- Stealth mutation claims (`move`, `reprice`, `retreat`) to prevent conflicting concurrent mutation.
- Cancel/re-entry policy evaluation runs before anchor repricing on ticker updates, so a policy-cancel decision wins over repricing the same revealed placement.

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
transition is immediately visible through `admin_status` but is not
republished by OrderEngine. Existing dashboard and terminal-console consumers
still label every `running=false` sample as “Stopped”; they do not yet render
STARTING or PAUSED distinctly.

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

1. User websocket message arrives.
2. Event dedup and channel dispatch.
3. `process_user_order` normalizes payload and resolves ownership.
4. Parent-row existence is ensured before delta persistence paths.
5. `OrderProgressTracker` computes per-snapshot deltas.
6. Delta fan-out:
- `fill_ledger` append (`WS_DERIVED` rows)
- `order_match_audit` append
- partial-fill follow-up evaluation
7. Terminal statuses trigger filled/cancelled handling and follow-up logic.
8. Dashboard state/log broadcast updates.

### 2. Stealth Lifecycle Flow

1. The bridge reserves the new `stealth_order_id` and owns its per-order lock
   across the manager's complete creation transaction. `create_stealth_order`
   persists root order and in-memory state, emits `CREATED`, and publishes the
   schedule before a ticker can evaluate that SID. The same ownership covers
   follow-up post-create metadata persistence.
2. The ticker worker publishes a defensive normalized snapshot to the bridge
   before dashboard/metrics work. The scheduler preserves websocket arrival
   order and evaluates only active orders for that product. Coinbase's ticker
   event time is preserved (UTC-normalized; host UTC is only the fallback), so
   an engine queue delay does not silently lengthen a configured hold. A
   detected upstream queue loss or out-of-order timestamp breaks continuous
   evidence before a retained/newer ticker can start a new hold.
3. Fixed time conditions use stable wall-clock deadlines. Price and spread
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
4. `TRIGGERED` is a committed snapshot. Runtime pause can defer placement, but
   later market events do not roll it back; reveal admission and inflight
   registration are atomic, and admission retries use the existing 100ms
   slice/retry cadence.
5. Anchor deadlines only mark a logical order due. The next live ticker for its
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
6. Reveal plan resolves submitted price (`configured_limit`, `top_of_book`, or `midpoint`) and post-only policy.
7. Placement happens via REST. For placement client order IDs that differ from
   the stealth root, `StealthOrderManager.reveal_order_slice` pre-inserts the
   `order_parent` row before the REST attempt so a racing WS user-channel event
   does not create an orphan root. If REST raises or Coinbase returns a
   rejected placement, the reveal path records a failed reveal event but
   leaves revealed size, remaining size, and active placement pointers
   unchanged.
8. Reveal events and lifecycle transitions persist to audit/history tables.
9. Cancel/re-entry policy can cancel a no-fill revealed placement, return the stealth order to `HIDDEN`, and later re-enter through the existing reveal path when the market moves far enough away.
10. Same-side post-fill retreat can move the nearest opted-in hidden order on the same product/side by configured price ticks after another order fills.
11. Anchor repricing can mutate revealed orders under claim guards and applies any cumulative post-fill retreat offset before computing the next target. Current limitation: canonical full reveal sets `remaining_size` to zero while the revealed repricer also uses `remaining_size` as live venue exposure, so ordinary fully revealed resting placements skip automatic cancel-replace; correcting that exposure model is separate from scheduler timing.
12. Move-revealed flow executes cancel-and-replace with audit row insertion.

### Stealth State and Exchange Truth

Stealth status is operational state, not display-only metadata:
- `HIDDEN`, `PENDING`, and `TRIGGERED` mean no live Coinbase placement should exist for that stealth order.
- `REVEALED` means a placement was submitted and may still be resting on the exchange. The active placement is tracked in `anchor_repricing_state_json.active_placement_client_order_id` and `active_exchange_order_id` when known.
- `ERROR` means exchange placement was rejected or acceptance could not be
  proven. It is terminal, excluded from active evaluation, and is never
  automatically resubmitted.
- A revealed order cannot become hidden again by local status mutation alone. The live exchange order must be cancelled, filled, moved/replaced, or reconciled closed before local state claims it is no longer revealed.
- If an exchange cancel fails, keep the local state conservative and surface operator action. Do not clear the active exchange pointer and mark the order hidden as if the order were gone.

Cancel/re-entry is not general hide-again behavior. It is a narrower policy-cancel/re-entry mechanism:
- It applies only to revealed stealth orders with no executed size.
- It cancels the tracked active exchange placement before marking the stealth order hidden.
- It persists policy and runtime state in `cancel_reentry_policy_json` and `cancel_reentry_state_json`.
- While state is `cancelled_by_policy`, normal reveal checks are held until re-entry distance, cooldown, and max-count rules allow re-entry.
- Re-entry calls the existing reveal path instead of adding a parallel placement implementation.

The old dashboard "Hide" action is not the same contract. It is a UI/operator action and must not be treated as proof that the exchange placement was cancelled unless the code path explicitly performs or reconciles that cancellation. Do not describe either UI Hide or cancel/re-entry as a general hide-again feature.

Same-side post-fill retreat is a separate hidden-order policy:
- It is opt-in on the hidden order being moved (`post_fill_retreat_policy_json`).
- It triggers from a filled same-product/same-side stealth placement.
- It chooses one nearest eligible hidden order by distance from the fill price.
- It never mutates `REVEALED` live exchange placements; those stay under cancel/move/reprice/reconcile paths.
- It updates `limit_price`, absolute reveal-condition price fields, pending trigger timestamps, and `anchor_repricing_state_json`.
- `anchor_repricing_state_json.post_fill_retreat_offset` is cumulative and is applied to future anchor target bands so anchor repricing does not erase the retreat.

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

Canonical tables (created in `database/order.py`):
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
- `conditional_orders`
- `partial_fill_progress`

Analytics support tables:
- `market_tick` (live recorder)
- `market_candle_1m` (historical candle fallback)

## Dashboard and Operator Interface

`dashboard_server.py` exposes command handlers for:
- runtime admin (`admin_status`, `admin_pause`, `admin_resume`, `admin_shutdown`)
- parent CRUD, stealth CRUD/update/move/reprice and create/import payloads carrying cancel/re-entry and post-fill retreat policy
- chart and calibration reads
- products list refresh
- move history and premark flows

Broadcast model:
- shared in-memory `engine_state`
- periodic and event-driven `state_update` pushes
- JSON-safe serialization for Decimal/datetime payloads

## Enterprise Admin API

The enterprise Admin API is the contract surface for the separate frontend
repository at `C:\coinbase-frontend`. HTTP mutating routes are no-live by
default. Manual Spot order and cancel are the only current route-scoped
configured exceptions, and they may reach the shared backend live branch only
after exact backend auth/RBAC, idempotency, approval, admission-audit,
cap/guard, reconciliation, manual acknowledgement, live-service, REST-client,
and event-stream gates pass. Other mutating HTTP routes remain
live-disabled/fail-closed.

Current modules:
- `api/v1/app.py`: FastAPI app factory.
- `api/v1/routes/admin.py`: read-only backend association, health,
  session/RBAC, capability, guard/risk policy, audit workbench, gate, and
  frontend-fixture routes.
- `api/v1/routes/orders.py`: thin route adapters for `POST /api/v1/orders`,
  `GET /api/v1/orders`, `GET /api/v1/orders/{client_order_id}`,
  `POST /api/v1/orders/{client_order_id}/cancel`, and
  `POST /api/v1/spot/campaign/executions`.
- `api/v1/routes/spot.py`: read-only spot operator routes.
- `api/v1/routes/stealth.py`: read-only stealth lifecycle evidence routes.
- `api/v1/routes/movement_repricing.py`: read-only movement/repricing
  evidence routes over `order_moves`, `stealth_order_moves`, stealth repricing
  state, and runtime-safe claim snapshots.
- `api/v1/routes/futures.py`: read-only futures/perpetual account, risk, and
  position evidence routes keyed by backend `position_key`.
- `application/admin_api/command_service.py`: shared command service used by
  HTTP routes and legacy dashboard compatibility adapters.
- `application/admin_api/auth.py`: fail-closed bearer-token/RBAC bootstrap.
- `application/admin_api/idempotency.py`: durable JSONL idempotency store and
  payload-hash contract.
- `application/admin_api/approval.py`: approval snapshot contract.
- `application/admin_api/audit.py`: durable JSONL command audit store.
- `application/admin_api/read_service.py`: read-only operator status service.
- `application/admin_api/route_inventory.py`: route/message inventory.
- `openapi/coinbase-admin-api.yaml`: generated backend-owned OpenAPI artifact.

Current behavior:
- Admin API mutating routes authenticate, authorize, evaluate idempotency, write
  audit records, and fail closed unless their route has explicit backend
  live-service admission.
- Manual Spot order creation and cancel-by-`client_order_id` are explicit
  configured live-service exceptions. They still require exact backend
  auth/RBAC, idempotency, approval, admission-audit, cap/guard,
  reconciliation, manual acknowledgement, live-service, REST-client, and
  event-stream evidence before calling the shared command-service live branch.
- Other mutating HTTP routes return live-disabled or not-implemented evidence
  and do not submit Coinbase orders, cancel Coinbase orders, or mutate live
  exchange state.
- Admin API OpenAPI includes typed `200` accepted/replayed command response
  schemas for explicit live-enabled states and typed blocked response contracts
  for live-disabled states.
- Legacy dashboard `place_order` and `cancel_order` WebSocket messages delegate
  to `AdminApiCommandService` as compatibility adapters.
- Order read routes are local-evidence reads keyed by `client_order_id`.
  Exchange-native ids are exposed only as `exchange_order_id` evidence.
- Stealth read routes are local-evidence reads keyed by `stealth_order_id`.
  Active placement client ids and exchange-native ids are exposed as evidence
  only. Stealth cancel is modeled as a live-disabled Admin API command keyed
  by `stealth_order_id`.
- Movement/repricing read routes expose durable parent move history, revealed
  stealth move audit rows, anchor repricing state, replacement-slot evidence,
  and runtime mutation claim state when safely observable. Movement reprice is
  modeled as a live-disabled Admin API command keyed by `stealth_order_id`;
  stealth move has a live-disabled Admin API draft keyed by `stealth_order_id`;
  live move execution, premark, and move-revealed command authority is not
  modeled.
- Futures/perpetual read routes expose account, margin, collateral, funding,
  liquidation, close/reduce-side, position, and P/L evidence. `position_key`
  is the position read identity. Configured product scope and observed
  position scope are separate. Close/reduce sides are backend-derived from
  observed position side and are not exchange-observed order flags.
- Guard/risk policy reads expose existing backend action-condition policy,
  configured cap rules, live execution gate posture, product capability
  policy, profitability-validator posture, authority sources, and rejection
  categories as evidence only. They do not fetch Coinbase wallets and do not
  approve browser live execution.
- Audit workbench reads expose route inventory, command audit events,
  correlation ids, request ids, audit ids, module summaries, and exchange
  evidence as a read-only cross-module workbench. They do not mutate audit
  history, fetch Coinbase, replay commands, or approve browser live execution.
- Admin bootstrap, health, session/RBAC, capabilities, release/recovery,
  fill-ledger health, and frontend fixture routes are read-only backend
  association surfaces for `C:\coinbase-frontend`.
- Admin API responses include observability headers and structured error
  payloads for auth, RBAC, and validation failures.
- Read-only spot routes expose readiness, sweep status, sweep P/L, cost-basis
  status, campaign status, and direct-order audit; they are auth/RBAC-gated and
  document `401`/`403` in the generated OpenAPI contract.

Future live behavior must use one path:

```text
frontend request
-> FastAPI route
-> auth/RBAC
-> idempotency and approval gate
-> shared command service
-> existing domain/bridge/exchange path
-> durable audit
-> typed response
```

Legacy dashboard WebSocket live commands that do not pass through equivalent
enterprise gates remain explicitly compatibility-only and excluded from new
frontend workflows.

## Optional Cross-Venue Intelligence

`market_intel/` introduces external-venue signal aggregation:
- Venue mappings in `market_intel/venues.py`
- Ring-buffered aggregator in `market_intel/cross_venue_aggregator.py`

Current scope is intentionally narrow and fail-soft:
- no mutation of trading state
- consumers treat missing intel as no-signal fallback
- terminal UI (`ui_console.py`) can display cross-venue premium/lead indicators

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
- register new enums in `core/enums.py` instead of adding new literals.
- update dashboard request/response contracts in `API_REFERENCE.md`.
- verify UI -> dashboard handler -> bridge -> manager wiring exists for every new dashboard action.
- for stealth lifecycle changes, test both local state transition and the exchange-facing cancel/place/reconcile boundary.
- add/extend regression tests before shipping.

---

Last updated: 2026-05-16
