# Admin Release 0.1 Route-To-UI Matrix

This document converts the Release 0.1 burn-down into a route-to-frontend
release matrix. It is not a new roadmap track. It exists so contextless
maintainers can see which backend routes already support operator work, which
frontend surface consumes them, and which blocker prevents the private operator
admin MVP from being usable.

The governing question remains:

> Does this make the frontend able to manage the project?

## Phase Instruction Review

`AGENTS.md` and `agent.md` were reviewed for this phase on 2026-06-27. No
phase-direction change was required. The controlling instructions remain:

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
| Admin shell | `/api/v1/admin/bootstrap`, `/health`, `/session`, `/capabilities`, `/live-enablement`, `/enterprise-readiness`, `/release-gate` | Overview, Modules, Settings, Admin Evidence | `blocked` | Read posture is usable, but lifecycle start/stop/pause/resume state is not modeled as backend-owned routes. | Add explicit lifecycle support classification: backend route if supported, otherwise `unsupported`/`not_modeled` UI evidence. |
| Account inventory | `/api/v1/admin/account-market-inventory`, `/api/v1/orders`, `/api/v1/orders/{client_order_id}`, `/api/v1/futures/account`, `/api/v1/futures/positions`, spot readiness/cost-basis/sweep/campaign reads | Inventory, Orders, Spot Operations, Futures/Perpetuals | `ready_with_data_gate` | First-class coverage exists for product catalog, spot wallets, spot balances, and spot fills. Coinbase reads are backend-only, bounded, and disabled unless explicitly enabled, so the frontend must render `data_status` instead of inventing browser reads. | Keep the frontend display-only, surface blocked data clearly, and use this route as the account/market source of truth. |
| Spot commands | `/api/v1/orders`, `/api/v1/orders/{client_order_id}/cancel`, `/api/v1/spot/command-suite`, `/api/v1/spot/campaign/executions`, `/api/v1/spot/sweep/automation-runs` | Command Workflows, Spot Operations, Campaigns | `blocked` | Command routes exist, but frontend-visible command contracts are currently live-disabled. | After inventory, choose one spot command path and make backend gate results operator-completable without browser authority. |
| Stealth commands | `/api/v1/stealth/orders`, reveal, move, cancel, recovery, reconciliation, command suite, proof routes | Stealth Orders, Command Workflows | `blocked` | Evidence is rich, but operator completion is blocked by exchange-reality, lifecycle-write, live-disabled, and reconciliation gates. | Surface every stealth command as usable or blocked by exact gate; do not add hide-again shortcuts. |
| Movement/repricing | `/api/v1/movement-repricing/evidence`, order detail, stealth detail, stealth reprice | Movement/Repricing, Command Workflows | `blocked` | Reprice exists as a live-disabled command route; move, premark, cooldown, claim, and cancel/replace workflows are not complete. | Add a movement action-state matrix before adding controls. |
| Automation/campaigns | Spot campaign status, campaign executions, sweep status, sweep P/L, sweep automation runs | Campaigns, Spot Operations, Command Workflows | `blocked` | Scheduler/run-limit/retry/pause-resume behavior is not operator-complete; execution routes remain gated. | Inventory campaign/sweep scheduler state and represent missing controls as `not_modeled`. |
| Audit/reconciliation | Approval, admission audit, cap/guard decisions, reconciliation plans, audit workbench, direct-order audit | Approvals, Admission Audits, Cap/Guard, Reconciliation, Audit | `usable` | Inspection and record evidence are usable. Execution/reconciliation authority remains backend-only and not implied by records. | Keep as release support; link command attempts to these records in the selected command slice. |
| Settings/policy | Guard/risk policy, capabilities, OIDC readiness, CSRF, live-execution decision reads/records | Guard/Risk, Settings, Admin | `blocked` | Read and disabled decision evidence exists, but safe operator editing of settings/policy is not modeled. | Add safe settings map: editable, read-only, secret, `unsupported`, `not_modeled`. |
| Unsupported behavior | Enterprise readiness command gaps, route inventory, capability registry | Modules, nav posture, command evidence | `blocked` | Gaps exist in evidence, but Release 0.1 needs a direct operator-facing blocker matrix rather than implied absence. | Add Release 0.1 unsupported/not-modeled panel to the frontend. |
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

## Follow-On Implementation Slice

The next implementation slice should be **Inventory Workflow Drilldowns**.

Reason: the account/market route now exposes backend-owned product, wallet,
balance, and fill rows. Release 0.1 usability improves next by linking those
rows into existing order, spot, futures, guard/risk, and audit views without
adding frontend trading behavior.

Expected backend result:

- Backend-owned route filters or identifiers for navigating from inventory rows
  to existing read surfaces.
- Explicit `unsupported` or `not_modeled` evidence where a drilldown target does
  not exist yet.
- No frontend wallet authority and no direct Coinbase browser calls.

Expected frontend result:

- The Inventory section keeps rendering backend-provided records and adds only
  safe navigation into existing backend read routes.
- Rows continue linking to order, spot, futures, guard/risk, audit, and
  reconciliation surfaces without adding browser-side trading behavior.

## Live Coinbase Execution

No live Coinbase execution was run for this matrix phase.

- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.
