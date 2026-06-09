# System Architecture

## Overview

The runtime is centered on a single `OrderEngine` instance (`core/order_engine.py`) with supporting subsystems:

- `dashboard_server.py`: operator command surface and state broadcast over WebSocket.
- `bridges/stealth_order_bridge.py`: stealth condition evaluation and reveal orchestration.
- `core/runtime_controller.py`: lifecycle admission gate and inflight drain coordinator.
- `core/startup_reconciler.py` + `core/periodic_reconciler.py`: exchange-vs-local drift audits.
- `calculation/fee_manager.py`: dynamic maker/taker fee telemetry and adaptive factors.

`main.py` wires these together and installs graceful shutdown hooks.

## Runtime Layers

1. **Ingress Layer**
- Coinbase user/ticker websocket events flow into `OrderEngine.on_message`.
- Dashboard websocket commands flow into `dashboard_server.handle_client_message`.

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

`StealthOrderBridge.start()` starts:
- condition evaluation loop (`~100ms` cadence)
- stealth DB reconciliation loop (`30s` cadence)

`PeriodicReconciler.start()` starts:
- deep exchange-vs-local audit loop (`15m` default)

### Locking and Concurrency

Primary lock boundaries:
- `OrderEngine.orderbook_lock`: guards in-memory order/parent/child mutations.
- `OrderEngine._coid_handler_locks[client_order_id]`: serializes ensure-parent-row + delta processing per COID.
- `PostgresDB._cursor_lock`: serializes cursor/commit/rollback on shared connection.
- `RuntimeController` state lock + inflight lock: lifecycle state and drain accounting.

Concurrency safety mechanisms:
- Dedup buckets via `EventBridge`.
- Follow-up claim ledgers (filled/cancelled namespaces) to prevent duplicate child creation.
- Replacement-slot claim accounting to enforce `max_order_replacement` under race.
- Stealth mutation claims (`move`, `reprice`, `retreat`) to prevent conflicting concurrent mutation.
- Cancel/re-entry policy evaluation runs before anchor repricing on ticker updates, so a policy-cancel decision wins over repricing the same revealed placement.

## Lifecycle State Machine

`RuntimeController` states:
- `RUNNING`: full admission.
- `PAUSING` -> `PAUSED`: no new originating work; cancels/fill handling continue.
- `DRAINING`: shutdown requested; no new originating work.
- `STOPPED`: terminal state.

Admission is enforced at dashboard and engine-originated entry points.
Inflight critical sections (`track_inflight`) allow graceful drain before stop hooks run.

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

1. `create_stealth_order` persists root order and in-memory state.
2. Bridge evaluator polls active stealth orders.
3. Condition evaluators decide when to transition to `TRIGGERED`.
4. Reveal plan resolves submitted price (`configured_limit`, `top_of_book`, or `midpoint`) and post-only policy.
5. Placement happens via REST. For placement client order IDs that differ from the stealth root, `StealthOrderManager.reveal_order_slice` pre-inserts the `order_parent` row before the REST attempt so a racing WS user-channel event does not create an orphan root. If REST raises or Coinbase returns a rejected placement, the reveal path records a failed reveal event but leaves revealed size, remaining size, and active placement pointers unchanged.
6. Reveal events and lifecycle transitions persist to audit/history tables.
7. Cancel/re-entry policy can cancel a no-fill revealed placement, return the stealth order to `HIDDEN`, and later re-enter through the existing reveal path when the market moves far enough away.
8. Same-side post-fill retreat can move the nearest opted-in hidden order on the same product/side by configured price ticks after another order fills.
9. Anchor repricing loop can mutate revealed orders under claim guards and applies any cumulative post-fill retreat offset before computing the next target.
10. Move-revealed flow executes cancel-and-replace with audit row insertion.

### Stealth State and Exchange Truth

Stealth status is operational state, not display-only metadata:
- `HIDDEN`, `PENDING`, and `TRIGGERED` mean no live Coinbase placement should exist for that stealth order.
- `REVEALED` means a placement was submitted and may still be resting on the exchange. The active placement is tracked in `anchor_repricing_state_json.active_placement_client_order_id` and `active_exchange_order_id` when known.
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
- Pull exchange open orders via REST.
- Pull local open view from `order_parent` (excluding terminal and pre-reveal stealth statuses).
- Diff into `unknown_to_local`, `open_on_exchange_terminal_locally`, `closed_on_exchange_open_locally`, `in_sync`.
- Optional safe auto-heal marks local-open/exchange-closed rows as `RECONCILED_CLOSED`.

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
- `order_id` is exchange-assigned and only used for exchange-side lookup/cancel/reporting.
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
