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
again on 2026-06-28 before the frontend Release Blockers implementation. No
phase-direction change was required. The controlling instructions remain:
They were reviewed again on 2026-06-28 before Admin Lifecycle Support
classification and Spot Buy/Sell/Cancel readiness. No phase-direction change
was required.

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
| `admin_system_health` | 33 | Health, session, account/market inventory coverage, approval, admission audit, cap/guard, reconciliation, live-execution decision, readiness, and release-gate evidence exist. Lifecycle start/stop/pause/resume controls are not modeled as backend routes. |
| `spot_operations` | 26 | Spot reads, command-suite evidence, order read/cancel/place routes, campaign/sweep routes, recovery, P/L checkpoint, and audit routes exist. Command routes are still live-disabled unless backend gates explicitly pass. |
| `stealth_orders` | 38 | Stealth reads and many proof/record routes exist. Create/reveal/move/cancel/recovery/reconciliation routes are present but remain blocked by exchange-reality and live-disabled gates. |
| `futures_perpetuals` | 11 | Account, position, command-suite, risk-proof, order, cancel, close/reduce, and reconciliation route contracts exist. Command execution remains disabled evidence, not usable live trading. |
| `movement_repricing` | 4 | Movement/repricing reads and stealth reprice route exist. Broader move, premark, cooldown, claim, and cancel/replace management is not operator-complete. |
| `guard_risk_policy` | 1 | Read-only guard/risk policy evidence exists. Safe policy edits are not modeled. |
| `audit_workbench` | 1 | Cross-module audit read evidence exists. |
| `legacy_dashboard_websocket` | 3 | Compatibility-only legacy commands exist. They are not enterprise frontend product routes. |

## Release Blocker Matrix

| Release area | Backend route evidence | Frontend surface | Status | Release gap | Next slice |
| --- | --- | --- | --- | --- | --- |
| Admin shell | `/api/v1/admin/bootstrap`, `/health`, `/session`, `/capabilities`, `/live-enablement`, `/enterprise-readiness`, `/release-gate` | Overview, Lifecycle, Modules, Settings, Admin Evidence | `blocked` | Read posture and lifecycle classification are usable, but lifecycle command execution remains `unsupported` or `not_modeled`. | Do not add lifecycle controls until backend-owned command contracts exist; move next release work to the highest-impact remaining blocked workflow. |
| Account inventory | `/api/v1/admin/account-market-inventory`, `/api/v1/orders`, `/api/v1/orders/{client_order_id}`, `/api/v1/futures/account`, `/api/v1/futures/positions`, spot readiness/cost-basis/sweep/campaign reads | Inventory, Orders, Spot Operations, Futures/Perpetuals | `ready_with_data_gate` | First-class coverage exists for product catalog, spot wallets, spot balances, and spot fills. Coinbase reads are backend-only, bounded, and disabled unless explicitly enabled, so the frontend must render `data_status` instead of inventing browser reads. | Keep the frontend display-only, surface blocked data clearly, and use this route as the account/market source of truth. |
| Spot commands | `/api/v1/orders`, `/api/v1/orders/{client_order_id}/cancel`, `/api/v1/spot/command-suite`, `/api/v1/spot/direct-orders/{client_order_id}/audit`, `/api/v1/spot/campaign/executions`, `/api/v1/spot/sweep/automation-runs` | Command Workflows, Spot Operations, Campaigns | `blocked` | Command routes exist, `GET /api/v1/spot/command-suite` exposes Buy/Sell/Cancel readiness, and manual order/cancel route adapters now pass backend admission decisions into the shared command-service `allow_live_execution` flag. Manual order admission can pass when exact backend approval, admission-audit, cap/guard, reconciliation, manual acknowledgement, and completed live-service evidence all match. The manual-order route now has a route-scoped configured backend live-service dependency that can reach the existing command-service live branch when backend env/config/event-stream gates pass; default runtime remains blocked. Accepted configured live manual BUY responses now expose `data.post_submit_reconciliation` with the direct-order audit route and no-mutation/no-browser/BFF-authority flags, and the frontend command workflow renders/links that handoff. The frontend Spot Operations panel can load the returned `client_order_id` through `GET /api/v1/spot/direct-orders/{client_order_id}/audit` for read-only inspection. SELL authority, internal planned-budget accounting, live Coinbase validation, reconciliation execution proof, and cancel acknowledgement/live-service contract remain blocked. | Make one Spot manual BUY path operator-completable through backend-owned configured service, live validation, and reconciliation proof before broadening to SELL/cancel. |
| Stealth commands | `/api/v1/stealth/orders`, reveal, move, cancel, recovery, reconciliation, command suite, proof routes | Stealth Orders, Command Workflows | `blocked` | Evidence is rich, but operator completion is blocked by exchange-reality, lifecycle-write, live-disabled, and reconciliation gates. | Surface every stealth command as usable or blocked by exact gate; do not add hide-again shortcuts. |
| Movement/repricing | `/api/v1/movement-repricing/evidence`, order detail, stealth detail, stealth reprice | Movement/Repricing, Command Workflows | `blocked` | Reprice exists as a live-disabled command route; move, premark, cooldown, claim, and cancel/replace workflows are not complete. | Add a movement action-state matrix before adding controls. |
| Automation/campaigns | Spot campaign status, campaign executions, sweep status, sweep P/L, sweep automation runs | Campaigns, Spot Operations, Command Workflows | `blocked` | Scheduler/run-limit/retry/pause-resume behavior is not operator-complete; execution routes remain gated. | Inventory campaign/sweep scheduler state and represent missing controls as `not_modeled`. |
| Audit/reconciliation | Approval, admission audit, cap/guard decisions, reconciliation plans, audit workbench, direct-order audit | Approvals, Admission Audits, Cap/Guard, Reconciliation, Audit | `usable` | Inspection and record evidence are usable. Execution/reconciliation authority remains backend-only and not implied by records. | Keep as release support; link command attempts to these records in the selected command slice. |
| Settings/policy | Guard/risk policy, capabilities, OIDC readiness, CSRF, live-execution decision reads/records | Guard/Risk, Settings, Admin | `blocked` | Read and disabled decision evidence exists, but safe operator editing of settings/policy is not modeled. | Add safe settings map: editable, read-only, secret, `unsupported`, `not_modeled`. |
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
generated OpenAPI contract and renders them without controls.

