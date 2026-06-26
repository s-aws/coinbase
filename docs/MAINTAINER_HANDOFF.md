# Maintainer Handoff

This guide is the backend entry point for maintainers and contextless agents
working on the enterprise admin platform.

## Scope

The backend repository owns trading behavior, Coinbase integration, guard
checks, authorization, audit evidence, OpenAPI schema generation, and all live
execution authority. The frontend repository at `C:\coinbase-frontend` owns the
browser application and must consume backend-owned contracts only.

Spot is the first complete product module, not the generic model for futures,
perpetuals, stealth orders, movement/repricing, or future modules.

## Start Here

1. Read `AGENTS.md`, then `agent.md`.
2. Read `docs/README.md` for the ordered documentation index.
3. Read `README.admin-api.md` for the Admin API boundary.
4. Read `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before changing module scope.
5. Read `docs/plans/ADMIN_API_ROUTE_INVENTORY.md` before adding or changing a route.
6. Read `docs/LIVE_ORDER_SURFACES.md` before any live-order or cancellation work.
7. Read `docs/plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md` before declaring a handoff complete.
8. Read `docs/plans/AUTONOMOUS_WORK_QUEUE.md` before advancing phases. Each
   active phase must map to an approved durable milestone and an explicit
   architecture or planning gap.

## Subagent Hygiene

Phase-end cleanup is the canonical timing. Close subagents spawned for the
completed phase after their findings have been consumed, remediated, or
explicitly deferred, and close stale or previously unused subagents from
earlier phases or milestones discovered during that sweep. Durable milestone
closeout is a final audit sweep, not the first cleanup point. Do not close a
subagent that is still running required validation, producing required
evidence, or awaiting a user decision. Any intentionally open handoff agent
must have recorded owner, purpose, and expected next action. Record the
phase-end or milestone-closeout sweep result before advancing.

## Backend Authority Rules

- Use one code path per behavior.
- Use `client_order_id` for internal order identity.
- Coinbase cancellation is the explicit exception: call the project wrapper
  `cancel_order(client_order_id)` because Coinbase accepts the client id.
- Do not put trading decisions in browser code or generated frontend clients.
- Do not import spot no-shorting or wallet-inventory rules into futures or
  perpetual workflows.
- Do not mutate stealth local state unless the corresponding live exchange
  handling has gone through the existing cancel, move, or reconcile path.

## Adding An Admin Module

1. Define the backend read or command contract first.
2. Add route inventory evidence in `application/admin_api/route_inventory.py`
   and `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`.
3. Add typed response/request models in `application/admin_api/models.py`.
4. Use existing shared services; do not introduce a parallel trading path.
5. Update `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`.
6. Update examples under `docs/examples/`.
7. Regenerate `openapi/coinbase-admin-api.yaml`.
8. Add focused regression coverage in `tests/regression/`.
9. Coordinate frontend generated-client changes from the OpenAPI output.
10. Run a blind/contextless review for module discoverability and authority boundaries.

## Contextless Task Card

Use this checked-in task shape when asking a fresh agent to prove the handoff
material is sufficient:

```text
Without chat history, explain how to add a read-only Admin API module for a
new backend evidence source. Identify the files you would read first, the
backend route/model/test/docs files you would change, how the frontend should
consume the generated OpenAPI contract, and which gates must pass. Do not
implement trading behavior or live Coinbase execution.
```

Passing answer requirements:

- names `docs/MAINTAINER_HANDOFF.md`, `README.admin-api.md`,
  `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, and
  `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`
- keeps backend authority over trading behavior and live execution
- sends frontend work through OpenAPI generation and canonical wrappers
- lists focused backend/frontend checks, autonomous validation, and
  blind/contextless review for ordinary phases
- reserves full backend regression and frontend release gate for durable
  milestone closeout, public/release-candidate handoff, deployment
  approval/closeout, release-hardening closeout, Admin API/backend association
  closeout, or explicit request
- reports live Coinbase execution as not run unless an explicit live phase is
  approved

## Required Gates

Backend changes must pass focused tests and validators for the changed
behavior. Full regression is a durable milestone-closeout, public/release-
candidate handoff, deployment approval/closeout, release-hardening closeout,
Admin API/backend association closeout, or explicit-request gate:

```powershell
python tools/run_parallel_regression.py --workers 4
python tools\run_autonomous_work_queue_check.py --summary-only
```

Frontend/API association changes must pass focused frontend checks for the
changed behavior. Full release gate is a durable milestone-closeout,
public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or
explicit-request gate:

```powershell
npm run release:gate
```

Live Coinbase execution is not part of normal handoff validation. If a live
phase is explicitly approved, report product, submitted notional, executed
notional, retained inventory, reconciliation result, and audit ids.

## Current Handoff State

- M9/M21/M23/M24/M25/M26 enterprise readiness is exposed by
  `GET /api/v1/admin/enterprise-readiness`.
- Latest completed autonomous range: `7161-7180` under M57.
- Active autonomous range: `7181-7200` under M57.
- Current range validation: in progress for execution-eligibility
  resolution-plan step review input store record-validation remediation
  dependency evidence and bounded command-suite materialized samples. Completed
  `7161-7180` record-validation remediation evidence remains carried forward.
  No live Coinbase
  execution is planned; submitted/executed notional remains `0` USDC.
- Current `7181-7200` blind/contextless review: phase-close local verification
  is in progress for the newly added store record-validation remediation dependency evidence. Fresh
  blind/contextless backend and frontend re-review could not be started earlier
  because Codex subagent usage was exhausted, so this handoff must not be read
  as completed fresh subagent evidence until the review log says so. The
  required boundary is that record-validation remediation dependency rows are
  backend-owned disabled evidence only; they do not create dependency graphs,
  create work items, claim work, create claim traces, perform remediation,
  configure validation gates, create stores, configure writers, allow writes,
  accept records, validate records, admit commands, call Coinbase, execute
  reconciliation, mutate futures/order/exchange state, or grant browser/BFF or
  spot-rule authority.
- Completed `7161-7180` blind/contextless review: phase-close local
  verification completed for store record-validation remediation evidence.
  Fresh subagent review was unavailable because of Codex usage limits; local
  autonomous verification is the recorded evidence.
- Completed `7141-7160` blind/contextless review: phase-close local
  verification completed for store record-validation evidence. Fresh subagent
  review was unavailable because of Codex usage limits; local autonomous
  verification is the recorded evidence.
- Completed `7121-7140` blind/contextless review: completed after remediation.
  The phase added backend-owned disabled store record-contract evidence and
  frontend display, preserved no-live/no-authority posture, and recorded that
  record-contract presence is not blocker resolution.
- Completed `7101-7120` blind/contextless review: completed after remediation.
  Arendt found only stale backend review-log/handoff evidence after verifying
  the store-requirement implementation as fail-closed; Hilbert found only
  stale frontend/backend review-log, frontend testing, and ignored local
  artifact evidence after verifying the frontend implementation as
  display-only. Bernoulli then found the backend read-service still emitted
  `approved_phase_range=7081-7100`; that finding was consumed by updating the
  read-service constant, backend contract assertions, OpenAPI, and generated
  frontend schema so runtime evidence now emits `7101-7120`. Parfit then found
  stale current-scope text in `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`; that
  finding was consumed by moving the matrix to `7101-7120` store-requirement
  evidence and adding the matrix to the autonomous checker. Noether performed
  the final blind/backend re-review and passed after verifying runtime
  `7101-7120` command-suite evidence, zero available/writer store requirement
  counts, and preserved no-live/no-authority posture. The findings were
  consumed by updating both review logs, frontend testing docs, and regenerated
  local release artifact evidence.
- Completed `7081-7100` blind/contextless review: completed after remediation.
  Carver initially found stale review logs plus public/raw command-suite
  payload size regression; the payload regression was remediated by bounded
  materialized detail samples. Ampere re-reviewed the remediated backend and
  found only stale review-log leadership, with no live-execution,
  reconciliation, futures-state-mutation, browser/BFF-authority, or spot-rule
  blocker. Socrates and Euler found only stale review-log leadership on the
  frontend side and no code-level authority leak.
- Completed `7081-7100` validation: focused backend/frontend checks passed for
  execution-eligibility resolution-plan step review input evidence and bounded
  command-suite materialized samples. Backend and frontend autonomous log
  validation passed after review-log and handoff updates. No live Coinbase
  execution was run; submitted/executed notional remains `0` USDC.
