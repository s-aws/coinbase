# Coinbase Admin MVP Goal

Goal ID: `futures_preview_acceptance_recovery_r8_r10_and_conditional_terminal_roundtrip_slice_3`

Last reviewed: 2026-07-16 UTC.

Status: `active — R8 terminal blocked with zero Preview calls; R9 readiness validation in progress`

The canonical cross-repository authority is
`/home/developer/coinbase/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This
backend copy records the behavior-owner interpretation and must remain aligned
with it.

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

The operator granted that exact one-use R6 Preview authorization, then
authorized a no-live migration-aware re-preparation after the verified S3
migration restore showed that the immutable files retained their exact bytes,
sizes, modes, and documented hashes but necessarily received new Docker
filesystem device/inode identities. The original nanosecond mtimes were
restored exactly. Re-preparation may update only the physical device/inode
bindings used by the dormant R6 chain; historical EC2 bindings embedded in
consumed R1-R5 evidence remain byte-identical and are still validated against
their exact file hashes. This authorization creates no R6 claim or Coinbase
call and does not broaden the existing one-use Preview scope.

After focused validation, independent safety and blind contextless audits,
contract-pair remediation, and synchronized pushed commits, R6 ran exactly
once on 2026-07-15. The V3 exact profile/state policy passed and all six fixed
read counters are `1`. Exactly one Coinbase Preview call occurred. The attempt
then stopped terminally with sanitized blocker
`preflight_or_preview_blocked:ValueError`; no exact internal exception,
Preview response, or seal-ready plan is persisted and none may be guessed. The
immutable R6 artifact is
`artifacts/futures_exact_no_live_preview_slice_2r6.jsonl`, file SHA-256
`df5959e95ed4a6027e6c0a6980045fc685e7dd201158b39ff5fcc9577bf73904`,
and evidence SHA-256
`bf26fa6b0f67499dea02f337517c1ebd42ae9a20c88fbb5cfbe45e3f30f9e4f9`.
Retry, fallback, Create, Cancel, Close, Reduce, and exchange-submission counters
are `0`; submitted and executed notional are `0 USDC`; live execution is
`not_run`. Default Admin API/UI readback selects immutable R6. R6 is consumed
and cannot be retried. Slice 2 is not accepted and Slice 3 remains inactive.

The operator authorized one end-to-end Slice 2R7 workflow. R7 preserved
the exact V3 profile/state policy, `AVP-20DEC30-CDE`, one-contract scope, and
strict `<100 / <150 / <300 USDC` caps while binding the corrected Coinbase
Preview-response schema: documented `margin_ratio_data` replaces the legacy
liquidation-buffer pair, and `predicted_liquidation_price` is optional but must
be finite and positive when present. Preparation may use offline checks and
official online documentation. After focused validation and independent safety
plus blind contextless audit, exactly one Preview Order call is permitted with
zero retries, fallbacks, redirects, or exchange mutations. An unknown outcome
consumes R7. Authorized offline diagnosis and remediation continue after any
failed gate or terminal result without another approval. No second Coinbase
call, R8, Slice 3 activation, or other live authority was granted.

After three bounded preparation/remediation cycles, focused validation and
independent safety plus blind contextless audits returned `GO`. The exact
readiness commits were pushed before the single authorized call. R7 then ran
exactly once on 2026-07-15. All six fixed Coinbase reads and exactly one
Preview call returned control to the backend, after which the workflow stopped
terminally with sanitized blocker `preflight_or_preview_blocked:ValueError`
before accepted Preview evidence was appended. Retry, fallback, redirect,
Create, Cancel, Close, Reduce, exchange submission, and submitted/executed
notional counters are all zero; live execution is `not_run`.

The immutable R7 artifact is
`artifacts/futures_exact_no_live_preview_slice_2r7.jsonl`, file SHA-256
`8e7bdf1a1efa67df9b1081cc8270dc9607e0b8c7285053d06985dcab195115e4`,
and evidence SHA-256
`65791ec5aae8bd9db7c623042e3238f80a54067209aeeb1916801ca1d02369c3`.
It contains no persisted Preview response or seal-ready plan. The narrowest
safe derived diagnostic is
`sdk_returned__post_preview_value_error__before_acceptance`, at boundary
`after_preview_return_before_accepted_evidence_append`, with exact reason
`not_persisted_and_unrecoverable`. This classification is computed from the
immutable terminal structure, is not persisted in R7, and is excluded from the
artifact's evidence hash. It is not proof that the corrected response schema,
a cap, available margin, candidate binding, seal construction, or any other
specific post-Preview check caused the failure.

R7 is consumed and cannot be retried. Its historical terminal facts, artifact
bytes, and documented hashes remain unchanged. The operator has since activated
the bounded R8-R10 Preview-acceptance recovery and a conditional Slice 3
terminal roundtrip without changing the product, contract count, V3 policy, or
strict caps.

At R7 closeout, the historical blocker was
`slice_2r7_consumed_without_accepted_preview_evidence` and the then-default
action was `await_operator_scope_change_decision_after_slice_2r7_closeout`.
Those literals remain predecessor evidence, not current work authority.

R8 is terminally consumed and cannot be retried. On 2026-07-16 UTC, an
otherwise synthetic malformed-key test escaped its temporary-path isolation
and created the fixed R8 artifact before failing locally. The preserved file is
mode `0400`, size `14921`, device/inode `2096/400341`, and SHA-256
`b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696`.
Independent sanitized diagnosis localizes the boundary to the first
API-key-permissions read boundary. It records one entered read boundary, zero
AWS service calls, zero real Coinbase requests, zero Preview attempts, zero
exchange submissions or mutations, and no accepted evidence. R8 content
remains opaque: only its exact hash/stat binding and this allowlisted forensic
classification may be read back.

R9 is now the current conditional successor. Its Coinbase Preview maximum is
`1`; the remaining authorized recovery maximum is `2` across R9 and R10. R10
may be prepared only after R9 terminates without accepted Preview evidence,
concrete offline remediation is complete, and focused validation plus fresh
independent safety and blind contextless audits pass. The first accepted
Preview extinguishes every later recovery revision. An unknown outcome
consumes only the active revision and is never retried.

The sealed R9 composition root must complete exactly one backend-only Default
credential resolution and construct the canonical zero-retry, zero-redirect
Coinbase session before reserving the R9 claim. It uses the pinned, signed AWS
CLI version with the fixed `default` credential files, `coinbase` secret id,
`us-east-1` region, official regional endpoint, bounded timeout, and no
inherited AWS endpoint/profile/proxy overrides. Any credential lookup, parsing,
or SDK-construction failure leaves R8 and every Slice 3 successor path absent
and makes zero Coinbase reads or Preview attempts. After preparation, the exact
same in-memory delegate is injected into the claim-gated Preview facade and,
only after exact accepted evidence, into conditional Slice 3. Secret material
and raw responses remain ephemeral and are never printed or persisted.

During Preview recovery, Create, Cancel, Close, Reduce, and every other exchange
mutation have a current maximum of `0`. Slice 3 is conditional and inactive; it
is represented separately from the Preview budget and cannot activate unless
the first accepted R9-R10 Preview and the exact Slice 3 readiness gates both
pass. R9 has no terminal outcome, counters, artifact, Preview response, or
accepted-evidence claim yet, and none may be invented. The default next action
is
`complete_r9_slice3_readiness_validation_then_execute_authorized_slice_2r9_once`.

`Default-profile Futures readback -> exact AVAX US CFM Coinbase Preview Order -> immutable operator-visible no-live preview readback`

## Ordered Sequence — R8-R10 Recovery And Conditional Slice 3

The active order is Preview acceptance recovery followed by conditional Slice
3. R8 is terminal blocked; R9 is current and R10 exists only under its
predecessor-failure, remediation, validation, and fresh-audit conditions. The first accepted Preview
ends recovery and is the necessary predecessor for Slice 3 activation. Slice 4
and Slice 5 remain unauthorized historical design context:

1. `futures_preview_acceptance_recovery_r8_r10_and_conditional_terminal_roundtrip_slice_3`:
   the R8-R10 backend-derived Default-profile US CFM Coinbase Preview Order
   recovery for AVAX perpetual
   `AVP-20DEC30-CDE` and exactly one contract/order candidate under the strict
   `<100.00 USDC` opening, `<150.00 USDC` exposure/buffered-close, and
   `<300.00 USDC` branch-turnover limits. Bind product
   metadata, exact decimals, market freshness, fees, margin/collateral,
   liquidation, caps, idempotency, and correlation. Zero create/cancel/close
   submissions, marker, ledger, or runtime. R9 is the only current generation;
   R10 remains conditional and an R9 acceptance extinguishes it. Repeatable
   Admin API/UI readback remains non-calling, exposes R8 only through its opaque
   forensic contract, and selects a valid R9 terminal when one exists.
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
3. `futures_intentional_fill_position_readback_slice_4`: unauthorized and out
   of scope; retained only as historical dependency design. If separately
   activated in the future, it would implement and audit
   with zero live execution, one marketable contract plus authoritative
   fill/fee/position-delta readback. The later live proof requires a Coinbase
   Preview Order-accepted, exchange-auto-terminal FOK or IOC configuration; GTC
   or any residual-active opening is ineligible. A create must bind Coinbase
   `preview_id` to the identical payload. Marketable price needs explicit
   concrete order authority; this is not a separate fill-testing permission.
   Stop and activate Slice 5 implementation; the live Slice 4 checkpoint
   remains pending.
4. `futures_position_closeout_slice_5`: unauthorized and out of scope; retained
   only as historical dependency design. If separately activated in the future,
   it would implement and audit, with zero live execution, exact-position
   closeout derived from fresh authoritative
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

Slice 3 is conditional and inactive while Preview recovery is underway. Its
readiness work may proceed only inside the exact current goal, and current
exchange-mutation authority remains zero. Slice 4 and Slice 5 are unauthorized
and out of scope. Their retained design text is historical dependency context,
not an ordered authorized successor list. No planning statement authorizes a
marker, ledger, runtime, Create, Cancel, Close, Reduce, or other exchange
mutation outside the conditional Slice 3 boundary.

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

Only R9 readiness/execution, the strictly conditional R10 recovery path, and
conditional Slice 3 readiness are current. Slice 4, Slice 5, and every unrelated
successor remain unauthorized; exact-hash live gates remain hard stops. Fan-out,
multi-product automation, schedulers, unattended loops, generic runtime/retry/
recovery tightening, wallet-ledger expansion, ladders/grids, unrelated domain
work, and broad cleanup remain parked.

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

R7 and R8 are terminal and their authorized offline diagnosis/remediation is
complete; never invoke either runner again. Stop R9 before its sole call if readiness or
either fresh audit fails. After any terminal non-accepted recovery result,
perform only the authorized bounded offline diagnosis/remediation and fresh
gates before a conditional successor. Never retry a consumed revision, run a
later recovery revision after acceptance, or activate Slice 3 before both its
acceptance and readiness conditions are satisfied.