What this clears:

- Lifecycle status is displayable through existing backend health evidence.
- `start` is explicitly `unsupported`.
- `stop`, `pause`, `resume`, and `drain` are explicit `not_modeled` backend
  contract gaps instead of missing UI.
- No route-local lifecycle execution, dashboard WebSocket bridge, browser/BFF
  process authority, shell helper, or Coinbase call was added.

## Follow-On Implementation Slice

The next implementation slice should come from the still-blocked spot command
workflow, not from more lifecycle classification or inventory read modeling.
Inventory read coverage is now `ready_with_data_gate`; the remaining Release
0.1 spot blocker is no longer route-local command flag binding or generic
live-service dependency wiring. Manual order and cancel route adapters now
source `allow_live_execution` from backend live admission, and manual order has
a route-scoped configured backend live-service dependency. Manual order
admission can now pass with exact backend records, manual acknowledgement, and
a completed backend live-service state. Accepted configured live responses now
return a structured `post_submit_reconciliation` audit handoff for
`GET /api/v1/spot/direct-orders/{client_order_id}/audit`; that is not
reconciliation execution and does not mutate order or exchange state. The
frontend command workflow now renders and links that backend evidence without
creating browser/BFF execution authority. The frontend Spot Operations panel
can also load the handoff `client_order_id` through the same direct-order
audit route for read-only inspection. The remaining blocker is making one
manual Spot BUY path operator-completable through live Coinbase validation
under the approved notional cap and eventual reconciliation execution proof.
SELL must wait for Admin API lot-authority and planned-budget sources; cancel
should stay out of the operator-completable slice until it has an explicit
acknowledgement contract.
Any implementation must keep auth, RBAC, operator intent, idempotency, audit,
approval snapshot, cap/guard, reconciliation, wallet/no-shorting, direct
acknowledgement, live-service, and Coinbase adapter authority in the backend.

## Live Coinbase Execution

No live Coinbase execution was run for this matrix phase.

- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.
