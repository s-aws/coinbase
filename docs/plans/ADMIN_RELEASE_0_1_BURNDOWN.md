# Admin Release 0.1 Burn-Down

This document is the release-control pivot for the enterprise admin platform.
It replaces evidence-only roadmap expansion as the active planning surface
until a private operator admin release candidate can manage the project without
falling back to `dashboard.py` for normal administration.

## Release Goal

Release 0.1 is a private operator MVP. It is not the public release.

The release is usable when an operator can open the admin frontend, inspect the
engine, run backend-supported commands through backend-owned contracts, see
unsupported behavior as explicit `unsupported` or `not_modeled` state, and use
audit/reconciliation evidence to understand what happened.

The governing question for every phase is:

> Does this make the frontend able to manage the project?

If the answer is no, the phase is not Release 0.1 work.

## Drift Stop Rule

No new evidence-only phase may be created unless it directly closes a named
Release 0.1 blocker below. Existing futures/perpetual proof evidence remains
historical context, but it is no longer the active roadmap driver.

Future agents must not add generic polish, recommendation-only phases, or more
proof-summary batches unless the work is tied to an operator workflow needed
for Release 0.1. A missing backend behavior must be surfaced as `unsupported`
or `not_modeled`; it must not be implemented in the browser, BFF, or route-local
FastAPI code.

## Release Blockers

P0 blockers must be cleared before Release 0.1 can be called a usable private
operator admin.

| Area | P0 Release Requirement | Current Rule |
| --- | --- | --- |
| Admin shell | Operator can see backend health, lifecycle state, and safe start/stop/pause/resume status where backend supports it. | No direct browser process authority unless backend-owned lifecycle contracts exist. |
| Account inventory | Products, accounts, balances, orders, fills, positions, and relevant funding/risk reads are visible from backend-owned contracts. | Missing or unsupported rows are explicit. |
| Spot commands | Spot buy, sell, and cancel workflows are usable through backend gates where already supported. | Spot no-shorting, wallet, cost-basis, and USDC rules stay spot-only. |
| Stealth commands | Create, cancel, reveal, move, reprice, recovery, and exchange-truth status are manageable where backend support exists. | No hide-again shortcut and no local stealth mutation without exchange cancel/move/reconcile proof. |
| Movement and repricing | Move, premark, reprice, cooldown, claim, cancel/replace, audit, and recovery workflows are manageable where backend support exists. | Existing mutation locks and replacement-slot rules remain authoritative. |
| Automation and campaigns | Operators can inspect scheduler/campaign state and use safe controls for supported runs, limits, pause/resume, and retry behavior. | No browser scheduler or unbounded loop authority. |
| Audit and reconciliation | Operators can correlate command attempts, approvals, cap/guard decisions, exchange intent, fills, and reconciliation status. | Audit/reconciliation authority stays backend-owned. |
| Settings and policy | Operators can inspect configuration and safely edit only backend-supported settings with audit and validation. | No secret exposure and no direct browser database repair. |
| Unsupported behavior | Every incomplete backend route or workflow appears as `unsupported` or `not_modeled` with a reason and next owning module. | Hidden gaps block release. |
| Validation | Focused tests pass per slice; full backend regression and frontend release gate run only at Release 0.1 closeout or another major gate. | Full regression is not an ordinary phase gate. |

## Non-Goals

- Public release readiness.
- More proof-summary expansion that does not unlock an operator workflow.
- Futures/perpetual live execution.
- Browser-owned trading authority or BFF execution authority.
- A second trading path beside the existing backend/domain/exchange path.
- Importing spot-only rules into stealth, futures/perpetuals, or movement
  modules.

## Active Phases 8101-8120

Batch label: Stealth Lifecycle Operator Controls.

These phases clear the next concrete Release 0.1 blocker for Stealth commands:
operators must be able to inspect stealth lifecycle state, exchange-reality
evidence, mutation-claim posture, command readiness, post-write evidence, and
blocked create/reveal/move/cancel/recovery/reconciliation paths through the
enterprise frontend/API without falling back to proof-of-concept dashboards.
This range is no-live by default: it may add or tighten read models,
adapters, command readiness, handoffs, mocks, and focused validation, but it
must not add browser/BFF trading authority, route-local execution, direct
Coinbase calls, stealth state mutation, hide-again shortcuts, exchange-order
id tracking, or a second trading path.

Every phase must answer: Does this make the frontend able to manage the project?

Active Release 0.1 `8101-8120` adds a Stealth Lifecycle Operator Controls
slice so operators can inspect stealth lifecycle state, exchange-reality
evidence, mutation-claim posture, command readiness, post-write evidence, and
blocked create/reveal/move/cancel/recovery/reconciliation paths through the
enterprise frontend/API without browser/BFF trading authority, route-local
execution, Coinbase calls, state mutation, hide-again shortcuts, or a second
trading path while completed `8081-8100` carries the Campaign/Sweep Operator
Controls evidence.

Exact autonomous phrase: Active Release 0.1 `8101-8120` adds a Stealth Lifecycle Operator Controls slice so operators can inspect stealth lifecycle state, exchange-reality evidence, mutation-claim posture, command readiness, post-write evidence, and blocked create/reveal/move/cancel/recovery/reconciliation paths through the enterprise frontend/API without browser/BFF trading authority, route-local execution, Coinbase calls, state mutation, hide-again shortcuts, or a second trading path while completed `8081-8100` carries the Campaign/Sweep Operator Controls evidence.

### Phase 8101 - Advance Active Queue Range

- Update autonomous validators, runtime phase evidence, durable state,
  handoff docs, and phase records so active work is `8101-8120` and completed
  `8081-8100` remains historical Campaign/Sweep Operator Controls evidence.
- Evidence update 2026-06-29: active range advanced to `8101-8120`
  Stealth Lifecycle Operator Controls. This follows the Release 0.1
  Stealth commands blocker and the route-to-UI matrix, which still marks
  stealth workflows blocked by exchange-reality, lifecycle-write,
  live-disabled, and reconciliation gates. Backend/frontend AGENTS and owner
  instructions were re-reviewed with no direction change. Blind reviewer
  `019f1438-6acf-70e2-aad2-fab95b575e99` passed the range selection and
  confirmed no higher-impact blocker was obvious, provided the range remains
  backend-owned operator management/gate surfacing and not live stealth
  execution. Live Coinbase execution was not run and submitted/executed
  notional stayed 0 USDC.
- Validation update 2026-06-29: backend and frontend autonomous validators
  now pass for `8101-8120`; backend focused phase-range regressions passed
  with 11 tests; OpenAPI freshness, ownership, frontend generated API
  coverage, typecheck, lint, focused unit tests, and stale-process checks
  passed. Admin API full contract validation timed out before completion and
  is not treated as a milestone closeout gate for this ordinary transition.

### Phase 8102 - Stealth Operator Scope

- Define the backend/frontend boundary for stealth lifecycle operator
  controls, including no-live posture, exchange-reality constraints,
  mutation-claim ownership, supported read evidence, and explicit
  unsupported or not-modeled gaps.

