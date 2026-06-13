# Admin API

This repository exposes the professional backend API for the separate
enterprise admin platform at `C:\coinbase-frontend`.
Spot is the first complete product module consumed by that platform; it is not
the generic contract shape for every backend feature.
The repository association is documented in
[Frontend Association](docs/FRONTEND_ASSOCIATION.md).
Maintainer handoff for contextless agents starts at
[Maintainer Handoff](docs/MAINTAINER_HANDOFF.md).

## Current Status

The repository now contains an Admin API contract, generated OpenAPI and
route-inventory artifacts, fail-closed auth/RBAC bootstrap, durable JSONL
idempotency/audit stores, structured error payloads, observability headers,
read-only admin diagnostics, order read routes, read-only stealth lifecycle
routes, a live-disabled
stealth cancel command contract, movement/repricing evidence routes, a
live-disabled movement reprice command contract, read-only futures/perpetual
account and position routes, read-only guard/risk policy evidence, read-only
cross-module audit workbench evidence, backend-owned approval, cap/guard,
admission audit, and reconciliation plan record routes, and read-only spot
operator routes. Live-shaped trading command HTTP routes still return
`not_implemented` after auth, permission, idempotency, and audit handling;
they do not submit orders, cancel orders, or call Coinbase.

The generated OpenAPI contract documents the eventual `200` accepted/replayed
command response shape and the current `501` live-disabled response shape.
The current runtime still returns `501` for create, order cancel, stealth
cancel, movement reprice, and campaign execution commands because HTTP live
execution is not approved. Read routes document typed `200` payloads plus
structured `401` and `403` errors.
Enterprise-readiness evidence also includes structured per-module
`command_gaps` and a top-level `command_gap_count` so unsupported, not
modeled, and live-disabled command paths are visible without relying on
free-form unsupported-action strings. The same readiness payload now includes
M48 `mutation_taxonomy` rows and aggregate counts. Each row maps a command
route or legacy command surface to exactly one backend-owned mutation family
with identity keys, RBAC permission, idempotency, operator intent, approval,
cap/guard, admission audit, reconciliation, and owning service evidence.
Taxonomy rows are read-only evidence; they do not create approval mutation,
route-local execution, live adapters, BFF execution authority, or Coinbase
calls.
M49 adds a backend-owned approval request and decision lifecycle through the
existing append-only approval store. Approval requests, approve/reject
decisions, revocations, and expiry-derived status are typed Admin API
contracts. Approved decisions link the existing resolver-compatible approval
snapshot record, but browser approval remains insufficient for live execution:
cap/guard, admission audit, reconciliation, disabled live service, and live
adapter gates still fail closed.
M50 adds backend-owned cap/guard decision execution records. These records
persist the backend decision envelope that binds route, method, module,
identity, actor, operator intent, payload hash, approval snapshot, admission
audit id, and cap/guard policy refs. They are evidence and resolver input
only; the browser and BFF do not evaluate wallet, margin, profitability,
inventory, account-limit, or spot-specific guard rules.
M51 adds backend-owned admission audit records. These records append exact
resolver-eligible audit proof that binds route, identity, payload hash,
idempotency, actor, operator intent, approval snapshot, expected cap/guard
decision ref, expected reconciliation plan ref, and disabled live-intent
evidence. The writer rejects records that claim live admission is allowed;
browser audit, BFF audit, and the audit row itself remain insufficient for
live execution.
M52 adds backend-owned reconciliation plan records. These records bind the
exact live-shaped route envelope to approval snapshot, admission audit,
cap/guard decision, reconciliation policy, product scope, retained-inventory
requirement, and notional caps. Only `allowed=true` with `status=passed` is
resolver-eligible. The routes do not execute reconciliation, mutate order or
exchange state, submit Coinbase orders, or create browser/BFF reconciliation
authority.
M53 adds one route-bound dry-run pilot adapter for `POST /api/v1/orders`
through the shared `AdminApiCommandService.place_manual_order` method. It is
configured evidence only and remains non-executable. M54 starts the Spot
command-suite with `GET /api/v1/spot/command-suite`, a read-only readiness
contract for manual order placement, cancel by `client_order_id`, and spot
campaign execution. The route reports blockers, missing gate-chain evidence,
proof routes for backend approval/audit/cap/reconciliation records, and
frontend/BFF display boundaries; it does not add live controls or execute
Coinbase orders. Proof routes are derived from `ADMIN_API_ROUTE_INVENTORY`
and are local-state evidence requirements only. They are not browser
authorization, BFF execution authority, live reconciliation execution, or
Coinbase calls.

