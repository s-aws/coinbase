# Documentation Index

Completed independent Goal 5:
[Operator Stealth Definition Lifecycle V1](OPERATOR_STEALTH_DEFINITION_LIFECYCLE_V1.md).
Goal `operator_stealth_definition_lifecycle_v1` provides routed,
authenticated, PostgreSQL-backed definition lifecycle, exact revision and
idempotency control, runtime-state interlocks, versioned export, durable
schema-validated import preview/apply, and fixed audit readback with zero
Coinbase calls or exchange mutations.

Completed independent Goal 4:
[Operator Parent Order Management V1](OPERATOR_PARENT_ORDER_MANAGEMENT_V1.md).
Goal `operator_parent_order_management_v1` provides routed, authenticated,
PostgreSQL-backed parent-strategy list/detail/create/edit/deactivate/delete,
exact revision and idempotency control, dependency-aware tombstoning, and
fixed audit readback with zero Coinbase calls or exchange mutations.
Closeout passed all canonical validation, deployment, safety, and
blind-contextless gates. The next independent goal is
`operator_stealth_definition_lifecycle_v1`.

Completed independent Goal 3:
[Operator Product Catalog Administration V1](OPERATOR_PRODUCT_CATALOG_ADMINISTRATION_V1.md).
Goal `operator_product_catalog_administration_v1` provides immutable
PostgreSQL catalog revisions, a bounded no-retry List Products refresh,
metadata-diff approval, administrative product lifecycle, rollback, and audit
readback without granting trading authority.

Completed independent Goal 2:
[Operator Fill Ledger and Inventory Repair V1](OPERATOR_FILL_LEDGER_AND_INVENTORY_REPAIR_V1.md).
Goal `operator_fill_ledger_and_inventory_repair_v1` provides the authenticated
PostgreSQL workflow for one exact `client_order_id`, approved `BTC-USDC`
product, or bounded time window; one no-retry logical fill catalog; immutable
missing-fill and FIFO inventory projection; exact-batch apply; and exact-batch
rollback. It grants no Coinbase order mutation.

Completed independent Goal 1:
[Operator Spot Recovery and Reconciliation V1](OPERATOR_SPOT_RECOVERY_AND_RECONCILIATION_V1.md).
Its optional canonical active-orphan Cancel allowance remains unconsumed.

Current operator goal:
[Operator Spot Automation Transport Explainability V13-V15](OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md).
Goal
`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`
adds prospective fixed/type-only Preview invocation classification and a
durable no-HTTP DNS/TCP/TLS readiness sequence before the unchanged atomic
eight-category policy. Validation, deployment, and both audits passed. V13 is
terminal at `TRANSPORT_UNKNOWN` after one successful readiness sequence,
eight exact eligibility reads, and one consumed Preview allowance with exact
wire count withheld. Create and Cancel remain unconsumed. V14/V15 remain
unused because no official-documentation-backed correction exists.
Current action: `close_v13_transport_unknown_v14_v15_unused`.

Completed predecessor:
[Operator Spot Automation Atomic Market Snapshot V10-V12](OPERATOR_SPOT_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_V10_V12.md).
Goal
`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`
is terminal after V10-V12. Each candidate completed eight exact reads and
consumed its distinct Preview allowance at terminal `TRANSPORT_UNKNOWN`, with
exact Preview wire count withheld. The aggregate ledger is 3/10 cycles and 24
exact reads; Create and Cancel remain unconsumed with zero calls. The backend binds the exact eight-category
atomic snapshot and one-use Preview claim; browser authority remains
acknowledgement-only. The V12 correction retains only fixed client/server/
redirect response classes when one response proves an exact Preview call;
otherwise the boundary remains transport-unknown and inexact.

Ordered entry point for the Coinbase Advanced Trading Engine documentation.

## Completed V7-V9 predecessor entry