### Phase 8103 - Backend Stealth Route Inventory

- Inventory stealth list/detail, command-suite, exchange-truth,
  mutation-claim, reveal-trigger, submission-adapter, recovery,
  cancel/replace, and post-write evidence contracts needed for operator
  management.

### Phase 8104 - Stealth Exchange-Reality Contract Map

- Map which routes prove live placement, exchange truth, cancel/replace
  prerequisites, and reveal state without marking revealed orders hidden or
  mutating local state without exchange handling.

### Phase 8105 - Stealth Mutation-Claim Contract Map

- Map mutation-claim evidence and ownership boundaries so the admin UI can
  show why create/reveal/move/cancel/recovery/reconciliation actions are
  usable, blocked, unsupported, or not modeled without acquiring claims in the
  browser.

### Phase 8106 - Stealth Command-Suite Action-State Audit

- Audit backend command-suite action-state rows for create, reveal, move,
  cancel, recovery, reconciliation, and movement reprice handoff coverage.

### Phase 8107 - Stealth Create/Cancel Draft Readiness

- Tighten backend and frontend readiness evidence for stealth create and
  cancel command drafts while keeping live placement and cancellation
  authority in existing backend paths.

### Phase 8108 - Stealth Reveal/Move/Reprice Draft Readiness

- Tighten readiness evidence for reveal, move, and movement reprice drafts,
  including exchange-reality, active-placement, and cancel/replace blockers.

### Phase 8109 - Stealth Recovery/Reconciliation Gap Surfacing

- Surface recovery and reconciliation blockers with exact backend evidence and
  `unsupported` or `not_modeled` status instead of browser repair or
  reconciliation logic.

### Phase 8110 - Post-Write Evidence Contract Review

- Review post-write execution journal, reconciliation proof, and verification
  evidence contracts so operators can inspect what happened without treating
  evidence presence as reconciliation execution.

### Phase 8111 - Frontend Stealth Status Adapter

- Tighten generated-wrapper adapters and typed view models for stealth
  lifecycle status, command-suite, and evidence rows.

### Phase 8112 - Stealth Detail Action Matrix UX

- Make selected stealth-order detail render a compact action-state matrix for
  supported, blocked, unsupported, and not-modeled lifecycle actions.

### Phase 8113 - Command Workflow Stealth Handoffs

- Ensure Stealth Orders hand off to Command Workflows with prefill-only
  `stealth_order_id` context and no `client_order_id`, active placement id,
  exchange `order_id`, acknowledgement, or automatic submission.

### Phase 8114 - Exchange Truth Evidence UX

- Make exchange-truth, active-placement, and Coinbase submission-policy
  evidence inspectable without implying Coinbase reads, cancellation,
  replacement, reveal, or lifecycle mutation authority.

### Phase 8115 - Mutation Claim And Post-Write Evidence UX

- Make mutation-claim, recovery-proof, cancel/replace-proof, post-write
  journal, reconciliation proof, and verification evidence inspectable from
  the owning stealth surfaces.

### Phase 8116 - No Browser/BFF Stealth Authority Assertions

- Add or tighten assertions that frontend/BFF code does not implement stealth
  trading behavior, mutation claims, exchange-truth resolution, dashboard
  WebSocket fallbacks, Coinbase calls, route-local execution, or a second
  stealth path.

### Phase 8117 - Mock Runtime Parity

- Align mock runtime stealth fixtures with backend unsupported/not-modeled,
  no-live, exchange-reality, mutation-claim, and non-authoritative evidence
  semantics.

### Phase 8118 - Route-To-UI Matrix Stealth Update

- Update route-to-UI and workflow matrices so every stealth lifecycle route
  maps to an owning frontend surface and explicit authority boundary.

### Phase 8119 - Focused Backend And Frontend Tests

- Run focused backend contract/regression checks and focused frontend adapter,
  command-security, generated API, and quality checks covering stealth
  lifecycle operator controls.

### Phase 8120 - Blind Review And Evidence Push

- Run blind/contextless backend/frontend review for stealth lifecycle operator
  controls, remediate blocking ambiguity, then commit and push synchronized
  backend/frontend evidence with no-live notional reporting.

## Completed Phases 8081-8100

Batch label: Campaign/Sweep Operator Controls.

These phases clear the next concrete Release 0.1 blocker for Automation and
Campaigns: operators must be able to inspect campaign and sweep automation
state, review scheduler/retry/control readiness, and use backend-owned
no-live controls through the enterprise frontend/API without falling back to
proof-of-concept dashboards. This range is no-live by default: it may add or
tighten read models, adapters, command readiness, handoffs, mocks, and focused
validation, but it must not add browser scheduler authority, BFF runner
authority, direct Coinbase calls, unbounded automation loops, order execution,
or a second campaign/sweep execution path.

Every phase must answer: Does this make the frontend able to manage the project?

Active Release 0.1 `8081-8100` adds a Campaign/Sweep Operator Controls slice
so operators can inspect campaign and sweep automation state, review
scheduler, retry, and control readiness, and use backend-owned no-live
controls through the enterprise frontend/API without browser scheduler, BFF
runner, or Coinbase execution authority while completed `8061-8080` carries
the Audit/Reconciliation Operator Correlation evidence.

Exact autonomous phrase: Active Release 0.1 `8081-8100` adds a Campaign/Sweep Operator Controls slice so operators can inspect campaign and sweep automation state, review scheduler, retry, and control readiness, and use backend-owned no-live controls through the enterprise frontend/API without browser scheduler, BFF runner, or Coinbase execution authority while completed `8061-8080` carries the Audit/Reconciliation Operator Correlation evidence.

### Phase 8081 - Advance Active Queue Range

- Update autonomous validators, durable state, handoff docs, and phase records
  so active work is `8081-8100` and completed `8061-8080` remains historical
  Audit/Reconciliation Operator Correlation evidence.
- Evidence update 2026-06-29: active range advanced to `8081-8100`
  Campaign/Sweep Operator Controls. This clears planning drift by tying the
  next work directly to the Automation and Campaigns Release 0.1 blocker and
  M58. AGENTS/owner instructions were re-reviewed in both repositories with no
  direction change. Focused backend/frontend metadata, ownership, quality,
  runtime, API, security, lint, diff, and stale-process checks passed. No
  phase-scoped subagents were spawned; the phase-end stale-subagent sweep
  found no open phase agents to close. Live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8082 - Campaign/Sweep Operator Scope

- Define the backend/frontend boundary for campaign and sweep operator
  controls, including no-live posture, scheduler/runner authority boundaries,
  and explicit unsupported or not-modeled gaps.
- Evidence update 2026-06-29: the automation-service status response now
  carries an operator scope matrix (`operator_scope_count` and
  `operator_scope`) for campaign/sweep read evidence, local pause/resume and
  retry-intent controls, dry-run command review, blocked execution gaps, and
  authority boundaries. This makes unsupported scheduler, retry,
  reconciliation, live Coinbase, browser scheduler, BFF runner, direct
  Coinbase, and second automation path behavior explicit before UI enablement.
  Live Coinbase execution was not run and submitted/executed notional stayed
  0 USDC.
