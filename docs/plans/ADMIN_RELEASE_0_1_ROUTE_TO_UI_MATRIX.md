# Admin Release 0.1 Route-To-UI Matrix

This document converts the Release 0.1 burn-down into a route-to-frontend
release matrix. It is not a new roadmap track. It exists so contextless
maintainers can see which backend routes already support operator work, which
frontend surface consumes them, and which blocker prevents the private operator
admin MVP from being usable.

The governing question remains:

> Does this make the frontend able to manage the project?

## Phase Instruction Review

`AGENTS.md` and `agent.md` were reviewed for this phase on 2026-06-27 and
again on 2026-06-28 before the frontend Release Blockers implementation,
Admin Lifecycle Support classification, Spot Buy/Sell/Cancel readiness, Admin
API spot SELL authority source wiring, Spot Sweep Automation Service Contract
read work, and scheduler/run-limit binding evidence. No phase-direction change
was required. The controlling instructions remain:

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
| Spot commands | `/api/v1/orders`, `/api/v1/orders/{client_order_id}/cancel`, `/api/v1/spot/command-suite`, `/api/v1/spot/direct-orders/{client_order_id}/audit`, `/api/v1/spot/campaign/executions`, `/api/v1/spot/sweep/automation-runs` | Command Workflows, Spot Operations, Campaigns | `blocked` | Command routes exist, `GET /api/v1/spot/command-suite` exposes Buy/Sell/Cancel readiness, and manual order/cancel route adapters now pass backend admission decisions into the shared command-service `allow_live_execution` flag. Manual order admission can pass when exact backend approval, admission-audit, cap/guard, reconciliation, manual acknowledgement, and completed live-service evidence all match. The manual-order route now has a route-scoped configured backend live-service dependency that can reach the existing command-service live branch when backend env/config/event-stream gates pass; default runtime remains blocked. Cancel now has explicit `manual_live_acknowledgement`, a route-scoped configured backend live-service dependency, and a service-level acknowledgement guard before it reaches the existing `cancel_order(client_order_id)` wrapper. Accepted configured live manual BUY responses now expose `data.post_submit_reconciliation` with the direct-order audit route and no-mutation/no-browser/BFF-authority flags, and the frontend command workflow renders/links that handoff. The frontend Spot Operations panel can load the returned `client_order_id` through `GET /api/v1/spot/direct-orders/{client_order_id}/audit` for read-only inspection. Capped live validation for one manual Spot BUY now proves Admin API order submission, read-only Coinbase fill lookup, fill-ledger backfill, and Admin API direct-order audit readback with `dashboard_dependency=false`. Admin API manual-order dependencies now source planned budget from durable `stealth_orders` rows and spot SELL lot authority from the shared fill ledger/imported baselines through `ActionConditionGuard`. No-live operator-facing SELL validation now runs through `tools/run_admin_api_manual_spot_sell_validation.py`, reaches the existing `POST /api/v1/orders` route and shared command service with fake REST, and reports live Coinbase execution not run with submitted/executed notional `0`. | Continue Release 0.1 closeout work through operator runbook/docs index/autonomous validator/contextless review; do not add browser/BFF authority or a second SELL path. |
| Stealth commands | `/api/v1/stealth/orders`, reveal, move, cancel, recovery, reconciliation, command suite, proof routes | Stealth Orders, Command Workflows | `blocked` | Evidence is rich, but operator completion is blocked by exchange-reality, lifecycle-write, live-disabled, and reconciliation gates. | Surface every stealth command as usable or blocked by exact gate; do not add hide-again shortcuts. |
| Movement/repricing | `/api/v1/movement-repricing/evidence`, order detail, stealth detail, stealth reprice | Movement/Repricing, Command Workflows | `blocked` | Reprice exists as a live-disabled command route; move, premark, cooldown, claim, and cancel/replace workflows are not complete. | Add a movement action-state matrix before adding controls. |
| Automation/campaigns | Spot campaign status, campaign executions, sweep status, sweep P/L, sweep automation service status, sweep automation runs, sweep automation controls, `GET /api/v1/spot/command-suite` `automation_control_readiness` | Campaigns, Spot Operations, Command Workflows | `blocked` | Campaign and sweep `dry_run=true` review is operator-visible through accepted backend responses, with scheduler/runner/Coinbase flags false and `submitted_notional_usdc=0` / `executed_notional_usdc=0`. Sweep automation run responses now include backend-owned `automation_execution_contract_status`, `automation_execution_decision`, scheduler dispatch readiness evidence, scheduler executor-admission evidence, retry execution readiness evidence, retry executor-admission evidence, reconciliation execution boundary evidence, live execution boundary evidence, and explicit blockers for disabled scheduler/retry/reconciliation/live execution. The scheduler/retry executor-admission rows are sourced from the same route admission decision used by the shared command service and keep scheduler executor, retry executor, runner, Coinbase, and notional flags false. `POST /api/v1/spot/sweep/automation-controls` records backend-owned pause/resume and retry-intent local-state controls with idempotency, admission evidence, audit id, no scheduler/runner/Coinbase invocation, and zero notional. `GET /api/v1/spot/sweep/automation-service` exposes campaign ledger, sweep ledger, operation-lock, scheduler status, retry plan, control ledger, scheduler due/not-due/disabled/max-run binding evidence, run-limit remaining counts, remaining reconciliation/live enablement blockers, and no-live proof for the Campaigns UI. The command suite marks scheduler dispatch, pause/resume, and retry-intent/retry review as `command_draft_live_disabled` while run-limit decision evidence is `read_only_ready`; reconciliation execution and live execution now have modeled no-live boundary evidence but remain blocked for actual execution with browser/BFF display-only boundaries and zero notional. | Next implementation must add the backend live scheduler/retry executor and recovery/reconciliation gate enforcement through the same backend-owned path; do not add browser scheduler, BFF runner authority, or a second sweep execution path. |
| Audit/reconciliation | Approval, admission audit, cap/guard decisions, reconciliation plans, audit workbench, direct-order audit | Approvals, Admission Audits, Cap/Guard, Reconciliation, Audit | `usable` | Inspection and record evidence are usable. Execution/reconciliation authority remains backend-only and not implied by records. | Keep as release support; link command attempts to these records in the selected command slice. |
| Settings/policy | `/api/v1/admin/settings-policy-map`, guard/risk policy, capabilities, OIDC readiness, CSRF, live-execution decision reads/records | Guard/Risk, Settings, Admin | `blocked` | Safe backend-owned visibility now classifies settings and policy surfaces as read-only, secret, unsupported, or not modeled with `editable_count=0`; safe operator editing remains not modeled. | Design the first backend-owned editable setting only after an exact owning workflow, permission, audit, validation, rollback, and frontend UX contract exists. |
| Unsupported behavior | Enterprise readiness command gaps, route inventory, capability registry | Modules, Release Blockers, nav posture, command evidence | `usable` | Direct operator-facing blocker matrix exists; underlying gaps still block their owning workflows. | Keep the panel aligned with enterprise-readiness while clearing the next owning workflow blocker. |
| Validation | Focused backend checks, autonomous checker, stale process checker, full regression runner | Release gate and docs | `usable` | Focused validation is usable. Full regression is reserved for closeout. | Keep focused checks per slice; run full regression at Release 0.1 closeout. |

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

