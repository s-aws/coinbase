# Coinbase Admin MVP Goal

## Completed sequential Goal 13 — operator-ready Controlled-live closeout

Goal ID: `operator_futures_hotpoint_canonical_single_child_v2`.

This independent goal implements the authenticated `/hotpoint`
`domain=FUTURES` lifecycle for the credential-bound `Default` / `DEFAULT`
profile, `AVP-20DEC30-CDE`, BUY, one generated post-only LIMIT/GTC child, and
strict `<100 / <150 / <300 USDC` caps. Separate PostgreSQL goal and call
ledgers reuse the shared canonical Futures lifecycle serialization lock and
exact-child Cancel invocation seal. One explicit `RUN_ONCE` may consume one of
ten no-retry six-category cycles, the single Preview, and only after an
accepted error-free result the identical Create. One later explicit
`SAFE_CLOSEOUT` may consume one exact one-page reconciliation and one
conditional exact-child Cancel.

Implementation, generated-contract synchronization, focused and full
backend/frontend gates, installed deployment validation, independent safety
and blind-contextless audits, and persistent Controlled-live handoff pass. No
legitimate installed, reconciled,
nonterminal Default-profile AVP parent has more than three contracts of
remaining capacity, and inherited exact-V3 eligibility requires the
post-trigger AVP position to be flat. The operator UI displays this source
blocker and ARM/RUN remain unavailable. Eligibility is `0/10`; Preview,
Create, reconciliation, and Cancel remain unconsumed. No Goal 13 Coinbase call
or live proof occurred.

Historical comparison inspected
`origin/prod:business/hotpoint_detector.py`,
`business/hotpoint_rate_limiter.py`, `business/hotpoint_placer.py`,
`business/hotpoint_decay_sweeper.py`, `dashboard_server.py`, and
`external/coinbase_client.py`. Official Coinbase and pinned-SDK Product/BBO,
permissions/portfolio, CFM position/margin, Preview/Create/List Orders/Cancel,
and market-hours contracts were checked. No published post-maintenance
breaking change was identified; modern CDP portfolio binding is
credential-owned and the deprecated order-level `retail_portfolio_id`
argument is omitted.

The terminal workflow grants no predecessor parent creation and must not
consume or transfer any Goal 13 allowance.

## Completed sequential Goal 12 — operator-ready Controlled-live

Goal ID: `operator_spot_order_truth_and_exact_cancel_reconcile_v1`.

This independent goal delivers approved-Test `CONSUMER` / `SPOT` order
inventory and exact operator actions for canonical parentless
`ADMIN_MANUAL_ROOT` rows. A separate PostgreSQL ledger owns one goal-global
no-retry truth cycle, usable by either catalog refresh or exact
reconciliation, plus one independent exact Cancel allowance. Local
list/detail/result reads are Coinbase-call-free. The strict Goal 12 binding
reuses canonical `POST /api/v1/orders/{client_order_id}/cancel`; no alternate
mutation route, service method, runner, or adapter is permitted. Durable read
claims are distinct from the wrapper's actual SDK-boundary callbacks, so
pre-boundary failures do not overstate Coinbase invocation. The read-only
truth cycle and exact Cancel allowances are unconsumed. Focused backend
validation passed 242 tests; the
canonical backend regression passed 1,294 tests with 6 skipped in parallel and
920 tests with 150 skipped and 1,300 deselected in serial. Frontend validation
passed 1,829 unit/component tests and 33 authenticated E2E tests. Independent
safety and blind-contextless audits pass, including the final remediation
delta. Implementation, validation, and audit made zero Coinbase calls. Every
immutable predecessor boundary remains preserved and R8 content and its hash
remained inaccessible. The canonical release gate, installed deployment, and
persistent Controlled-live status verification pass. The frontend listens on
`0.0.0.0:3000`, the backend remains loopback-only, runtime authority is armed,
and no current service decision or eligible live path exists.

## Completed sequential Goal 6

Goal ID: `operator_spot_recovery_execution_ui_v1`.

This independent successor delivers the normal authenticated
`/spot/recovery` create, exact refresh, immutable-plan review, PostgreSQL
apply, safe rollback, and conditional canonical exact-order Cancel workflow.
`operator_spot_recovery_goal` owns one non-transferable ten-cycle refresh
budget and one goal-global Cancel outcome. Existing
`operator_spot_recovery_and_reconciliation_execution_v1` rows and allowances
remain preserved and cannot authorize Goal 6. All Goal 6 external-call
allowances are unconsumed pending full gates and independent audits.

## Current V13-V15 transport-explainability goal

Goal ID:
`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`

Status: terminal after V13. Validation, deployment, and both audits passed.
V13 is terminal at `TRANSPORT_UNKNOWN` after one successful no-HTTP DNS/TCP/TLS
sequence, one cycle, eight exact eligibility reads, and one consumed Preview
allowance with exact wire count withheld. Create and Cancel remain unconsumed.
V14/V15 remain unused because no official-documentation-backed correction
exists. Current action: `close_v13_transport_unknown_v14_v15_unused`.

