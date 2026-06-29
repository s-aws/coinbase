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

## Active Phases 8041-8060

Batch label: Spot Command Operator E2E.

Active Release 0.1 `8041-8060` adds a Spot Command Operator E2E slice so
operators can verify manual spot order, cancel-by-client_order_id,
direct-order audit, and command handoff workflows through the enterprise
frontend/API without browser/BFF trading authority while completed `8021-8040`
carries the Movement/Repricing Action-State Matrix evidence.

Exact autonomous phrase: Active Release 0.1 `8041-8060` adds a Spot Command Operator E2E slice so operators can verify manual spot order, cancel-by-client_order_id, direct-order audit, and command handoff workflows through the enterprise frontend/API without browser/BFF trading authority while completed `8021-8040` carries the Movement/Repricing Action-State Matrix evidence.

### Phase 8041 - Advance Active Queue Range

- Move autonomous docs, validators, and durable state to active `8041-8060`
  while preserving completed `8021-8040` Movement/Repricing Action-State
  Matrix evidence.

### Phase 8042 - Spot Command Operator E2E Scope

- Scope the manual Spot order/cancel operator happy path against the Release
  0.1 spot-command blocker and existing backend route gates.

### Phase 8043 - Backend Spot Command Happy-Path Contract Audit

- Audit backend manual order, cancel-by-`client_order_id`, direct-order audit,
  admission, cap/guard, reconciliation, live-service, and event-stream
  evidence without changing live execution posture.

### Phase 8044 - Manual Order Request Evidence Fixtures

- Add or tighten deterministic request/response fixtures for manual BUY/SELL
  dry-run and backend-mediated live-disabled review paths.

### Phase 8045 - Cancel By Client Order Handoff Evidence

- Prove cancel handoffs remain keyed by `client_order_id`, never exchange
  `order_id`, and preserve the backend `cancel_order(client_order_id)`
  wrapper boundary.

### Phase 8046 - Direct Order Audit Handoff Parity

- Ensure accepted manual-order responses, frontend links, and Spot Operations
  audit lookup all point to the same direct-order audit evidence.

### Phase 8047 - Frontend Command Runtime State Audit

- Audit command workflow runtime state so order/cancel drafts,
  acknowledgements, disabled buttons, and result panels remain display or
  forward-only evidence.

### Phase 8048 - Spot Operations Audit Lookup E2E

- Add or tighten operator-level tests for loading direct-order audit evidence
  from Spot Operations through the canonical backend runtime client.

### Phase 8049 - Orders To Cancel Handoff E2E

- Add or tighten operator-level tests for Orders-to-Command-Workflows cancel
  handoff, preserving `client_order_id` identity and no automatic submit.

### Phase 8050 - Spot Sell Authority Visibility E2E

- Make no-live SELL authority, lot authority, planned-budget evidence, and
  guard blockers visible in the operator flow without adding a sell guard in
  the browser.

### Phase 8051 - Backend Association Smoke Script

- Add or tighten a no-live backend association smoke that exercises the
  enterprise Admin API command/read path expected by the frontend.

### Phase 8052 - Frontend Browser Smoke Path

- Add or tighten a Playwright smoke path for the private operator command
  workflow using mock or local-backend no-live evidence.

### Phase 8053 - BFF Forwarding Boundary Assertions

- Assert the BFF forwards only allowed Admin API routes and never becomes
  command execution authority.

### Phase 8054 - No-Live Authority Assertions

- Prove the surface adds no live Coinbase execution, browser/BFF execution
  authority, dashboard WebSocket calls, route-local execution, reconciliation,
  or order/exchange state mutation.

### Phase 8055 - Mock Runtime Parity

- Keep mock frontend/backend fixtures in parity with the spot command
  operator E2E contract.

### Phase 8056 - Focused Backend Tests

- Run focused Admin API, spot command, direct-order audit, and ownership tests
  covering the backend contracts.

### Phase 8057 - Focused Frontend Tests

- Run focused frontend command workflow, spot operations, backend runtime,
  API, browser-smoke, and quality tests.

### Phase 8058 - Blind Contextless Review

- Run blind/contextless backend/frontend review for the spot command operator
  E2E path and remediate blocking ambiguity before advancing.

### Phase 8059 - Validation And Hygiene

- Run targeted validators, diff checks, and phase-end subagent cleanup.

### Phase 8060 - Commit And Push Evidence

- Commit and push synchronized backend/frontend evidence with no-live notional
  reporting.

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
