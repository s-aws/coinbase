# Coinbase Admin MVP Goal

Goal ID: `futures_default_profile_readback_slice_1`

Last reviewed: 2026-07-13 UTC.

Status: `complete`

The canonical cross-repository authority is
`/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This backend copy
records the behavior-owner interpretation and must remain aligned with it.

## Completed Slice

`Default-profile Futures account -> authoritative US CFM position list -> exact portfolio-scoped position detail -> operator-visible no-live readback`

The backend now selects the Futures portfolio exclusively from the API-key
permissioned UUID and requires one matching catalog record named `Default`,
typed `DEFAULT`, and `can_view=true`. It reads CFM positions and
margin/collateral only after that binding succeeds. Raw `can_trade` is
credential capability evidence, not Admin command authority.

Position identity is
`futures_position:{portfolio_uuid}:{product_id}`. Exact detail and close/reduce
preflight must resolve that key from fresh authoritative positions; a product
alias, stale key, caller-supplied product contradiction, oversized close, or
wrong profile fails before any exchange call.

Spot and Futures authority are deliberately separate. A Default key and wallet
balance cannot satisfy Spot admission. Spot requires the configured exact Test
portfolio UUID, `Test`/`CONSUMER`, `can_view=true`, and `can_trade=true`.

Slice 1 made no order, cancel, close, reduce, marker, ledger, runtime, or local
approval mutation. Live Coinbase execution is `not_run` and notional is
`0 USDC`.

## Ordered Successors — Not Execution Authority

Continue implementation and independent audit only in this order, stopping for
explicit operator activation after every no-live acceptance boundary:

1. `futures_exact_no_live_preview_slice_2`: one backend-derived Default-profile
   US CFM Coinbase Preview Order call for one configured product and one contract/order
   candidate below the preferred `30.00 USDC` reference limit. Bind product
   metadata, exact decimals, market freshness, fees, margin/collateral,
   liquidation, caps, idempotency, and correlation. Zero create/cancel/close
   submissions, marker, ledger, or runtime. Stop for operator activation before
   implementation and again before Slice 3 preparation.
2. `futures_terminal_order_roundtrip_slice_3`: separately implement, audit,
   seal, and exactly approve one resting order, authoritative OPEN readback,
   at most one exchange-ID cancel resolved from its `client_order_id`, and
   terminal CANCELLED/zero-active readback. Zero retries and fallback calls.
   The same sealed plan must include an independently audited risk-off close
   primitive before placement: PARTIAL permits at most one residual cancel and
   one exact-delta close, FILLED permits zero cancel and one exact-delta close,
   and unknown outcomes consume the placement claim and permit read-only
   reconciliation plus only the already-sealed close if a nonzero delta becomes
   authoritative. Exact approval activates each separately claimed conditional
   cancel or risk-off close. Exit restores the pre-order position baseline.
   Opening reference is `<25.00 USDC`, maximum concurrent exposure is
   `<30.00 USDC`, the fresh exact-position close reference times `1.20` is
   `<30.00 USDC`, and opening-plus-conservative-close branch turnover is
   `<55.00 USDC`; an ineligible branch prevents placement.
3. `futures_intentional_fill_position_readback_slice_4`: implement and audit,
   with zero live execution, one marketable contract plus authoritative
   fill/fee/position-delta readback. The later live proof requires a Coinbase
   Preview Order-accepted, exchange-auto-terminal FOK or IOC configuration; GTC
   or any residual-active opening is ineligible. A create must bind Coinbase
   `preview_id` to the identical payload. Marketable price needs explicit
   concrete order authority; this is not a separate fill-testing permission.
   Stop and activate Slice 5 implementation; the live Slice 4 checkpoint
   remains pending.
4. `futures_position_closeout_slice_5`: implement and audit, with zero live
   execution, exact-position closeout derived from fresh authoritative
   readback. After acceptance, stop. Only a later combined sealed plan may run
   the Slice 4 opening/fill checkpoint followed immediately, without an
   approval pause, by the Slice 5 one-attempt close. Exit requires flat/absent
   position, zero active orders, refreshed margin/collateral, fees, notional,
   audit, and reconciliation.

The combined 4/5 plan uses exact numeric semantics: opening reference notional
`<25.00 USDC`, maximum concurrent exposure `<30.00 USDC`, conservative unpriced
close reference (`fresh exact-position reference * 1.20`) `<30.00 USDC`, and
aggregate opening-plus-conservative-close turnover `<55.00 USDC`. The plan hash
explicitly acknowledges the unpriced Coinbase Close Position policy. A proven
price-protected replacement requires a revised seal. One opening and one
conditional close are the maxima, with zero retries.

## Shared Successor Safety

Every live plan binds canonical JSON/SHA-256, a maximum 120-minute TTL or
shorter evidence expiry, backend/OpenAPI revisions, exact
`actor=operator-controlled-futures-proof`, and BFF role `trader`. It binds fresh
unique permission-selected `Default`/`DEFAULT` portfolio evidence with
`can_view=true`, `can_trade=true`, no request override, US CFM family and
explicit INTX exclusion, including permission/catalog hashes and timestamps.

For every attempt it binds route, method, service method, permission, product,
side, contracts, order configuration, identity, request payload hash, market
timestamp, per-attempt submitted/executed caps, exposure/turnover caps,
idempotency/correlation IDs, attempt maximum, branches, and stop conditions.
Create Order binds an identical-payload Coinbase `preview_id`; cancel binds the
authoritative exchange `order_id` resolved from sealed `client_order_id`; the
unpriced close binds the exact position snapshot/hash, fresh mark/reference,
and `1.20` buffer rather than inventing a preview ID. The seal also binds
approval, admission, cap-guard, reconciliation, live-service, adapter,
margin/collateral/liquidation and fee/funding evidence IDs/hashes and cannot
inherit a `100.00 USDC` runner default.

Before each SDK call, a durable atomic one-use semantic claim binds plan hash,
action index/kind, portfolio, product, and operator identity or position
snapshot. A new idempotency key cannot repeat the same semantic action. Unknown
outcomes leave the claim consumed and permit reads only, except for a separately
claimed risk-off branch already in the seal. Preparation is read/preflight only
and creates no marker, ledger, runtime, or exchange authority. Exact hash
approval activates only named artifacts and actions.

The browser remains operator UI only. It never selects a portfolio, calculates
trading readiness, manufactures order identity, calls Coinbase, or grants
authority. `client_order_id` is operator identity; `order_id` is exchange
evidence or an exchange-required submission parameter.

## Legacy Translation

Slice 1 inspected backend `origin/prod` references
`configuration.py::get_futures_positions`,
`core/order_engine.py::refresh_positions_if_needed`, and
`core/order_engine.py::process_user_snapshot`. They confirm historical
position reads but lack safe profile binding. The current implementation keeps
the behavior backend-owned and does not restore the dashboard WebSocket as
frontend authority.

## Predecessor Completion

The selected-chain V15 Spot goal is resolved. Plan
`bbe5d85c38bbea42f4326c7a8d250d77c632875721d843aefd048a016b129559`
used one authoritative exchange-ID cancel submission, zero client-ID exchange
submissions, fallbacks, retries, or placements. Its child is CANCELLED with
zero fill, active placement cleared, zero active Test Spot orders, and disabled
service/runtime. Evidence:
`artifacts/controlled-root-child-batch-20260713T101046Z-ed9b8bbd/v15r6-terminal-closeout-handoff.json`.

## Scope And Validation

Default work may implement only an explicitly active slice, remove a focused
test/runtime blocker causally preventing it, or prevent an immediate
authorization, duplicate-order, cap, wallet, data-loss, audit,
reconciliation, rollback, or traceability failure on it.

A candidate blocker cannot make itself in scope by generating evidence about the candidate blocker.

Because Slice 1 is complete and no successor is active, stop and request
operator activation of Slice 2. Fan-out, multi-product automation, schedulers,
unattended loops, generic runtime/retry/recovery tightening, wallet-ledger
expansion, ladders/grids, unrelated domain work, and broad cleanup remain
parked.

Standing order-level limits constrain later approved plans but do not activate
them. Fill status is an outcome, not a permission class. The same Default
profile, margin, cap, authorization, audit, reconciliation, rollback, and
readback gates apply whether an order rests, partially fills, or fills.

Use focused tests for ordinary changes. Run full backend/frontend suites only
at durable milestone, release/deployment, cross-repository closeout, after
broad cross-cutting changes, or when explicitly requested.
