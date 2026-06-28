# Admin API Contract Agent

## Owns

- `api/**` FastAPI route modules
- `application/admin_api/**` shared command service adapters
- `openapi/**` generated schema artifacts
- Admin API contract tests
- Admin API docs in coordination with the Architect Agent

## Canonical Path

```text
frontend request
-> FastAPI route
-> auth/RBAC
-> idempotency and approval gate
-> shared command service
-> existing domain/bridge/exchange path
-> durable audit
-> typed response
```

Current HTTP command routes are authenticated, authorized, idempotent, and
audited. They are no-live by default and return typed `501`
`not_implemented` responses unless a route has an explicit configured backend
live-service exception and exact backend admission evidence. The only current
manual Spot exceptions are `POST /api/v1/orders` and
`POST /api/v1/orders/{client_order_id}/cancel`; those routes may reach the
shared backend live branch only after exact backend auth/RBAC, idempotency,
approval, admission-audit, cap/guard, reconciliation, manual acknowledgement,
live-service, REST-client, and event-stream gates pass. Other mutating HTTP
command routes remain live-disabled/fail-closed. The generated OpenAPI schema
includes typed `200` accepted/replayed response contracts for explicit
live-enabled states and typed live-disabled response contracts for blocked
states.
`X-Operator-Intent` is required command evidence. It must be recorded in the
durable command audit event and included in the idempotency payload hash.

## Platform And Module Boundary

