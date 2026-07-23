# Admin API Contract Agent

Current MVP:
`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`.
The contract exposes only fixed value-blind Preview failure classes and fixed
no-HTTP DNS/TCP/TLS readiness statuses/counts. It never exposes addresses,
certificates, exception messages, response bodies, or raw Preview identity.
Implementation is complete and validation is pending; no V13-V15 external
operation has run. The completed V10-V12 predecessor remains immutable.
Current action:
`validate_transport_boundary_then_execute_one_authorized_v13_successor_proof`.

## Owns

- `api/**` FastAPI route modules
- `application/admin_api/**` shared command service adapters
- `openapi/**` generated schema artifacts
- Admin API contract tests
- Admin API docs in coordination with the Architect Agent

## Canonical Path

```text
frontend request
-> FastAPI route
-> auth/RBAC
-> idempotency and approval gate
-> shared command service
-> existing domain/bridge/exchange path
-> durable audit
-> typed response
```
## Terminal V10-V12 contract

Goal
`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`
is terminal after V10-V12. Each candidate completed eight exact reads and
consumed its distinct Preview allowance at terminal `TRANSPORT_UNKNOWN`, with
exact Preview wire count withheld. The aggregate ledger is 3/10 cycles and 24
exact reads; Create and Cancel remain unconsumed with zero calls and no
exchange mutation.

The active generated route is
`POST /api/v1/automation/atomic-market-snapshot-candidates/authorize`.
Policy revision 5 binds final terms, evidence, identities, the exact eight-read
ledger, run, and one-use Preview claim atomically. It reuses canonical
Preview/Create/Cancel scopes and exposes only fixed sanitized diagnostics,
hash retention, and exact-or-withheld call accounting. Response-bearing HTTP
client/server and blocked-redirect exceptions use fixed value-blind classes
and exact one-call evidence; exception messages and bodies remain unread. The
browser supplies no trading term. V12 is distinct rather than a V10 or V11
retry, and no successor remains. The event contract accepts a null-source
`automation_spot_preview_invocation_started` event only as the durable genesis
of an atomic V10-V12 run; ordinary run chains retain their claimed-run genesis.

## Completed V7-V9 predecessor


Current goal
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`
is complete at `complete_terminal_eligibility_cycles_exhausted_v7`.
Current action: `complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.
The backend-owned `BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` V7-V9 path
binds six-category preparation and eight-category eligibility to `10/10`
durable no-retry cycles and fixed sanitized classifications. Get Market Trades
supplies same-snapshot price/freshness evidence. Preview/Create/Cancel calls are
`0/0/0`; cycles 1–5 remain immutable generic
`automation_minimum_size_preparation_unknown` records with zero completed
categories and exact call count withheld. The first approved category was not
confirmed. Cycle 3 exposed an unprotected REST-client method lookup, and cycle
4 exposed response processing outside the fixed stage envelope. Cycle 5 remained generic after both fixes. The deployed outer-boundary split classified cycle 6 as `automation_minimum_size_materialization_unknown` after all six read categories completed. Schema-only inspection localized a concrete materialization blocker: two obsolete fixed-1.00-USDC PostgreSQL CHECK constraints remained active beside the dynamic-cap constraints. The completed migration removed only those legacy constraints and proved a synthetic 1.01-USDC dynamic-cap row survives startup migration. Cycle 7 materialized V7; cycles 8–10 each stopped at Get Market Trades `BEST_BID_ASK` after four successful categories and five exact reads. Backend readback is terminal at `automation_spot_eligibility_cycles_exhausted` with no action. All Preview/Create/Cancel allowances remain unconsumed; no child exists and V8–V9 were not created. See
[`OPERATOR_SPOT_AUTOMATION_MINIMUM_SIZE_V7_V9.md`](../OPERATOR_SPOT_AUTOMATION_MINIMUM_SIZE_V7_V9.md).

Previous V4 near-market goal
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`
is complete at `complete_terminal_no_valid_size`. Current action:
`complete_v4_no_valid_size_preview_create_cancel_unconsumed`.
Default action: `await_operator_policy_or_cap_decision`.
The backend-owned `BTC_USDC_POST_ONLY_BEST_BID_V1` policy is confined to the
V4-V6 Spot Automation ledgers. Its exact route, PostgreSQL claim, generated
contract, RBAC, no-retry reads, cap evidence, Preview/Create/Cancel claims, and
privacy boundary are documented in
[`OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md`](../OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md).
V4 preparation completed one cycle and all six approved categories with `6`
exact Coinbase read calls, then terminated as `near_market_no_valid_size`.
No definition or child exists; goal-global cycles are `1/10` and
Preview/Create/Cancel calls are `0/0/0`, with those allowances unconsumed.
Complete validation and both independent audits pass.

### Previous Preview-explainability closeout

Goal
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`
is complete at `complete_no_documented_successor_correction`, the authorized
`no documented correction remains` stop.
Current action:
`complete_preview_explainability_v4_v6_allowances_unconsumed`.
Default action: `await_operator_policy_decision`.