The completed predecessor goal is
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`.
Status: `complete_terminal_eligibility_cycles_exhausted_v7`.
Current action: `complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.
The backend-owned `BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` policy,
six-category preparation, eight-category eligibility, fixed sanitized boundary
classification, and strict below-3.10 dynamic cap are documented in
[`OPERATOR_SPOT_AUTOMATION_MINIMUM_SIZE_V7_V9.md`](OPERATOR_SPOT_AUTOMATION_MINIMUM_SIZE_V7_V9.md).
Get Market Trades supplies the same-snapshot price and freshness evidence.
Goal-global cycles are `10/10`; cycles 1–5 remain immutable generic
`automation_minimum_size_preparation_unknown` records with zero completed
categories and conservatively withheld exact call count. The first approved
category was not confirmed. Cycle 3 exposed an unprotected REST-client method
lookup, and cycle 4 exposed response processing outside the fixed stage
envelope. The deployed outer-boundary split classified cycle 6 as
`automation_minimum_size_materialization_unknown` after all six read
categories completed. Schema-only inspection localized two obsolete fixed-
1.00-USDC PostgreSQL CHECK constraints beside the dynamic-cap constraints.
The completed migration removed only those legacy checks. Cycle 7 materialized
immutable V7 with a 1.01-USDC dynamic cap. Cycles 8–10 each used five exact
reads and stopped at Get Market Trades `BEST_BID_ASK` after four successful
categories. Backend readback is terminal at
`automation_spot_eligibility_cycles_exhausted` with no action.
Preview/Create/Cancel calls are `0/0/0`; all allowances remain unconsumed, no
child exists, and V8–V9 were not created.

### V4 near-market predecessor entry

The completed V4 successor goal is
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`.
Status: `complete_terminal_no_valid_size`. Current action:
`complete_v4_no_valid_size_preview_create_cancel_unconsumed`.
Default action: `await_operator_policy_or_cap_decision`.
The versioned, backend-owned `BTC_USDC_POST_ONLY_BEST_BID_V1` quantized
best-bid post-only policy and its
durable V4-V6 claims plus eight-category run eligibility are documented in
[`OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md`](OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md).
One installed V4 preparation cycle completed all six approved categories with
`6` exact Coinbase read calls and terminated as `near_market_no_valid_size`.
No definition or child exists. Goal-global cycles are `1/10`;
Preview/Create/Cancel calls are `0/0/0`, and those allowances remain
unconsumed. V5-V6 were not attempted. Complete validation and both independent
audits pass.

### Previous Preview-explainability closeout

The previous Preview-explainability goal is
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`.
Its exact allowlisted Preview classification and no-correction terminal boundary
are recorded in
[`OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md`](OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md).
Status: `complete_no_documented_successor_correction`.
Current action: `complete_preview_explainability_v4_v6_allowances_unconsumed`.
Default action: `await_operator_policy_decision`.

The classifier, PostgreSQL readback, OpenAPI, generated client, and operator UI
now retain only fixed sanitized rejection codes. V3 retained no exact error
enum, and its `10,000 USDC` standing BUY limit cannot be moved near market
without broadening the installed policy. The backend exact-allowlists
Coinbase's documented Preview `errs` enum. Goal-global V4-V6 eligibility cycles
are `0/10`; Preview/Create/Cancel calls `0/0/0`; all successor allowances
remain unconsumed. The stop boundary is `no documented correction remains`.
No Coinbase call or exchange mutation occurred in this goal.
The V3 predecessor used the documented exact-product Get Market Trades source.

### V3 predecessor terminal record

The authenticated operator workflow completed one distinct V3 candidate.
Eight no-retry eligibility cycles used `58` exact reads with distribution
`8, 8, 8, 5, 8, 5, 8, 8`; cycle 8 proved exact eligibility. Exactly one
Preview then terminated as `automation_spot_preview_rejected` with sanitized
`REJECTED` / `DOCUMENTED_REJECTION` evidence. Preview/Create/Cancel calls are
`1/0/0`; allowances are `consumed/unconsumed/unconsumed`; total Coinbase calls
are `59`; no child or allowed action remains. Preview identity is unavailable,
and no raw response or withheld exception text was retained.
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

