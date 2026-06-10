# Admin API Contract Agent

## Owns

- Future `api/**` FastAPI route modules
- Future `application/admin_api/**` shared command service adapters
- Future `openapi/**` generated schema artifacts
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

Legacy dashboard compatibility path:

```text
dashboard WebSocket message
-> compatibility adapter
-> compatibility idempotency/approval/cap treatment for live commands
-> shared command service
-> existing domain/bridge/exchange path
-> dashboard response/state update
```

## Planned Shared Service Boundary

Initial implementation should introduce:

- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/idempotency.py`
- `application/admin_api/approval.py`
- `application/admin_api/audit.py`
- `api/v1/routes/*.py`
- `openapi/coinbase-admin-api.yaml`
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`

Initial shared command service methods should cover manual placement,
cancel-by-`client_order_id`, and hotpoint test placement before HTTP live routes
are exposed.

## Must Not Do

- Do not implement a second live trading path in FastAPI.
- Do not bypass existing guard, sizing, wallet, bridge, runtime, or inflight
  tracking behavior.
- Do not use `order_id` for internal tracking.
- Do not hand-maintain OpenAPI schemas that drift from backend models.
- Do not make frontend acknowledgement the only live-order approval gate.

## Required Tests Once Implementation Starts

```powershell
pytest tests/regression/ -v --tb=short
```

Focused tests must cover auth denial, RBAC denial, idempotent retry,
idempotency conflict, approval mismatch, cap rejection, no REST call on guard
failure, cancel by `client_order_id`, audit creation, and WebSocket/HTTP
parity.