The canonical Preview boundary exact-allowlists Coinbase's documented Preview `errs`
enum and emits only a fixed sanitized rejection code. PostgreSQL, OpenAPI, the
generated frontend client, strict frontend validation, and Automation run
detail readback share that enum. Existing V1-V3 records are not rewritten; V3
has no recoverable exact enum. Its standing BUY terms also cannot be moved near
market without broadening the installed policy. Goal-global V4-V6 eligibility
cycles are `0/10`; Preview/Create/Cancel calls `0/0/0`; all successor
allowances remain unconsumed. The stop boundary is `no documented correction
remains`. No Coinbase call or exchange mutation occurred in this goal.

### V3 predecessor terminal record

Goal `operator_spot_automation_documented_market_freshness_successor_v3` is
complete and terminal. Status: `complete_terminal_preview_rejected`.
Current action: `complete_v3_terminal_preview_rejected_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.
Its eight-category contract uses one exact `BTC-USDC` Get Market Trades
snapshot and the matching Coinbase trade event time under the unchanged
30-second guard; receipt time and unrelated proxy fields are forbidden.

Eight no-retry V3 cycles made `58` exact eligibility reads; cycle 8 proved
eligibility. The route then admitted exactly one Preview, which terminated as
`automation_spot_preview_rejected` with sanitized `REJECTED` /
`DOCUMENTED_REJECTION` evidence. Preview/Create/Cancel calls are `1/0/0`,
allowances are `consumed/unconsumed/unconsumed`, total Coinbase calls are `59`,
and no child or allowed action remains.
Canonical terminal marker: V3 eligibility cycles `8/10`; exact Coinbase reads
`58`; Preview/Create/Cancel calls `1/0/0`; allowances
`consumed/unconsumed/unconsumed`; allowed actions `0`.

V3 validation evidence: backend full `1182 passed, 6 skipped` parallel and
`669 passed, 150 skipped` serial; frontend full `1565 passed`; E2E `15/15`;
build, typecheck, lint, generated-contract, command-security, and release gates
`PASS`; independent safety and blind-contextless audits `PASS`.
V3 release/deployment gate: `PASS` (canonical rerun complete). All validation
and deployment-smoke phases reported no live Coinbase execution.

### V2 predecessor terminal record

Goal `operator_spot_automation_preview_gated_successor_candidate_v2` is complete.
Status: `complete_terminal_eligibility_cycles_exhausted`.
Current action: `complete_terminal_eligibility_exhausted_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

All ten V2 no-retry Eight-category eligibility cycles are terminal: `55` exact
Coinbase reads, zero Preview, zero Create, and zero Cancel calls. The strict
contract returns `BLOCKED` / `automation_run_blocked`, no allowed action, no
Preview claim, and all live allowances unconsumed.

The boundary is Best Bid/Ask source-timestamp freshness under the unchanged
30-second guard. No browser or legacy path may substitute receipt time, add an
eleventh cycle, or infer Preview/Create authority. V1 remains sealed.

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

## Historical pre-closeout contract checkpoint

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was at
an eight-category, canonical-single-child-execution-implemented,
validation-pending checkpoint. Its status was
`canonical_single_child_execution_implemented_validation_pending`; its
checkpoint action was `complete_validation_audits_deployment_and_bounded_live_proof`. The
durable operator refresh includes the account-wide active Spot-order catalog;
exact-run authorization owns a separate final authorization refresh of the
same bound evidence before any Create claim.

The canonical domain-owned one-child Create and exact-child safe-closeout
Cancel coordinators are installed through typed route-owned admission and the
existing Spot command service. At that checkpoint they could not be described
as operator-ready until full validation, independent audits, and installed
deployment validation passed. No goal-scoped Coinbase call had run; eligibility-cycle,
final-authorization-read, Create, and Cancel allowances remain unconsumed. The
former source-gated checkpoint is historical. See
`docs/OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md`.