Completed predecessor:
## Terminal V10-V12 atomic market snapshot goal

Goal ID:
`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`

Status: terminal after V10-V12. Each candidate completed eight exact reads and
consumed its distinct Preview allowance at terminal `TRANSPORT_UNKNOWN`, with
exact Preview wire count withheld. The aggregate ledger is 3/10 cycles and 24
exact reads; Create and Cancel remain unconsumed with zero calls and no
exchange mutation. V10-V12 are distinct, and no successor remains.

Backend policy revision 5 claims one no-retry eight-category cycle, derives
final post-only best-bid terms, fee-reserved cap, evidence, plan/child
identities, and commits them with the run and consumed Preview claim in one
PostgreSQL transaction. The canonical command path independently requires the
exact same-snapshot bid and both notionals strictly below 3.10 USDC. The first
accepted error-free Preview may reach one identical Create; only its exact
nonterminal child may reach one Cancel. See
[`OPERATOR_SPOT_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_V10_V12.md`](../docs/OPERATOR_SPOT_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_V10_V12.md).

## Completed V7-V9 predecessor


Goal ID:
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`

Last reviewed: 2026-07-22 UTC.

Status: `complete_terminal_eligibility_cycles_exhausted_v7`.

Current action:
`complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.

Default action: `await_operator_direction_for_next_mvp`.

The backend-owned `BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` policy is
restricted to the approved Test portfolio, BTC-USDC, one child, and V7-V9. It
derives the smallest valid post-only fresh Get Market Trades best-bid terms,
submitted notional, and fee-reserved dynamic execution cap, with both caps
strictly below 3.10 USDC. Product minimum, increment, fee, wallet, freshness,
and cap failures use fixed sanitized classifications. Six-category preparation
and eight-category run eligibility share `10/10` durable no-retry cycles.
Cycles 1–5 remain immutable generic
`automation_minimum_size_preparation_unknown` records with zero completed
categories and exact call count withheld; the first approved category was not
confirmed. Cycle 3 exposed an unprotected REST-client method lookup, and cycle
4 exposed response processing outside the fixed stage envelope. Cycle 5 remained generic after both fixes. The deployed outer-boundary split classified cycle 6 as `automation_minimum_size_materialization_unknown` after all six read categories completed. Schema-only inspection localized a concrete materialization blocker: two obsolete fixed-1.00-USDC PostgreSQL CHECK constraints remained active beside the dynamic-cap constraints. The completed migration removed only those legacy constraints and proved a synthetic 1.01-USDC dynamic-cap row survives startup migration. Cycle 7 materialized V7; cycles 8–10 each stopped at Get Market Trades `BEST_BID_ASK` after four successful categories and five exact reads. Backend readback is terminal at `automation_spot_eligibility_cycles_exhausted` with no action. Preview/Create/Cancel calls are `0/0/0`; all allowances remain unconsumed, no child exists, and V8–V9 were not created.

## V4 near-market predecessor closeout

Goal ID:
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`

Status: `complete_terminal_no_valid_size`.

Current action: `complete_v4_no_valid_size_preview_create_cancel_unconsumed`.

Default action: `await_operator_policy_or_cap_decision`.

The backend-owned `BTC_USDC_POST_ONLY_BEST_BID_V1` policy is restricted to the
approved Test portfolio, `BTC-USDC`, one child, V4-V6, and the unchanged
3.10/1.00 USDC caps. PostgreSQL claims preparation before any read, shares the
goal-global ten-cycle namespace with run eligibility, and preserves the
existing one-use Preview/Create/Cancel boundaries. One installed V4
preparation cycle completed all six approved categories with `6` exact
Coinbase read calls and terminated as `near_market_no_valid_size`. No
definition or child exists; goal-global cycles are `1/10`;
Preview/Create/Cancel calls are `0/0/0`, and those allowances remain
unconsumed. V5-V6 were not attempted. Complete backend regression, the
canonical frontend release gate, installed smoke, and independent safety plus
blind-contextless audits pass.

## Previous Preview-explainability closeout

Goal ID:
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`

Last reviewed: 2026-07-21 UTC.

Status: `complete_no_documented_successor_correction`.

Current action:
`complete_preview_explainability_v4_v6_allowances_unconsumed`.

Default action: `await_operator_policy_decision`.

The backend exact-allowlists Coinbase's documented Preview `errs` enum and
persists/projects only fixed sanitized rejection codes. Goal-global V4-V6
eligibility cycles are `0/10`; Preview/Create/Cancel calls `0/0/0`; all
successor allowances remain unconsumed. The authorized terminal boundary is
`no documented correction remains`: V3 has no recoverable exact enum and its
standing BUY cannot move near market without broadening installed policy. No
Coinbase call or exchange mutation occurred in this goal.
The authorized eight-category proof budget therefore remained unused.