Admin API work must distinguish reusable admin platform primitives from domain
modules. Shared primitives include OpenAPI, auth/RBAC, idempotency, audit,
approval gates, observability headers, route inventory, and release evidence.
Spot is the first complete product module. Do not copy spot-only wallet,
USDC, cost-basis, average-cost, lot authority, or no-shorting rules into
futures/perpetuals, stealth orders, repricing, or risk modules. Add or update
`docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before broadening a module.

Legacy dashboard compatibility path:

```text
dashboard WebSocket message
-> compatibility adapter
-> compatibility idempotency/approval/cap treatment for live commands
-> shared command service
-> existing domain/bridge/exchange path
-> dashboard response/state update
```

## Shared Service Boundary

Implemented modules:

- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/idempotency.py`
- `application/admin_api/approval.py`
- `application/admin_api/audit.py`
- `api/v1/routes/*.py`
- `openapi/coinbase-admin-api.yaml`
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`

Shared command service methods currently cover manual placement,
cancel-by-`client_order_id`, hotpoint test placement for legacy dashboard
compatibility, live-disabled stealth cancel by `stealth_order_id`, and a
live-disabled movement reprice command keyed by `stealth_order_id`, and a
live-disabled spot campaign execution contract, and a live-disabled spot sweep
automation command contract keyed by `sweep_config_id`.

Read-only Admin API routes currently cover backend bootstrap, health,
session/RBAC evidence, capabilities, guard/risk policy evidence, audit
workbench evidence, release/spot-direct-order recovery gates, fill-ledger health, frontend
fixtures, order list/detail, stealth lifecycle list/detail, stealth
command-suite readiness,
movement/repricing evidence, futures/perpetual account and position evidence,
spot readiness, sweep status, sweep P/L, cost-basis status, campaign status,
and direct order audit.
Spot sweep automation command admission is route-bound evidence only. It may
bind `sweep_config_id`, cadence, notional, run-limit, dry-run, and operator
acknowledgement fields to the Admin API command envelope, but it must not call
sweep runner tools, create a browser scheduler, call Coinbase, or mark the
wider sweep automation gap complete before scheduler, recovery, and
reconciliation contracts exist.
The movement reprice command draft is not the legacy dashboard repricer: it
must not clear cooldowns, call `process_anchor_repricing_for_product`, or
mutate live revealed placements until the existing exchange-reality
reconciliation path is explicitly wired.
Guard/risk policy reads expose existing backend policy and authority sources as
evidence only. They must not become browser preflight approval or a second
guard engine.
Live-enablement approval snapshot evidence is read-only missing-approval
evidence. It may list required durable approval fields and backend sources,
but it must not become approval storage, browser approval, command authority,
Coinbase execution, or reconciliation proof.
Live-enablement approval-store contract evidence is read-only store
infrastructure evidence. It may list configured durable backend store behavior
and backend sources, but it must not become approval mutation, browser
approval, command authority, Coinbase execution, or reconciliation proof.
Approval snapshot resolver infrastructure is backend-only. It may resolve an
exact unexpired approval-store record into immutable evidence, but it must not
become approval mutation, browser approval, command authority, Coinbase
execution, or reconciliation proof.
Approval lifecycle routes are backend-owned local-state mutations. They may
request, approve/reject, revoke, and expose expiring approval snapshot
evidence through `application/admin_api/approval_service.py`, but they must not
call Coinbase, call command execution adapters, run guard decisions, execute
reconciliation, or make browser approval sufficient for live execution.
Cap/guard decision routes are backend-owned local-state mutations and reads.
They may persist and expose route-bound cap/guard decision evidence through
`application/admin_api/cap_guard_service.py`, but they must not call Coinbase,
call command execution adapters, evaluate wallet, margin, profitability,
inventory, account-limit, or spot-specific guards in the browser/BFF, execute
reconciliation, or make a cap/guard record sufficient for live execution.
Admission audit routes are backend-owned local-state mutations and reads over
the existing append-only Admin API audit store. They may persist and expose
route-bound admission audit proof through
`application/admin_api/admission_audit_service.py`, but they must not call
Coinbase, call command execution adapters, evaluate guards, execute
reconciliation, create browser audit authority, or mark live admission allowed.
Reconciliation plan routes are backend-owned local-state mutations and reads
over the append-only reconciliation plan store. They may persist and expose
route-bound post-submit reconciliation plan proof through
`application/admin_api/reconciliation_service.py`, but they must not call
Coinbase, call command execution adapters, execute reconciliation, mutate
order or exchange state, create browser reconciliation authority, or mark live
admission allowed.
Resolver-backed command admission evidence remains fail-closed. A resolved
snapshot may remove only `approval_snapshot_missing`; it does not authorize
live execution while live-disabled, admission-audit, cap/guard,
reconciliation, or browser-authority blockers remain.
Command admission live execution intent evidence remains fail-closed. It may
bind route, identity, payload hash, idempotency key, actor, operator intent,
and shared service method for review, but it must not create an executable
adapter, browser approval, BFF execution authority, Coinbase call, or parallel
command path.
Resolver-backed command admission audit evidence remains fail-closed. A
resolved audit proof may remove only `admission_audit_missing`; it does not
authorize live execution while live-disabled, cap/guard, reconciliation, or
browser-authority blockers remain.
Resolver-backed command admission cap/guard proof evidence remains
fail-closed. A resolved cap/guard proof may remove only `cap_guard_missing`;
it does not authorize live execution while live-disabled, reconciliation, or
browser-authority blockers remain.
Resolver-backed command admission reconciliation plan proof evidence remains
fail-closed. A resolved reconciliation plan proof may remove only
`reconciliation_plan_missing`; it does not authorize live execution while
live-disabled or browser-authority blockers remain, and it must not execute
reconciliation or mutate exchange/order state.
Command admission live execution service boundary evidence remains
fail-closed. It may report that the backend live execution service is
required but disabled/unconfigured; it must not remove
`live_execution_disabled`, authorize browser evidence, call Coinbase, or
create a second command path.
The disabled live execution service descriptor is evidence-only. It may make
the backend-owned service boundary visible to admission evidence, but it must
not expose create, cancel, submit, execute, Coinbase, browser approval, BFF
execution authority, or route-local execution methods.
Live execution adapter contract evidence is live-enablement evidence only. It
may map a live-shaped route to the shared `AdminApiCommandService` method and
list forbidden execution methods, but it must not become a route-local
executor, browser approval workflow, BFF execution authority, Coinbase call,
live switch, or order/exchange-state mutation path.
Live readiness precondition evidence is live-enablement evidence only. It may
normalize approval store, approval snapshot, admission audit, cap/guard,
reconciliation, adapter, intent, browser/BFF, and disabled live service
prerequisites, but it must be derived from existing read-only live-enablement
evidence. It must not call command admission with synthetic values, create a
new preflight endpoint, remove blockers, mark paths live eligible, authorize
browser/BFF execution, call Coinbase, or create route-local execution.
Live-enablement admission-audit trail evidence is read-only missing-audit
evidence. It may list required append-only backend admission facts and
sources, but it must not become audit storage, approval storage, browser
approval, command authority, Coinbase execution, or reconciliation proof.
Live-enablement cap/guard contract evidence is read-only missing-guard
evidence. It may list required backend cap/guard bindings and backend sources,
but it must not become guard execution, browser wallet or profitability
authority, browser approval, command authority, Coinbase execution, or
reconciliation proof.
Audit workbench reads expose route inventory, command audit, correlation,
module, and exchange evidence only. They must not become command replay, audit
mutation, Coinbase read, or frontend approval paths.
Futures/perpetual reads use `position_key` for position identity, separate
configured product scope from observed position scope, and must not import
spot wallet, no-shorting, cost-basis, or average-cost authority.
OIDC/JWT auth mode is implemented as a fail-closed verifier: readiness reports
required issuer, audience, and JWKS settings, and configured requests validate
RS256 JWTs before deriving actor/role evidence from claims.
`tools/run_admin_oidc_readiness_smoke.py --summary-only` proves missing-config
blocking, JWKS reachability, verified-claim session evidence, and no-live
Coinbase posture.

## Must Not Do

- Do not implement a second live trading path in FastAPI.
- Do not bypass existing guard, sizing, wallet, bridge, runtime, or inflight
  tracking behavior.
- Do not use `order_id` for internal tracking.
- Do not hand-maintain OpenAPI schemas that drift from backend models.
- Do not make frontend acknowledgement the only live-order approval gate.

## Required Tests

Run focused Admin API coverage for ordinary Admin API changes:

```powershell
pytest tests/regression/test_admin_api_contract.py -v --tb=short
```

Run the full backend regression gate before durable milestone closeout,
public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or explicit
user request:

```powershell
python tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

Focused tests must cover auth denial, RBAC denial, idempotent retry,
idempotency conflict, approval/live-disabled gate evidence, no live REST call
from HTTP command routes except the explicitly gated manual Spot order/cancel
path, cancel by `client_order_id`, audit creation, operator intent
audit/idempotency evidence, WebSocket/HTTP shared-service parity, typed
OpenAPI routes, and read-only route contracts. OIDC verifier changes must also
keep the no-live OIDC readiness smoke covered by
`tests/regression/test_admin_api_contract.py`.
