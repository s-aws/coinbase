# Admin Release 0.1 Route-To-UI Matrix

This document converts the Release 0.1 burn-down into a route-to-frontend
release matrix. It is not a new roadmap track. It exists so contextless
maintainers can see which backend routes already support operator work, which
frontend surface consumes them, and which blocker prevents the private operator
admin MVP from being usable.

The governing question remains:

> Does this make the frontend able to manage the project?

## Phase Instruction Review

`AGENTS.md` and `agent.md` were reviewed for this phase on 2026-06-27, again
on 2026-06-28 before the frontend Release Blockers implementation, Admin
Lifecycle Support classification, Spot Buy/Sell/Cancel readiness, Admin API
spot SELL authority source wiring, Spot Sweep Automation Service Contract read
work, and scheduler/run-limit binding evidence, and again on 2026-06-29 before
Phase 8087 frontend campaign status adapter work and Phase 8088 frontend
sweep service adapter work. No phase-direction change was required. The
controlling instructions remain:

- Release 0.1 work must clear a named blocker or directly improve the usable
  admin product.
- Missing behavior must appear as `unsupported` or `not_modeled`.
- Trading authority stays in the backend; no browser, BFF, route-local FastAPI,
  or second trading path may fill a gap.
- Full regression is a durable milestone closeout gate, not an ordinary phase
  gate.

## Status Taxonomy

| Status | Meaning |
| --- | --- |
| `usable` | Backend route and frontend surface are sufficient for a private operator to inspect or perform the stated task through backend-owned authority. |
| `blocked` | A route or surface exists, but a required Release 0.1 behavior is missing, live-disabled, incomplete, or not operator-completable. |
| `unsupported` | Backend explicitly says the behavior is not supported for this release or module. |
| `not_modeled` | No backend contract exists yet, so frontend must not invent the behavior. |
| `defer_public` | Not required for private Release 0.1 but required before public release. |

## Route Inventory Snapshot

The current generated route inventory
`openapi/coinbase-admin-api-route-inventory.json` reports:

| Module | Route count | Release reading |
| --- | ---: | --- |
| `admin_system_health` | 38 | Health, session, account/market inventory coverage, approval, admission audit, cap/guard, reconciliation, live-execution decision, settings/policy map, readiness, release-gate evidence, and backend-owned lifecycle pause/resume/drain/stop routes exist. Lifecycle start remains unsupported. |
| `spot_operations` | 27 | Spot reads, command-suite evidence, order read/cancel/place routes, campaign/sweep routes, automation-service status, recovery, P/L checkpoint, and audit routes exist. Command routes are still live-disabled unless backend gates explicitly pass. |
| `stealth_orders` | 38 | Stealth reads and many proof/record routes exist. Create/reveal/move/cancel/recovery/reconciliation routes are present but remain blocked by exchange-reality and live-disabled gates. |
| `futures_perpetuals` | 11 | Account, position, command-suite, risk-proof, order, cancel, close/reduce, and reconciliation route contracts exist. Command execution remains disabled evidence, not usable live trading. |
| `movement_repricing` | 4 | Movement/repricing reads and stealth reprice route exist. Broader move, premark, cooldown, claim, and cancel/replace management is not operator-complete. |
| `guard_risk_policy` | 1 | Read-only guard/risk policy evidence exists. Safe policy edits are not modeled. |
| `audit_workbench` | 1 | Cross-module audit read evidence exists. |
| `legacy_dashboard_websocket` | 3 | Compatibility-only legacy commands exist. They are not enterprise frontend product routes. |

## Release Blocker Matrix