## V3 predecessor terminal record

V3 is a distinct exact `BTC-USDC` / approved-Test-portfolio successor under
the unchanged 3.10/1.00 USDC caps. It uses Coinbase's documented authenticated
Get Market Trades snapshot, requires the exact-product trade event `time` to
pass the unchanged 30-second guard with only the V3-specific one-second
Coinbase-to-host skew bound, preserves the original trade time with a clamped
30-second expiry, and binds bid/ask from that
same response. Receipt time and unrelated proxy fields are forbidden. V1/V2
rows, identities, call records, allowances, artifacts, and hashes remain
sealed.

The authenticated operator path created exactly one V3 candidate. Its eight
no-retry eligibility cycles used `8, 8, 8, 5, 8, 5, 8, 8` calls (`58` exact
eligibility reads), and cycle 8 proved exact eligibility. Exactly one Preview
was then claimed and invoked. It terminated as
`automation_spot_preview_rejected` with sanitized `REJECTED` /
`DOCUMENTED_REJECTION` evidence and warning-present readback. Preview identity
retention is `UNAVAILABLE`; no raw response, secret, private identifier, or
withheld exception text was persisted or exposed. Create and Cancel were not
reached. Canonical V3 accounting is total Coinbase calls `59`,
Preview/Create/Cancel `1/0/0`, allowances
`consumed/unconsumed/unconsumed`, no child, and no remaining action.
Canonical terminal marker: V3 eligibility cycles `8/10`; exact Coinbase reads
`58`; Preview/Create/Cancel calls `1/0/0`; allowances
`consumed/unconsumed/unconsumed`; allowed actions `0`.

V3 validation evidence: backend full `1182 passed, 6 skipped` parallel and
`669 passed, 150 skipped` serial; frontend full `1565 passed`; E2E `15/15`;
build, typecheck, lint, generated-contract, command-security, and release gates
`PASS`; independent safety and blind-contextless audits `PASS`.
V3 release/deployment gate: `PASS` (canonical rerun complete). All validation
and deployment-smoke phases reported no live Coinbase execution.

## V2 predecessor terminal record

Goal ID: `operator_spot_automation_preview_gated_successor_candidate_v2`

Status: `complete_terminal_eligibility_cycles_exhausted`.

Current action:
`complete_terminal_eligibility_exhausted_preview_create_cancel_unconsumed`.

Default action: `await_operator_direction_for_next_mvp`.

The V2 goal created one distinct immutable `BTC-USDC` candidate for the
approved Test portfolio while preserving the V1 predecessor. All ten no-retry
Eight-category cycles are terminal, with exact distribution
`8, 5, 5, 4, 5, 5, 5, 5, 5, 8`.

Durable accounting is `55` Coinbase reads, zero Preview, zero Create, and zero
Cancel calls. The run is `BLOCKED` / `automation_run_blocked`, exposes no
action, has no Preview claim, and retains every live allowance unconsumed.

The terminal boundary is Coinbase Best Bid/Ask source-time freshness under the
unchanged 30-second guard. Receipt time and unrelated fields are not accepted
substitutes. No retry, Preview, mutation, alternate identity, candidate, or
child may be inferred from the remaining allowances. V1 remains sealed.

Validation evidence: backend full `1180 passed, 6 skipped` parallel and
`668 passed, 150 skipped` serial; focused backend `240 passed`; frontend full
`1563 passed`; E2E `15/15`; build, typecheck, lint, generated-contract, and
command-security gates `PASS`; independent safety and blind-contextless audits
`PASS`.
Release/deployment gate: `PASS` (canonical rerun complete).
Every immutable R1-R12 and predecessor artifact byte and documented hash
remains preserved, and R8 content and hash remain inaccessible.
Canonical terminal marker: V2 eligibility cycles `10/10`; exact Coinbase reads
`55`; Preview/Create/Cancel calls `0/0/0`; allowances
`unconsumed/unconsumed/unconsumed`; allowed actions `0`.

## Historical pre-closeout implementation record

Historical checkpoint status:
`canonical_single_child_execution_implemented_validation_pending`.
Historical checkpoint action:
`complete_validation_audits_deployment_and_bounded_live_proof`.

The operator path includes a durable, explicit eight-category eligibility
refresh whose final category is the account-wide active Spot-order catalog.
Exact-run authorization owns a separate final authorization refresh of the same
plan-, revision-, portfolio-hash-, and freshness-bound evidence before any
Create claim. Both are fixed order and no retry.

