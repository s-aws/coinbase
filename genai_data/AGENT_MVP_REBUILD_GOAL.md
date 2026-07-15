# Coinbase Admin MVP Goal

Goal ID: `futures_exact_no_live_preview_slice_2`

Last reviewed: 2026-07-15 UTC.

Status: `blocked — Slice 2R6 prepared no-live; exact R6 execution authorization required`

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

Slice 2 remains the current slice. The authorized R5 integration and one-use
attempt are complete, but R5 stopped before Preview because the exact
`retail_regular` margin-window state was the documented but operator-rejected
`MARGIN_WINDOW_TYPE_UNSPECIFIED`. Its fixed scope is the
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

After explicit R4 authorization, the fixed one-use command and its restricted
read/Preview-only client boundary were implemented and pushed at backend commit
`8435bf0b`. Focused validation and two independent pre-execution audits passed,
including adversarial proof that malformed or unknown Preview response fields
cannot leak or prevent a terminal result. The R4 command then ran exactly once
on 2026-07-15 and stopped terminally before Preview at sanitized stage
`remaining_margin_validation` with reason
`futures_preview_margin_windows_ambiguous`. Its immutable artifact is
`artifacts/futures_exact_no_live_preview_slice_2r4.jsonl`, file SHA-256
`90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf`,
and evidence SHA-256
`0edeffdb0702ba119a7d9c3e32874b75e295ee596538432df5f7be0a67a4af3e`.
The operational typed setting remains
`INTRADAY_MARGIN_SETTING_INTRADAY`; the margin-window diagnostic classification
is `margin_window_type_not_exact_operational_enum_token` and deliberately
withholds the unknown value, raw responses, identifiers, and external exception
text. All six aggregate read counters are exactly `1`. Preview, retry, fallback,
Create, Cancel, Close, and Reduce counters are `0`; exchange submissions,
submitted notional, and executed notional are `0`; no marker, ledger, or runtime
was created. Default Admin API readback now selects R4 and returns HTTP `200`
with live execution disabled, and the focused frontend R4 diagnostic view passes.
An independent post-execution audit recomputed the artifact, evidence, and typed
diagnostic hashes and returned `PASS`. R4 is consumed and cannot be retried.
Slice 2 is not accepted, Slice 3 remains inactive, and any offline diagnosis or
distinct follow-up attempt requires a new explicit operator decision.

On 2026-07-15 the operator authorized offline-only diagnosis of the consumed R4
margin-window ambiguity, focused validation, independent audit, and preparation
of proposed distinct R5 wording. That authority granted no Coinbase call,
Preview attempt, exchange mutation, marker, ledger, runtime, or production
implementation. The diagnosis localized the exact failure boundary: R4 proves
that the response container, row `0`, recognized `retail_regular` profile,
ready status, nested margin-window mapping, field presence, string type,
trimming, and safe-token form all passed. The returned value then failed the
singleton operational allowlist `{MARGIN_WINDOW_TYPE_INTRADAY}`. Because the
classifier raised at that point, R4 does not prove the literal token,
`end_time`, kill-switch values, row `1`, sweeps, or the later positive-margin
check.

The consumed artifact intentionally makes the token unrecoverable. The
installed official Coinbase SDK describes Get Current Margin Window as
selecting intraday versus overnight rates but models `margin_window_type` only
as `str`. R4 ran at approximately 23:57 Eastern, making an overnight semantic
state plausible, while a cached official example uses
`MARGIN_WINDOW_TYPE_UNSPECIFIED`; neither clue proves the returned literal.
The separate `FCM_MARGIN_WINDOW_TYPE_*` balance-summary values are a different
field and cannot be converted into a REST allowlist. No offline evidence
justifies exposing or accepting `OVERNIGHT`, `UNSPECIFIED`, `WEEKEND`,
`TRANSITION`, or any other inferred value.

Focused validation passed `44` margin-window/R4 tests, including immutable
predecessor binding, default operator readback, sanitized diagnostic behavior,
unknown-token rejection, and terminal zero-Preview behavior. Independent
forensic and safety audits agree that R5 must first verify the exact REST enum
and profile/state semantics from official Coinbase primary sources. All five
consumed artifacts remain byte-identical and retain their original hashes and
read-only metadata. No code, schema, diagnostic version, allowlist, profile
policy, R5 claim, or R5 artifact was created during this diagnosis.

The operator then granted the exact proposed R5 primary-source verification
authorization, with implementation and a single Preview attempt effective only
if both enum and profile/state semantics were unambiguous. Coinbase's official
generated [`Get Current Margin Window` schema](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-current-margin-window.md)
defines the REST response enum
exactly as `MARGIN_WINDOW_TYPE_UNSPECIFIED`,
`MARGIN_WINDOW_TYPE_OVERNIGHT`, `MARGIN_WINDOW_TYPE_WEEKEND`,
`MARGIN_WINDOW_TYPE_INTRADAY`, and `MARGIN_WINDOW_TYPE_TRANSITION`. The
retrieved official Markdown SHA-256 is
`3bcf6504cb092e2565c604ff6938682de2652d662be415612d51a0c28b82db3c`.
It also defines the regular and intraday query-profile literals.