- Completed `7061-7080` validation: backend/frontend focused validation,
  OpenAPI and generated schema freshness, autonomous queue, ownership,
  stale-process, runtime-artifact report-only, and diff checks passed for
  execution-eligibility resolution-plan step review evidence. Full regression
  remains a durable milestone closeout gate. No live Coinbase execution was
  run; submitted/executed notional remains `0` USDC.
- Completed `7061-7080` blind/contextless review: backend and frontend fresh
  reviewers passed after remediation and confirmed resolution-plan step review
  evidence remained backend-owned, read-only, fail-closed, no-live, and
  display-only.
- Completed `7041-7060` blind/contextless review: Ohm initially failed on
  missing carried-forward resolution-plan terms in `genai_data/agent_state.md`
  and stale review-log leadership, and Plato initially failed on stale
  frontend/backend review-log leadership plus frontend quality gates still
  expecting `7021-7040`. The findings were consumed and remediated by adding
  current `7041-7060` review-log entries, moving active quality gates to
  `7041-7060`, and preserving `7021-7040` as completed history. Ohm and
  Plato re-reviewed and passed after remediation, then phase-end cleanup
  closed both agents.
- Completed `7041-7060` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility resolution-plan
  step evidence. Full regression remains a durable milestone closeout gate. No
  live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Completed `7021-7040` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility resolution-plan
  evidence. Full regression remains a durable milestone closeout gate. No live
  Coinbase execution was run; submitted/executed notional remains `0` USDC.
- Completed `7021-7040` blind/contextless review: Hubble initially failed on
  stale backend active-range docs, Hilbert initially failed on stale frontend
  active-range/current-phase docs, both sets of findings were remediated, both
  re-reviews passed, and phase-end subagent cleanup closed Hubble and Hilbert.
- Completed `7001-7020` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility semantic
  closure evidence. Full regression remains a durable milestone closeout gate.
  No live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Completed `7001-7020` blind/contextless review: the final fresh backend and
  frontend reviews passed after remediation and confirmed semantic closure
  evidence remained backend-owned disabled/read-only evidence. The frontend
  only displayed backend contracts without browser/BFF/live execution
  authority, no spot-only wallet/cost-basis/sell-guard rule was imported into
  futures/perpetuals, and phase-end subagent cleanup was completed.
- Current enterprise manual Spot order path is dry-submit/review only:
  `POST /api/v1/orders` remains live-disabled, may derive backend-owned
  `client_order_id`, and exits before Spot wallet, no-short sell authority,
  product capability, event-stream audit, or REST submission checks unless a
  future HTTP live-execution gate explicitly passes
  `allow_live_execution=true`. Backend `trader` or `admin` RBAC authority is
  required for order-create command tests; a frontend human "operator" label is
  not enough backend authority.
- Active range adds futures request payload validation record
  execution-eligibility resolution-plan step evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`.
  The current fields include `execution_eligibility_resolution_plan_ref`,
  `execution_eligibility_resolution_plan_contract_ref`,
  `execution_eligibility_resolution_plan_step_ref`,
  `execution_eligibility_resolution_plan_step_contract_ref`,
  `resolution_plan_step_kind`, `resolution_plan_step_ready=false`,
  `resolution_plan_step_accepted=false`, `ordered_resolution_step_ref`,
  `ordered_resolution_step_refs`, `ordered_resolution_step_count`,
  `resolution_plan_present=true`, `resolution_plan_ready=false`,
  `resolution_plan_accepted=false`,
  `runtime_evidence_satisfies_semantic_contract=false`,
  `validation_record_admission_link_ready=false`, and
  `blocker_resolved=false`. Resolution plan step presence is not blocker
  resolution, runtime acceptance, command admission, Coinbase execution,
  reconciliation execution, futures/order/exchange mutation, browser/BFF
  execution authority, or spot-rule authority.
- Completed `7021-7040` carries forward futures request payload validation
  record execution-eligibility resolution-plan evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py`.
- Completed `7001-7020` carries forward futures request payload validation
  record execution-eligibility semantic closure evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py`
  and
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py`.
- Completed `6981-7000` carries forward disabled futures request payload
  validation record reconciliation semantics through
  `application/admin_api/futures_request_payload_validation_record_reconciliation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_reconciliation_semantics`.