| Release area | Backend route evidence | Frontend surface | Status | Release gap | Next slice |
| --- | --- | --- | --- | --- | --- |
| Admin shell | `/api/v1/admin/bootstrap`, `/health`, `/session`, `/capabilities`, `/live-enablement`, `/settings-policy-map`, `/enterprise-readiness`, `/release-gate`, `/lifecycle/pause`, `/lifecycle/resume`, `/lifecycle/drain`, `/lifecycle/stop` | Overview, Lifecycle, Modules, Settings, Admin Evidence | `usable` | Read posture, lifecycle classification, backend-owned settings/policy visibility, and backend-owned pause/resume/drain/stop controls are usable. Start remains `unsupported`. | Keep lifecycle and settings controls limited to backend-owned routes and move next release work to the highest-impact remaining blocked workflow. |
| Account inventory | `/api/v1/admin/account-market-inventory`, `/api/v1/orders`, `/api/v1/orders/{client_order_id}`, `/api/v1/futures/account`, `/api/v1/futures/positions`, spot readiness/cost-basis/sweep/campaign reads | Inventory, Orders, Spot Operations, Futures/Perpetuals | `ready_with_data_gate` | First-class coverage exists for product catalog, spot wallets, spot balances, and spot fills. Coinbase reads are backend-only, bounded, and disabled unless explicitly enabled, so the frontend must render `data_status` instead of inventing browser reads. | Keep the frontend display-only, surface blocked data clearly, and use this route as the account/market source of truth. |
| Spot commands | `/api/v1/orders`, `/api/v1/orders/{client_order_id}/cancel`, `/api/v1/spot/command-suite`, `/api/v1/spot/direct-orders/{client_order_id}/audit`, `/api/v1/spot/campaign/executions`, `/api/v1/spot/sweep/automation-runs` | Command Workflows, Spot Operations, Campaigns | `blocked` | Completed `8041-8060` made manual spot order, cancel-by-`client_order_id`, direct-order audit, no-live SELL authority, and command handoff paths verifiable through the enterprise frontend/API. Completed `8061-8080` made audit/reconciliation correlation usable across command attempts, approvals, admission audits, cap/guard decisions, exchange intent, fills, and reconciliation status. Manual Spot live paths remain no-live by default and can only reach existing backend command-service live branches after exact backend gates pass. | Active `8081-8100` moves the next Release 0.1 work to Automation/campaigns. Spot command changes in this range must directly support campaign/sweep operator controls and must not add browser/BFF authority, route-local execution, reconciliation execution, direct Coinbase calls, or a second trading path. |
| Stealth commands | `/api/v1/stealth/orders`, reveal, move, cancel, recovery, reconciliation, command suite, proof routes | Stealth Orders, Command Workflows | `blocked` | Evidence is rich, but operator completion is blocked by exchange-reality, lifecycle-write, live-disabled, and reconciliation gates. | Surface every stealth command as usable or blocked by exact gate; do not add hide-again shortcuts. |
| Movement/repricing | `/api/v1/movement-repricing/evidence`, order detail, stealth detail, stealth reprice | Movement/Repricing, Command Workflows | `blocked` | Reprice exists as a live-disabled command route, and the Movement/Repricing panel now renders backend-owned action-state rows for move, premark, reprice, cooldown, claim, cancel/replace, audit, and recovery. Move, premark, cooldown, claim, and cancel/replace workflows are still not operator-complete. | Keep the action-state matrix as the boundary before any controls; move the next release slice to the spot command operator E2E path. |
| Automation/campaigns | Spot campaign status, campaign executions, sweep status, sweep P/L, sweep automation service status, sweep automation runs, sweep automation controls, `GET /api/v1/spot/command-suite` `automation_control_readiness` | Campaigns, Spot Operations, Command Workflows | `blocked` | Campaign and sweep `dry_run=true` review is operator-visible through accepted backend responses, with scheduler/runner/Coinbase flags false and `submitted_notional_usdc=0` / `executed_notional_usdc=0`. Campaign execution responses now include `campaign_execution_readiness_checks` rows for idempotency, operator intent, RBAC, live admission boundary, dry-run requirement, request scope, runner boundary, no-live execution, and frontend/BFF authority; accepted dry-runs can show live admission `blocked` while still proving no live execution. Sweep automation run responses now include backend-owned `automation_execution_contract_status`, `automation_execution_decision`, scheduler dispatch readiness evidence, scheduler executor-admission evidence, scheduler executor boundary evidence, retry execution readiness evidence, retry executor-admission evidence, retry executor boundary evidence, scoped recovery-gate pass/block evidence for the requested `sweep_config_id`, reconciliation execution boundary evidence, live execution boundary evidence, and explicit blockers for disabled scheduler/retry/recovery/reconciliation/live execution. The scheduler executor and retry executor admission rows are sourced from the same route admission decision used by the shared command service, are recovery-gate-aware through `executor_ready_for_admission`, and keep scheduler executor, retry executor, runner, Coinbase, and notional flags false. Scheduler executor and retry executor boundary rows name the missing backend executor contracts and keep all executor, recovery, reconciliation, Coinbase, and notional flags false. `POST /api/v1/spot/sweep/automation-controls` records backend-owned pause/resume and retry-intent local-state controls with structured `control_contract_checks` rows for idempotency, operator intent, RBAC, admission evidence, cap/guard boundary, local ledger persistence, no-live execution, browser/BFF authority, audit id, no scheduler/runner/Coinbase invocation, and zero notional. `GET /api/v1/spot/sweep/automation-service` exposes campaign ledger, sweep ledger, operation-lock, scheduler status, retry plan, control ledger, scheduler due/not-due/disabled/max-run binding evidence, run-limit remaining counts, bounded recovery-gate status/counts/run ids, remaining reconciliation/live enablement blockers, no-live proof, a `service_postures` matrix for configured, paused, retryable, unsupported, and not-modeled states, and an `operator_scope` matrix for read evidence, local controls, dry-run review, blocked execution gaps, and browser/BFF authority boundaries in the Campaigns UI. The command suite marks scheduler dispatch, scheduler executor, pause/resume, retry-intent/retry review, and retry executor as `command_draft_live_disabled`; scheduler executor and retry executor rows are action-disabled blocker evidence, while run-limit and recovery-gate decision evidence are `read_only_ready`; reconciliation execution, fill-backfill execution, and live execution remain blocked for actual execution with browser/BFF display-only boundaries and zero notional. | Next implementation must replace the no-live scheduler executor and retry executor boundary with a backend-owned executor service only after approval, cap/guard, recovery, reconciliation, live-service, audit, and post-live reconciliation gates can pass; do not add browser scheduler, BFF runner authority, or a second sweep execution path. |
| Audit/reconciliation | Approval, admission audit, cap/guard decisions, reconciliation plans, audit workbench, direct-order audit | Approvals, Admission Audits, Cap/Guard, Reconciliation, Audit | `usable` | Inspection and record evidence are usable. Execution/reconciliation authority remains backend-only and not implied by records. | Keep as release support; link command attempts to these records in the selected command slice. |
| Settings/policy | `/api/v1/admin/settings-policy-map`, guard/risk policy, capabilities, OIDC readiness, CSRF, live-execution decision reads/records | Guard/Risk, Settings, Admin | `blocked` | Safe backend-owned visibility now classifies settings and policy surfaces as read-only, secret, unsupported, or not modeled with `editable_count=0`; safe operator editing remains not modeled. | Design the first backend-owned editable setting only after an exact owning workflow, permission, audit, validation, rollback, and frontend UX contract exists. |
| Unsupported behavior | Enterprise readiness command gaps, route inventory, capability registry | Modules, Release Blockers, nav posture, command evidence | `usable` | Direct operator-facing blocker matrix exists; underlying gaps still block their owning workflows. | Keep the panel aligned with enterprise-readiness while clearing the next owning workflow blocker. |
| Validation | Focused backend checks, autonomous checker, stale process checker, full regression runner | Release gate and docs | `usable` | Focused validation is usable. Full regression is reserved for closeout. | Keep focused checks per slice; run full regression at Release 0.1 closeout. |

