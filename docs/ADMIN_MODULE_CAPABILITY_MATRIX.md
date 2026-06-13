# Admin Module Capability Matrix

This matrix records what the enterprise Admin API and associated frontend can
support per module. It prevents spot-specific assumptions from becoming the
implicit platform model.

| Module | Read-only views | Command drafts | Dry-submit | Live execution | Backend namespace | Identity key | Product-specific rules | Required gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Admin / System Health | Implemented for bootstrap, health, session, OIDC readiness, capabilities, CSRF, live-enablement readiness, enterprise-readiness evidence, approval lifecycle reads, admission audit reads, cap/guard decision reads, reconciliation plan reads, guard/risk policy, audit workbench, release gate, spot/direct-order recovery gate, fill-ledger health, and frontend fixtures | Implemented as backend-owned approval request/decision/revoke lifecycle mutations, admission audit record mutations, cap/guard decision record mutations, and reconciliation plan record mutations; not trading commands | Approval lifecycle, admission audit, cap/guard decision, and reconciliation plan mutations are idempotent/audited backend records only and do not dry-submit Coinbase commands | Live-enablement and enterprise-readiness routes are read-only evidence; approval lifecycle, admission audit, cap/guard decision, and reconciliation plan routes do not enable live execution | `/api/v1/admin/*` | Request id, correlation id, actor id, approval request id, approval id, admission audit id, cap/guard decision id, reconciliation plan id, backend policy ids, audit ids, and module-specific identity when reported | Platform primitive; no trading rules; live-enablement reports cap/approval/guard/audit/reconciliation requirements, controlled-live preflight check evidence, route-specific approval snapshot requirements, approval-store contract requirements, live-admission audit trail requirements, route-specific cap/guard contract requirements, live execution adapter contract evidence, and M46 normalized live readiness precondition evidence; command responses report M34 route-bound admission decision evidence; M35 persists that evidence in append-only Admin API audit events and read-only Audit Workbench rows; M36 adds backend-owned append-only approval-store infrastructure while approval snapshots remain absent and live execution remains disabled; M37 adds backend-only approval snapshot resolver infrastructure without approving commands or enabling live execution; M38 wires live-disabled command admission evidence to that resolver so snapshot-present/missing status is auditable without live authority; M39-M41 wire live-disabled command admission evidence to backend-owned audit, cap/guard, and reconciliation proof without browser authority or live execution; M42-M46 define disabled live execution service, adapter, intent, and readiness precondition evidence without adding a live switch, browser authority, BFF execution authority, or Coinbase calls; M47 adds enterprise-readiness `functionality_inventory`; M48 adds enterprise-readiness `mutation_taxonomy`; M49 adds backend-owned approval lifecycle request/decision/revoke/expiry/snapshot-linking contracts and the `admin.approval_lifecycle` mutation taxonomy row; M50 adds backend-owned cap/guard decision execution records and the `admin.cap_guard_decisions` mutation taxonomy row; M51 adds backend-owned admission audit records and the `admin.admission_audits` mutation taxonomy row; M52 adds backend-owned reconciliation plan records and the `admin.reconciliation_plans` mutation taxonomy row without reconciliation execution or exchange/order-state mutation; browser approval, browser/BFF audit, browser/BFF guard evaluation, and browser/BFF reconciliation proof remain insufficient for execution | Admin API contract tests, frontend release gate when consumed |
| Spot Operations | Implemented for readiness, sweep status, P/L, cost basis, campaign status, direct-order audit, command-suite readiness with proof routes, order reads, and frontend read-model interactions | Implemented as live-disabled HTTP contracts for manual order, cancel by `client_order_id`, and campaign execution | Implemented for tests, smokes, and gated no-live frontend review; UI may call canonical backend/BFF dry-submit helpers only when capability evidence is matched, `frontend_safe=true`, and `live_enabled=false` | HTTP command routes return `501` until live approval/cap/audit/reconciliation gates are complete; `GET /api/v1/spot/command-suite` is read-only coverage with backend proof-route linkage and never live authority; legacy approved tools remain outside frontend authority | `/api/v1/spot/*`, `/api/v1/orders`, `/api/v1/orders/{client_order_id}` | `client_order_id`; exchange `order_id` evidence only | spot-only USDC scope, wallet inventory, no shorting, cost basis, average cost, lot authority, known profitable inventory; these rules must not become platform defaults | Admin API regression, spot readiness regression, frontend release gate, contextless spot-order review |
| Futures / Perpetuals | Implemented as backend read-only account, risk, and position routes with enterprise frontend read model | Not yet modeled | Not yet modeled | Not approved through frontend | `/api/v1/futures/*` for reads | `position_key` for positions; configured product scope and observed position scope are separate | Must not import spot-only rules; close/reduce sides are backend-derived from observed position side, not exchange-observed order flags; funding remains `not_modeled` | Admin API contract tests, frontend route coverage, frontend release gate, contextless non-spot review |
| Stealth Orders | Implemented as backend read-only stealth lifecycle list/detail routes and read-only enterprise frontend module | Implemented as live-disabled HTTP contract for cancel by `stealth_order_id` | Implemented for tests, smokes, and gated no-live frontend review; UI may call the canonical backend/BFF stealth cancel dry-submit helper only when capability evidence is matched, `frontend_safe=true`, and `live_enabled=false` | HTTP stealth cancel returns `501` until exchange handling and reconciliation gates are complete | `/api/v1/stealth/*` for reads and live-disabled cancel; dashboard remains compatibility surface | `stealth_order_id`; active placement client id and exchange ids are evidence only | Must preserve exchange-reality state, flat hierarchy, mutation claims, and placement lifecycle rules; no spot wallet/cost-basis assumptions; no active-placement or exchange-id cancel keys | Stealth regression, Admin API contract tests, frontend release gate, command dry smoke, contextless module review |
| Order Movement / Repricing | Implemented as backend movement/repricing evidence routes and enterprise frontend read model | `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` live-disabled | Implemented as live-disabled `501` dry-submit evidence for tests, smokes, and gated no-live frontend review; UI may call the canonical backend/BFF reprice dry-submit helper only when capability evidence is matched, `frontend_safe=true`, and `live_enabled=false` | Not approved through frontend | `/api/v1/movement-repricing/*` for reads plus live-disabled reprice draft; dashboard remains compatibility surface | `client_order_id` for order/placement evidence; `stealth_order_id` for stealth lifecycle and reprice draft; exchange ids are evidence only | Must preserve move/reprice claim locks and cannot hide revealed live placements without exchange handling; the reprice draft must not clear cooldowns or invoke live repricing; cancel-class permission is intentional because future live repricing is cancel/replace-shaped | Movement/repricing regression, Admin API contract tests, frontend release gate, contextless review |
| Campaigns / Sweeps | Spot campaign and sweep reads implemented under Spot Operations | Spot campaign execution route exists but is live-disabled | Spot campaign dry-submit path exists for tests, smokes, and gated no-live frontend review; UI keeps `dry_run=true` and requires matched live-disabled capability evidence before request | Not approved through frontend | `/api/v1/spot/campaign/*` today; other campaign namespaces require backend contract first | Campaign id plus backend-defined order identity | Spot campaign rules are spot-only; non-spot campaigns need separate domain contracts | Admin API regression, frontend command smoke, contextless review |
| P/L, Ledger, And Reconciliation | Implemented for spot P/L and fill-ledger health evidence | Not applicable today | Not applicable today | Not applicable through frontend | `/api/v1/spot/sweep/pnl`, `/api/v1/admin/fill-ledger-health` today | Backend-defined ledger ids and `client_order_id` where applicable | Spot operational P/L is not tax accounting; futures/perpetual P/L must be position/collateral aware | Backend read contract tests and frontend adapter tests |
| Guard / Risk Policy | Implemented as backend read-only guard/risk policy evidence and consumed by the enterprise frontend | Not a frontend command module | Not applicable | Not approved through frontend | `/api/v1/admin/guard-risk-policy` | Backend-defined policy ids, product id filter, correlation ids, and audit ids | Browser must not calculate wallet, margin, guard, profitability, or live approval authority; route does not fetch Coinbase wallets | Guard regression, Admin API contract tests, frontend release gate, contextless review |
| Audit Workbench | Implemented as backend read-only cross-module route, command, correlation, audit, and exchange evidence | Not a frontend command module | Not applicable | Not approved through frontend | `/api/v1/admin/audit-workbench` | `client_order_id`, `stealth_order_id`, or `position_key` depending on module; exchange ids are evidence only | Browser must not mutate audit history, call Coinbase, replay commands, or treat exchange ids as tracking/cancel keys | Admin API contract tests, frontend route coverage, frontend release gate, contextless review |

