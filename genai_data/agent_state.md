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

- Latest completed and pushed range before this work: `7701-7720`.
- Active approved range: `7721-7740`.
- Scope: futures command prerequisite summary evidence and frontend display.
  This continues M57 by aggregating existing per-command prerequisite rows into
  `prerequisite_summaries` so unresolved prerequisite families are visible
  without enabling any command path.
- Backend implementation status: complete locally.
- Frontend implementation status: complete locally.
- Contextless review status: PASS after remediation for `7721-7740`.
- Commit/push status: pending for `7721-7740`.
- Prior phase-end subagent sweep: reviewers
  `019f07d6-5e12-7a73-be72-b23e328d7b8b` and
  `019f07e2-e8e4-7161-9dba-bb976db49b31` were closed after `7701-7720`
  findings were consumed. No prior phase-scoped subagents remain intentionally
  open.

## Phase Contract

- The `7721-7740` fields are backend-owned disabled evidence on the existing
  futures command-suite read model. They derive from the existing command
  prerequisite rows and do not resolve command readiness.
- Presence of futures command prerequisite summary evidence is not
  prerequisite resolution, command enablement clearance, contextless review
  passage for command readiness, approval passage, cap/guard passage,
  reconciliation passage, command admission, Coinbase execution,
  reconciliation execution, browser/BFF authority, or spot-rule authority.
- The summary evidence can report blocked families, affected commands,
  evidence routes, and required evidence refs, but it cannot resolve
  prerequisites, clear command enablement, call Coinbase, execute
  reconciliation, mutate state, grant browser/BFF authority, or import
  spot-rule authority.
- Exact boundary phrase: prerequisite summaries cannot resolve prerequisites.
- The frontend consumes generated OpenAPI/backend contracts and remains
  display-only for this evidence surface.
- No spot-only wallet, no-shorting, USDC quote, cost-basis, inventory-lot, or
  known-profitable-inventory rule may be imported into futures/perpetual
  readiness.

## m57_7721_7740_blind_review

- Result: PASS after remediation.
- Reviewer agents:
  `019f0812-deb8-7500-9284-fd5e06f96f36` failed the first review and
  `019f081c-d367-7071-8e4e-a4ca4d9c179b` passed the fresh re-review.
- Scope: active M57 `7721-7740` futures command prerequisite summary evidence
  and frontend display.
- Remediation: preserved `prerequisite_summaries.required_evidence_refs` in
  the public compacted futures command-suite payload, added public-route
  regression coverage, and changed completed `7701-7720` history from active
  to completed wording.
- Live Coinbase execution: not run; submitted notional `0` USDC; executed
  notional `0` USDC.

## m57_7701_7720_blind_review

- Result: PASS after remediation.
- Reviewer agents:
  `019f07d6-5e12-7a73-be72-b23e328d7b8b` failed the first review and
  `019f07e2-e8e4-7161-9dba-bb976db49b31` passed the fresh re-review.
- Scope: completed M57 `7701-7720` command enablement contextless-review
  blocker summary evidence and frontend display.
- Remediation: made prior blind-review evidence traceable, corrected stale
  active/completed range docs, hardened autonomous validators, rendered the
  evidence ref and phase-end sweep status, and preserved the display-only
  no-live boundary.
- Phase-end subagent sweep: both reviewers were closed after findings were
  consumed; no phase-scoped subagents remain intentionally open for
  `7701-7720`.
- Commit/push status: completed in both repositories before active
  `7721-7740`.
- Live Coinbase execution: not run; submitted notional `0` USDC; executed
  notional `0` USDC.

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

- `7701-7720` closeout validation passed before commit/push in both repos.
- `7721-7740` validation so far:
  - Backend `python -m py_compile application\admin_api\models.py application\admin_api\read_service.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py` passed.
  - Backend `pytest tests\regression\test_admin_api_futures_risk_proofs.py::test_futures_command_enablement_blocker_summaries_remain_read_only -q --tb=short` passed.
  - Backend `pytest tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands tests\regression\test_admin_api_contract.py::test_admin_api_frontend_fixtures_are_bounded_and_offline_safe -q --tb=short` passed.
  - Backend remediation check `pytest tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands -q --tb=short` passed.
  - Backend `python tools\run_autonomous_work_queue_check.py --summary-only` passed.
  - Frontend `npm run typecheck` passed.
  - Frontend `npm run api:check` passed.
  - Frontend `npm run test -- tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx tests/unit/qualityGates.test.tsx` passed with `89` tests.
  - Frontend `npm run autonomous:check` passed.
  - `python tools\check_stale_test_processes.py --include-sibling-frontend`
    passed with no stale test processes.
- Remaining before phase closeout: final status after subagent cleanup, commit,
  and push.

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

1. Finish `7721-7740` frontend mock/read-model/tests and docs.
2. Run focused backend/frontend validators for prerequisite summaries.
3. Run blind/contextless review for `7721-7740` and remediate any blocker.
4. Run autonomous validators, final diff/status checks, and phase-end stale
   subagent cleanup.
5. Commit and push both repositories.

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
