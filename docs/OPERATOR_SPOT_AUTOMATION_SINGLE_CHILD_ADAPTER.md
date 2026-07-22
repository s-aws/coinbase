# Operator Spot Automation Single-Child Adapter v1

## Current status

Goal
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`
is active at `ready_for_bounded_operator_proof`. Current action:
`commit_push_deploy_and_run_bounded_operator_proof`.
Default action: `continue_authorized_workflow_without_new_authorization`.
The adapter now recognizes only typed V4-V6 policy-revision-3 plans under
`BTC_USDC_POST_ONLY_BEST_BID_V1` produced by
the durable preparation contract; all other routes retain the existing
standing-price policy. See
[`OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md`](OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md).
No goal-scoped Coinbase call has run; goal-global cycles are `0/10` and
Preview/Create/Cancel calls are `0/0/0`. Complete validation and both
independent audits pass.

### Previous Preview-explainability closeout

Goal
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`
is complete at `complete_no_documented_successor_correction`. Current action:
`complete_preview_explainability_v4_v6_allowances_unconsumed`. Default action:
`await_operator_policy_decision`. The backend exact-allowlists Coinbase's
documented Preview `errs` enum. Goal-global V4-V6 eligibility cycles are
`0/10`; Preview/Create/Cancel calls `0/0/0`; all successor allowances remain
unconsumed. The stop boundary is `no documented correction remains`. No
Coinbase call or exchange mutation occurred in this goal. See
[`OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md`](OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md).

### V3 predecessor terminal record

Goal `operator_spot_automation_documented_market_freshness_successor_v3` is
complete and terminal. The documented-market-freshness contract is specified in
[`OPERATOR_SPOT_AUTOMATION_DOCUMENTED_MARKET_FRESHNESS_V3.md`](OPERATOR_SPOT_AUTOMATION_DOCUMENTED_MARKET_FRESHNESS_V3.md).
Status: `complete_terminal_preview_rejected`.
Current action: `complete_v3_terminal_preview_rejected_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

V3 uses the documented exact-product Get Market Trades source in the
eight-category backend flow. Eight no-retry cycles made `58` eligibility reads
with distribution `8, 8, 8, 5, 8, 5, 8, 8`; cycle 8 proved exact eligibility.
Exactly one Preview then terminated as
`automation_spot_preview_rejected` with sanitized `REJECTED` /
`DOCUMENTED_REJECTION` evidence. No raw response or withheld text was exposed.
Create and Cancel were not reached, no child exists, and no action remains.
Canonical terminal marker: V3 eligibility cycles `8/10`; exact Coinbase reads
`58`; Preview/Create/Cancel calls `1/0/0`; allowances
`consumed/unconsumed/unconsumed`; allowed actions `0`.

V3 validation evidence: backend full `1182 passed, 6 skipped` parallel and
`669 passed, 150 skipped` serial; frontend full `1565 passed`; E2E `15/15`;
build, typecheck, lint, generated-contract, command-security, and release gates
`PASS`; independent safety and blind-contextless audits `PASS`.
V3 release/deployment gate: `PASS` (canonical rerun complete). All validation
and deployment-smoke phases reported no live Coinbase execution.

V3 preserves all V1/V2 evidence and replaces no predecessor row or allowance.

### V2 predecessor terminal record

Goal `operator_spot_automation_preview_gated_successor_candidate_v2` is complete.
Status: `complete_terminal_eligibility_cycles_exhausted`.
Current action: `complete_terminal_eligibility_exhausted_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The V2 successor preserved V1 and created distinct goal, candidate, identity,
idempotency, and allowance records. All ten no-retry eight-category cycles are
terminal, with `55` exact Coinbase reads. Preview, Create, and Cancel call
counts are zero.

Terminal readback is `BLOCKED` / `automation_run_blocked`, exposes no action,
and preserves all three live allowances unconsumed. The source boundary is the
unchanged 30-second freshness check over Coinbase Best Bid/Ask source time.
No receipt-time substitution, Preview, mutation, retry, alternate identity,
candidate, child, scheduler, or fan-out occurred.

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

## Historical pre-closeout implementation checkpoint

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was at an
eight-category, canonical-single-child-execution-implemented,
validation-pending checkpoint. Its status was
`canonical_single_child_execution_implemented_validation_pending`; its
checkpoint action was `complete_validation_audits_deployment_and_bounded_live_proof`. It
was not yet an operator-ready completion.