- Validation update 2026-06-29: focused Admin API contract/OpenAPI checks,
  autonomous queue validation, ownership check, stale-process check, and
  `git diff --check` passed. No phase-scoped subagents were spawned; the
  phase-end stale-subagent sweep found no open phase agents to close.

### Phase 8083 - Backend Campaign State Inventory

- Inventory backend campaign status, sweep status, command-suite, and
  automation-control contracts needed for operator management.
- Implementation update 2026-06-29: campaign status now exposes a durable
  backend-owned inventory contract through `campaign_inventory` rows so the
  frontend can render campaign/sweep state, limits, blockers, unsupported
  behavior, and authority boundaries without inventing browser scheduling,
  BFF runner authority, reconciliation execution, direct Coinbase calls, or a
  second automation path.
- Validation update 2026-06-29: focused Admin API campaign inventory/OpenAPI
  checks, autonomous queue validation, ownership check, stale-process check,
  and `git diff --check` passed. Live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC. No phase-scoped subagents were
  spawned; the phase-end stale-subagent sweep found no open phase agents to
  close.

### Phase 8084 - Sweep Automation Service Status Contract

- Verify or extend backend-owned sweep automation service status evidence so
  operators can distinguish configured, paused, retryable, unsupported, and
  not-modeled states without browser authority.
- Current implementation result: `GET /api/v1/spot/sweep/automation-service`
  exposes five backend-owned `service_postures` rows for configured, paused,
  retryable, unsupported, and not-modeled automation-service states. The rows
  make operator state readable without scheduler, runner, reconciliation,
  Coinbase, browser/BFF, route-local, or second-path authority.
- Validation result: focused Admin API contract/OpenAPI tests, Python compile,
  ownership, autonomous queue, whitespace, and stale-process checks passed.
  Blind contextless review passed with no required fixes. Live Coinbase
  execution was not run; submitted/executed notional was 0 USDC. The
  phase-end subagent sweep closed the single review subagent and found no open
  phase agents remaining.

### Phase 8085 - Sweep Control Command Contract Review

- Completed backend sweep automation control command review. Accepted and
  rejected service responses for `POST /api/v1/spot/sweep/automation-controls`
  now include enum-backed `control_contract_checks` rows for idempotency,
  operator intent, RBAC permission, route-bound admission evidence, cap/guard
  boundary, local control ledger persistence, no-live execution, and
  frontend/BFF authority.
- The command remains a backend-owned local-state mutation: no scheduler,
  sweep runner, retry execution, reconciliation, Coinbase order submission,
  browser/BFF execution authority, route-local executor, or second sweep path
  is invoked, and submitted/executed notional remains 0/0 USDC.
- Validation result: focused Admin API contract tests, core enum tests,
  Python compile, ownership, autonomous queue, whitespace, stale-process
  checks, and blind contextless review passed after mock parity remediation.
  Live Coinbase execution was not run; submitted/executed notional was 0 USDC.
  The phase-end subagent sweep closed the review subagent and found no open
  phase agents remaining.

### Phase 8086 - Campaign Execution Dry-Run Readiness

- Verify campaign execution dry-run readiness and make rejection/acceptance
  evidence operator-visible without enabling live Coinbase execution.
- Instruction review 2026-06-29: backend `AGENTS.md` and frontend
  `AGENTS.md` were re-reviewed. No scope direction changed; focused checks are
  the ordinary phase gate and blind contextless review applies.
- Current implementation result: campaign execution responses now expose
  backend-owned `campaign_execution_readiness_checks` rows and readiness
  counts. Accepted dry-run review reports the dry-run requirement as passed
  while route-bound live admission remains blocked; non-dry requests report the
  dry-run requirement as blocked. Both paths keep scheduler, runner, retry,
  reconciliation, Coinbase order submission, browser/BFF authority, and
  submitted/executed notional disabled.
- Validation result: focused backend Python compile, campaign execution Admin
  API contract tests, enum/model signature tests, ownership check, autonomous
  queue check, stale-process check, and whitespace check passed. Focused
  frontend typecheck, command dry-submit/UI/mock tests, API freshness, lint,
  command-security, autonomous queue, stale-process, and whitespace checks
  passed. Blind contextless review passed after stale-doc cleanup. Live
  Coinbase execution was not run; submitted/executed notional was 0 USDC. The
  phase-end subagent sweep closed reviewer
  `019f1382-9c62-7130-88a5-6f06da6609ad` and found no open phase agents
  remaining.

### Phase 8087 - Frontend Campaign Status Adapter

- Tighten frontend adapters for backend campaign status and execution-review
  evidence through generated API wrappers only.
- Implementation update 2026-06-29: sibling frontend maps backend
  `GET /api/v1/spot/campaign/status` `campaign_inventory` rows into typed
  campaign inventory table rows and maps status route, dry-run command route,
  no-live notional, unsupported behavior, and browser/BFF authority evidence
  into execution-review metrics. This is a frontend adapter/view association
  only; backend route authority, scheduler/retry/reconciliation/live execution
  boundaries, and zero-notional no-live posture are unchanged.
- Validation update 2026-06-29: sibling frontend focused adapter/read-only
  view/Campaigns read-model tests and quality checks passed; backend ownership,
  autonomous queue, stale-process, whitespace, and blind contextless review
  passed. Full backend regression was not run because this phase changed
  backend docs only and is not a milestone closeout. Live Coinbase execution
  was not run; submitted/executed notional was 0 USDC.

### Phase 8088 - Frontend Sweep Service Adapter

- Tighten frontend adapters for sweep service, scheduler, retry, and control
  evidence through generated API wrappers only.
- Implementation update 2026-06-29: sibling frontend maps backend
  `GET /api/v1/spot/sweep/automation-service` scheduler, run-limit, retry,
  recovery, control, route, blocker, and no-live evidence into typed sweep
  adapter rows and renders durable backend automation control records. This is
  a frontend adapter/view association only; backend route authority,
  scheduler/retry/reconciliation/live execution boundaries, and zero-notional
  no-live posture are unchanged.
- Validation update 2026-06-29: sibling frontend focused adapter/read-only
  view/runtime/mock tests and quality checks passed; backend ownership,
  autonomous queue, stale-process, whitespace, and blind contextless review
  passed. Full backend regression was not run because this phase changed
  backend docs only and is not a milestone closeout. Live Coinbase execution
  was not run; submitted/executed notional was 0 USDC.

### Phase 8089 - Campaigns Control Panel UX

- Add or refine operator UI for campaign status, dry-run review, blockers,
  audit references, and handoffs without browser execution authority.
- Implementation update 2026-06-29: sibling frontend Campaigns now has a
  first-read Campaign Control Panel that summarizes backend campaign/sweep
  state, campaign execution dry-run route evidence, blocker/control counts,
  prefill-only handoff count, and display-only/no-live authority. This is a
  frontend UX association only; backend route authority, scheduler/retry/
  reconciliation/live execution boundaries, and zero-notional no-live posture
  are unchanged.