## Phase 8087 Frontend Association Update

The sibling frontend now consumes `GET /api/v1/spot/campaign/status`
campaign inventory evidence through typed generated-wrapper adapters and
renders it as Spot Campaign Status inventory rows plus Campaigns dry-run
execution-review metrics. The associated metrics cover status routes, dry-run
command routes, no-live notional, unsupported behavior, and browser/BFF
authority. This update does not change backend execution authority: scheduler,
retry runner, reconciliation executor, Coinbase calls, browser/BFF execution,
route-local execution, and second automation paths remain blocked or
unsupported as already recorded in the Automation/campaigns row.

## Phase 8088 Frontend Association Update

The sibling frontend now consumes
`GET /api/v1/spot/sweep/automation-service` scheduler status, run-limit
status, retry-plan, recovery-gate, latest-control, blocker, route, no-live,
and durable automation control-record evidence through typed
generated-wrapper adapters. The Campaigns UI renders this as combined sweep
automation adapter rows plus separate durable control-record evidence. This
update does not change backend execution authority: scheduler execution,
retry execution, reconciliation execution, Coinbase calls, browser/BFF
execution, route-local execution, and second automation paths remain blocked
or unsupported as already recorded in the Automation/campaigns row.

## Implemented Account/Market Coverage Slice