The PostgreSQL control plane can store one immutable `BTC-USDC` LIMIT/GTC
single-child plan, carry it across definition revisions, claim one explicit
operator run, derive one deterministic `client_order_id`, reserve one durable
Create allowance, and project backend-owned plan, eligibility, cap, child,
audit, and call-accounting evidence through generated contracts. The routed UI
can create and review the definition, request eligibility, authorize one exact
child, and request exact-child safe closeout only when backend readback exposes
the corresponding action.
The goal-wide plan-bearing definition slot is singleton and race-safe:
definition plus plan creation commits in one transaction, revision carry is
atomic, exact replay verifies the persisted plan, and any partial write rolls
back. Generic planless control-plane definitions remain unaffected.

The installed application adapter includes a typed, route-owned eligibility
coordinator for the eight approved read categories: API-key permissions,
portfolio catalog, account/wallet balances, product metadata, best bid/ask,
fee summary, exact-order reconciliation, and one logical account-wide active
Spot-order catalog. An authenticated operator must explicitly acknowledge the
approved reads, the active-order catalog, and unknown-outcome cycle consumption
before starting a cycle. Ordinary page loading and navigation are call-free.
The coordinator claims a goal-global PostgreSQL cycle, invokes each category
once in fixed order with no application or page retry, fails short, persists
only sanitized hashes and fixed diagnostics, and replays terminal evidence
without constructing a reader. Up to ten cycles may be consumed across the
goal; restart recovery and idempotency cannot reopen a consumed category or
cycle.

Exact-run authorization owns a separate final authorization refresh. That
request allocates its own durable cycle and re-proves the same exact plan
revision, configured approved-Test portfolio hash, freshness, and eight
category outcomes before any Create claim. Missing, stale, ambiguous,
mismatched, or ineligible evidence fails closed without a Create.

The canonical domain-owned one-child Create coordinator resolves typed
approval, cap, admission, and live-service evidence, enters only the existing
canonical Spot execution scope, durably claims the exact deterministic child,
and delegates to the existing command service. Its response classification and
call accounting are sanitized and value-blind. The distinct
exact-child safe-closeout Cancel coordinator reconciles the backend-selected
child, claims its one-use Cancel allowance, and delegates to the existing
canonical exact-order cancel scope. Unknown outcomes consume the applicable
allowance and cannot be retried. No gateway or boolean override can bypass
these boundaries.

The one-run boundary is goal-global and durable: the singleton goal row
serializes concurrent plan-bearing claims, and the first claim permanently
uses the run slot even when its initial source-gated state is `BLOCKED`.
Definition readback removes `RUN_ONCE` for every plan-bearing definition after
that claim. Planless generic control-plane definitions retain their historical
per-definition behavior and receive no Spot execution authority.

Runtime `adapter_status` is backend evidence for the selected run, not a goal
completion label. The implementation may expose `REFRESH_ELIGIBILITY`,
`AUTHORIZE_SINGLE_CHILD`, or `SAFE_CLOSEOUT_CHILD` only from exact backend
state and actor permission. It must not be described as operator-ready until
full validation, independent audits, and installed deployment validation pass.
Earlier direct command-service and injectable-gateway prototypes remain
removed because they bypassed the canonical route-owned admission and
execution scope.

## Preserved invariants

- persistence stores only the configured portfolio's SHA-256 binding and
  revalidates current configuration at every invocation boundary;
  readback says `CONFIGURED_UNVERIFIED` unless the latest eligibility cycle has
  exact successful portfolio-catalog evidence durably hash-bound to the same
  plan portfolio, and only then may it display `Test`; this binding is not a
  wall-clock freshness claim;
- product is exactly `BTC-USDC`, with one definition, one run, and at most one
  deterministic child;
- submitted notional is at most `3.10 USDC` and possible-execution notional is
  at most `1.00 USDC`;
- the browser cannot supply portfolio identity, child identity, cap decisions,
  eligibility, or exchange authority;
- local definition and run mutations retain RBAC, exact operator intent,
  idempotency, audit, revision binding, and duplicate prevention;
- eligibility categories are fixed, ordered, single-call/no-retry, freshness
  bound, plan/revision/portfolio bound, and persisted without raw Coinbase
  payloads or private identifiers;
- terminal cycle replay performs zero reader construction and zero Coinbase
  calls; changed operator reason, acknowledgements, plan, actor, or correlation
  identity cannot replay the same idempotency key;
- the single goal-global run slot cannot be reopened by a new definition,
  idempotency key, process, or restart after a blocked claim;
- unknown post-claim outcomes are never reported as exact zero and are never
  retried;
- an accepted active child survives restart; only an unresolved Create or a
  consumed-but-unfinalized Cancel boundary becomes unknown-consumed;
- no recurring scheduler, unattended activation, ladder, sweep, fan-out,
  Futures action, alternate product, or browser-side Coinbase path exists.

## Live-proof status