## Update Rules

- Add or update a row before adding a module route or frontend module.
- Use `Not yet modeled` instead of vague planned support.
- Keep spot-only rules in the Spot Operations row or spot-specific docs.
- Add backend contracts before frontend read models, drafts, dry-submit, or
  live UI.
- Keep `GET /api/v1/admin/enterprise-readiness` command-gap evidence aligned
  with this matrix when a module moves between unsupported, not modeled,
  live-disabled draft, or live-approved status.
- Keep enterprise-readiness module registry fields aligned with this matrix:
  `module_id`, `primary_owner`, contract refs, docs, identity keys, and
  spot-rule boundary must change with module ownership or scope.
- Keep enterprise-readiness `functionality_inventory` rows aligned with this
  matrix whenever a workflow becomes admin-exposed, draft/live-disabled,
  backend-contract-required, unsupported, or compatibility-only.
- Keep enterprise-readiness `mutation_taxonomy` rows aligned with this matrix
  and `ADMIN_API_ROUTE_INVENTORY` whenever a command route, legacy command
  surface, required permission, identity key, idempotency rule, approval rule,
  cap/guard rule, audit rule, reconciliation rule, or owning backend service
  changes.
- Keep route inventory and capability `module_id` evidence aligned with this
  matrix whenever routes move between modules.