One distinct immutable `BTC-USDC` V2 candidate consumed all ten no-retry
Eight-category eligibility cycles: exact distribution
`8, 5, 5, 4, 5, 5, 5, 5, 5, 8`, or `55` Coinbase reads total. Preview, Create,
and Cancel call counts are zero.

The terminal run is `BLOCKED` / `automation_run_blocked`, exposes no action,
has no Preview claim, and retains all live allowances unconsumed. The boundary
is Coinbase Best Bid/Ask source-time freshness under the unchanged 30-second
guard. No receipt-time substitution, Preview, mutation, retry, alternate
identity, candidate, or child occurred. V1 remains sealed.

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

### Historical pre-closeout project entry

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was an
eight-category, canonical-single-child-execution-implemented,
validation-pending checkpoint. The one-child `BTC-USDC` contracts, goal-global ten-cycle
PostgreSQL ledger, fixed no-retry eligibility coordinator (including the
account-wide active Spot-order catalog), and explicit operator refresh are
implemented. Exact-run authorization owns a separate final authorization
refresh of the same bound evidence.

The canonical domain-owned one-child Create and exact-child safe-closeout
Cancel coordinators are implemented through typed admission and the existing
Spot command service. Historical checkpoint status was
`canonical_single_child_execution_implemented_validation_pending`; its
checkpoint action was `complete_validation_audits_deployment_and_bounded_live_proof`. No
goal-scoped Coinbase call had run. Eligibility-cycle, final-authorization-read,
Create, and Cancel allowances remain unconsumed. Full validation, independent
audits, installed deployment validation, and the bounded live proof remained
pending. Previous source-gated gate counts remain historical. See [Operator
Spot Automation Single-Child Adapter v1](OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md).

Completed predecessor `operator_automation_control_plane_origin_prod_alignment_v1`
established the PostgreSQL Automation control plane; its historical status is
`complete`.

## Completed core-workspaces predecessor

Historical Status: `complete`.
Goal `operator_core_workspaces_origin_prod_alignment_v1` is complete. Its
historical action is `complete_core_operator_workspaces_origin_prod_alignment`;
its historical default was `await_operator_direction_for_next_mvp`. The lane delivered
a persistent authenticated operator shell and routed Portfolio, Spot
Operations, Futures Operations, Orders-detail, Automation, and System
Operations workspaces while keeping Diagnostics separate.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. At that predecessor closeout, the statement `Automation is GET-only`
meant one local `GET /api/v1/admin/capabilities`; it is historical and does not
replace the current `SOURCE_GATED` successor readback above.

Current validation evidence is backend full `1109 passed, 6 skipped` parallel
and `599 passed, 150 skipped` serial, frontend full `1440 passed`, E2E
`13 passed`, and independent safety audit `PASS`. The final blind re-audit is
not claimed as passed; neither are the canonical release gate or final
installed Controlled-live stack verification.

Historical predecessor
`operator_follow_up_operations_queue_and_single_live_proof` completed with
status `complete_zero_candidates`. Its passive backend-owned local-SQL
Follow-up Operations workspace is deployed, and focused/full validation,
deployment validation, and both independent audits passed. Its exact post-gate
local `materialization_review` candidate count is `0`.

The implemented queue obtains its page and four latest durable operation slots
in one PostgreSQL statement without per-item reads. Its top-level current
request activity is exact zero; durable eligibility-read, Create,
reconciliation-read, and Cancel activity remains separate from one-use
allowance consumption. Replays preserve that durable activity while reporting
zero new current-request activity. Only entirely null legacy accounting may be
projected conservatively; partial explicit accounting fails closed. Typed
follow-up errors remain sanitized and value-blind. The passive queue made `0`
Coinbase reads, `0` Create calls, and `0` Cancel calls. The goal-scoped
single-candidate proof claim was not created and was not required. Eligibility,
reconciliation, Create, and Cancel did not run; all one-use proof allowances
remain unconsumed. The goal authority is closed and grants no continuing proof
call. Keep the Controlled-live stack available for operator review under its
separate durable controls.
The exact completed goal is protected by a durable terminal-goal seal. A later
candidate is reported as non-actionable with fixed reason
`follow_up_live_proof_goal_terminal`, and the claim transaction rejects it
before any eligibility read or new proof acquisition. Attached-intent
navigation and already-existing exact-child safe-closeout readback remain
available. A preexisting claim for the same fixed identity makes startup fail
closed rather than sealing over in-progress evidence. Reusing the installed
generic materialization path for another proof requires a distinct goal
identity and explicit operator authorization; this seal is never reopened.