- Completed `6961-6980` carries forward disabled futures request payload
  validation record cancel semantics through
  `application/admin_api/futures_request_payload_validation_record_cancel_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`, and
  `iter_futures_request_payload_validation_record_cancel_semantics`.
- Completed `6941-6960` carries forward disabled futures request payload validation record
  order semantics through
  `application/admin_api/futures_request_payload_validation_record_order_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_order_semantics`,
  including `request_payload_validation_record_order_semantic_count`,
  `blocking_request_payload_validation_record_order_semantic_count`,
  `ready_request_payload_validation_record_order_semantic_count`,
  `runtime_observed_request_payload_validation_record_order_semantic_count`,
  `request_payload_validation_record_order_semantics`,
  `order_semantics_ref`, `order_semantics_contract_ref`,
  `evidence_routes`, `order_semantics_contract_available=false`,
  `order_semantics_contract_ready=false`, `order_identity_bound=false`,
  `order_side_bound=false`, `order_size_bound=false`,
  `order_price_bound=false`, `order_type_bound=false`,
  `runtime_order_evidence_observed=false`,
  `runtime_evidence_satisfies_order_semantics=false`, and
  `validation_record_order_semantics_ready=false`.
  Completed `6921-6940` carries forward disabled futures request payload
  validation record funding semantics through
  `application/admin_api/futures_request_payload_validation_record_funding_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_funding_semantics`,
  including `request_payload_validation_record_funding_semantic_count`,
  `blocking_request_payload_validation_record_funding_semantic_count`,
  `ready_request_payload_validation_record_funding_semantic_count`,
  `runtime_observed_request_payload_validation_record_funding_semantic_count`,
  `request_payload_validation_record_funding_semantics`,
  `funding_semantics_ref`, `funding_semantics_contract_ref`,
  `evidence_routes`, `funding_semantics_contract_available=false`,
  `funding_semantics_contract_ready=false`, `funding_rate_bound=false`,
  `funding_fee_bound=false`, `funding_interval_bound=false`,
  `funding_cost_bound=false`, `runtime_funding_evidence_observed=false`,
  `runtime_evidence_satisfies_funding_semantics=false`, and
  `validation_record_funding_semantics_ready=false`.
  Completed `6901-6920` carries forward disabled futures request payload
  validation record close-only semantics through
  `application/admin_api/futures_request_payload_validation_record_close_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_close_only_semantics`.
  Completed `6881-6900` carries forward disabled futures request payload
  validation record reduce-only semantics through
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_reduce_only_semantics`.
  Completed `6861-6880` carries forward disabled futures request payload
  validation record liquidation semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_liquidation_semantics`.
  Completed `6841-6860` carries forward disabled futures request payload
  validation record collateral semantics through
  `application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_collateral_semantics`.
  Completed `6821-6840` carries forward disabled futures request payload
  validation record margin semantics through
  `application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_margin_semantics`.
  Completed `6801-6820` carries forward disabled futures request payload
  validation record position semantics through
  `application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_position_semantics`,
  including `request_payload_validation_record_position_semantic_count`,
  `blocking_request_payload_validation_record_position_semantic_count`,
  `ready_request_payload_validation_record_position_semantic_count`,
  `runtime_observed_request_payload_validation_record_position_semantic_count`,
  `request_payload_validation_record_position_semantics`,
  `position_semantics_ref`, `position_semantics_contract_ref`,
  `evidence_routes`, `position_semantics_contract_available=false`,
  `position_semantics_contract_ready=false`, `position_identity_bound=false`,
  `position_scope_bound=false`, `position_side_derivation_bound=false`,
  `position_size_bound=false`, `position_notional_bound=false`,
  `runtime_position_evidence_observed=false`,
  `runtime_evidence_satisfies_position_semantics=false`, and
  `validation_record_position_semantics_ready=false`.
  Completed `6781-6800` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
  Completed `6761-6780` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence binding.
  Completed `6701-6720` carries forward disabled futures request payload
  validation record semantic artifact definition review input evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_inputs.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs`.
  Completed `6661-6680`
  carries forward disabled futures request payload validation record semantic
  artifact definition evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definitions.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_semantic_artifact_definitions`.
  Completed `6641-6660` carries forward disabled futures request payload
  validation record semantic artifact evidence.