The next implementation slice should continue the approved Release 0.1
operator runbook, documentation index, autonomous validator, and contextless
review work. Inventory read coverage is now `ready_with_data_gate`; the
remaining Release 0.1 spot blocker is no longer route-local command flag
binding, generic live-service dependency wiring, BUY post-submit audit
handoff, or SELL operator-facing validation evidence. Manual order and cancel
route adapters now source `allow_live_execution` from backend live admission,
and manual order has a route-scoped configured backend live-service
dependency. Manual order admission can now pass with exact backend records,
manual acknowledgement, and a completed backend live-service state. Accepted
configured live responses now return a structured
`post_submit_reconciliation` audit handoff for
`GET /api/v1/spot/direct-orders/{client_order_id}/audit`; that is not
reconciliation execution and does not mutate order or exchange state. The
frontend command workflow now renders and links that backend evidence without
creating browser/BFF execution authority. The frontend Spot Operations panel
can also load the handoff `client_order_id` through the same direct-order
audit route for read-only inspection. Capped live validation now proves one
manual Spot BUY through the Admin API route, post-submit REST-fill backfill,
and direct-order audit readback with `dashboard_dependency=false`. The Admin
API manual-order path now has backend-owned planned-budget and spot SELL
lot-authority sources through the shared action-condition guard, plus a
no-live operator validation runner that proves the SELL route/service/guard
path with fake REST and `0` USDC live Coinbase notional.
Any implementation must keep auth, RBAC, operator intent, idempotency, audit,
approval snapshot, cap/guard, reconciliation, wallet/no-shorting, direct
acknowledgement, live-service, and Coinbase adapter authority in the backend.

## Live Coinbase Execution

No live Coinbase execution was run for this matrix phase.

- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.