Goal `futures_preview_acceptance_recovery_r12` is terminal
`complete_terminal_unknown_consumed`. Its single durable claim is consumed,
the source-bound release gate remains `False`, and no further eligibility read,
Preview call, R13 attempt, or Slice 3/4/5 activation is authorized.

The predecessor R11 goal is complete. R11 is consumed, terminal `blocked`,
immutable, and cannot be retried. It stopped at
`remaining_margin_validation` before Preview after six bounded reads; Preview,
retry, fallback, submission, and mutation counts remained `0`. The exact V3
operator-policy boundary is `margin_window_type_documented_but_operator_rejected`.
No acceptance broadening, Slice 3/4/5, or other live authority follows from
R11. R12 is governed only by its consumed terminal boundary.

Historical goal `futures_post_r10_preview_compatibility_and_direction_selection`
is a completed compatibility/direction record, not current work authority.

- [Futures Slice 2R12 Preparation](FUTURES_SLICE_2R12_PREPARATION.md) - separate
  eligibility/attempt phases, ten-cycle ledger, exact nine-GET allowlist,
  single-use claim recovery, and source-disabled release gate
- [Current MVP Goal](../genai_data/AGENT_MVP_REBUILD_GOAL.md) - Follow-up
  Operations queue and bounded single-proof authority, plus immutable
  predecessor history
- [Futures Slice 2R11 Terminal Diagnosis](FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md) -
  exact pre-Preview V3 operator-policy boundary, immutable terminal hashes,
  six-read/zero-Preview accounting, and permanent no-retry tombstone
- [Futures Post-R10 Preview Compatibility And Direction](FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md) -
  historical official-source mapping, two-layer validator boundary, value-blind
  safety posture, ranked direction, and the finding that ten attempts were
  unwarranted at that checkpoint
- [Futures Slice 2R7 Preparation and Closeout](FUTURES_SLICE_2R7_PREPARATION.md) -
  immutable R6 ancestry, corrected response-schema binding, one-use transport
  posture, readiness gates, and terminal record
- [Futures Slice 2R7 Terminal Diagnosis](FUTURES_SLICE_2R7_TERMINAL_DIAGNOSIS.md) -
  derived sanitized failure boundary, hash semantics, terminal machine state,
  and no-retry/no-successor authority
- [Futures Slice 2R8 Terminal Diagnosis](FUTURES_SLICE_2R8_TERMINAL_DIAGNOSIS.md) -
  opaque fixed-artifact binding, zero-call forensic classification, test-path
  remediation, and conditional R9 successor posture
- [Futures Slice 2R9 Terminal Diagnosis](FUTURES_SLICE_2R9_TERMINAL_DIAGNOSIS.md) -
  exact immutable file/evidence hashes, one-Preview response-validation
  boundary, zero-mutation proof, and historical R10 preparation posture
- [Futures Slice 2R10 Terminal Diagnosis](FUTURES_SLICE_2R10_TERMINAL_DIAGNOSIS.md) -
  exact immutable terminal binding, sanitized economics-validation boundary,
  zero-mutation accounting, permanent runner disablement, and no-successor state
- [Root README](../README.md)
- [Expanded AI Context](../genai_data/README.md)
- [Architecture](../genai_data/ARCHITECTURE.md)
- [Order ID Handling](../genai_data/ORDER_ID_HANDLING.md)

## Main Workflows

