# Coinbase Admin MVP Goal

Goal ID: `legacy_fill_follow_up_operator_slice`

Last reviewed: 2026-07-11 UTC.

The canonical cross-repository goal is
`/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This backend copy
records the behavior-owner interpretation and must stay aligned with it.

## Objective

Restore the shortest operator-usable workflow from `origin/prod` through the
current backend-owned Admin API:

`Admin order -> fill/readback evidence -> follow-up decision -> operator-visible parent/child chain`

The Admin frontend is operator UI only. The backend owns validation,
authorization, wallet and cap checks, fill handling, follow-up claims,
Coinbase calls, reconciliation, rollback, and audit persistence.

## Previous-Version Baseline

Legacy source material is backend `origin/prod` commit
`9bc7834584be9da4a7818acea0531dc220737378`, especially:

- `dashboard_server.py` for the old operator command surface;
- `core/order_engine.py` for fill and flat parent/child follow-up behavior;
- `integration/fill_event_hooks.py` and `business/post_fill_hook.py` for fill
  lifecycle integration;
- fill/follow-up claim, partial-fill, deduplication, and hierarchy tests; and
- `order.py:create_limit_order_span`, `ui_order_span_builder.html`, and legacy
  ladder-generation tests for the parked single-product order-set idea. The
  random-ladder test imports an untracked `genai_tools` implementation, so it
  is behavioral clue rather than recoverable source authority.

The legacy dashboard WebSocket remains compatibility source material. It is
not authority for new frontend product behavior.

## Current State

The guarded no-live compatibility contract and injected operator path are
implemented on `main`:

- order and fill readback keyed by `client_order_id`;
- fill-event replay and live-readiness evidence;
- parent/child chain and flat-hierarchy readback;
- trigger admission preview;
- guarded no-live trigger execution with route-bound approval, wallet/cap,
  reconciliation, duplicate-claim, and audit-correlation prerequisites; and
- accepted child readback without Coinbase execution in focused injected
  contract tests.

The operator selected single-process embedding with the canonical live engine.
`main.py` now has an opt-in embedded FastAPI server that validates exact
engine/bridge/manager/orderbook identity, strictly hydrates before binding,
serves reads while mutations remain gated, and starts bridge/engine producers
only after the bind. Mutations open after an authenticated `user` subscription
acknowledgement from the same retained WebSocket worker and reclose when that
worker's actual socket or the user-event consumer is lost. Hidden SDK retries
are disabled for this proof boundary; terminal loss synchronously closes
runtime admission and starts the canonical drain. Bridge reveal, reprice, and
reentry entry points honor that state so cached ticker data cannot originate a
new placement during the drain handoff. Ingress stops before bridge and engine
shutdown, and queued user events remain represented in drain accounting until
the consumer exits.

Focused synthetic coverage proves the production handler and real claim kernel
create one hidden child for duplicate FILLED inputs. The child ID is
restart-stable from the filled placement, its `order_parent` and `stealth_orders`
rows commit atomically before in-memory publication, and chain readback requires
both sources. Explicit no-child outcomes release the claim; ambiguous creation
or persistence exceptions remain `processing` instead of being misreported as
terminal success. Restart hydration rebuilds native JSONB placement lookup.

The embedded mode is disabled by default. The deployed
`tools/run_admin_api.py` app-only runner intentionally remains fail-closed.
Activating `COINBASE_ADMIN_API_EMBEDDED_ENABLED=true` necessarily runs inside
the automatic/live fill-event engine, so activation and a process-level fill
proof remain behind the separate explicit fill-testing decision.

The remaining legacy-parity gap is automatic/live fill-event processing. That
scope requires explicit fill-testing approval plus live-fill,
wallet/cap/reconciliation, duplicate-order, audit-correlation, rollback, and
readback evidence.

## Closed Scope Rule

Default work must implement a missing step in the current vertical slice,
remove a blocker demonstrated by a failing focused test or runtime observation
on that slice, or prevent an immediate critical safety failure on that slice.

A candidate blocker cannot make itself in scope by generating evidence about the candidate blocker.

Fan-out, scheduler, runtime-control, retry/recovery, wallet-ledger, unrelated
futures evidence, broad stealth/repricing expansion, ladder/grid order sets,
and phase-range tightening remain parked. Their unresolved blockers prevent
those features from running; they do not make those features current work.

When the no-live slice is clean and no direct blocker is demonstrated, stop
and request a scope decision. Do not continue from the highest-rated parked
blocker.

## Safety And Validation

- Preserve one behavior path. Admin routes must call existing backend domain
  services and claim mechanisms rather than reimplementing fill/follow-up
  logic.
- Preserve `client_order_id` as operator and local identity. Exchange
  `order_id` is evidence or an exchange-required parameter only.
- Preserve the flat hierarchy: every child links to the original root parent.
- Keep live execution fail-closed on authorization, idempotency, cap/wallet,
  duplicate claims, audit, reconciliation, rollback, and readback evidence.
- Standing notional, distance, count, and rate limits in the canonical goal
  remove only a separate approval request. They do not prioritize parked work
  or authorize fill testing.
- Use focused tests for ordinary changes. Run full backend/frontend suites only
  for durable milestone, release/deployment or cross-repository association
  closeout, broad cross-cutting changes, or explicit operator request.

No additional no-live implementation lane remains. The selected topology is
implementation-ready but deliberately inactive; automatic/live fill-event
activation and validation require separate explicit fill-testing approval.