The required operational semantics remain ambiguous. The official schema has
no profile-to-state mapping or operational eligibility definition. The
[official SDK](https://coinbase.github.io/coinbase-advanced-py/coinbase.rest.html#coinbase.rest.RESTClient.get_current_margin_window)
discusses only intraday versus overnight rates, not weekend, transition, or
allowed profile combinations. As verified on 2026-07-15,
[Coinbase Help](https://help.coinbase.com/en/coinbase/derivatives/us-derivatives-leverage-margin)
says `6pm-4pm ET`, while the official SDK and
[`Set Intraday Margin Setting`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/set-intraday-margin-settings)
documentation say `8am-4pm ET`. The operator subsequently clarified that
`8am-4pm` applies to futures and `6pm-4pm` applies to perpetuals. Neither
schedule is converted into a local clock, holiday, or profile-to-state rule.
The distinct `FCM_MARGIN_WINDOW_TYPE_*` balance enum cannot fill that gap.

Per the authorization's explicit stop clause, blocker
`futures_preview_margin_profile_state_semantics_ambiguous` prevented all R5
implementation and creation. No operational allowlist/profile-policy change,
diagnostic V2, schema, path, CLI, claim, or artifact exists. No Coinbase API,
credential, Preview, retry, redirect, fallback, mutation, marker, ledger, or
runtime call occurred. Default readback and the production entrypoint remain
fixed to immutable R4. The conditional R5 attempt authority never activated.
The operator then explicitly authorized the second path: an
operator-defined, Slice-2-Preview-only policy that independently accepts the
four documented non-`UNSPECIFIED` states for both exact profiles without
representing that profile/state mapping as Coinbase-documented behavior. The
versioned V2 policy accepts exactly `MARGIN_WINDOW_TYPE_OVERNIGHT`,
`MARGIN_WINDOW_TYPE_WEEKEND`, `MARGIN_WINDOW_TYPE_INTRADAY`, or
`MARGIN_WINDOW_TYPE_TRANSITION` for each of
`MARGIN_PROFILE_TYPE_RETAIL_REGULAR` and
`MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1`.
`MARGIN_WINDOW_TYPE_UNSPECIFIED` is documented but rejected; unknown,
malformed, FCM-prefixed, non-string, and unknown-profile values are withheld
and rejected.

Typed V2 evidence identifies the enum authority as official Coinbase
documentation and the profile/state mapping authority as
`operator_defined_slice_2_preview_only_not_coinbase_documented`. It fixes
R5-attempt authority, execution allowance, Create eligibility, and later-live
eligibility to `false`. The operator then authorized the exact R5 integration,
audits, and one-use Preview attempt. Backend commit `48051bb3` and frontend
commit `979e7fd0` were pushed before execution. The fixed preflight validated
the complete R4-to-original chain and created no artifact or Coinbase client.

R5 ran exactly once on 2026-07-15 and stopped terminally before Preview at
sanitized stage `remaining_margin_validation` with reason
`futures_preview_margin_windows_ambiguous`. The immutable artifact is
`artifacts/futures_exact_no_live_preview_slice_2r5.jsonl`, file SHA-256
`4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7`,
and evidence SHA-256
`194cdd842944f8a453408051c04ff8e117b6b2b3ab6dcd7b1e78f44f4a5a467f`.
The operational setting remains the documented
`INTRADAY_MARGIN_SETTING_INTRADAY`. V2 margin-window evidence records
`retail_regular=MARGIN_WINDOW_TYPE_UNSPECIFIED`, which is documented but
operator-rejected, and
`retail_intraday_margin_1=MARGIN_WINDOW_TYPE_INTRADAY`, which is accepted.
Raw responses, external exception text, and unknown identifiers are absent.
All six fixed read counters are `1`; Preview, retry, fallback, Create, Cancel,
Close, Reduce, and exchange-submission counters are `0`; submitted/executed
notional is `0 USDC`; no marker, ledger, or runtime was created. Default Admin
API/UI readback now selects this immutable model-valid R5 result. R5 is
consumed and cannot be retried. Slice 2 is not accepted, Slice 3 remains
inactive, and continuing requires a distinct explicit operator decision.

The operator has now authorized and completed offline R6 implementation,
focused validation, independent audit, and preparation only. The versioned V3
policy accepts exactly one profile/state pair:
`MARGIN_PROFILE_TYPE_RETAIL_REGULAR=MARGIN_WINDOW_TYPE_UNSPECIFIED` and
`MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1=MARGIN_WINDOW_TYPE_INTRADAY`.
The enum remains labeled Coinbase-documented; this exact mapping is labeled
operator-defined, Slice-2-Preview-only, and not Coinbase-documented. R6 attempt
authority, execution, Create Order eligibility, and later-live eligibility are
all false in the policy evidence. The dormant R6 claim contract binds that exact policy,
the immutable R5 predecessor hashes, one Preview maximum, zero retries,
fallbacks, redirects, and exchange mutations, and the existing strict
`100/150/300 USDC` caps. The fixed R6 preflight creates no client, claim, or
artifact and makes no Coinbase call. Production default readback remains R5.
No R6 claim, result artifact, credential hydration, or Coinbase call exists;
running the one-use R6 attempt requires a separate exact authorization.

`Default-profile Futures readback -> exact AVAX US CFM Coinbase Preview Order -> immutable operator-visible no-live preview readback`

## Ordered Sequence — Slice 2 Blocked At R6 Execution Authorization

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
