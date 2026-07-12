# Coinbase Admin MVP Goal

Goal ID: `selected_order_execution_closeout_slice`

Last reviewed: 2026-07-12 UTC.

Status: `complete`

The canonical cross-repository goal is
`/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This backend copy
records the behavior-owner interpretation and must stay aligned with it.

## Objective

Close the restored operator workflow through the current backend-owned Admin
API and operator UI:

`Selected Admin root -> client_order_id-bound fill-ledger and audit readback -> child terminal-cancel proof -> read-only recovery posture -> operator-visible execution closeout`

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
the automatic/live fill-event engine. Activation does not create or grant a
separate permission class: every order processed by that engine is governed by
the canonical goal's explicit side, price, notional, rate, and cancellation
limits plus backend authorization, wallet, cap, audit, reconciliation,
rollback, and readback gates, whether the order ultimately fills or not.

V14 completed automatic/live fill-event parity for ten Test-profile Spot roots
and ten first-child submissions under the approved `30.00 USDC` reference cap.
Every root was authoritatively FILLED, every child was authoritatively CANCELLED
with zero child fill, every final chain was flat with active placement cleared,
the final active-order count was zero, and shutdown was quiescent. The frontend
then completed the read-only selected-root closeout against those backend-owned
reads. No next work item is selected. A predicted fill, non-fill, or
far-from-market outcome does not add or remove permission, and there is no
separate no-fill, fill-testing, or live-fill approval category.

Durable closeout validation passed after the final selected-root fixes. Backend
`python3.13 tools/run_parallel_regression.py --workers 4` passed `1458/1458`
tests (`1005` parallel plus `453` serial), ownership, and diff checks with live
Coinbase execution false and submitted/executed notional `0 USDC`; evidence is
under
`genai_tools/pytest-tmp/parallel-regression/4f87afaef742452b83c938640c168c14/`.
The frontend baseline and canonical release gate passed `548/548` unit tests,
`8/8` Playwright tests, focused deploy `142/142`, all
deployment/backend/local-stack/dry smokes, and managed-process cleanup while
reporting live execution `not_run` and notional `0 USDC`.

## Closed Scope Rule

Default work must implement a missing step in the current vertical slice,
remove a blocker demonstrated by a failing focused test or runtime observation
on that slice, or prevent an immediate critical safety failure on that slice.

A candidate blocker cannot make itself in scope by generating evidence about the candidate blocker.

Fan-out, scheduler, runtime-control, retry/recovery, wallet-ledger, unrelated
futures evidence, broad stealth/repricing expansion, ladder/grid order sets,
and phase-range tightening remain parked. Their unresolved blockers prevent
those features from running; they do not make those features current work.

When the current slice is complete and no direct blocker is demonstrated,
stop. Do not continue from the highest-rated parked blocker. A live order that
is part of this slice remains governed by the canonical order-level limits and
backend gates; do not invent an additional decision based on whether the order
is expected to fill.

## Safety And Validation

- Preserve one behavior path. Admin routes must call existing backend domain
  services and claim mechanisms rather than reimplementing fill/follow-up
  logic.
- Preserve `client_order_id` as operator and local identity. Exchange
  `order_id` is evidence or an exchange-required parameter only.
- Preserve the flat hierarchy: every child links to the original root parent.
- Keep live execution fail-closed on authorization, idempotency, cap/wallet,
  duplicate claims, audit, reconciliation, rollback, and readback evidence.
- The canonical goal's explicit live-order side, price/distance, notional,
  count/rate, and cancellation limits govern every order together with backend
  authorization, wallet, cap, audit, reconciliation, rollback, and readback
  gates. Fill status is an outcome, not a permission class; do not create a
  separate no-fill, non-fill, fill-testing, or live-fill approval requirement.
- Those order-level limits do not prioritize parked work or waive any backend
  gate.
- Use focused tests for ordinary changes. Run full backend/frontend suites only
  for durable milestone, release/deployment or cross-repository association
  closeout, broad cross-cutting changes, or explicit operator request.

The selected slice is complete. Do not select a parked lane merely because it
has a blocker or is next in a roadmap. Any future automatic/live activation or
mutating child action requires a new operator-selected scope and continues to
use the canonical order-level limits and backend gates; activation itself is
not a second permission source.