The canonical domain-owned one-child Create and exact-child safe-closeout
Cancel coordinators are implemented through typed admission, durable one-use
claims, and the existing Spot command service. No bare enablement boolean,
untyped gateway, alternate placement path, recurring scheduler, second child,
or fan-out is installed. No goal-scoped Coinbase call has run.
Eligibility-cycle, final-authorization-read, Create, and Cancel allowances
remained unconsumed. At that checkpoint full validation, independent audits,
installed deployment validation, and the bounded live proof remained pending. The previous
source-gated checkpoint and its gate counts are historical, not evidence for this
implementation increment. See
`docs/OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md`.

Completed predecessor `operator_automation_control_plane_origin_prod_alignment_v1`
established the PostgreSQL Automation control plane and is historical
`complete` evidence.

## Completed core-workspaces predecessor

Goal ID: `operator_core_workspaces_origin_prod_alignment_v1`

Last reviewed: 2026-07-20 UTC.

Status: `complete`.

Goal `operator_core_workspaces_origin_prod_alignment_v1` is complete. Current
action: `complete_core_operator_workspaces_origin_prod_alignment`. Default
action: `await_operator_direction_for_next_mvp`. It delivered the persistent
authenticated operator shell and routed Portfolio, Spot Operations, Futures
Operations, Orders-detail, Automation, and System Operations workspaces while
keeping Diagnostics separate.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. At that predecessor closeout, the statement `Automation is GET-only`
meant one local `GET /api/v1/admin/capabilities`; that is historical evidence,
not the current `SOURCE_GATED` successor posture.

Current validation evidence is backend full `1109 passed, 6 skipped` parallel
and `599 passed, 150 skipped` serial, frontend full `1440 passed`, E2E
`13 passed`, and independent safety audit `PASS`. The final blind re-audit is
not claimed as passed; neither are the canonical release gate or final
installed Controlled-live stack verification.

The backend remains authoritative for authentication, RBAC, approved Test
portfolio and product scope, account and wallet evidence, price/size/cap
validation, identity, idempotency, admission, audit, reconciliation, exchange
call accounting, terminal classification, and runtime controls. Page loads use
call-free local projections. The only goal-scoped external-read boundary was one
explicit operator account-reality refresh across the six authorized categories
without category retry. It completed successfully, its allowance is consumed
and sealed, and its evidence is now stale for live eligibility. The optional
post-gate proof remains unconsumed: at
most one manual Spot Create under the installed 3.10 USDC submitted and 1.00
USDC possible-execution caps, followed only if necessary by one exact-order
Cancel, with no retry, fallback, redirect, alternate order, or other mutation.

Historical predecessor Goal ID:
`operator_follow_up_operations_queue_and_single_live_proof`.
Historical predecessor status: `complete_zero_candidates`.

The routed Follow-up Operations workspace is deployed and its focused/full
validation, deployment validation, independent safety audit, and
blind-contextless audit passed. The queue is passive local SQL and is never
live eligibility. Its exact post-gate local `materialization_review` candidate
count is `0`. The passive queue made `0` Coinbase reads, `0` Create calls, and
`0` Cancel calls. With zero candidates, the goal-scoped single-candidate proof
claim was not created and was not required. Eligibility, reconciliation,
Create, and Cancel did not run. All one-use proof allowances and all live
allowances remain unconsumed. The goal authority is closed and grants no
continuing proof call. The Controlled-live operator stack is to remain
available, but its availability is not authority from this completed goal.
The backend persists a durable terminal-goal seal for this exact goal identity.
Any candidate that appears after closeout is backend-classified blocked with
fixed diagnostic `follow_up_live_proof_goal_terminal`; the claim transaction
checks the seal before candidate selection or any live eligibility read. It
does not suppress attached-intent navigation or already-existing exact-child
safe-closeout readback. If startup finds a preexisting claim under the same
fixed goal identity, initialization fails closed rather than sealing over an
in-progress operation. The installed generic follow-up materialization
implementation remains reusable, but a future proof must use a distinct goal
identity and explicit operator authorization rather than reopening or deleting
this seal.

Current machine alignment:
`operator_follow_up_operations_queue_single_proof_v1`. Current/default action:
`complete_zero_candidates_all_live_allowances_unconsumed`. Work mode:
`complete_zero_candidates_all_live_allowances_unconsumed`. Next action:
`await_operator_direction_for_next_mvp`. Operator wording: Follow-up Operations
workspace deployed; exact post-gate candidate count 0; all live allowances
remain unconsumed. Any future live proof requires distinct operator authority.

Bounded Controlled-live observation for candidate counting: the audited
installed operator review stack reported runtime mode `controlled_live`, frontend
`0.0.0.0:3000`, backend `127.0.0.1:8787`, and approved Test portfolio
configuration without exposing its identifier. This observation made zero
Coinbase calls and does not claim final post-closeout deployment health.
Release, startup, and status made zero Coinbase calls and consumed no
live-proof allowance.

