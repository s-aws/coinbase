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

Current HTTP command routes are authenticated, authorized, idempotent, audited,
and live-disabled. They return typed `501` `not_implemented` responses until
live HTTP approval, guard, cap, and audit gates are complete. The generated
OpenAPI schema also includes typed `200` accepted/replayed response contracts
for the future live-enabled state.

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
compatibility, and a live-disabled spot campaign execution contract.

Read-only Admin API routes currently cover backend bootstrap, health,
session/RBAC evidence, capabilities, guard/risk policy evidence,
release/recovery gates, fill-ledger health, frontend fixtures, order
list/detail, stealth lifecycle list/detail, movement/repricing evidence,
futures/perpetual account and position evidence, spot readiness, sweep status,
sweep P/L, cost-basis status, campaign status, and direct order audit.
Guard/risk policy reads expose existing backend policy and authority sources as
evidence only. They must not become browser preflight approval or a second
guard engine.
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

```powershell
pytest tests/regression/ -v --tb=short
```

Focused Admin API tests live in:

```powershell
pytest tests/regression/test_admin_api_contract.py -v --tb=short
```

Focused tests must cover auth denial, RBAC denial, idempotent retry,
idempotency conflict, approval/live-disabled gate evidence, no live REST call
from HTTP command routes, cancel by `client_order_id`, audit creation,
WebSocket/HTTP shared-service parity, typed OpenAPI routes, and read-only route
contracts. OIDC verifier changes must also keep the no-live OIDC readiness
smoke covered by `tests/regression/test_admin_api_contract.py`.