- Validation update 2026-06-29: sibling frontend focused Campaigns
  read-model/AdminShell tests and quality checks passed; backend ownership,
  autonomous queue, stale-process, whitespace, and blind contextless review
  passed. Full backend regression was not run because this phase changed
  backend docs only and is not a milestone closeout. Live Coinbase execution
  was not run; submitted/executed notional was 0 USDC.

### Phase 8090 - Sweep Automation Control UX

- Add or refine operator UI for sweep automation status, pause/resume/control
  readiness, limits, retry posture, and blockers without browser scheduler or
  runner authority.
- Implementation update 2026-06-29: sibling frontend Campaigns now renders a
  Sweep Automation Control Summary ahead of the backend local-control form.
  It summarizes pause/resume posture, retry-intent readiness, run-limit
  evidence, blockers, and no-live proof from existing backend
  automation-service read models. This is a frontend UX association only;
  backend route authority, scheduler/retry/reconciliation/live execution
  boundaries, and zero-notional no-live posture are unchanged.
- Validation update 2026-06-29: sibling frontend focused Campaigns
  read-model/AdminShell tests and quality checks passed; focused backend
  automation-service/control contract tests passed; backend ownership,
  autonomous queue, stale-process, whitespace, and blind contextless review
  passed. Full backend regression was not run because this phase is not a
  milestone closeout. Live Coinbase execution was not run; submitted/executed
  notional was 0 USDC.

### Phase 8091 - Command Workflow Campaign Handoffs

- Ensure Campaigns and Sweep panels hand off to command workflows with
  campaign/sweep identity only and no client_order_id or exchange order_id
  substitution.
- Implementation update 2026-06-29: sibling frontend Command Workflows now
  renders display-only result links from campaign dry-run review to Campaigns
  by `campaign_id` and from sweep dry-run review to Spot Operations by
  `sweep_config_id`. The backend route contracts and authority are unchanged:
  no `client_order_id`, exchange `order_id`, `coinbase_order_id`, active
  placement id, browser/BFF execution authority, scheduler, retry executor,
  reconciliation executor, Coinbase call, route-local executor, or second
  automation path was introduced.
- Validation update 2026-06-29: sibling frontend focused Command
  Workflow/Campaigns read-model tests and quality checks passed; backend
  ownership, autonomous queue, stale-process, whitespace, and blind
  contextless review passed. Full backend regression was not run because this
  phase is not a durable milestone closeout. Live Coinbase execution was not
  run; submitted/executed notional was 0 USDC. The phase-end subagent sweep
  closed reviewer `019f13d9-09c8-7b52-b7de-fe7defaaee9a`.

### Phase 8092 - Automation Limits And Caps Visibility

- Surface automation run limits, notional caps, max-products controls, and
  backend guard/cap evidence as operator-visible blockers.

### Phase 8093 - Scheduler/Retry Unsupported Gap Surfacing

- Show scheduler, retry, runner, and recovery gaps as `unsupported` or
  `not_modeled` with owning backend modules and no browser fallback.

### Phase 8094 - No Browser/BFF Scheduler Authority Assertions

- Add or tighten assertions that Campaigns/Sweep UI and BFF code do not
  schedule, retry, loop, place Coinbase orders, or mutate backend state outside
  backend-owned Admin API contracts.

### Phase 8095 - Mock Runtime Parity

- Align mock runtime fixtures with backend campaign/sweep response shapes,
  no-live flags, unsupported/not-modeled rows, and authority boundaries.

### Phase 8096 - Route-To-UI Matrix Campaign Update

- Update route-to-UI and capability matrices so contextless maintainers can
  trace campaign/sweep routes to operator surfaces and unsupported gaps.

### Phase 8097 - Focused Backend Tests

- Run focused backend tests and validators covering campaign/sweep status,
  control contracts, route inventory, OpenAPI, and no-live authority.
- Validation update 2026-06-29: focused Admin API campaign/sweep selection
  passed with 16 selected tests; spot campaign and spot portfolio sweep
  regressions passed with 80 tests; OpenAPI generation, route-inventory export,
  autonomous queue validation, ownership check, stale-process check, and diff
  whitespace checks passed. Generated artifacts were current. No live Coinbase
  execution was run; submitted/executed notional remained 0 USDC.

### Phase 8098 - Focused Frontend Tests

- Run focused frontend adapter, UI, command-security, generated API, and
  quality checks covering campaign/sweep operator controls.
- Validation update 2026-06-29: sibling frontend campaign/sweep unit pack
  passed with 165 tests; typecheck, lint, generated API route coverage,
  command security guard, autonomous queue, dry read/command/BFF/spot-command
  smoke, production build, scoped Playwright desktop admin shell browser
  smoke, stale-process check, and diff whitespace check passed. No live
  Coinbase execution was run; submitted/executed notional remained 0 USDC.

### Phase 8099 - Blind Contextless Review

- Run blind/contextless backend/frontend review for campaign/sweep operator
  controls and remediate blocking ambiguity before advancing.
- Review update 2026-06-29: blind reviewer
  `019f1427-06fb-7080-8994-6342cd8007e8` passed with no remediation and
  confirmed the no-live campaign/sweep slice is traceable, backend-owned, and
  safe to advance to Phase 8100 evidence commit/push. Live scheduler, retry,
  reconciliation, and Coinbase execution remain outside this slice. Live
  Coinbase execution was not run; submitted/executed notional remained 0 USDC.

### Phase 8100 - Commit And Push Evidence

- Commit and push synchronized backend/frontend evidence with no-live notional
  reporting.
- Closeout update 2026-06-29: Phase 8100 re-reviewed backend and frontend
  `AGENTS.md`/owner instructions and found no direction change. The
  campaign/sweep operator-controls range remains no-live, backend-owned, and
  limited to Release 0.1 Automation/Campaigns blocker evidence already proven
  by Phase 8097 focused backend checks, Phase 8098 focused frontend checks,
  and Phase 8099 blind/contextless review. No phase-scoped subagents were
  spawned for this closeout phase. Live Coinbase execution was not run;
  submitted/executed notional remained 0 USDC.

## Completed Phases 8061-8080

Batch label: Audit/Reconciliation Operator Correlation.

These phases clear the next concrete Release 0.1 blocker for audit and
reconciliation: operators must be able to correlate command attempts,
approvals, admission audits, cap/guard decisions, exchange intent, fills, and
reconciliation status through the enterprise frontend/API without falling back
to proof-of-concept dashboards. This range is no-live by default: it may add or
tighten read models, adapters, UI timelines, filters, handoffs, mocks, and
focused validation, but it must not add browser/BFF trading authority, bypass
backend gates, call Coinbase directly, execute reconciliation, mutate order or
exchange state, or create a second order path.

Every phase must answer: Does this make the frontend able to manage the project?

Completed Release 0.1 `8061-8080` added an Audit/Reconciliation Operator
Correlation slice so operators can correlate command attempts, approvals,
admission audits, cap/guard decisions, exchange intent, fills, and
reconciliation status through the enterprise frontend/API without browser/BFF
trading authority while completed `8041-8060` carries the Spot Command Operator
E2E evidence.