Historical Futures Goal ID: `futures_preview_acceptance_recovery_r12`.
Historical readiness: terminal closeout complete. Eligibility cycle 2 completed
`exact_v3_eligible`, the one durable claim was created and consumed, and
offline claim recovery appended terminal blocker
`claim_only_recovery_unknown_consumed` without a Coinbase client or factory.
The source gate is closed and no further Coinbase call is permitted.

Historical machine alignment: `r12_separate_eligibility_and_single_use_attempt_v1`.
Slice status: `complete_terminal_unknown_consumed`. Work mode:
`r12_terminal_unknown_consumed_offline_closeout_complete`.

The canonical cross-repository authority is
`/home/developer/coinbase/coinbase-frontend/docs/CURRENT_MVP_GOAL.md`. This
backend copy records the behavior-owner interpretation and must remain aligned
with it.

## Historical Completed Operator Follow-Up Materialization Goal

The historical predecessor goal `operator_authorize_and_materialize_follow_up_intent`
is terminally complete. The authenticated Admin API and generated operator contract expose a
separately acknowledged, backend-owned, one-use materialization path and an
exact-child safe-closeout path. Attachment acknowledgement remains local-only
and is never reinterpreted as live authority. All source/root identity, full-
fill and terminal-state revalidation, approved Test portfolio and Spot-product
policy, wallet/cap admission, RBAC, idempotency, exactly-once claiming, child
identity/linkage, audit, reconciliation, duplicate prevention, rollback, and
authoritative readback remain backend-owned.

Terminal live-proof facts:

- no eligible filled attached intent existed; candidate count: `0`
- Coinbase eligibility/reconciliation reads: `0`
- Coinbase Create calls: `0`
- Coinbase Cancel calls: `0`
- durable materialization attempts/claims: `0`
- materialized children: `0`
- submitted/executed notional: `0 USDC` / `0 USDC`
- no unknown live outcome
- live-proof allowances remain unconsumed
- Synthetic tests are not live proof.

Terminal validation evidence:

- backend focused: `164 passed`
- backend canonical full: `1102 passed, 6 skipped` parallel and
  `457 passed, 150 skipped` serial; runner status `passed`, live Coinbase
  execution `false`, and notional `0`
- frontend focused: `179 passed`
- independent safety audit: `PASS`
- blind-contextless audit: `PASS`

The predecessor implementation and validation goal is complete. Its historical
terminal action was `await_operator_direction_for_next_mvp`; it is not current
authority. No second child, retry,
fallback, redirect, scheduler, fan-out, Futures action, or other exchange
authority is implied.

## Historical Slice 2R12 Terminal Workflow

Slice 2R12 kept eligibility and attempt phases structurally separate. Two of
the authorized at most ten state-refresh cycles were durably counted. Each
complete cycle used six categories at most once and exactly nine authenticated
GETs, with Futures sweeps and every other endpoint excluded. Cycle 1 completed
the legacy-readable pre-claim ineligible class without a claim. Cycle 2
completed `exact_v3_eligible` under the unchanged V3 pair,
`AVP-20DEC30-CDE`, one contract, and strict `<100 / <150 / <300 USDC` caps.

Before cycle 2, the fractional external market timestamp mismatch was
remediated: external market evidence accepts canonical whole seconds or
exactly six fractional digits, internal timestamp contracts remain
whole-second, and the fixed skew window is unchanged. No endpoint, read count,
policy, product, contract count, cap, retry, or mutation authority changed.

Cycle 2 created and consumed the one durable R12 claim. The run left claim-only
evidence. Offline claim recovery appended
`claim_only_recovery_unknown_consumed` without constructing a Coinbase client
or factory. The generic Preview-attempt counter is conservative: `1` records
the consumed post-claim attempt boundary but does not prove network reach.
Preview network reach is unknown, so this record does not claim Preview
definitely ran. Retry, fallback, redirect, Create, Cancel, Close, Reduce,
submission, other exchange-mutation, order, and submitted/executed-notional
counts are zero.

The production runner is source-bound to `R12_RELEASE_READY=False`; no
environment variable or CLI flag can activate it. Startup recovery runs before
that gate, uses no client or factory, and returns the strict sanitized terminal
without another Coinbase call. All evidence and diagnostics remain fixed,
sanitized, and value-blind. Raw responses, secrets, private identifiers, raw
Preview identifiers, and withheld exception text are never persisted or
exposed. Existing evidence bytes and documented hashes remain immutable, and
restricted predecessor material remains inaccessible.

R12 is terminally consumed and cannot be retried. No further eligibility read,
Coinbase call, Preview attempt, R13 attempt, or Slice 3, Slice 4, or Slice 5
activation is authorized. The separately authorized
`operator_attach_single_follow_up_intent` successor is complete. The prior R12
post-closeout action
`await_operator_authorization_for_operator_attach_single_follow_up_intent` is
historical and no longer a current blocker. The detailed R12 boundary remains
`docs/FUTURES_SLICE_2R12_PREPARATION.md`.