- Keep enterprise-readiness `action_posture` counts aligned with backend
  route-inventory `module_id` ownership; do not use path-prefix grouping as
  module authority.
- Keep Enterprise Command Gap Triage aligned with enterprise-readiness
  command gaps and backend capability rows. It is read-only triage evidence,
  not a command backlog, approval surface, or browser authority source.
- Keep Enterprise Module Capability Linkage aligned with backend capability
  rows and enterprise-readiness command routes. It is read-only evidence for
  command workflow posture, not a separate source of command authority.
- Keep live-enablement governance linkage aligned with backend capability
  rows, enterprise-readiness module rows, and route-inventory live-shaped
  command paths. It is read-only evidence for gate posture and blockers, not
  approval for live execution.
- Keep controlled-live preflight checks aligned with live-enablement path
  rows. They are readiness evidence only; they must not become a browser
  approval path, live switch, command route, or reconciliation substitute.
- Keep route-specific approval snapshot evidence aligned with live-enablement
  path rows. It is missing-approval evidence only; it must not become
  approval storage, browser approval, command authority, Coinbase execution,
  or reconciliation evidence.
- Keep approval-store contract evidence aligned with live-enablement path
  rows. After M36 it may report configured backend store infrastructure, but
  it must not become an approval endpoint, browser approval, command
  authority, Coinbase execution, or reconciliation evidence.
- Keep approval snapshot resolver infrastructure backend-only. It may derive
  immutable evidence from exact unexpired approval-store records, but it must
  not become approval mutation, browser approval, command authority, Coinbase
  execution, or reconciliation evidence.
- Keep approval lifecycle routes backend-owned and separate from command
  execution. They may request, approve/reject, revoke, and display expiring
  snapshot evidence, but browser approval, BFF forwarding, or a linked
  approval snapshot is not sufficient live execution authority.
- Keep live-admission audit trail evidence aligned with live-enablement path
  rows. It is missing append-only backend audit evidence only; it must not
  become audit storage, approval storage, browser approval, command authority,
  Coinbase execution, or reconciliation authority.
- Keep route-specific cap/guard contract evidence aligned with
  live-enablement path rows. It is missing backend cap/guard decision evidence
  only; it must not become guard execution, browser wallet/profitability
  authority, browser approval, command authority, Coinbase execution, or
  reconciliation authority.
- Keep command admission decision evidence aligned with existing live-disabled
  command responses and the shared command service. It is backend-owned
  route/payload blocker evidence only; it must not become browser approval,
  command authority, Coinbase execution, or reconciliation authority.
- Keep persisted command admission audit evidence aligned with existing
  append-only Admin API audit events and read-only Audit Workbench rows. It
  must not become audit mutation, browser approval, command authority,
  Coinbase execution, or reconciliation authority.
- Keep command admission cap/guard proof evidence aligned with backend-owned
  append-only cap/guard decision rows and existing live-disabled command
  responses. It must not become guard mutation, browser wallet/profitability
  authority, browser approval, command authority, Coinbase execution, or
  reconciliation authority.
- Keep command admission reconciliation plan proof evidence aligned with
  backend-owned append-only reconciliation plan rows and existing
  live-disabled command responses. It must not become reconciliation
  execution, browser approval, command authority, Coinbase execution, or live
  admission authority.
- Keep command admission live execution service boundary evidence aligned with
  existing live-disabled command responses. It must not become a live switch,
  browser approval, command authority, Coinbase execution, or BFF execution
  authority.
- Keep disabled live execution service descriptor evidence non-executable. It
  may expose service state to admission evidence, but must not expose create,
  cancel, submit, execute, browser, BFF, or Coinbase authority methods.
- Keep live execution adapter contract evidence aligned with live-enablement
  path rows and shared `AdminApiCommandService` methods. It may name the
  future backend adapter boundary, but must not become route-local execution,
  browser approval, BFF execution authority, Coinbase execution, or
  order/exchange-state mutation.
- Keep live readiness precondition evidence aligned with live-enablement path
  rows. It must be derived from existing evidence and must not become a new
  preflight endpoint, command admission call, browser approval, BFF execution
  authority, Coinbase execution, or route-local executor.
- Update route inventory, OpenAPI, examples, frontend association, and
  contextless review prompts when a module changes status.