Completed predecessor goal
`operator_automation_control_plane_origin_prod_alignment_v1` has historical
status `complete` and action
`complete_operator_automation_control_plane_origin_prod_alignment`. The earlier
predecessor `operator_core_workspaces_origin_prod_alignment_v1` delivered the persistent
authenticated operator shell and routed Portfolio, Spot Operations, Futures
Operations, Orders-detail, Automation, and System Operations workspaces while
keeping Diagnostics separate.

Historical predecessor record: Status: `complete`. Goal
`operator_core_workspaces_origin_prod_alignment_v1` is complete. Current action
is `complete_core_operator_workspaces_origin_prod_alignment`; default action is
`await_operator_direction_for_next_mvp`. Its historical Automation is GET-only
posture is superseded by the current PostgreSQL control plane and is not current
authority.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. Automation now has a feature-gated PostgreSQL control plane with typed
definitions, actor-scoped local lifecycle/posture/schedule mutations, terminal
one-shot classification, restart recovery, and paginated definition/control/run
audit routes. Its v1 domain adapters were unavailable at closeout, it started
no recurring scheduler, and every predecessor route reported zero
Coinbase/exchange activity. The current typed successor is `SOURCE_GATED` and
still reports zero current activity.

Historical core-workspaces validation evidence was backend full `1109 passed,
6 skipped` parallel and `599 passed, 150 skipped` serial, frontend full `1440
passed`, E2E `13 passed`, and independent safety audit `PASS`. The final blind
re-audit is not claimed as passed for that historical checkpoint.

Closeout evidence is backend full `1156 passed, 6 skipped` parallel and `609
passed, 150 skipped` serial, frontend full `1499 passed`, browser E2E `15/15`,
independent safety and blind-contextless audits `PASS`, and the canonical
release gate `PASS`. Packaged and installed validation exercised the real
Controlled-live entrypoint on a fresh empty PostgreSQL database and proved
durable Automation readback with zero Coinbase or exchange activity.

Historical predecessor goal
`operator_follow_up_operations_queue_and_single_live_proof` completed with
status `complete_zero_candidates`. The deployed passive local-SQL
Follow-up Operations queue retrieves its page, exact count, and four
latest durable operation slots in one PostgreSQL statement with no N+1 reader.
Its current-request activity is exact zero. Durable eligibility-read, Create,
reconciliation-read, and Cancel activity is distinct from one-use allowance
consumption; replay preserves durable evidence but reports zero new activity.
Only all-null legacy accounting may project conservatively, while partial or
incoherent explicit tuples and mismatched identities fail closed. Specialized
follow-up error responses expose fixed sanitized activity rather than raw
responses, private identifiers, or exception text. Focused/full gates,
deployment validation, and independent audits passed. The exact post-gate local
`materialization_review` candidate count is `0`; the goal-scoped proof claim was
not created or required, eligibility/reconciliation/Create/Cancel did not run,
and all one-use proof allowances remain unconsumed. The goal authority is
closed and grants no continuing proof call. Keep the Controlled-live stack
available under its separate runtime controls.
The repository persists a terminal seal for that exact fixed goal identity.
Queue readback classifies any later candidate as blocked/non-actionable with
`follow_up_live_proof_goal_terminal`, and the transactional claim boundary
checks the seal before a live eligibility read or new proof acquisition.
Attached-intent navigation and already-existing exact-child safe-closeout
readback remain available. A preexisting claim under the same fixed identity
makes initialization fail closed rather than sealing over in-progress
evidence. The generic materialization implementation remains installed, but a
future proof requires a distinct goal identity and explicit operator
authorization; the completed identity cannot be reopened.
The autonomous work-queue summary reports that terminal seal as tracked-source
policy evidence only. It does not query or claim to verify the installed
database seal; installed database verification requires separate deployment
evidence.

The four installed Controlled-live mutation routes are manual Spot LIMIT/GTC
place/cancel and explicit attached-intent materialization/exact-child
safe-closeout. Each requires the exact execution flag, manager-owned lease,
current post-lease service decision, route membership, RBAC, distinct operator
intent and acknowledgement, idempotency, caps, exact Test portfolio/wallet
evidence, audit, reconciliation, and a route-bound final exchange scope. Intent
attachment and the Follow-up Operations queue remain local-only. All other
browser/HTTP command routes are no-live/local-evidence or source-disabled.
Legacy schema/transition records remain historical evidence, not current
execution authority.
`X-Operator-Intent` is required command evidence. It must be recorded in the
durable command audit event and included in the idempotency payload hash.

## Platform And Module Boundary

