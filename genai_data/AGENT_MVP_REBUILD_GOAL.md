# Coinbase Admin MVP Goal

Goal ID: `selected_chain_child_cancel_v15_slice`

Last reviewed: 2026-07-12 UTC.

Status: `in_progress`

The canonical cross-repository goal is
`/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This backend copy
records the behavior-owner interpretation and must stay aligned with it.

## Objective

Implement and seal the shortest operator-visible mutation adjacent to the
restored fill/follow-up closeout through the current backend-owned Admin API
and operator UI:

`Selected Admin root with one active deterministic first child -> sealed-plan-bound backend cancel readiness -> exactly-once child cancel -> authoritative local/exchange terminal readback -> refreshed operator-visible closeout`

The Admin frontend is operator UI only. The backend owns validation,
authorization, wallet and cap checks, fill handling, follow-up claims,
Coinbase calls, reconciliation, rollback, and audit persistence.

The current authorization is implementation, independent audit, and
preparation of one owner-only V15 Test-profile BTC-USDC plan. It binds exactly
two future exchange-submission attempts (one intentional-fill root and one
deterministic first child) plus exactly one `client_order_id`-bound child-cancel
command, with root notional below `9.99 USDC`, child notional at or below
`2.00 USDC`, aggregate reference notional below a new slice-local `12.00 USDC`
cap, and a 120-minute plan lifetime. No marker, ledger, runtime, approval
record, root, child, cancel command, or live Coinbase order is authorized until
the resulting plan hash receives a separate exact operator approval.

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
reads. The operator has now selected the sealed V15 deterministic-first-child
cancel successor. A predicted fill, non-fill, or far-from-market outcome does
not add or remove permission, and there is no separate no-fill, fill-testing,
or live-fill approval category.

V15 durable no-live validation passed after the final independent audit.
Backend `python3.13 tools/run_parallel_regression.py --workers 4` passed
`1461/1461` tests (`1005` parallel plus `456` serial), ownership, and diff
checks with live Coinbase execution false and submitted/executed notional
`0 USDC`; evidence is under
`genai_tools/pytest-tmp/parallel-regression/b077499ed98d43f0a24316d18df7691d/`.
The synchronized frontend baseline passed `563/563` unit tests and `8/8`
Playwright tests with live execution `not_run` and notional `0 USDC`. The
canonical release gate is rerun after the final backend/frontend commit
association and before plan preparation.

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

The current authorized milestone ends after the committed implementation is
independently audited and an immutable V15 plan is prepared without creating a
marker, ledger, runtime, approval record, or order. Stop there and request exact
approval of the resulting plan hash. The frontend action must remain absent or
disabled until that hash is active in the same embedded backend runtime.

The live path must resolve the exact deterministic child from the selected root
in the backend, bind the plan hash through durable preparation and one
crash-safe cancel-command claim, call the existing controlled child-cancel
service exactly once by `client_order_id`, prohibit the exchange-id fallback
for V15, and require terminal zero-fill exchange/local readback. The 120-minute
expiry closes new V15 execution starts; once the sealed marker proves the root
and child slice started inside that window, the exact active-child cleanup and
read-only reconciliation authority remains available so expiry or parent loss
cannot strand the child. It never authorizes another placement or a second
cancel boundary.
Do not select a parked lane merely because it has a blocker or is next in a
roadmap.