## Historical Completed Slice 2R11 Successor Workflow

The cross-repository alignment token is
`r11_terminal_pre_preview_v3_operator_policy_rejection`. R11 is consumed,
terminal `blocked`, immutable, and cannot be retried. The single-use workflow
stopped at `remaining_margin_validation` before candidate construction or
Coinbase Preview with fixed reason
`futures_preview_margin_windows_ambiguous`. All six bounded reads ran exactly
once; Preview, retry,
fallback, redirect, submission, Create, Cancel, Close, Reduce, and every other
exchange-mutation counter remained `0`.

The structured boundary is
`margin_window_type_documented_but_operator_rejected`: failing row `1`,
recognized profile `retail_intraday_margin_1`, field `margin_window_type`, and
value type `string`. The returned state token was documented, but it did not
satisfy the exact V3 operator-defined profile/state pair. This is not a
Preview-response schema incompatibility and does not justify changing the V3
policy, product `AVP-20DEC30-CDE`, one-contract scope, or strict
`<100 / <150 / <300 USDC` caps.

The immutable R11 file/evidence SHA-256 pair is
`effb4bd037b853e06da14a0327d71eb8104e2b7edb2f56970b4c47ef855b6061` /
`548bbb02709c70dc320219bc15520b40ed948309ad09ec0f8af8f812d63bedea`.
During the completed R12 successor workflow, default API/UI readback did not
select or open the historical R11 terminal. It bound directly to the fixed R12
singleton and returned the strict recovered R12 terminal.
R1-R10 remain byte-for-byte unchanged, and R8 content/hash remain inaccessible.
The runner is permanently tombstoned. Synthetic backend/frontend remediation
now foregrounds the exact policy boundary without exposing raw responses,
restricted identifiers, secrets, private identifiers, or exception text.

The R11 workflow and offline terminal diagnosis are complete. R11 grants no
second R11 call, independent successor authority, Slice 3, Slice 4, or Slice 5
activation, or other live authority. Its historical default next action was
`stop_and_await_operator_direction`. R12 is governed by the completed terminal,
source-disabled workflow above.
Details are in `docs/FUTURES_SLICE_2R11_PREPARATION.md` and
`docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md`.

## Historical Completed Post-R10 Compatibility And Direction Selection

Historical goal id:
`futures_post_r10_preview_compatibility_and_direction_selection`.

The bounded post-R10 goal is complete. Its stable cross-repository alignment
token is
`official_wire_schema_and_project_acceptance_separated_prospectively`.
Coinbase's documented Preview response shape is now treated as a wire-schema
compatibility boundary, while the project's exact one-contract V3 safety
requirements remain a separate, stricter acceptance policy. This prospective
correction does not reinterpret R10's value-blind terminal category and is not
wired to any consumed R1-R10 claim or runner.

`Official Coinbase Preview wire schema -> prospective project acceptance policy -> ranked no-live direction selection`

A future successor must pass the raw SDK envelope to the shallow validator
before any recursive `_plain()` normalization. `preview_id` must remain
ephemeral and restricted, then be hashed or withheld before persistence or
readback. It must never place that restricted identifier in diagnostics or
frontend payloads. The SDK dependency is pinned to the verified
`coinbase-advanced-py 1.8.4` envelope. These are no-live integration
preconditions, not R11 or runner authority.

All R1-R10 evidence remains immutable. R8 content and hash remain inaccessible;
only its existing opaque forensic contract may be used. This goal made zero
Coinbase API or Preview calls, retries, fallbacks, redirects, Create, Cancel,
Close, Reduce, or other exchange mutations. It grants no R11 authority, no
Slice 3/4/5 activation, and no other live authority.

No R11 exists.

The evidence-backed direction is:

1. Consider at most one separately authorized future successor only after the
   prospective compatibility correction passes deployment validation plus
   independent safety and blind-contextless audit. A successor must retain the
   exact V3 policy, `AVP-20DEC30-CDE`, one contract, strict
   `<100 / <150 / <300 USDC` caps, one Preview maximum, and zero retries,
   fallbacks, redirects, or exchange mutations.
2. If the remaining wire-policy boundary is still uncertain, seek official
   Coinbase clarification and reassess before any successor.
3. Otherwise park the sequence. Ten future attempts are not warranted by the
   available evidence, so no ten-attempt authorization set was produced.

The historical next action was
`await_operator_decision_on_one_post_r10_successor_or_official_clarification`.
That action is a decision point, not work or live authority. The durable schema
mapping, source evidence, safety boundaries, and recommendation are recorded in
`docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md`.

## Historical Predecessor And Slice Record

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