The Account and Market Inventory coverage slice is now represented by
`GET /api/v1/admin/account-market-inventory` and the frontend Inventory
section. It is a backend-owned, read-only contract that lists inventory
families, their support status, data status, bounded records, release-blocking
status, and route linkage.

What this clears:

- The private operator can see a single account/market inventory coverage
  surface instead of inferring gaps from scattered order, spot, and futures
  panels.
- Existing order, futures account, futures positions, guard/risk, audit,
  readiness, cost-basis, and campaign reads are linked from one inventory
  contract.
- Product catalog, spot wallet, spot balance, and spot fill contracts are
  read-only ready. Their Coinbase-backed data rows remain backend-gated and
  surface `data_status`, `data_fetch_error`, and truncation metadata instead of
  browser-side inventory reads.

## Implemented Unsupported/Not-Modeled Panel Slice

The frontend Release Blockers panel now consumes
`GET /api/v1/admin/enterprise-readiness` and renders unsupported modules,
unsupported actions, `not_modeled` gaps, and live-disabled drafts as a direct
operator-facing Release 0.1 blocker matrix.

What this clears:

- Unsupported behavior is no longer implied by missing controls or scattered
  module catalog details.
- The UI shows required backend contracts, frontend boundaries, live Coinbase
  execution status, and USDC notional evidence from backend-owned readiness
  rows.
- Browser execution authority, BFF execution authority, route-local FastAPI
  execution, dashboard WebSocket calls, guard/wallet/reconciliation logic, and
  Coinbase calls remain absent.

## Implemented Admin Lifecycle Support Slice

`GET /api/v1/admin/enterprise-readiness` now exposes `lifecycle_support`
classification for `status`, `start`, `stop`, `pause`, `resume`, and `drain`.
The frontend Admin Lifecycle Support panel consumes those rows from the
generated OpenAPI contract and renders backend-owned controls only for
supported pause/resume/drain/stop routes.

What this clears:

- Lifecycle status is displayable through existing backend health evidence.
- `pause`, `resume`, `drain`, and `stop` are explicit backend-owned Admin API command routes.
- `start` is explicitly `unsupported`.
- `stop` is runtime terminal-state control only. It calls the backend
  drain-and-stop controller primitive and does not terminate the OS process,
  cancel Coinbase orders, or execute reconciliation.
- No route-local lifecycle execution, dashboard WebSocket bridge, browser/BFF
  process authority, shell helper, or Coinbase call was added.

## Follow-On Implementation Slice

The next implementation slice is active `8081-8100` Campaign/Sweep Operator
Controls. Completed `8061-8080` made audit/reconciliation correlation usable
for command attempts, approvals, admission audits, cap/guard decisions,
exchange intent, fills, and reconciliation status. The next Release 0.1 blocker
is automation and campaigns: operators need campaign and sweep state, scheduler
posture, retry posture, run limits, controls, blockers, and no-live proof to be
usable through the enterprise frontend/API without falling back to dashboards
or local browser automation. The active slice must keep campaign and sweep
authority in existing backend routes and services, make unsupported scheduler,
retry executor, recovery, reconciliation, and live execution behavior explicit
as `unsupported` or `not_modeled`, and avoid browser schedulers, BFF runner
authority, route-local executors, unbounded loops, direct Coinbase calls, and
second automation paths.
Any implementation must keep auth, RBAC, operator intent, idempotency, audit,
approval snapshot, cap/guard, reconciliation, run-limit, retry, scheduler,
live-service, and Coinbase adapter authority in the backend.

## Live Coinbase Execution

No live Coinbase execution was run for this matrix phase.

- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.