- [Action Condition Guards](../README.action-condition-guards.md)
- [Spot Trading](../README.spot-trading.md)
- [Spot Portfolio Sweep](../README.spot-portfolio-sweep.md)
- [Spot Campaigns](../README.spot-campaign.md)
- [Spot Recovery Proof Records](../README.spot-recovery-proofs.md)
- [Spot Recovery Snapshot Records](../README.spot-recovery-snapshots.md)
- [Stealth Command Suite Readiness](../README.stealth-command-suite.md)
- [Stealth Active-Placement Exchange-Truth Evidence](../README.stealth-exchange-truth-proofs.md)
- [Stealth Mutation-Claim Snapshot Proofs](../README.stealth-mutation-claim-proofs.md)
- [Stealth Manager-Invocation Policy](../README.stealth-manager-invocation-policy.md)
- [Stealth Coinbase Exchange Policy](../README.stealth-coinbase-exchange-policy.md)
- [Stealth State-Mutation Policy](../README.stealth-state-mutation-policy.md)
- [Stealth Post-Write Reconciliation Execution Policy](../README.stealth-post-write-reconciliation-execution-policy.md)
- [Stealth Recovery Proofs](../README.stealth-recovery-proofs.md)
- [Stealth Reveal-Trigger Proofs](../README.stealth-reveal-trigger-proofs.md)
- [Stealth Reconciliation Proofs](../README.stealth-reconciliation-proofs.md)
- [Stealth Cancel/Replace Proofs](../README.stealth-cancel-replace-proofs.md)
- [Stealth Order Reads](STEALTH_ORDER_READS.md)
- [Spot Campaign Public Runbook](SPOT_CAMPAIGN_PUBLIC_RUNBOOK.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Live Order Surfaces](LIVE_ORDER_SURFACES.md)
- [Admin API](../README.admin-api.md)
- [Admission Audit Records](../README.admission-audits.md)
- [Cap/Guard Decision Records](../README.cap-guard-decisions.md)
- [Reconciliation Plan Records](../README.reconciliation-plans.md)
- [Movement And Repricing](../README.movement-repricing.md)
- [Futures/Perpetuals Admin Reads](../README.futures-perpetuals.md)
- [Guard/Risk Policy Admin Reads](../README.guard-risk-policy.md)
- [Audit Workbench Admin Reads](../README.audit-workbench.md)
- [Admin Platform Architecture](ADMIN_PLATFORM_ARCHITECTURE.md)
- [Admin Module Capability Matrix](ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Maintainer Handoff](MAINTAINER_HANDOFF.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [USDC Pair Snapshot Limit Automation MVP](plans/USDC_PAIR_SNAPSHOT_LIMIT_AUTOMATION_MVP.md)
- [Frontend Association](FRONTEND_ASSOCIATION.md)
- [Admin API E2E Plan](plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Command Workflows](COMMAND_WORKFLOWS.md)
- [Operator Read Models](OPERATOR_READ_MODELS.md)
- [Admin API Contextless Review Log](plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md)
- [Autonomous Work Queue](plans/AUTONOMOUS_WORK_QUEUE.md) - historical planning
  and artifact evidence only
- [Spot Phases 185-196 Report](plans/SPOT_PHASE_185_196_REPORT.md)
- [API Reference](../genai_data/API_REFERENCE.md)
- [Configuration](../genai_data/CONFIGURATION.md)
- [Data Models](../genai_data/DATA_MODELS.md)

## Tooling And Policy

- [Agents Overview](agents/README.md)
- [Public Invariants](agents/INVARIANTS.md)
- [Ownership](agents/OWNERSHIP.md)
- [Admin API Contract Agent](agents/AGENT_ADMIN_API_CONTRACT.md)
- [Public Release Readiness](PUBLIC_RELEASE_READINESS.md)
- [External Testing Runbook](EXTERNAL_TESTING_RUNBOOK.md)
- [Regression Process](REGRESSION_PROCESS.md)
- [Testing Strategy](../genai_data/TESTING_STRATEGY.md)
- [Spot Readiness Test Gate](SPOT_READINESS_TEST_GATE.md)
- [Spot Contextless Agent Testing](SPOT_CONTEXTLESS_AGENT_TESTING.md)
- Contextless checklist harness:
  `python3.13 tools/run_spot_contextless_agent_checklist.py --summary-only`
- Direct spot order audit:
  `python3.13 tools/run_spot_direct_order_audit.py --client-order-id <client_order_id>`
- Dashboard direct spot order audit:
  `request_spot_direct_order_audit` with `params.client_order_id`
- Spot campaign operator reports:
  `python3.13 tools/run_spot_campaign.py --ledger-cleanup-plan --summary-only`
  and `python3.13 tools/run_spot_campaign.py --pnl-delta-report --summary-only`
- Local app-only Admin API runner:
  `python3.13 tools/run_admin_api.py --dev-token local-admin-token`
- Canonical engine embedding:
  `main.py` with `COINBASE_ADMIN_API_EMBEDDED_ENABLED=true`; activation is not
  a separate fill-testing permission, and every order remains subject to the
  separately authorized order scope and complete backend gate chain. Terminal
  R11 grants no such live-order authority.
- Process-parallel regression closeout:
  `python3.13 tools/run_parallel_regression.py --workers 4`
- Stale test-process check before closeout and after interrupted tests:
  `python3.13 tools/check_stale_test_processes.py --include-sibling-frontend`
- Runtime artifact check after regression memory spikes:
  `python3.13 tools/check_runtime_artifacts.py`
- Admin API OIDC readiness smoke:
  `python3.13 tools/run_admin_oidc_readiness_smoke.py --summary-only`
- Admin API route inventory export:
  `python -m tools.export_admin_api_route_inventory`
- Autonomous work queue check:
  `python3.13 tools/run_autonomous_work_queue_check.py --summary-only`

## Examples

- [Action Condition Guard Examples](examples/action-condition-guards.md)
- [Spot Trading Examples](examples/spot-trading.md)
- [Spot Feature Intake Examples](examples/spot-feature-intake.md)
- [Spot Portfolio Sweep Examples](examples/spot-portfolio-sweep.md)
- [Spot Campaign Examples](examples/spot-campaign.md)
- [Spot Recovery Proof Examples](examples/spot-recovery-proofs.md)
- [Spot Recovery Snapshot Examples](examples/spot-recovery-snapshots.md)
- [Stealth Command Suite Examples](examples/stealth-command-suite.md)
- [Stealth Active-Placement Exchange-Truth Examples](examples/stealth-exchange-truth-proofs.md)
- [Stealth Mutation-Claim Snapshot Proof Examples](examples/stealth-mutation-claim-proofs.md)
- [Stealth Manager-Invocation Policy Examples](examples/stealth-manager-invocation-policy.md)
- [Stealth Coinbase Exchange Policy Examples](examples/stealth-coinbase-exchange-policy.md)
- [Stealth State-Mutation Policy Examples](examples/stealth-state-mutation-policy.md)
- [Stealth Post-Write Reconciliation Execution Policy Examples](examples/stealth-post-write-reconciliation-execution-policy.md)
- [Stealth Recovery Proof Examples](examples/stealth-recovery-proofs.md)
- [Stealth Reveal-Trigger Proof Examples](examples/stealth-reveal-trigger-proofs.md)
- [Stealth Reconciliation Proof Examples](examples/stealth-reconciliation-proofs.md)
- [Stealth Cancel/Replace Proof Examples](examples/stealth-cancel-replace-proofs.md)
- [Spot Campaign Retry Fixture](examples/spot-campaign-retry-plan-fixture.json)
- [Admin API Examples](examples/admin-api.md)
- [Admission Audit Examples](examples/admission-audits.md)
- [Cap/Guard Decision Examples](examples/cap-guard-decisions.md)
- [Reconciliation Plan Examples](examples/reconciliation-plans.md)
- [Movement And Repricing Examples](examples/movement-repricing.md)
- [Futures/Perpetuals Examples](examples/futures-perpetuals.md)
- [Guard/Risk Policy Examples](examples/guard-risk-policy.md)
- [Audit Workbench Examples](examples/audit-workbench.md)

## State, Modes, And Roadmaps

- [Public Roadmap](PUBLIC_ROADMAP.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Historical Agent State Snapshot](../genai_data/agent_state.md)
- [Debugging Strategy](../genai_data/DEBUGGING_STRATEGY.md)
