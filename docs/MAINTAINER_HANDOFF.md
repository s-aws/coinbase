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
- Latest completed autonomous range: `6841-6860` under M57.
- Active autonomous range: `6861-6880` under M57.
- Current range validation: backend focused validation passed on 2026-06-25
  with `python -m pytest tests\regression\test_admin_api_futures_risk_proofs.py -q --tb=short`
  plus OpenAPI freshness subset
  `python -m pytest tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract -q --tb=short`
  (18 total focused tests passed). Backend autonomous queue, ownership,
  stale-process, runtime-artifact report-only, and diff checks also ran. No
  live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Active range blind/contextless review: no callable subagent tool was
  available in this session, so a direct contextless-file review plus checker
  hardening was used. Fresh backend/frontend fallback review passed and the
  phase-end stale-subagent sweep found no phase-scoped subagents left open.
- Current enterprise manual Spot order path is dry-submit/review only:
  `POST /api/v1/orders` remains live-disabled, may derive backend-owned
  `client_order_id`, and exits before Spot wallet, no-short sell authority,
  product capability, event-stream audit, or REST submission checks unless a
  future HTTP live-execution gate explicitly passes
  `allow_live_execution=true`. Backend `trader` or `admin` RBAC authority is
  required for order-create command tests; a frontend human "operator" label is
  not enough backend authority.
- Active range adds disabled futures request payload validation record liquidation
  semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_liquidation_semantics`,
  including `request_payload_validation_record_liquidation_semantic_count`,
  `blocking_request_payload_validation_record_liquidation_semantic_count`,
  `ready_request_payload_validation_record_liquidation_semantic_count`,
  `runtime_observed_request_payload_validation_record_liquidation_semantic_count`,
  `request_payload_validation_record_liquidation_semantics`,
  `liquidation_semantics_ref`, `liquidation_semantics_contract_ref`,
  `evidence_routes`, `liquidation_semantics_contract_available=false`,
  `liquidation_semantics_contract_ready=false`,
  `liquidation_buffer_bound=false`, `liquidation_price_bound=false`,
  `liquidation_distance_bound=false`, `liquidation_threshold_bound=false`,
  `runtime_liquidation_evidence_observed=false`,
  `runtime_evidence_satisfies_liquidation_semantics=false`, and
  `validation_record_liquidation_semantics_ready=false`.
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