Slice 2 was the active slice for the historical record below. The authorized
R5 integration and one-use attempt are complete, but R5 stopped before Preview
because the exact
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
remains opaque: only its documented SHA-256, exact stat metadata, and this
allowlisted forensic classification may be read back. Runtime must never open,
read, or recompute the hash of R8.

R9 is terminally consumed and cannot be retried. All six fixed read categories
ran once and exactly one Coinbase Preview returned. The first post-return
stage, `preview_response_validation`, then blocked before normalized Preview
evidence, a Preview identifier, or a seal-ready plan could be persisted. The
R9 diagnostic reason is the fixed value-blind
`futures_preview_response_validation_unclassified`; raw response content and
withheld exception text were never persisted and must not be reconstructed.
Retry, fallback, redirect, Create, Cancel, Close, Reduce, exchange submission,
and submitted/executed notional are all zero; Slice 3 remained `not_run`.

The immutable R9 artifact is
`artifacts/futures_exact_no_live_preview_slice_2r9.jsonl`, file SHA-256
`5c7dd3f27605b623edc910a87dcc4b6c9ea6621aa9ee63dbfcc4b2994990dacf`,
and evidence SHA-256
`2fd73aa0059da49dfe6c836f6dea29b12158fb3dfbe8abdd6d8f4f0f7d702464`.
It is mode `0400`, size `24406`, device/inode `2096/401766`, mtime-ns
`1784173141720439487`, and link count `1`. See
`docs/FUTURES_SLICE_2R9_TERMINAL_DIAGNOSIS.md` for its complete immutable
binding and the official-schema comparison.

The source-supported R10 remediation leaves R7-R9 on their exact historical v1
response binding. R10 uses a v2 binding that requires authoritative valid
`margin_ratio_data`, permits the documented coexistence of legacy liquidation
keys, and ignores legacy values without parsing, persisting, or falling back to
them. It also adds fixed value-blind response-validation diagnostic categories.
This corrects the v1 rule that rejected the mere presence of a documented
legacy key, but it does not claim knowledge of the withheld R9 response.

R10 is terminally consumed and cannot be retried. It completed all six fixed
read categories once and made exactly one Coinbase Preview call. The SDK method
returned, then the first post-return stage, `preview_response_validation`,
blocked with fixed sanitized category
`futures_preview_response_economics_invalid`. No normalized Preview response,
Preview identifier, seal-ready plan, or accepted evidence was persisted. The
exact field is intentionally not persisted and cannot be reconstructed.

The immutable R10 artifact is
`artifacts/futures_exact_no_live_preview_slice_2r10.jsonl`, file SHA-256
`5dd010a706c61e78454caeec478e05cafb1a50761e9e5a9a3d485051c4efee64`,
and evidence SHA-256
`5121e980ec9da81f44d9a3b14b9bbcaa7bdaf41c99189cd9234cedc08d652005`.
It is mode `0400`, size `26144`, device/inode `2096/221388`, mtime-ns
`1784179469052389092`, and link count `1`. Retry, fallback, redirect, Create,
Cancel, Close, Reduce, exchange submission, and submitted/executed notional are
all zero. At that historical R10 checkpoint, the production selector bound
this exact terminal and reached R8 only through documented-SHA/stat-metadata-
only validation.

R10 was not accepted, so Slice 3 did not run. Its accepted handoff, admission,
activation, action journal, read journal, and terminal artifacts are absent.
The standalone and composite R10 entrypoints are permanently hard-false. No
Preview authority remained and no R11 existed at that checkpoint. The default
next action was historically recorded as
`await_operator_selection_of_separately_authorized_next_goal`; the completed
post-R10 goal superseded it, and separately authorized R11 later consumed its
claim and terminated before Preview as recorded at the top of this file.

`Default-profile Futures readback -> exact AVAX US CFM Coinbase Preview Order -> immutable operator-visible no-live preview readback`

## Terminal Sequence — R8-R10 Recovery And Unused Conditional Slice 3

The authorized recovery sequence is complete. R8, R9, and R10 are terminal
blocked and immutable. R10 was not accepted, so conditional Slice 3 never
became eligible. Slice 4 and Slice 5 remain unauthorized historical design
context:

The numbered bodies below are frozen historical acceptance criteria.
Imperative verbs are inert and grant no work selection, Coinbase call,
Preview, mutation, retry, or successor authority.

1. `futures_preview_acceptance_recovery_r8_r10_and_conditional_terminal_roundtrip_slice_3`:
   the R8-R10 backend-derived Default-profile US CFM Coinbase Preview Order
   recovery for AVAX perpetual
   `AVP-20DEC30-CDE` and exactly one contract/order candidate under the strict
   `<100.00 USDC` opening, `<150.00 USDC` exposure/buffered-close, and
   `<300.00 USDC` branch-turnover limits. Bind product
   metadata, exact decimals, market freshness, fees, margin/collateral,
   liquidation, caps, idempotency, and correlation. Zero create/cancel/close
   submissions, marker, ledger, or runtime. R10 is consumed, no R11 is
   authorized, and repeatable Admin API/UI readback selects the exact immutable
   R10 terminal while exposing R8 only through its opaque forensic contract.
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