Admin API work must distinguish reusable admin platform primitives from domain
modules. Shared primitives include OpenAPI, auth/RBAC, idempotency, audit,
approval gates, observability headers, route inventory, and release evidence.
Spot is the first complete product module. Do not copy spot-only wallet,
USDC, cost-basis, average-cost, lot authority, or no-shorting rules into
futures/perpetuals, stealth orders, repricing, or risk modules. Add or update
`docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before broadening a module.

Legacy dashboard mutation boundary:

```text
dashboard WebSocket message
-> fixed source-disabled response
-> no runtime, command-service, guard, or REST lookup
```

## Shared Service Boundary

Implemented modules:

- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/idempotency.py`
- `application/admin_api/approval.py`
- `application/admin_api/audit.py`
- `api/v1/routes/*.py`
- `openapi/coinbase-admin-api.yaml`
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`

Shared command service methods currently cover authenticated Admin API manual
Spot LIMIT/GTC placement and cancel-by-`client_order_id`, synthetic hotpoint
regression behavior, generic-live-disabled stealth reveal/cancel by
`stealth_order_id`, local-evidence fill-follow-up behavior, a live-disabled
movement reprice command keyed by `stealth_order_id`, a source-disabled spot
campaign execution contract, and a source-disabled spot sweep automation
contract keyed by `sweep_config_id`.

Read-only Admin API routes currently cover backend bootstrap, health,
session/RBAC evidence, capabilities, guard/risk policy evidence, audit
workbench evidence, release/spot-direct-order recovery gates, fill-ledger health, frontend
fixtures, order list/detail, stealth lifecycle list/detail, stealth
command-suite readiness,
movement/repricing evidence, futures/perpetual account and position evidence,
spot readiness, sweep status, sweep P/L, cost-basis status, campaign status,
and direct order audit.
Spot sweep automation command admission is route-bound evidence only. It may
bind `sweep_config_id`, cadence, notional, run-limit, dry-run, and operator
acknowledgement fields to the Admin API command envelope, but it must not call
sweep runner tools, create a browser scheduler, call Coinbase, or mark the
wider sweep automation gap complete before scheduler, recovery, and
reconciliation contracts exist.
The movement reprice command draft is not the legacy dashboard repricer: it
must not clear cooldowns, call `process_anchor_repricing_for_product`, or
mutate live revealed placements until the existing exchange-reality
reconciliation path is explicitly wired.
Guard/risk policy reads expose existing backend policy and authority sources as
evidence only. They must not become browser preflight approval or a second
guard engine.
Live-enablement approval snapshot evidence is read-only missing-approval
evidence. It may list required durable approval fields and backend sources,
but it must not become approval storage, browser approval, command authority,
Coinbase execution, or reconciliation proof.
Live-enablement approval-store contract evidence is read-only store
infrastructure evidence. It may list configured durable backend store behavior
and backend sources, but it must not become approval mutation, browser
approval, command authority, Coinbase execution, or reconciliation proof.
Approval snapshot resolver infrastructure is backend-only. It may resolve an
exact unexpired approval-store record into immutable evidence, but it must not
become approval mutation, browser approval, command authority, Coinbase
execution, or reconciliation proof.
Approval lifecycle routes are backend-owned local-state mutations. They may
request, approve/reject, revoke, and expose expiring approval snapshot
evidence through `application/admin_api/approval_service.py`, but they must not
call Coinbase, call command execution adapters, run guard decisions, execute
reconciliation, or make browser approval sufficient for live execution.
Cap/guard decision routes are backend-owned local-state mutations and reads.
They may persist and expose route-bound cap/guard decision evidence through
`application/admin_api/cap_guard_service.py`, but they must not call Coinbase,
call command execution adapters, evaluate wallet, margin, profitability,
inventory, account-limit, or spot-specific guards in the browser/BFF, execute
reconciliation, or make a cap/guard record sufficient for live execution.
Admission audit routes are backend-owned local-state mutations and reads over
the existing append-only Admin API audit store. They may persist and expose
route-bound admission audit proof through
`application/admin_api/admission_audit_service.py`, but they must not call
Coinbase, call command execution adapters, evaluate guards, execute
reconciliation, create browser audit authority, or mark live admission allowed.
Reconciliation plan routes are backend-owned local-state mutations and reads
over the append-only reconciliation plan store. They may persist and expose
route-bound post-submit reconciliation plan proof through
`application/admin_api/reconciliation_service.py`, but they must not call
Coinbase, call command execution adapters, execute reconciliation, mutate
order or exchange state, create browser reconciliation authority, or mark live
admission allowed.
Resolver-backed command admission evidence remains fail-closed. A resolved
snapshot may remove only `approval_snapshot_missing`; it does not authorize
live execution while live-disabled, admission-audit, cap/guard,
reconciliation, or browser-authority blockers remain.
Command admission live execution intent evidence remains fail-closed. It may
bind route, identity, payload hash, idempotency key, actor, operator intent,
and shared service method for review, but it must not create an executable
adapter, browser approval, BFF execution authority, Coinbase call, or parallel
command path.
Resolver-backed command admission audit evidence remains fail-closed. A
resolved audit proof may remove only `admission_audit_missing`; it does not
authorize live execution while live-disabled, cap/guard, reconciliation, or
browser-authority blockers remain.
Resolver-backed command admission cap/guard proof evidence remains
fail-closed. A resolved cap/guard proof may remove only `cap_guard_missing`;
it does not authorize live execution while live-disabled, reconciliation, or
browser-authority blockers remain.
Resolver-backed command admission reconciliation plan proof evidence remains
fail-closed. A resolved reconciliation plan proof may remove only
`reconciliation_plan_missing`; it does not authorize live execution while
live-disabled or browser-authority blockers remain, and it must not execute
reconciliation or mutate exchange/order state.
Command admission live execution service boundary evidence remains
fail-closed. It may report that the backend live execution service is
required but disabled/unconfigured; it must not remove
`live_execution_disabled`, authorize browser evidence, call Coinbase, or
create a second command path.
The disabled live execution service descriptor is evidence-only. It may make
the backend-owned service boundary visible to admission evidence, but it must
not expose create, cancel, submit, execute, Coinbase, browser approval, BFF
execution authority, or route-local execution methods.
Live execution adapter contract evidence is live-enablement evidence only. It
may map a live-shaped route to the shared `AdminApiCommandService` method and
list forbidden execution methods, but it must not become a route-local
executor, browser approval workflow, BFF execution authority, Coinbase call,
live switch, or order/exchange-state mutation path.
Live readiness precondition evidence is live-enablement evidence only. It may
normalize approval store, approval snapshot, admission audit, cap/guard,
reconciliation, adapter, intent, browser/BFF, and disabled live service
prerequisites, but it must be derived from existing read-only live-enablement
evidence. It must not call command admission with synthetic values, create a
new preflight endpoint, remove blockers, mark paths live eligible, authorize
browser/BFF execution, call Coinbase, or create route-local execution.
Live-enablement admission-audit trail evidence is read-only missing-audit
evidence. It may list required append-only backend admission facts and
sources, but it must not become audit storage, approval storage, browser
approval, command authority, Coinbase execution, or reconciliation proof.
Live-enablement cap/guard contract evidence is read-only missing-guard
evidence. It may list required backend cap/guard bindings and backend sources,
but it must not become guard execution, browser wallet or profitability
authority, browser approval, command authority, Coinbase execution, or
reconciliation proof.
Audit workbench reads expose route inventory, command audit, correlation,
module, and exchange evidence only. They must not become command replay, audit
mutation, Coinbase read, or frontend approval paths.
Futures/perpetual reads use `position_key` for position identity, separate
configured product scope from observed position scope, and must not import
spot wallet, no-shorting, cost-basis, or average-cost authority.
OIDC/JWT auth mode is implemented as a fail-closed verifier: readiness reports
required issuer, audience, and JWKS settings, and configured requests validate
RS256 JWTs before deriving actor/role evidence from claims.
`tools/run_admin_oidc_readiness_smoke.py --summary-only` proves missing-config
blocking, JWKS reachability, verified-claim session evidence, and no-live
Coinbase posture.

## Must Not Do

- Do not implement a second live trading path in FastAPI.
- Do not bypass existing guard, sizing, wallet, bridge, runtime, or inflight
  tracking behavior.
- Do not use `order_id` for internal tracking.
- Do not hand-maintain OpenAPI schemas that drift from backend models.
- Do not make frontend acknowledgement the only live-order approval gate.

## Required Tests

Run focused Admin API coverage for ordinary Admin API changes:

```powershell
pytest tests/regression/test_admin_api_contract.py -v --tb=short
```

Run the full backend regression gate before durable milestone closeout,
public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or explicit
user request:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

Focused tests must cover auth denial, RBAC denial, idempotent retry,
idempotency conflict, approval/live-disabled gate evidence, no live REST call
from HTTP command routes, cancel by `client_order_id`, audit creation,
operator intent audit/idempotency evidence, WebSocket/HTTP shared-service
parity, typed OpenAPI routes, and read-only route contracts. OIDC verifier
changes must also keep the no-live OIDC readiness smoke covered by
`tests/regression/test_admin_api_contract.py`.
