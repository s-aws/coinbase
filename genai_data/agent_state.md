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

- Latest completed and pushed range before this work: `7681-7700`.
- Active approved range: `7701-7720`.
- Scope: futures command enablement contextless-review blocker summary evidence
  and frontend display. This intentionally pivots from the prior evidence
  ladder to an explicit M57 blocker exposed by the command-suite summary:
  `CONTEXTLESS_REVIEW_GATE` is required but must not be treated as command
  enablement clearance.
- Backend implementation status: complete locally.
- Frontend implementation status: complete locally.
- Contextless review status: PASS after remediation for `7701-7720`.
- Commit/push status: pending for `7701-7720`.
- Phase-end subagent sweep: reviewers
  `019f07d6-5e12-7a73-be72-b23e328d7b8b` and
  `019f07e2-e8e4-7161-9dba-bb976db49b31` were closed after findings were
  consumed. No phase-scoped subagents remain intentionally open.

## Phase Contract

- The `7701-7720` fields are backend-owned disabled evidence on the existing
  command enablement blocker summary. They carry the latest completed
  `7681-7700` blind-review evidence but do not resolve command readiness.
- Presence of command enablement contextless-review evidence is not command
  enablement clearance, contextless review passage for command readiness,
  approval passage, cap/guard passage, reconciliation passage, command
  admission, Coinbase execution, reconciliation execution, browser/BFF
  authority, or spot-rule authority.
- The frontend consumes generated OpenAPI/backend contracts and remains
  display-only for this evidence surface.
- No spot-only wallet, no-shorting, USDC quote, cost-basis, inventory-lot, or
  known-profitable-inventory rule may be imported into futures/perpetual
  readiness.

## m57_7681_7700_blind_review

- Result: PASS after remediation.
- Reviewer agent: `019f07a2-87db-75a1-99eb-bc34c30927d3`.
- Scope: completed M57 `7681-7700` validation-record acceptance
  contextless-review acceptance evidence and frontend display.
- Remediation: tracked the new backend registry, corrected stale active-range
  docs, added direct frontend read-model and mock-backend assertions, and
  preserved no-live/no-browser/no-BFF/no-spot-rule authority.
- Phase-end subagent sweep: reviewer was closed after findings were consumed;
  no phase-scoped subagents remain intentionally open for `7681-7700`.
- Live Coinbase execution: not run; submitted notional `0` USDC; executed
  notional `0` USDC.

## Local Validation

- Backend:
  - `python -m py_compile application\admin_api\models.py application\admin_api\read_service.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py` passed.
  - `pytest tests/regression/test_admin_api_futures_risk_proofs.py::test_futures_command_enablement_blocker_summaries_remain_read_only -q --tb=short` passed.
  - `pytest tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract -q --tb=short` passed.
  - `pytest tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands -q --tb=short` passed.
  - `pytest tests\regression\test_admin_api_contract.py::test_admin_api_frontend_fixtures_are_bounded_and_offline_safe -q --tb=short` passed after stale test-process checker reported no stale processes from the interrupted prior run.
- Frontend:
  - `npm run typecheck` passed.
  - `npm run api:check` passed and reported generated schema fresh, route
    coverage passed, live Coinbase execution not run, notional `$0`.
  - `npm run test -- tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx tests/unit/qualityGates.test.tsx` passed with `89` tests before final active-range metadata/doc corrections.

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

1. Consume the blind/contextless review for `7701-7720` and remediate any
   blocker.
2. Run backend/frontend autonomous validators after metadata corrections.
3. Run final diff/status checks and phase-end stale subagent cleanup.
4. Commit and push both repositories.
5. Select the next concrete M57 implementation range from an explicit
   futures/perpetual blocker only after this range is pushed.

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