Exact autonomous phrase: Active Release 0.1 `8061-8080` adds an Audit/Reconciliation Operator Correlation slice so operators can correlate command attempts, approvals, admission audits, cap/guard decisions, exchange intent, fills, and reconciliation status through the enterprise frontend/API without browser/BFF trading authority while completed `8041-8060` carries the Spot Command Operator E2E evidence.

### Phase 8061 - Advance Active Queue Range

- Update autonomous validators, durable state, handoff docs, and phase records
  so active work is `8061-8080` and completed `8041-8060` remains historical
  Spot Command Operator E2E evidence.
- Evidence update 2026-06-29: active range advanced to `8061-8080`
  Audit/Reconciliation Operator Correlation, directly tied to the Release 0.1
  Audit and Reconciliation blocker. AGENTS.md, `agent.md`, agent ownership
  docs, and frontend AGENTS/ownership docs were re-reviewed for this phase and
  did not change direction. Backend runtime metadata, autonomous checker,
  OpenAPI artifact, docs, examples, handoff, and focused regression
  expectations now report `8061-8080` with `current_phase=8060`.
  Frontend autonomous policy, artifact contract, deployment readiness,
  mock/runtime fixtures, generated schema, docs, and unit expectations now
  report `8061-8080`. Focused backend phase-range tests passed with `5`
  selected tests; frontend metadata unit coverage passed with `7` files and
  `145` tests. Backend and frontend autonomous checks, frontend API check,
  frontend typecheck, stale-process checks, ownership, and diff checks passed.
  No phase-scoped subagents were spawned. Live Coinbase execution was not run
  and submitted/executed notional stayed 0 USDC.

### Phase 8062 - Audit/Reconciliation Operator Scope

- Scope the operator correlation path against the Release 0.1 audit and
  reconciliation blocker and existing backend-owned evidence sources.
- Evidence update 2026-06-29: added backend-owned Audit Workbench
  `correlation_scope` contract rows for command attempts, approvals,
  admission audits, cap/guard wallet evidence, exchange intent, fills, and
  reconciliation. This gives operators a stable view of what evidence should
  correlate while preserving no browser authority, no BFF execution authority,
  no reconciliation execution, and no order/exchange state mutation. The
  OpenAPI artifact and frontend generated schema were refreshed, focused
  backend and frontend checks passed, no phase-scoped subagents were spawned,
  and live Coinbase execution was not run with 0 USDC submitted/executed
  notional.

### Phase 8063 - Backend Audit Source Inventory

- Inventory backend command attempts, approvals, admission audits, cap/guard,
  exchange intent, fills, and reconciliation sources without adding live
  execution or new mutation paths.
- Evidence update 2026-06-29: Audit Workbench now exposes
  `source_inventory` so operators can see which backend evidence source owns
  each correlation surface before interpreting events. The inventory keeps
  read-only/no-live/no-authority flags on every row and includes explicit
  runtime-unavailable handling instead of falling back to dashboard or
  browser inference.

### Phase 8064 - Command Attempt Timeline Contract

- Add or tighten backend-owned timeline contract fields that let an operator
  trace a command attempt from request through result evidence.
- Evidence update 2026-06-29: Audit Workbench now has `command_timelines`
  derived from command-audit events. This removes guesswork from operator
  tracing while keeping timelines read-only and no-live.

### Phase 8065 - Approval And Admission Correlation Contract

- Correlate approval records and admission-audit records by backend-owned ids
  and status fields for operator inspection.
- Evidence update 2026-06-29: Audit Workbench now exposes
  `approval_admission_links` so operators can see whether approval snapshot
  and admission audit evidence are linked, missing, or not reported for a
  command attempt.

### Phase 8066 - Cap Guard And Wallet Correlation Contract

- Correlate cap/guard, wallet, lot, and budget evidence with the command
  attempt timeline without moving guard logic into the frontend.
- Evidence update 2026-06-29: Audit Workbench now exposes
  `cap_guard_wallet_links`; missing wallet, lot, or budget refs remain
  explicit `not_reported` evidence instead of browser-side inference.

### Phase 8067 - Exchange Intent And Fill Correlation Contract

- Correlate exchange intent, submission, Coinbase evidence ids, fill-ledger
  rows, and imported baselines as read-only evidence.
- Evidence update 2026-06-29: Audit Workbench now exposes
  `exchange_fill_links`; exchange ids remain evidence only, and fill/ledger/
  imported-baseline refs stay explicit `not_reported` evidence unless backend
  command evidence supplies them.

### Phase 8068 - Reconciliation Status Correlation Contract

- Correlate reconciliation plans, post-submit audit handoffs, pending gaps,
  and unsupported/not_modeled states without executing reconciliation.
- Evidence update 2026-06-29: Audit Workbench now exposes
  `reconciliation_links`; plan/proof/handoff evidence is visible while
  reconciliation execution remains disabled from the workbench. Backend and
  frontend agent instructions were re-reviewed for this phase and did not
  change the Release 0.1 no-browser/no-BFF-authority boundary.

### Phase 8069 - Frontend Audit Timeline Adapter

- Map generated backend timeline evidence into typed frontend adapters using
  canonical runtime clients only.
- Evidence update 2026-06-29: completed as frontend-only grouping over the
  existing Audit Workbench contract; no backend live or reconciliation
  execution behavior changed. No phase-scoped subagents were spawned; live
  Coinbase execution was not run and submitted/executed notional stayed
  0 USDC.

### Phase 8070 - Frontend Reconciliation Evidence Panel

- Render reconciliation status, blockers, handoff ids, unsupported states, and
  next owning module in the operator UI.
- Evidence update 2026-06-29: completed as a frontend-only evidence panel
  over existing Audit Workbench reconciliation links; no backend live,
  proof-writing, or reconciliation execution behavior changed. No
  phase-scoped subagents were spawned; live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8071 - Spot Command Result To Audit Timeline Handoff

- Link manual Spot command results into the audit timeline by client_order_id
  and backend evidence ids without automatic resubmission.
- Evidence update 2026-06-29: completed as frontend-only command result
  handoff over existing backend evidence. Manual Spot command result links now
  point operators from backend response identities to Audit Workbench anchors
  and direct-order audit readback anchors, while keeping backend command
  admission, reconciliation, live execution, and Coinbase authority unchanged.
  No phase-scoped subagents were spawned; live Coinbase execution was not run
  and submitted/executed notional stayed 0 USDC.

### Phase 8072 - Orders/Fills To Reconciliation Handoff

- Link orders, fills, and direct-order audit views into reconciliation evidence
  using backend-owned read paths.
- Evidence update 2026-06-29: frontend-only reconciliation handoff links now
  connect order list/detail rows and Direct Order Audit readback to Audit
  Workbench reconciliation evidence by `client_order_id`; reconciliation rows
  also expose backend plan anchors when a real `reconciliation_plan_id` exists.
  This closes a navigation gap for the Audit and Reconciliation Release 0.1
  blocker without changing backend behavior, adding reconciliation execution,
  writing proofs, mutating order/exchange state, calling Coinbase, granting
  browser/BFF authority, or promoting exchange `order_id` to application
  identity. Backend and frontend `AGENTS.md` requirements were re-reviewed
  during this phase and did not change direction. No phase-scoped subagents
  were spawned; live Coinbase execution was not run and submitted/executed
  notional stayed 0 USDC.