No goal-scoped Coinbase call has run. Eligibility-cycle,
final-authorization-read, Create, and exact-child Cancel allowances remain
unconsumed. The implementation work has not treated synthetic fixtures, local tests, old
source-gated evidence, or ordinary page reads as live proof. The authorized
bounded proof may be considered only after focused and full gates, independent
safety and blind-contextless audits, and installed deployment validation pass.

## Validation evidence

The previous source-gated checkpoint passed backend full regression with
`1170 passed, 6 skipped` in the parallel partition and `651 passed, 150 skipped` in the serial
partition. Frontend validation passed 89 files and `1536` tests, browser E2E
passed `15/15`, and independent safety plus blind-contextless audits returned
`PASS` with no P0, P1, or P2 finding. Generated-contract, typecheck, lint,
build, command-security, and release-readiness checks passed. The managed
browser and regression runners reported no Coinbase execution and `0 USDC`
notional. Those counts are historical and do not validate the current
implementation increment. Full validation, both independent audits, installed
deployment validation, and the bounded live proof remain pending.

## Remaining closeout work

The authorized continuation has implemented the previously required canonical
path. Before operator-ready closeout it must:

1. finish focused remediation and generated OpenAPI/frontend synchronization;
2. pass full backend/frontend gates and browser E2E without a Coinbase call;
3. pass independent safety and blind-contextless audits;
4. validate and install the Controlled-live operator deployment; and
5. only then evaluate the exact eligible run for the authorized one-Create and
   optional exact-child safe-closeout proof, leaving allowances unconsumed when
   no exact eligible candidate exists.

## Historical consolidated successor authorization wording

The following wording is preserved as the authorization record that enabled
the current implementation. It is not the current status or next action.

> I authorize one bounded continuation of
> `operator_spot_automation_single_child_execution_adapter_v1`. It preserves
> the exact approved Test portfolio, `BTC-USDC`, one definition, one run, one
> child, and the existing `3.10 USDC` submitted and `1.00 USDC`
> possible-execution caps. It may perform up to 10 combined offline,
> official-documentation-only, PostgreSQL migration, TDD, generated-contract,
> local deployment, safety-audit, blind-contextless-audit, remediation, and
> state-refresh cycles needed to finish canonical admission, execution,
> reconciliation, and exact-child safe-closeout identified by the source-gated
> checkpoint. The continuation must reuse the installed typed route-owned
> eligibility coordinator and must not reintroduce a bare
> enablement boolean, untyped gateway, or parallel Spot placement path. Each refresh cycle
> may invoke each existing approved category at most once with no individual or
> page retry: API-key permissions, portfolio catalog, account/wallet balances,
> product metadata, best bid/ask, fee summary, and exact-order reconciliation.
> It additionally permits exactly one logical account-wide active Spot order
> catalog read per cycle on the approved Test portfolio, including required
> cursor pages with no page retry, solely to enforce the canonical zero-active-
> order guard. The ten-cycle limit is goal-global, not per run. The backend must
> preserve the atomic definition-revision and immutable-plan binding, bind all
> evidence to the same plan revision and portfolio hash, prove the configured
> UUID is the approved Test portfolio, enforce
> freshness, use real typed approval/cap/admission/live-service evidence, enter
> only canonical Spot execution scopes, prevent duplicate reads, and account
> truthfully for every call. After all focused/full gates, installed deployment
> checks, independent safety audit, and blind-contextless audit pass, it permits
> exactly one operator-triggered Coinbase Spot Create for that exact child and,
> only if the exact child is authoritatively nonterminal, at most one Cancel for
> that child. It permits zero retries, fallbacks, redirects, alternate
> identities, second children, fan-out, product expansion, Futures actions,
> scheduler activation, or other exchange mutations. An unknown outcome
> consumes the applicable allowance. If any phase or terminal proof fails,
> continue bounded offline diagnosis and remediation without requesting another
> authorization. Preserve all immutable R1-R12 artifacts and documented hashes,
> keep R8 content and hash inaccessible, never expose raw responses, secrets,
> private identifiers, or withheld exception text, and leave the Controlled-live
> operator stack running. Stop only if proceeding would change the portfolio,
> product, caps, child count, enumerated endpoint set, or exchange-call limits.

The operator explicitly supplied that continuation. It defines the current
bounded scope, but it does not waive the pending validation/audit/deployment
gates or grant any extra Coinbase call, product, child, retry, or fan-out.

## Historical comparison

The implementation review compared the current backend with
`origin/prod` references including `dashboard_server.py`,
`business/hotpoint_placer.py`, and `core/order_engine.py`. Direct REST mutation,
WebSocket authority, in-memory-only claims, automatic workers, and fan-out were
not copied. Only acquire/commit/rollback, durable linkage, and restart-recovery
ideas were translated into the current backend-owned control plane.