Slice 3 is terminally unused because no R10 accepted evidence exists. Current
exchange-mutation authority is zero. Slice 4 and Slice 5 are unauthorized and
out of scope. Their retained design text is historical dependency context, not
an ordered authorized successor list. No planning statement authorizes a
marker, ledger, runtime, Create, Cancel, Close, Reduce, or other exchange
mutation.

## Shared Successor Safety

Every live plan binds canonical JSON/SHA-256, a maximum operator-policy
120-minute TTL or shorter authoritative evidence expiry, backend/OpenAPI
revisions, exact
`actor=operator-controlled-futures-proof`, and BFF role `trader`. It binds fresh
unique permission-selected `Default`/`DEFAULT` portfolio evidence with
`can_view=true`, `can_trade=true`, no request override, US CFM family and
explicit INTX exclusion, including permission/catalog hashes and timestamps.
That operator-policy TTL is not Coinbase Preview expiry evidence. Coinbase
documents no Preview expiry field or TTL, so an accepted Preview cannot satisfy
the Slice 3 freshness gate and pre-Create mutation remains fail-closed.

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

## Completed Successor MVP — Operator-Attached Single Follow-Up

Goal ID: `operator_attach_single_follow_up_intent`.

The separately authorized implementation and its operator-ready closeout are
complete. Its local intent-persistence boundary granted no Coinbase read or
call, automatic trigger, child creation, Preview, Create, Cancel, Close, Reduce,
R13, or other live authority.

The backend command lets an authorized human attach exactly one
durable future follow-up intent to a system-owned source order identified by
`source_client_order_id`. Attachment is not immediate child creation or
exchange submission. Backend eligibility must use fresh authoritative evidence,
a positive per-module stable-state allowlist, zero filled quantity, supported
ownership and product capability, and proof that no intent, attributed child,
partial-fill allocation, or active conflicting follow-up semantic claim already
exists. A completed automatic or positive-fill root claim may remain only as
historical evidence for an existing child; that child's matching manual root
must be terminal FILLED or CANCELLED. Unknown,
stale, conflicting, transitional, terminal, partially filled, external or
unowned, and unsupported module state fails closed. Spot-only rules must not be
copied into Futures/Perpetuals or platform primitives.

One durable atomic compare-and-set claim keyed by
`source_client_order_id` and its single follow-up slot must revalidate status
and absence in the same critical section as persistence. Route-scoped
idempotency replays only the same payload, conflicts on changed payload, and
cannot let concurrent distinct requests create more than one intent. Unknown
persistence blocks another attempt until authoritative readback. Backend RBAC,
`Idempotency-Key`, `X-Correlation-Id`, `X-Operator-Intent`, and durable audit
must bind the actor, environment, portfolio scope, source and root
`client_order_id`, intent hash, claim, and result.

If the source is a child, later materialization still links the new child to
the original root and records the immediate `source_client_order_id`
separately; grandchildren and re-parenting remain forbidden. Attachment-time
evidence is never live-order approval. Later materialization or Coinbase
submission must freshly pass the canonical backend product, authorization,
wallet or margin, cap/guard, audit, reconciliation, rollback, duplicate-order,
and readback gates under a separately authorized scope. The frontend remains a
generated-contract forwarding and evidence surface, never the trading decision
or claim owner.

## Scope And Validation

R12 terminal closeout is complete under the hard source-disabled release gate.
It grants no new eligibility evidence, claim, idempotency key, Preview attempt,
or Coinbase call. `operator_attach_single_follow_up_intent` is complete. The
successor goal `operator_authorize_and_materialize_follow_up_intent` is also
complete. The Follow-up Operations goal is `complete_zero_candidates`; its
current action is `complete_zero_candidates_all_live_allowances_unconsumed`
and its next action is `await_operator_direction_for_next_mvp`. There are no
automatically selected successors beyond the completed authorization.

A candidate blocker cannot make itself in scope by generating evidence about the candidate blocker.

The post-R10 compatibility goal, its historical recovery predecessor, and the
Slice 2R11 and Slice 2R12 workflows are complete. R12 is consumed, immutable,
and terminal unknown after offline claim-only recovery; no Preview network
reach is asserted. R13, Slice 3, Slice 4, Slice 5, and every unrelated
successor remain unauthorized. Fan-out,
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

All predecessor workflows through R12 are terminal and their authorized offline
diagnosis/remediation is complete; never invoke any consumed runner again.
Keep `R12_RELEASE_READY=False`. A second R12 call, R13 attempt, Slice 3/4/5
activation, product/policy/cap change, unenumerated endpoint, or exchange
mutation remains outside authority.