### Phase 8073 - Audit Search And Filter Operator UX

- Add or tighten operator search/filter affordances for command id,
  client_order_id, status, blocker type, and evidence family.
- Evidence update 2026-06-29: frontend-only Audit Workbench filters now narrow
  loaded command timeline, timeline adapter, approval/admission,
  cap/guard-wallet, exchange/fill, reconciliation, and audit-event evidence by
  command/client identity, status, blocker text, and evidence family. This
  directly improves the operator path for correlating failed or blocked command
  attempts while preserving backend ownership of queries, execution,
  reconciliation, proof writing, Coinbase calls, and state mutation. No
  phase-scoped subagents were spawned; live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8074 - Unsupported Gap Surfacing

- Ensure missing correlation behavior is visible as `unsupported` or
  `not_modeled` with owning module and next action, not hidden by browser
  fallbacks.
- Evidence update 2026-06-29: frontend-only Audit Workbench gap rows now make
  backend `unsupported` and `not_modeled` correlation states explicit with
  owning module, identity, blockers, evidence, next backend action, and
  no-authority flags. This closes a visibility gap for the Release 0.1
  unsupported-behavior blocker without creating browser fallbacks, BFF
  execution, reconciliation execution, proof writing, order/exchange mutation,
  Coinbase calls, or backend schema changes. No phase-scoped subagents were
  spawned; live Coinbase execution was not run and submitted/executed notional
  stayed 0 USDC.

### Phase 8075 - Mock Runtime Parity

- Keep mock runtime fixtures in parity with the backend audit/reconciliation
  correlation contract and mark mock data non-authoritative.
- Evidence update 2026-06-29: reviewed backend and frontend `AGENTS.md`; no
  phase constraints changed. Frontend mock Audit Workbench fixtures now expose
  non-authoritative audit/reconciliation parity metadata and a backend-shaped
  `not_modeled` reconciliation link so mock/runtime tests cover the same
  unsupported-gap contract operators see in the UI. No backend execution path,
  live Coinbase read/order, reconciliation execution, proof writing,
  browser/BFF authority, or order/exchange mutation changed. No phase-scoped
  subagents were spawned; submitted/executed notional stayed 0 USDC.

### Phase 8076 - No-Live Authority Assertions

- Prove this slice adds no live Coinbase execution, browser/BFF execution
  authority, dashboard WebSocket calls, route-local execution,
  reconciliation execution, or order/exchange state mutation.
- Evidence update 2026-06-29: frontend added an Audit Workbench no-live
  source-scope boundary manifest and focused unit test to keep the display
  slice free of direct fetch, browser WebSocket/EventSource/XMLHttpRequest,
  backend-client/runtime-loader construction, dashboard WebSocket paths,
  Coinbase calls, reconciliation execution, and order/exchange mutation
  identifiers. No backend schema or execution behavior changed. No
  phase-scoped subagents were spawned; live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8077 - Focused Backend Tests

- Run focused backend Admin API, audit, reconciliation, autonomous, ownership,
  and generated-contract checks that cover the correlation path.
- Evidence update 2026-06-29: focused backend validation passed for 50 selected
  Admin API/audit/reconciliation tests, including generated OpenAPI parity,
  route inventory/OpenAPI sync, Audit Workbench route and read-service
  normalization, reconciliation plan record/replay/fail-closed/exact resolver
  behavior, direct-order audit dashboard isolation, spot direct-order audit,
  and cross-source reconciliation. Ownership and autonomous queue validators
  also passed. This was not a full regression closeout gate. No phase-scoped
  subagents were spawned; live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8078 - Focused Frontend Tests

- Run focused frontend adapter, UI, runtime, generated API, browser-smoke, and
  quality checks that cover the operator correlation path.
- Evidence update 2026-06-29: frontend validation passed 112 focused Vitest
  tests and 3 targeted Chromium Playwright admin-shell smoke tests. Typecheck,
  lint, generated API/route coverage, autonomous queue, and stale-process
  checks also passed. This validated the Audit/Reconciliation operator
  correlation path from API client/runtime/mock data through AdminShell browser
  rendering without adding backend behavior. No phase-scoped subagents were
  spawned; live Coinbase execution was not run and submitted/executed notional
  stayed 0 USDC.

### Phase 8079 - Blind Contextless Review

- Run blind/contextless backend/frontend review for the audit/reconciliation
  operator correlation path and remediate blocking ambiguity before advancing.
- Evidence update 2026-06-29: backend/frontend `AGENTS.md` files were
  re-read for this phase; no durable instruction change was required. Initial
  blind review failed contextless clarity because Command Workflows had no
  route-level permission hint, viewer access was asserted as enabled, and the
  shell lacked role context. Remediation added explicit frontend
  `order:create` route hinting, manual Spot create/cancel role-boundary
  evidence for `trader`/`admin` only, AdminShell session-role wiring, focused
  tests, and docs clarifying that backend-role `operator` can inspect evidence
  but cannot initiate manual Spot order create/cancel. Fresh blind review
  passed; minor time-in-force and admin-proof notes were remediated locally.
  Focused frontend RBAC/command workflow tests passed with 48 tests. Reviewers
  `019f12c6-81b2-7903-902b-e8f6987aaf52` and
  `019f12d4-0f65-7163-bd27-5275cc8e17ec` were closed in the phase-end
  stale-subagent sweep. Live Coinbase execution was not run and
  submitted/executed notional stayed 0 USDC.

### Phase 8080 - Commit And Push Evidence

- Commit and push synchronized backend/frontend evidence with no-live notional
  reporting.
- Evidence update 2026-06-29: synchronized Phase 8079 remediation and review
  evidence was committed and pushed on branch
  `codex/stealth-live-service-decision-3501`. Backend commit `b104f226`
  recorded blind/contextless review evidence and roadmap updates. Frontend
  commit `7016cca` clarified the Command Workflows role boundary, tests, and
  docs. Live Coinbase execution was not run; submitted notional `0` USDC,
  executed notional `0` USDC.

## Completed Phases 8041-8060

Batch label: Spot Command Operator E2E.

Completed Release 0.1 `8041-8060` added a Spot Command Operator E2E slice so
operators can verify manual spot order, cancel-by-client_order_id,
direct-order audit, and command handoff workflows through the enterprise
frontend/API without browser/BFF trading authority. The range completed and
pushed in backend commit `05093483` and frontend commit `6f86b37`. Live
Coinbase execution was not run for this range; submitted notional `0` USDC,
executed notional `0` USDC.

Exact historical phrase: Completed Release 0.1 `8041-8060` added a Spot Command Operator E2E slice so operators can verify manual spot order, cancel-by-client_order_id, direct-order audit, and command handoff workflows through the enterprise frontend/API without browser/BFF trading authority while completed `8021-8040` carries the Movement/Repricing Action-State Matrix evidence.
## Completed Phases 8021-8040

