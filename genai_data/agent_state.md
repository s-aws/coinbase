# Agent State

Use this file as the concise durable source of truth for active engineering
work. Historical milestone detail belongs in
`docs/plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md`.

## Metadata

- Last updated (ET): 2026-06-27
- Updated by: Codex
- Backend branch: `codex/stealth-live-service-decision-3501`
- Frontend branch: `codex/stealth-live-service-decision-3501`
- Current milestone: M57 - Futures/Perpetuals Contract Foundation And Commands

## Current Objective

- Build the enterprise admin frontend/API path for the entire Coinbase trading
  engine, with Spot as the first complete product module but not the generic
  model.
- Every new admin module must use backend-owned contracts, preserve the single
  trading behavior path, avoid importing spot-only rules into non-spot domains,
  and remain understandable to contextless/blind agents through docs,
  capability matrices, tests, and review logs.

## Current Phase

- Latest completed autonomous range before this work: `7661-7680`.
- Phase range completing in this handoff: `7681-7700`.
- API active approved phase range remains `7681-7700` until the next M57
  range is implemented.
- Scope: futures request payload validation record execution-eligibility
  resolution-plan step review input store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation check output schema field-constraint source-ref
  validation-record acceptance contextless-review acceptance evidence and
  frontend display.
- Backend implementation status: complete locally.
- Frontend implementation status: complete locally.
- Contextless review status: passed for behavior through blind reviewer agent
  `019f07a2-87db-75a1-99eb-bc34c30927d3`.
- Review remediation: include the new backend registry file
  `application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_field_constraint_source_ref_validation_record_acceptance_contextless_review_acceptances.py`
  in the commit; otherwise `read_service.py` and the futures risk-proof test
  import path will fail in a fresh checkout.
- Commit/push status: pending final commit and push.
- Phase-end subagent sweep: blind reviewer agent
  `019f07a2-87db-75a1-99eb-bc34c30927d3` was closed after findings were
  consumed. No phase-scoped subagents remain intentionally open.

## Phase Contract

- The `7681-7700` rows are backend-owned disabled evidence derived from the
  completed `7661-7680` validation-record acceptance contextless-review rows.
- Presence of contextless-review acceptance evidence is not acceptance passage,
  contextless-review passage, validation-record acceptance passage,
  source-ref record acceptance passage, source-ref acceptance passage,
  source-ref declaration, constraint declaration, field-type declaration,
  field-name declaration, field declaration, schema declaration, command
  admission, Coinbase execution, reconciliation execution, browser/BFF
  authority, or spot-rule authority.
- The frontend consumes generated OpenAPI/backend contracts and remains
  display-only for this evidence surface.
- No spot-only wallet, no-shorting, USDC quote, cost-basis, inventory-lot, or
  known-profitable-inventory rule may be imported into futures/perpetual
  readiness.

## Local Validation

- Backend:
  - `python -m py_compile core\enums.py application\admin_api\models.py application\admin_api\read_service.py application\admin_api\futures_request_payload_validation_record_validation_check_output_schema_field_constraint_source_ref_validation_record_acceptance_contextless_review_acceptances.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py` passed.
  - `pytest tests/regression/test_admin_api_futures_risk_proofs.py::test_futures_command_service_contracts_are_disabled -q --tb=short` passed.
  - `pytest tests/regression/test_admin_api_contract.py::test_admin_api_admin_read_routes_return_backend_contracts -q --tb=short` passed.
  - `pytest tests/regression/test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands -q --tb=short` passed.
- Frontend:
  - `npm run typecheck` passed.
  - `npm run api:check` passed and reported generated schema fresh, route
    coverage passed, live Coinbase execution not run, notional `$0`.
  - `npm run test -- tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx` passed with `73` tests.

## Live Execution

- Live Coinbase execution for this phase: not run.
- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.

## Regression Policy

- Full backend regression is not an ordinary phase gate. It remains reserved
  for durable milestone closeout, public/release-candidate handoff,
  deployment approval/closeout, release-hardening closeout, Admin API/backend
  association closeout, or explicit user request.
- Full frontend `npm run release:gate` is likewise reserved for durable
  frontend milestone closeout or explicit closeout gates.

## Next Actions

1. Consume the blind/contextless review for `7681-7700` and remediate any
   blocker. Complete.
2. Update capability/milestone docs from current to completed if the review
   passes. Complete.
3. Run final diff/status checks and phase-end stale subagent cleanup. Complete.
4. Commit and push both repositories.

## Durable Decisions

- Use `client_order_id` for internal tracking. Use `order_id` only for
  exchange-native evidence and endpoints that require it. Coinbase
  cancellation is the explicit exception: use project wrapper
  `cancel_order(client_order_id)` because Coinbase accepts the client id.
- Preserve a single code path per behavior.
- Use enums from `core/enums.py`; do not add magic strings where an enum
  belongs.
- Respect module locks and thread-safety invariants.
- Phase-end subagent cleanup is mandatory after findings are consumed,
  remediated, or explicitly deferred. Durable milestone closeout performs a
  final stale-subagent sweep.