The legacy dashboard `place_order`, `cancel_order`, and
`place_hotpoint_test_order` WebSocket messages now delegate to
`application.admin_api.command_service.AdminApiCommandService` as compatibility
adapters. New product UI must use the HTTP API contract, not the dashboard
WebSocket.

Mutating HTTP command responses include the current fail-closed live execution
gate decision and M34 route-bound admission decision evidence. M35 persists
that same admission decision in the existing append-only Admin API audit log
and exposes it through the read-only Audit Workbench. M36 adds the
backend-owned append-only approval-store foundation while approval snapshots
remain absent and HTTP live execution remains disabled. M37 adds backend-only
approval snapshot resolver infrastructure over that store without making the
resolver an approval endpoint, browser approval, command authority, or live
execution path. M38 wires existing command admission evidence to that resolver
so a command response can report whether an exact unexpired snapshot was found
without enabling live execution. M39 wires existing command admission evidence
to backend-owned append-only admission audit proof so a command response can
report whether an exact audit event was found. The admission decision binds
the route, method, module id, identity key, identity value, requesting actor,
idempotency key, operator intent, and payload hash to the approval snapshot,
admission audit, cap/guard, and reconciliation blockers before HTTP live
execution can be enabled.
For `POST /api/v1/orders`, the route attaches a stable backend-owned
`client_order_id` before admission when the request omits one. The id is
derived from endpoint, actor, idempotency key, and the payload hash so replay
evidence is stable while the browser still does not create or override order
identity. The command remains live-disabled and returns `501`.

Current read-only HTTP surfaces include:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/live-enablement`
- `GET /api/v1/admin/enterprise-readiness`
- `GET /api/v1/admin/guard-risk-policy`
- `GET /api/v1/admin/audit-workbench`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/admin/approvals`
- `GET /api/v1/admin/approvals/requests/{approval_request_id}`
- `GET /api/v1/admin/admission-audits`
- `GET /api/v1/admin/admission-audits/{admission_audit_id}`
- `GET /api/v1/admin/cap-guard/decisions`
- `GET /api/v1/admin/cap-guard/decisions/{decision_id}`
- `GET /api/v1/admin/reconciliation/plans`
- `GET /api/v1/admin/reconciliation/plans/{plan_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`
- `GET /api/v1/spot/command-suite`

`GET /api/v1/admin/enterprise-readiness` also exposes per-module
`action_posture` evidence. The posture counts read routes, command routes,
live-disabled/live-eligible routes, unsupported actions, and command gaps from
backend route-inventory `module_id` ownership. It is display evidence only; it
does not authorize browser-side commands or replace backend guard, wallet,
margin, approval, audit, cap, or reconciliation gates.

The same response exposes M48 `mutation_taxonomy` evidence. Current taxonomy
rows cover the five live-disabled HTTP command routes, three legacy dashboard
WebSocket compatibility command surfaces, and two backend-contract-required
families for futures/perpetual commands and fill-ledger repair. Every current
command surface in `ADMIN_API_ROUTE_INVENTORY` must appear in exactly one
taxonomy row.
M49 adds the `admin.approval_lifecycle` taxonomy row for approval request,
decision, and revoke local-state mutation routes.
M50 adds the `admin.cap_guard_decisions` taxonomy row for backend-owned
cap/guard decision record routes. Only records with `allowed=true` and
`status=passed` can become resolver-eligible for exact backend admission
matching; blocked and warning records remain durable fail-closed evidence.
M51 adds the `admin.admission_audits` taxonomy row for backend-owned
admission audit records. Admission audit records are exact proof input only;
they remain blocked/no-live evidence and cannot mark live admission allowed.
M52 adds the `admin.reconciliation_plans` taxonomy row for backend-owned
reconciliation plan records. Passed records are exact resolver input only;
they do not execute reconciliation or mark exchange/order state reconciled.

Current mutating HTTP command surfaces are:

- `POST /api/v1/orders`
- `POST /api/v1/orders/{client_order_id}/cancel`
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
- `POST /api/v1/spot/campaign/executions`

Current local-state approval lifecycle mutation surfaces are:

- `POST /api/v1/admin/approvals/requests`
- `POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions`
- `POST /api/v1/admin/approvals/{approval_id}/revoke`
- `POST /api/v1/admin/admission-audits`
- `POST /api/v1/admin/cap-guard/decisions`
- `POST /api/v1/admin/reconciliation/plans`

These local-state routes are authenticated, authorized, idempotent, and
audited. They write backend-owned approval lifecycle, admission audit,
cap/guard decision, or reconciliation plan evidence only; they do not submit
orders, cancel orders, evaluate browser guards, execute reconciliation, mutate
order/exchange state, or call Coinbase.

See [Admission Audit Records](README.admission-audits.md),
[Cap/Guard Decision Records](README.cap-guard-decisions.md),
[Reconciliation Plan Records](README.reconciliation-plans.md), and
[Admin API Examples](docs/examples/admin-api.md) for record contracts and
payload examples.

The current operational dashboard is still the proof-of-concept WebSocket and
HTML surface documented in `agent.md` and `genai_data/API_REFERENCE.md`.
For the current boundary between legacy live WebSocket commands, read-only
HTTP routes, and sweep/campaign execution, see
[Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

The frontend release-hardening gate is owned by `C:\coinbase-frontend` and is
the canonical no-live command:

```powershell
npm run release:gate
```

That gate expands to build, typecheck, lint, generated API freshness, command
security, release/deployment checks, release artifact generation, runtime
evidence, autonomous queue validation, unit tests, dry read/command/BFF/OIDC
smokes, and Playwright e2e. Those checks are no-live checks and must report
live Coinbase execution as not run with notional `$0`. They are not approval
for live Coinbase execution. The release artifact is written in the frontend
repository at
`artifacts/release-readiness.json`; the package manifest is
`artifacts/deployment-package-manifest.json`; and the route/header drill is
`artifacts/observability-drill.json`. Synthetic probe evidence is written to
`artifacts/synthetic-probes.json`, and the public release checklist is written
to `artifacts/public-release-checklist.json`. Runtime/UI evidence is written
to `artifacts/runtime-evidence.json`. They are uploaded by frontend CI; they
are not backend approval to trade. These checks do not replace this
repository's required backend regression gate when backend files change.
In short: runtime evidence is saved, and these artifacts are not approval for
live Coinbase execution.
No-live release artifacts are not approval for live Coinbase execution.

Enterprise readiness also acts as the backend-owned module registry. Each
module row exposes a stable `module_id`, primary owner, backend contract refs,
frontend contract refs, documentation refs, identity keys, and a
`spot_rule_boundary` so future non-spot work does not copy spot wallet,
USDC, cost-basis, or no-shorting assumptions by accident.

Route and capability evidence is module-bound too. Every route inventory row
has a backend-owned `module_id`, and `GET /api/v1/admin/capabilities` exposes
that id so the frontend can prove route ownership without deriving trading
authority in the browser.

The current frontend read-model interaction batch consumes backend-shaped
admin, order, spot, campaign, audit, and diagnostics reads as display evidence
only. The frontend may locally filter/sort already-loaded rows, select
`client_order_id` details, render audit anchors for client order id,
correlation id, and audit id, switch campaign evidence tabs, show named
empty/error states, and keep tables usable on narrow viewports. None of those
interactions create frontend trading authority, wallet checks, guard
decisions, order profitability checks, Coinbase calls, or exchange
`order_id` identity.
The current frontend command draft scope remains crypto-USDC spot pairs and
must not be broadened in browser code before backend Admin API contracts and
tests define a broader scope.
The platform/module split is documented in
[Admin Platform Architecture](docs/ADMIN_PLATFORM_ARCHITECTURE.md) and
[Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md).

## Direction

- Use FastAPI with backend-owned OpenAPI.
- Keep `openapi/coinbase-admin-api-route-inventory.json` generated from
  `ADMIN_API_ROUTE_INVENTORY`; frontend route checks consume this artifact
  instead of scraping backend Python source.
- Keep the backend as the only authority for trading behavior.
- Keep HTTP live-order execution disabled until approval/cap gates are complete.
- Keep legacy dashboard WebSocket handlers as compatibility adapters.
- If a legacy WebSocket live command does not pass through enterprise
  idempotency, approval, and cap gates, label it compatibility-only and exclude
  it from new frontend workflows.
- Use `client_order_id` for internal and operator-facing order tracking.
- Manual order create may omit `client_order_id`; the backend route derives it
  before approval/admission evidence. Frontend and BFF code must display the
  returned id but must not generate or override it.
- Preserve Coinbase cancellation through the project wrapper
  `cancel_order(client_order_id)`, which accepts only explicit Coinbase
  `success: true` cancel evidence as success.
- Treat exchange-native `order_id` as exchange evidence only. The order read
  model exposes it as `exchange_order_id`; it is not an identity or cancel key.
- Order list/detail read rows may include `correlation_id` and `audit_id`
  when the backend row source has durable evidence for them. These fields are
  audit navigation evidence, not order identity.
- Stealth read rows use `stealth_order_id` for stealth lifecycle identity,
  `active_placement_client_order_id` for active placement evidence, and
  `active_exchange_order_id` as exchange evidence only. The enterprise Admin
  API has a live-disabled stealth cancel command keyed by `stealth_order_id`;
  it must not use active placement ids or exchange ids as cancel keys, and it
  must not mutate lifecycle state until exchange handling and reconciliation
  are implemented.
- Movement/repricing read rows combine durable `order_moves`,
  `stealth_order_moves`, and `stealth_orders.anchor_repricing_state_json`
  evidence. Runtime mutation claims and pending replacement claims are shown
  only when safely observable through the existing manager/engine state; if
  unavailable, the response says so instead of treating the database as proof
  that no runtime claim exists.
- Movement repricing command draft:
  `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
  is live-disabled and keyed by `stealth_order_id`. It does not clear
  cooldowns, invoke the live repricer, cancel placements, or call Coinbase.
  Its `live_exchange_cancel` action class and `order:cancel` permission are
  intentional because approved live repricing would be cancel/replace-shaped;
  no standalone browser repricing permission exists. Dry-submit for this
  command means preserving the backend `501` response, idempotency, audit,
  operator-intent, and no-live evidence.
- Futures/perpetual read rows use backend-defined `position_key` identity.
  Account evidence separates `configured_product_scope` from
  `observed_position_scope`; close/reduce sides are backend-derived from
  observed position side and are not exchange-observed order flags.
- Guard/risk policy reads expose existing backend action-condition policy,
  configured cap rules, product capability policy, live gate posture,
  profitability-validator posture, authority sources, and rejection categories
  as evidence only. They do not fetch Coinbase wallets and do not approve live
  execution.
- Capability reads expose backend route-inventory metadata, including command
  action class, permission, shared service method, idempotency, approval,
  caps, audit, compatibility, and parity evidence. This metadata is a
  frontend validation source only; it does not make command routes live.
  `frontend_safe=true` means safe for Admin frontend/BFF contract exposure
  under backend authority; it is not permission to submit, cancel, reprice, or
  execute live Coinbase orders.
- Live-enablement reads expose controlled M8 live path readiness, cap
  posture, approval requirements, guard requirements, audit requirements, and
  reconciliation requirements. They also expose per-route controlled-live
  preflight checks that separate passed backend-owned prerequisites from
  blocking approval, cap/guard, live-execution-service, and reconciliation
  prerequisites. M30 route-specific approval snapshot evidence makes the
  missing durable, backend-owned, expiring, payload-bound approval record
  explicit per live-shaped path. M36 approval-store foundation evidence makes
  configured durable backend approval-store infrastructure explicit per
  live-shaped path without creating approval snapshots. M37 approval snapshot
  resolver foundation is internal backend infrastructure for exact unexpired
  store records; it does not prove a route-specific approval snapshot is
  present. M32 live-admission audit trail evidence makes the missing
  append-only backend admission audit facts explicit per live-shaped path.
  M33 route-specific cap/guard contract evidence makes the missing backend
  cap, guard, payload, approval, admission-audit, and product-scope bindings
  explicit per live-shaped path. The
  route is read-only, reports
  `default_live_coinbase_execution=not_run`, submitted/executed notional
  `$0`, and does not enable any command path.
- M34 command admission decision evidence is emitted on live-disabled HTTP
  command responses. It is route-bound and payload-bound evidence for why the
  command remains blocked; it is not browser approval, guard execution,
  reconciliation authority, or live Coinbase execution.
- M35 command admission audit persistence writes the same admission decision
  to existing Admin API audit events and exposes it through Audit Workbench
  read evidence. It is not audit mutation, browser approval, guard execution,
  reconciliation authority, or live Coinbase execution.
- M36 durable approval-store foundation adds backend-owned append-only
  approval record storage and exact-match lookup semantics. It is not an
  approval endpoint, browser approval, BFF mutation, live admission, Coinbase
  execution, or proof that a route-specific approval snapshot exists.
- M37 approval snapshot resolver foundation can derive immutable backend
  snapshot evidence from an exact unexpired approval-store record. It is not
  an approval endpoint, browser approval, BFF mutation, live admission,
  Coinbase execution, or proof that command admission may proceed.
- M38 command admission snapshot resolver wiring lets existing live-disabled
  command responses report `approval_snapshot_present`, snapshot ids, actor
  binding, expiry, identity value, and missing-snapshot reasons. A resolved
  snapshot removes only the `approval_snapshot_missing` blocker; live-disabled,
  admission-audit, cap/guard, reconciliation, and browser-authority blockers
  still prevent Coinbase submission.
- M39 command admission audit resolver wiring lets existing live-disabled
  command responses report `admission_audit_present`, audit ids, audit source,
  recorded time, and missing-audit reasons. A resolved audit proof removes
  only the `admission_audit_missing` blocker; live-disabled, cap/guard,
  reconciliation, and browser-authority blockers still prevent Coinbase
  submission.
- M40 command admission cap/guard proof wiring lets existing live-disabled
  command responses report `cap_guard_present`, cap/guard decision ids,
  cap/guard source, recorded time, and missing-cap/guard reasons. A resolved
  cap/guard proof removes only the `cap_guard_missing` blocker; live-disabled,
  reconciliation, and browser-authority blockers still prevent Coinbase
  submission.
- M41 command admission reconciliation plan proof wiring lets existing
  live-disabled command responses report `reconciliation_plan_present`,
  reconciliation plan ids, source, recorded time, and missing-reconciliation
  reasons. A resolved reconciliation plan proof removes only the
  `reconciliation_plan_missing` blocker; live-disabled and browser-authority
  blockers still prevent Coinbase submission.
- M42 command admission live execution service boundary evidence lets
  existing live-disabled command responses report that the backend live
  execution service is required but absent/disabled. It does not remove
  `live_execution_disabled`, authorize the browser, or submit to Coinbase.
- M43 disabled live execution service foundation makes that backend service
  boundary present as evidence with source `disabled_backend_service`. The
  descriptor has no create, cancel, submit, execute, browser, BFF, or Coinbase
  authority methods, so command routes remain no-live.
- M44 live execution adapter contract evidence maps live-shaped routes to
  shared `AdminApiCommandService` methods on read-only live-enablement path
  rows. The adapter evidence is disabled, unconfigured, and non-executable.
- M45 live execution intent envelope evidence lets command admission decisions
  report the route, identity, payload hash, idempotency key, actor, operator
  intent, service method, and disabled blockers for a command-to-live-execution
  attempt. The intent is not prepared, not executable, and display-only.
- M46 live readiness precondition evidence lets
  `GET /api/v1/admin/live-enablement` report a normalized backend-owned
  checklist for approval store, approval snapshot, admission audit, cap/guard,
  reconciliation, adapter, intent, browser/BFF, and disabled live service
  prerequisites. It is read-only evidence and does not broaden command
  admission, browser approval, BFF execution authority, or Coinbase execution.
- Approval-store rows created before M37 that lack `requested_by_actor_id`
  fail closed during strict JSONL reads. They are ignored by resolver lookup
  rather than treated as reusable approval authority.
- Audit workbench reads normalize route inventory, command audit, order,
  stealth, movement/repricing, futures/perpetual, guard/risk, and campaign
  evidence into one read-only surface. They do not mutate audit history, read
  Coinbase, or create a second command path.
- Enterprise-readiness command-gap evidence is read-only. It records action,
  status, reason, required backend contract, frontend boundary, live Coinbase
  posture, and notional for command paths that must not be implemented from
  the browser. It is not a command route registry or live approval source.
- Configure `COINBASE_ADMIN_API_BEARER_TOKEN` before exercising HTTP routes.
  Without it, routes fail closed with `401`.
- `COINBASE_ADMIN_API_AUTH_MODE=bootstrap_bearer` is the local/bootstrap
  verifier. `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt` verifies RS256 JWTs
  against the configured issuer, audience, and JWKS, then derives actor and
  role evidence from JWT claims.
- The `oidc_jwt` verifier readiness contract reports required
  `COINBASE_ADMIN_API_OIDC_ISSUER`,
  `COINBASE_ADMIN_API_OIDC_AUDIENCE`, and
  `COINBASE_ADMIN_API_OIDC_JWKS_URL` settings. Missing settings fail closed.

## Local Run

Run the existing FastAPI app directly when developing the enterprise frontend:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The helper starts `api.v1.app:app` on `http://127.0.0.1:8787`, sets local CORS
for `http://127.0.0.1:3000`, and keeps live Coinbase execution disabled. It
does not import trading clients or submit/cancel exchange orders.

For a deployment-like local run, configure auth explicitly instead of using
`--dev-token`:

```powershell
$env:COINBASE_ADMIN_API_BEARER_TOKEN = "local-admin-token"
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
python tools\run_admin_api.py --port 8787
```

`COINBASE_ADMIN_API_CORS_ORIGINS` is an allowlist, not a wildcard. The Admin
API accepts browser preflight requests only from configured origins and allows
the session/BFF bridge headers required by the frontend:
`Authorization`, `X-Admin-Actor`, `X-Admin-Roles`, `X-Correlation-Id`,
`X-Request-Id`, `X-Operator-Intent`, `Idempotency-Key`, and `X-CSRF-Token`.
Bearer tokens still belong on the backend/session boundary; do not expose them
through `NEXT_PUBLIC_*` frontend variables.

The frontend BFF may copy only documented response-evidence headers back to
browser code: `Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Treat missing BFF authority as a session/transport
configuration failure, not as a live trading gate result.

For mutating HTTP commands, `X-Operator-Intent` is durable audit evidence and
part of the idempotency payload hash together with endpoint, actor/roles, body,
and path identity. Reusing an `Idempotency-Key` with changed operator intent
returns conflict instead of replaying the prior command.

Frontend `server_env_static` BFF authority is local/staging evidence only.
Production readiness requires frontend `backend_oidc_jwt` BFF mode and
backend `oidc_jwt` verifier configuration. Browser-visible RBAC remains a UI
hint; backend RBAC is the enforcement authority.
`GET /api/v1/admin/oidc-readiness` exposes backend OIDC verifier evidence for
release checks, including active auth mode, required/missing environment
settings, claim mapping, JWKS reachability, and no-live notional posture.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as usable by the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

The smoke uses backend TestClient and temporary JWKS evidence to prove missing
config blocks, configured JWKS readiness reports ready, and `oidc_jwt`
session claims override forged browser actor/role headers. It does not contact
Coinbase and reports live Coinbase execution not run with notional `$0`.

CSRF enforcement is opt-in for cookie/session or BFF deployments:

```powershell
$env:COINBASE_ADMIN_API_CSRF_REQUIRED = "true"
$env:COINBASE_ADMIN_API_CSRF_TOKEN = "local-csrf-token"
```

When required, unsafe HTTP methods under `/api/v1/` must include
`X-CSRF-Token` matching the configured token. Read-only `GET` routes are not
blocked by CSRF middleware. Failed CSRF checks return structured `403` errors
with `X-Live-Execution-Enabled: false`.
`GET /api/v1/admin/csrf` exposes the CSRF posture, header name, token source,
and rotation policy without disclosing a token value.

## Must Not Do

- Do not implement live order behavior directly in FastAPI handlers.
- Do not duplicate guard, wallet, sizing, or Coinbase REST logic in the
  frontend.
- Do not treat frontend acknowledgement as sufficient enterprise approval.
- Do not expose Coinbase credentials to browser code.

## References

- [Admin API E2E Plan](docs/plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Architecture](docs/ADMIN_PLATFORM_ARCHITECTURE.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Movement And Repricing](README.movement-repricing.md)
- [Futures/Perpetuals Admin Reads](README.futures-perpetuals.md)
- [Guard/Risk Policy Admin Reads](README.guard-risk-policy.md)
- [Audit Workbench Admin Reads](README.audit-workbench.md)
- [Frontend Association](docs/FRONTEND_ASSOCIATION.md)
- [Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md)
- [API Reference](genai_data/API_REFERENCE.md)
- [Order ID Handling](genai_data/ORDER_ID_HANDLING.md)
- [Documentation Index](docs/README.md)