Batch label: Movement/Repricing Action-State Matrix.

Completed Release 0.1 `8021-8040` added a Movement/Repricing Action-State Matrix
so operators can see move, premark, reprice, cooldown, claim, cancel/replace,
audit, and recovery workflows as usable, blocked, unsupported, or not modeled
from backend evidence while completed `8001-8020` carries the M55 Stealth
Action-State Matrix evidence.

Exact historical phrase: Completed Release 0.1 `8021-8040` added a Movement/Repricing Action-State Matrix so operators can see move, premark, reprice, cooldown, claim, cancel/replace, audit, and recovery workflows as usable, blocked, unsupported, or not modeled from backend evidence while completed `8001-8020` carries the M55 Stealth Action-State Matrix evidence.

### Phase 8021 - Advance Active Queue Range

- Move autonomous docs, validators, and durable state to active `8021-8040`
  while preserving completed `8001-8020` M55 action-state evidence.

### Phase 8022 - Blind Contextless Preflight Review

- Run the required blind/contextless review before broadening
  movement/repricing UI behavior and remediate blocking ambiguity.

### Phase 8023 - Movement/Repricing Action-State Scope

- Scope the movement/repricing action-state matrix against the Movement and
  Repricing Release 0.1 blocker.

### Phase 8024 - Backend Movement Action-State Contract

- Expose backend-owned movement/repricing action-state rows without move,
  premark, reprice, cancel/replace, reconciliation, Coinbase, or state
  mutation execution.

### Phase 8025 - Move And Premark Gate Source Map

- Tie move and premark action-state rows to exact backend blockers, evidence
  refs, mutation locks, replacement-slot boundaries, and missing contracts.

### Phase 8026 - Reprice Cooldown Claim Source Map

- Tie reprice, cooldown, and claim action-state rows to exact backend blockers,
  evidence refs, cooldown boundaries, claim ownership, and missing contracts.

### Phase 8027 - Cancel Replace Boundary Rows

- Surface cancel/replace boundary rows as backend evidence only, preserving
  exchange-reality and replacement-slot invariants.

### Phase 8028 - Audit Recovery Boundary Rows

- Surface movement audit and recovery blockers as backend evidence only.

### Phase 8029 - Frontend Schema Sync

- Regenerate the frontend API client from backend OpenAPI.

### Phase 8030 - Movement Adapter Action-State Mapping

- Map backend movement/repricing action-state rows through canonical frontend
  adapters.

### Phase 8031 - Movement Read Model Action-State Matrix

- Render movement/repricing action states in the Movement/Repricing read model.

### Phase 8032 - Command Handoff Gate Labels

- Align handoff links with backend gate labels and blocked-state language.

### Phase 8033 - Unsupported Not-Modeled Visibility

- Ensure unsupported and not-modeled movement/repricing behaviors are visible.

### Phase 8034 - No-Live Authority Assertions

- Prove the surface adds no browser/BFF, dashboard WebSocket, route-local,
  reconciliation, Coinbase, or movement state-mutation authority.

### Phase 8035 - Mock Runtime Parity

- Keep mock frontend/backend fixtures in parity with the contract.

### Phase 8036 - Focused Backend Tests

- Run focused Admin API, movement/repricing, and ownership tests covering the
  backend contract.

### Phase 8037 - Focused Frontend Tests

- Run focused frontend adapter, read-model, API, and quality tests.

### Phase 8038 - Documentation Update

- Update Movement/Repricing, command workflow, release, and example docs.

### Phase 8039 - Focused Validation And Hygiene

- Run targeted validators, diff checks, and phase-end subagent cleanup.

### Phase 8040 - Commit And Push Evidence

- Commit and push synchronized backend/frontend evidence with no-live notional
  reporting.

## Completed Phases 8001-8020

Batch label: M55 Stealth Action-State Matrix.

Completed Release 0.1 `8001-8020` added backend-derived selected stealth
command-family action-state templates and a frontend selected stealth
action-state matrix. Blind/contextless review passed after remediation
clarified `scope=command_family_template`, `order_specific_adjudication=false`,
and no browser/BFF execution authority. Backend commit `bab25737` and frontend
commit `65de74a` were pushed. Live Coinbase execution was not run; submitted
notional `0` USDC, executed notional `0` USDC.

## Completed Phases 7981-8000

Batch label: Release 0.1 Operator Admin Pivot.

Active Release 0.1 `7981-8000` pivots the admin platform to product-managing
operator workflows while completed M57 `7961-7980` carries forward futures
risk-proof record validation remediation summary evidence.

Exact autonomous phrase: Active Release 0.1 `7981-8000` pivots the admin platform to product-managing operator workflows while completed M57 `7961-7980` carries forward futures risk-proof record validation remediation summary evidence.

### Phase 7981 - Close Proof Expansion

- Mark `7961-7980` complete and freeze further futures/perpetual proof-summary
  expansion unless a future proof field directly closes a Release 0.1 blocker.

### Phase 7982 - Release Blocker Inventory

- Inventory backend and frontend gaps against the Release 0.1 blocker table.

### Phase 7983 - Admin Shell Operability Map

- Map health, lifecycle, pause/resume, stop/drain, and operator status flows
  from backend route to frontend surface.

### Phase 7984 - Account And Market Coverage Map

- Map product, account, balance, order, fill, position, funding, and risk reads
  to the frontend surfaces that need them.

### Phase 7985 - Spot Command Usability Map

- Identify the smallest backend-owned spot buy/sell/cancel workflow needed for
  the private operator MVP.

### Phase 7986 - Stealth Command Usability Map

- Identify supported stealth create/cancel/reveal/move/reprice/recovery flows
  and unsupported gaps that must surface as `unsupported` or `not_modeled`.

### Phase 7987 - Movement/Repricing Usability Map

- Identify supported move, premark, reprice, cooldown, claim, cancel/replace,
  audit, and recovery flows.

### Phase 7988 - Automation And Campaign Usability Map

- Identify supported scheduler, campaign, retry, pause/resume, run-limit, and
  recovery flows.

### Phase 7989 - Audit, Reconciliation, And Settings Map

- Identify audit, reconciliation, settings, policy, and safe-edit paths needed
  before private operator release.

### Phase 7990 - Backend Route-To-UI Release Matrix

- Produce a route-to-frontend matrix that classifies each admin workflow as
  usable, blocked, `unsupported`, or `not_modeled`.

### Phase 7991 - Frontend Workflow Release Matrix

- Produce a navigation/workflow matrix that shows which operator tasks can be
  completed end to end in the frontend.

### Phase 7992 - Unsupported Gap Classification

- Ensure unsupported and not-modeled gaps are visible in both backend and
  frontend evidence instead of implied by missing UI.

### Phase 7993 - Next Implementation Slice Selection

- Select the next implementation slice strictly by release impact and state the
  blocker it clears.
