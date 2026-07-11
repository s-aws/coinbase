# Coinbase Admin MVP Goal

Goal ID: `legacy_fill_follow_up_operator_slice`

Last reviewed: 2026-07-10 UTC.

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

The guarded no-live compatibility slice is implemented on `main`:

- order and fill readback keyed by `client_order_id`;
- fill-event replay and live-readiness evidence;
- parent/child chain and flat-hierarchy readback;
- trigger admission preview;
- guarded no-live trigger execution with route-bound approval, wallet/cap,
  reconciliation, duplicate-claim, and audit-correlation prerequisites; and
- accepted child readback without Coinbase execution.

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

No default backend implementation step remains in this goal until the operator
approves automatic/live fill-event scope or new focused evidence identifies a
direct blocker in the current no-live operator slice.
