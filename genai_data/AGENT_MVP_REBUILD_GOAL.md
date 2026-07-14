# Coinbase Admin MVP Goal

Goal ID: `futures_exact_no_live_preview_slice_2`

Last reviewed: 2026-07-13 UTC.

Status: `active`

The canonical cross-repository authority is
`/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This backend copy
records the behavior-owner interpretation and must remain aligned with it.

## Completed Predecessor And Active Slice

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

Slice 2 is active by explicit operator authorization. It is fixed to the
permission-selected `Default`/`DEFAULT` portfolio, configured AVAX perpetual
`AVP-20DEC30-CDE`, and exactly one contract. The strict slice-local limits are
opening/reference notional `<100.00 USDC`, maximum concurrent exposure and a
fresh exact-position close reference multiplied by `1.20` `<150.00 USDC`, and
opening-plus-conservative-close branch turnover `<300.00 USDC`. A preliminary
read-only eligibility check observed conservative values of `64.80 USDC`,
`77.76 USDC`, and `142.56 USDC`, respectively, using the greater of the
product price and fresh best ask, and made zero Preview, Create, Cancel, Close,
or Reduce calls.

The first one-shot Slice 2 claim terminated fail-closed on 2026-07-13 before
Preview because the initial classifier assumed `status=online` and
`contract_expiry_type=PERPETUAL`. Coinbase instead returned the exact
`AVP-20DEC30-CDE` product as `AVAX PERP` with an empty status, all tradability
flags false, and the documented US CFM perp-style 2030 contract shape whose
expiry type is `EXPIRING`. Terminal evidence
`3b09cb9dfe02991dc886a1c6f041330d417ff11a0f1d45e3734bdc59bfb219b8`
records Preview `0`, exchange submissions `0`, and submitted/executed
notional `0`. The immutable claim remains consumed. The offline classifier is
now corrected and independently test-gated. The operator explicitly authorized
one fresh Slice 2R1 attempt in a new immutable artifact while preserving and
never modifying, deleting, or reusing the consumed Slice 2 artifact. R1 ran
exactly once on 2026-07-13 and stopped terminally before Preview because the
authoritative CFM intraday-margin setting did not match the explicitly accepted
setting values. Immutable R1 evidence
`a1b7820aa217b7119a6353a8f4fbffa5227ebfe5e4c8d8a1cde5449d370fc6f0`
records `futures_preview_margin_setting_ambiguous`, Preview `0`, every retry,
fallback, Create, Cancel, Close, and Reduce counter `0`, exchange submissions
`0`, and submitted/executed notional `0`. Its file SHA-256 is
`55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7`.
The R1 authorization is consumed and cannot be retried. Slice 2 is not
accepted and Slice 3 must not activate unless a distinct R2 terminal result is
accepted.

On 2026-07-14 the operator explicitly authorized official-primary-source enum
verification, the exact allowlist implementation, focused validation,
independent audit, and—effective only after those gates—one distinct Slice 2R2
Preview-only attempt. Official Coinbase Advanced Trade GET and SET documentation
defines exactly `INTRADAY_MARGIN_SETTING_UNSPECIFIED`,
`INTRADAY_MARGIN_SETTING_STANDARD`, and
`INTRADAY_MARGIN_SETTING_INTRADAY`. R2 records all three as documented while
permitting only `STANDARD` or `INTRADAY` to reach Preview; `UNSPECIFIED`, legacy
tokens, malformed shapes, unknown margin-window tokens, enabled or ambiguous
killswitches, nonempty sweeps, and incomplete margin evidence stop before
Preview.

The primary enum evidence is Coinbase's official Advanced Trade
[`Get Intraday Margin Setting`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-intraday-margin-setting)
and [`Set Intraday Margin Settings`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/set-intraday-margin-settings)
documentation. The adjacent official
[`Get Current Margin Window`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-current-margin-window)
contract supplies the fixed window and killswitch fields. No SDK-inferred or
newly observed token may broaden these exact allowlists.

The authorized R2 artifact is fixed to
`artifacts/futures_exact_no_live_preview_slice_2r2.jsonl` and binds the exact
immutable R1 file plus R1's exact original Slice 2 predecessor. It permits the
fixed permission, portfolio, product, market, position, balance,
intraday-margin-setting/window, and sweep reads and at most one Preview call.
It permits zero retries, fallbacks, Create, Cancel, Close, Reduce, marker,
ledger, runtime, or other exchange mutation. Raw account and margin responses
and external exception text are never persisted; only strict sanitized evidence
and hashes are operator-visible. An unknown Preview outcome consumes R2 and may
not be retried. At the pre-attempt checkpoint, R2 was absent and all Coinbase
and Preview attempt counters were zero.

Focused backend/frontend validation, exact contract freshness, transport
exact-once tests, and independent safety plus blind contextless audits passed.
R2 then ran exactly once on 2026-07-14 and stopped terminally after enum
diagnostic capture but before complete candidate/request-context capture or
Preview. Its immutable artifact is
`artifacts/futures_exact_no_live_preview_slice_2r2.jsonl`, file SHA-256
`1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053`,
and evidence SHA-256
`afebf81c4d95c0abd7635fd700f6618e92191423173df3e2db0f875102b6f1c9`.
The terminal blocker is the intentionally redacted
`preflight_or_preview_blocked:ValueError`. Typed sanitized evidence proves
Coinbase returned `INTRADAY_MARGIN_SETTING_INTRADAY`, with documented-enum and
operational allowlist matches both true and raw response inclusion false.
Therefore the official setting enum was not the blocker. Code-path and artifact
shape confine the failure interval to remaining margin validation,
candidate/request construction, or context sanitization; the exact condition
was deliberately not persisted and must not be guessed.

All six aggregate preflight-read counters are exactly `1`. Preview, retry,
fallback, Create, Cancel, Close, and Reduce counters are `0`; exchange
submissions, submitted notional, and executed notional are `0`. Admin API
readback returns HTTP `200` with live execution disabled. R2 is consumed and
cannot be retried. Slice 2 is not accepted and Slice 3 remains inactive; a
distinct attempt requires a new explicit operator decision.

After implementation, focused validation, and independent audit passed, the
authorized distinct R3 command ran exactly once on 2026-07-14. R3 stopped
terminally before Preview at sanitized stage `remaining_margin_validation`
with reason `futures_preview_margin_windows_ambiguous`. Its immutable artifact
is `artifacts/futures_exact_no_live_preview_slice_2r3.jsonl`, file SHA-256
`7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c`,
and evidence SHA-256
`e79beb3d9f1324cf8f90ba78cd45869fec5b7963afe3745bd6e26617313718e8`.
All six aggregate read counters are exactly `1`; Preview, retry, fallback,
Create, Cancel, Close, and Reduce counters are `0`; exchange submissions and
submitted/executed notional are `0`. The diagnostic is canonically hashed and
records no raw response, external exception text, or identifiers. The exact
margin-setting token remains documented and operationally accepted as
`INTRADAY_MARGIN_SETTING_INTRADAY`; no candidate, Preview request, Preview
response, or seal-ready plan was created. Admin API readback is HTTP `200`
with live execution disabled. R1, R2, and R3 are consumed and immutable; there
is no remaining Preview or exchange-call authority. Slice 2 is not accepted,
Slice 3 remains inactive, and any distinct follow-up attempt or offline
diagnosis requires a new explicit operator decision.

`Default-profile Futures readback -> exact AVAX US CFM Coinbase Preview Order -> immutable operator-visible no-live preview readback`

## Ordered Sequence — Slice 2 Active

Continue implementation and independent audit only in this order. Prospective
operator authority permits crossing documented no-live acceptance boundaries,
but never an exact-hash live execution gate:

1. `futures_exact_no_live_preview_slice_2`: at most one backend-derived
   Default-profile US CFM Coinbase Preview Order call for AVAX perpetual
   `AVP-20DEC30-CDE` and exactly one contract/order candidate under the strict
   `<100.00 USDC` opening, `<150.00 USDC` exposure/buffered-close, and
   `<300.00 USDC` branch-turnover limits. Bind product
   metadata, exact decimals, market freshness, fees, margin/collateral,
   liquidation, caps, idempotency, and correlation. Zero create/cancel/close
   submissions, marker, ledger, or runtime. The one-shot backend tool may call
   Preview; the repeatable Admin API/UI path reads immutable evidence and calls
   Coinbase zero times. Failure after the one Preview attempt is fail-closed
   with no retry.
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
   Opening reference is `<100.00 USDC`, maximum concurrent exposure is
   `<150.00 USDC`, the fresh exact-position close reference times `1.20` is
   `<150.00 USDC`, and opening-plus-conservative-close branch turnover is
   `<300.00 USDC`; an ineligible branch prevents placement.
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
`<100.00 USDC`, maximum concurrent exposure `<150.00 USDC`, conservative
unpriced close reference (`fresh exact-position reference * 1.20`)
`<150.00 USDC`, and aggregate opening-plus-conservative-close turnover
`<300.00 USDC`. The plan hash
explicitly acknowledges the unpriced Coinbase Close Position policy. A proven
price-protected replacement requires a revised seal. One opening and one
conditional close are the maxima, with zero retries.

The operator prospectively authorized Slices 3, 4, and 5 no-live implementation
and independent audit in order once each predecessor is accepted. If Slice 3
reaches its exact-hash live checkpoint while the operator is unavailable, that
checkpoint remains an explicit blocker while only Slices 4 and 5 no-live work
may continue. No prospective statement authorizes a marker, ledger, runtime,
Create, Cancel, Close, Reduce, or any other exchange mutation.

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
inherit a generic runner cap. It must seal the exact slice-local `<100.00`
opening, `<150.00` exposure/buffered-close, and `<300.00 USDC` turnover
bounds.

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

Slices 1 and 2 inspected backend `origin/prod` references
`configuration.py::get_futures_positions`,
`external/coinbase_client.py` Futures position reads,
`core/order_engine.py::refresh_positions_if_needed`, and
`core/order_engine.py::process_user_snapshot`. They confirm historical
position reads but lack safe profile binding, Preview Order, `preview_id`, and
authoritative margin-preview behavior. The current implementation keeps the
behavior backend-owned and does not restore the dashboard WebSocket as frontend
authority.

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

Slice 2 is active. Prospectively authorized no-live successor work may continue
only in order after documented predecessor acceptance; exact-hash live gates
remain hard stops. Fan-out, multi-product automation, schedulers, unattended
loops, generic runtime/retry/recovery tightening, wallet-ledger expansion,
ladders/grids, unrelated domain work, and broad cleanup remain parked.

Standing order-level limits constrain later approved plans but do not activate
them. The operator explicitly authorized the AVAX sequence-local exception of
`<100.00 USDC` opening, `<150.00 USDC` exposure/buffered close, and
`<300.00 USDC` branch turnover. Fill status is an outcome, not a permission
class. The same Default profile, margin, cap, authorization, audit,
reconciliation, rollback, and readback gates apply whether an order rests,
partially fills, or fills.

Use focused tests for ordinary changes. Run full backend/frontend suites only
at durable milestone, release/deployment, cross-repository closeout, after
broad cross-cutting changes, or when explicitly requested.