- Current implementation result: Account and Market Inventory coverage is
  implemented through `GET /api/v1/admin/account-market-inventory` and the
  frontend Inventory section. Product catalog, spot wallet, spot balance, and
  spot fill coverage is now a `ready_with_data_gate` read surface, not a
  missing-contract blocker.
- Current implementation result: Admin Lifecycle Support Classification is
  implemented through backend `lifecycle_support` rows and the frontend
  Lifecycle section. Lifecycle controls remain absent until backend command
  contracts exist.
- Current implementation result: Spot Buy/Sell/Cancel readiness is surfaced
  from backend `GET /api/v1/spot/command-suite` evidence in the frontend Spot
  Command Suite. Live spot buy/sell and cancel remain blocked by backend
  admission, proof, approval, cap/guard, reconciliation, audit,
  wallet/no-shorting, direct acknowledgement, and live-service gates.
- Current implementation result: backend manual order and
  cancel-by-`client_order_id` route adapters now pass the evaluated backend
  admission decision into the shared command-service command objects as
  `allow_live_execution`. Manual order admission can pass when exact backend
  approval, admission-audit, cap/guard, reconciliation, manual
  acknowledgement, and completed live-service evidence all match. Manual order
  now has a route-scoped configured backend live-service dependency that can
  reach the existing command-service live branch when backend env, REST client,
  and durable order-event publisher gates pass. The default disabled service
  remains blocked/no-live, the generic live-service dependency remains disabled
  for other routes, and no live Coinbase execution is enabled by default.
  Cancel now carries `manual_live_acknowledgement`, uses a route-scoped
  configured backend live-service dependency, requires the same exact backend
  admission chain, and reaches only the shared
  `cancel_order(client_order_id)` wrapper when all gates pass. Accepted
  configured live manual BUY responses now expose
  a structured `post_submit_reconciliation` audit handoff with the direct-order
  audit route, admission ids, submission-event status, and no-mutation/
  no-browser/BFF-authority flags. The frontend command workflow now renders
  and links that handoff without creating browser/BFF execution authority. The
  next release-linked blocker was making one manual Spot BUY path
  operator-completable through Admin API direct-order audit readback and
  post-submit fill-ledger backfill proof after capped live Coinbase
  validation. Admin API manual-order dependencies now also supply durable
  `stealth_orders` planned-budget reads and shared fill-ledger/imported
  baseline spot SELL lot authority through the existing action-condition guard.
  Current manual Spot BUY validation must use
  `python tools\run_admin_api_manual_spot_buy_live.py`, not the direct Coinbase
  smoke script, so the proof covers the enterprise Admin API route and shared
  command service. Latest live validation selected `MOG-USDC`, submitted
  `1.00` USDC, executed `0.99935033` USDC, ran read-only Coinbase
  `list_fills`, appended one fill-ledger row through
  `business.spot_fill_backfill.backfill_fill_ledger_from_order_reports`, and
  read back `GET /api/v1/spot/direct-orders/{client_order_id}/audit` through
  `application.admin_api.read_service` with `dashboard_dependency=false`.
  No-live operator-facing SELL validation now uses
  `python tools\run_admin_api_manual_spot_sell_validation.py --summary-only`
  to seed exact Admin API admission evidence, call the existing
  `POST /api/v1/orders` route through the FastAPI app, reach the shared
  command service with fake REST, and prove planning-cap, wallet/planned-budget,
  and `known_inventory_available` lot-authority wiring without browser/BFF
  execution authority, a second SELL path, or live Coinbase execution.
- Current automation/campaign implementation result: `GET
  /api/v1/spot/sweep/automation-service` is a backend-owned read-only service
  status contract for campaign ledger, sweep ledger, operation-lock,
  scheduler-status, retry-plan, missing-contract, and no-live proof evidence.
  It reports `not_modeled` control gaps without invoking a scheduler, runner,
  Coinbase order, browser job, BFF execution path, or second sweep path. The
  next release-linked automation blocker is an exact backend-owned
  pause/resume and retry control contract, not more proof-summary expansion.

### Phase 7994 - Operator Runbook Update

- Update the operator runbook so a contextless maintainer can start the admin
  API/frontend and understand what Release 0.1 can and cannot do.
- Current implementation result: the frontend human operator runbook now
  states backend Admin API startup, BFF mode as the normal local operator
  path, direct backend mode as session-bridge/test-harness only, usable Release
  0.1 surfaces, non-operator-complete workflows, Spot BUY/SELL/cancel backend
  authority status, prior backend BUY live-validation notional, and this
  phase's no-live Coinbase notional evidence. Backend and frontend handoff
  docs were synced to the same current Spot command posture.

### Phase 7995 - Documentation Index Update

- Link the burn-down, milestones, handoff, and work queue from the ordered docs
  index.
- Current implementation result: backend `docs/README.md` now links the local
  Release 0.1 burn-down, maintainer handoff, durable milestones, autonomous
  work queue, backend route-to-UI matrix, and sibling frontend workflow matrix
  from ordered navigation sections.

### Phase 7996 - Autonomous Validator Pivot

- Update autonomous validators and artifacts so active work is `7981-8000` and
  proof-only drift fails validation.
- Current implementation result: backend
  `tools/run_autonomous_work_queue_check.py` now validates the exact approved
  Release 0.1 active phase titles and fails if an active phase is renamed into
  proof-only futures/perpetual summary drift or if an unapproved active phase is
  inserted. Focused regression coverage lives in
  `tests/regression/test_autonomous_work_queue_check.py`.

### Phase 7997 - Backend Contextless Review

- Run a blind/contextless backend review focused on whether Release 0.1 scope
  and next work are understandable without chat history.
- Current implementation result: backend blind/contextless review passed after
  remediation. Stale docs that still described all HTTP mutating routes as
  categorically live-disabled were corrected, including expanded
  `genai_data` references. Current docs now state that manual Spot order/cancel
  are no-live by default and are route-scoped configured live exceptions only
  after exact backend gates; frontend/BFF remain display or forward-only and
  cannot become trading authority. The contextless checklist command now works
  as both the documented module invocation and a direct script invocation. No
  live Coinbase execution ran; submitted notional `0` USDC, executed notional
  `0` USDC.

### Phase 7998 - Frontend Contextless Review

- Run a blind/contextless frontend review focused on whether Release 0.1 scope,
  blockers, and backend association are understandable without chat history.

### Phase 7999 - Focused Validation And Hygiene

- Run focused validators/tests for changed docs, artifacts, and quality gates.
  Run stale-process checks if any backend/frontend test command is interrupted
  or times out.

### Phase 8000 - Commit And Push Evidence

- Commit and push synchronized backend/frontend pivot changes and record live
  Coinbase execution status. Default evidence for this pivot is no live
  Coinbase execution, submitted notional `0` USDC, executed notional `0` USDC.
- Current sweep executor readiness result: backend commit `70426b34` and
  frontend commit `b14d021` were pushed with scheduler/retry executor
  readiness rows rendered as action-disabled no-live blocker evidence. Focused
  backend/frontend validation and blind/contextless review remediation passed.
  Live Coinbase execution was not run; submitted notional `0` USDC, executed
  notional `0` USDC.
