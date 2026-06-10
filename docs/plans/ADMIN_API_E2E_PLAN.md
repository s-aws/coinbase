# Admin API E2E Plan

This plan defines how the backend repository moves from proof-of-concept
dashboard surfaces to a professional enterprise API consumed by the separate
admin frontend repository at `C:\coinbase-frontend`.

## Non-Negotiable Direction

Do not add a second trading path. FastAPI handlers must not implement live
placement, cancellation, wallet checks, guard logic, or Coinbase calls beside
the existing engine paths. The migration must extract shared command services
first, then make the legacy WebSocket handlers and new HTTP handlers call the
same backend behavior.

## Target Architecture

Canonical request path:

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

## Planned Module Boundary

Implementation must introduce the service boundary before adding live HTTP
routes.

Target modules:

- `application/admin_api/command_service.py`: shared command entrypoints used by
  FastAPI routes and legacy WebSocket adapters.
- `application/admin_api/models.py`: Pydantic-compatible command DTOs and typed
  results, using enums from `core/enums.py`.
- `application/admin_api/idempotency.py`: durable idempotency lookup, conflict
  detection, replay handling, and `client_order_id` reuse.
- `application/admin_api/approval.py`: approval snapshot hashing and execution
  matching.
- `application/admin_api/audit.py`: durable accepted/rejected command audit
  writer.
- `api/v1/routes/*.py`: thin FastAPI route adapters only.
- `openapi/coinbase-admin-api.yaml`: generated schema artifact consumed by
  `C:\coinbase-frontend`.
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`: checked-in route/message
  inventory synchronized with `application/admin_api/route_inventory.py`.

Initial command service methods:

- `place_manual_order(command)`: extracted from the current dashboard
  `place_order` branch.
- `cancel_order_by_client_order_id(command)`: extracted from the current
  dashboard `cancel_order` branch and still calling the project
  `cancel_order(client_order_id)` wrapper.
- `place_hotpoint_test_order(command)`: extracted from the current dashboard
  hotpoint test placement branch if that workflow is exposed over HTTP.

The first extraction target is direct manual placement and cancellation because
those are the current live dashboard branches most likely to become enterprise
API endpoints.

## Initial Route And Message Inventory

Before implementation, create a checked-in inventory table with one row per
route or legacy message. Each row must include action class, permission,
idempotency requirement, approval requirement, cap policy, audit event, command
service method, and parity test.

Initial target inventory:

| Surface | Action class | Permission | Idempotency | Approval | Caps | Audit | Shared method | Parity test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/orders` | `live_exchange_place` | `order:create` | Required | Required | Required | Required | `place_manual_order` | HTTP vs `place_order` guard/result parity |
| `place_order` WebSocket | `live_exchange_place` | compatibility policy | Required for enterprise mode or explicitly compatibility-only | Required for enterprise mode or explicitly compatibility-only | Required | Required | `place_manual_order` | WebSocket vs HTTP guard/result parity |
| `POST /api/v1/orders/{client_order_id}/cancel` | `live_exchange_cancel` | `order:cancel` | Required | Not required unless policy adds approval | Required for rate/session controls | Required | `cancel_order_by_client_order_id` | HTTP vs `cancel_order` parity |
| `cancel_order` WebSocket | `live_exchange_cancel` | compatibility policy | Required for enterprise mode or explicitly compatibility-only | Not required unless policy adds approval | Required for rate/session controls | Required | `cancel_order_by_client_order_id` | WebSocket vs HTTP parity |
| read-only status routes | `read_only` | route-specific read permission | Not required | Not required | Not applicable | Optional read audit | read service method | no Coinbase REST placement |

If a legacy WebSocket live command is not passed through enterprise
idempotency/approval/cap gates, it must be explicitly labeled
compatibility-only, constrained to localhost/operator mode, and excluded from
new frontend product workflows.

## Phase 1 - Contract Boundary

- Add a versioned API namespace, initially `/api/v1`.
- Use FastAPI with Pydantic request/response models.
- Generate and snapshot OpenAPI under `openapi/coinbase-admin-api.yaml`.
- Use enums from `core/enums.py`; do not duplicate magic strings.
- Represent money, sizes, fees, and prices as `Decimal` or serialized strings,
  not floats.
- Keep order-facing identifiers centered on `client_order_id`.
- Make cancellation client-order-id keyed, for example:
  `POST /api/v1/orders/{client_order_id}/cancel`.
- Do not expose raw Coinbase pass-through payloads as the primary API contract.

Exit criteria:

- OpenAPI schema exists and is generated from backend models.
- Frontend can generate a TypeScript client without hand-maintained schema.
- Contract tests cover schema generation and representative typed responses.

## Phase 2 - Shared Command Services

- Extract live command handling out of `dashboard_server.py` into shared
  application services.
- Keep WebSocket handlers operational as compatibility adapters.
- Make new HTTP handlers call the same services.
- Preserve existing runtime admission, product capability, size validation,
  manual spot acknowledgement, action-condition guards, `track_inflight`, and
  `order_event_stream` submission evidence.
- Preserve the Coinbase cancellation exception: call the project wrapper
  `cancel_order(client_order_id)`.
- Start with the `place_order`, `cancel_order`, and hotpoint test placement
  branches before exposing equivalent HTTP routes.

Exit criteria:

- WebSocket and HTTP parity tests prove equivalent guard failures and command
  results.
- No new behavior exists only in `dashboard_server.py` or only in FastAPI.
- The route/message inventory is checked in and names the command service
  method for every live route or message.

## Phase 3 - Command Classification

Classify every API operation as one of:

- `read_only`
- `local_state_mutation`
- `live_exchange_place`
- `live_exchange_cancel`
- `admin_runtime`
- `audit`

Read-only status operations such as spot readiness, sweep status, campaign
status, cost-basis status, and direct order audit must remain read-only unless
renamed and redesigned as mutating commands.

Exit criteria:

- Route inventory documents action class, permission, audit behavior, and live
  exchange risk for every route.
- Tests prove read-only routes cannot submit Coinbase REST orders.

## Phase 4 - Auth And RBAC

- Define backend-enforced roles before implementation: viewer, operator,
  trader, admin, auditor, and emergency if needed.
- Map every route to permissions.
- Use backend-verifiable bearer/OIDC-style tokens or equivalent.
- Lock CORS to approved frontend origins.
- Keep Coinbase credentials exclusively on backend hosts.
- Treat frontend button hiding as usability only.

Exit criteria:

- Auth denial and RBAC denial regression tests exist for representative read
  and mutating routes.
- Mutating routes fail closed without authenticated actor identity.

## Phase 5 - Idempotency

- Require `Idempotency-Key` on live POST commands.
- Persist command key, actor, role, endpoint, payload hash, generated
  `client_order_id`, status, response, failure stage, and timestamps.
- Replays with the same key and same payload hash return the original result.
- Replays with the same key and different payload hash return conflict.
- Never mint a second `client_order_id` for a retried placement.

Exit criteria:

- Regression covers idempotent retry, conflict, and no duplicate Coinbase call.
- Audit history links idempotency records to command outcomes.

## Phase 6 - Approval Gates And Live Caps

- Live placement requires server-side approval, not only a frontend checkbox.
- Approval binds to product, side, size, price, order config, cap result, actor,
  generated `client_order_id`, and payload hash.
- Execution rejects when the submitted payload differs from the approved
  snapshot.
- Keep manual spot live acknowledgement, but do not treat it as sufficient
  enterprise approval.
- Enforce caps before Coinbase REST calls:
  - max notional per order
  - max orders per minute/session/day
  - max product exposure
  - max open live orders
  - role-specific limits
- Placement is impossible outside the required runtime state.
- Cancellations remain available while paused or draining when policy allows,
  but they are still RBAC-gated and inflight-tracked.

Exit criteria:

- Regression covers approval mismatch, cap rejection, runtime rejection, and no
  REST call when gates fail.
- Live Coinbase tests remain separately approved and must report notional.

## Phase 7 - Durable Audit

- Add durable command audit records as a new table or a clearly separated
  `order_event_stream` event family.
- Log successful and rejected commands.
- Capture actor, role, endpoint, request id, idempotency key, approval id,
  guard decisions, REST attempt/result, `client_order_id`, Coinbase `order_id`,
  failure stage, IP, user agent, and correlation id where applicable.

Exit criteria:

- Regression covers audit row creation for accepted and rejected commands.
- Operator responses include correlation id and audit reference.

## Phase 8 - Compatibility And Migration

- Freeze the current WebSocket message contract in docs before migration.
- Introduce HTTP endpoints behind shared services without removing POC
  dashboards.
- Add parity tests before switching frontend workflows.
- Mark legacy dashboard-only paths as compatibility surfaces once HTTP parity
  exists.

Exit criteria:

- Existing dashboard tests still pass.
- New HTTP tests pass.
- `pytest tests/regression/ -v --tb=short` passes.

## Phase 9 - Frontend Integration

- Frontend consumes only generated OpenAPI client and typed read-only stream
  contracts.
- Frontend displays backend guard decisions, not locally inferred safety.
- Frontend uses mocks for local development and real backend only by explicit
  environment configuration.

Exit criteria:

- Frontend quality gate passes.
- Backend regression gate passes for every backend API change.
- Browser tests prove live controls are disabled without backend authority.

## Phase 10 - Contextless Blind-Agent Gate

Before broadening order or campaign API behavior, run a fresh contextless agent
review against:

- `README.admin-api.md`
- this plan
- `genai_data/API_REFERENCE.md`
- `genai_data/ORDER_ID_HANDLING.md`
- `docs/agents/AGENT_ADMIN_API_CONTRACT.md`

The agent must explain:

- how a frontend request reaches existing backend order behavior
- where auth and RBAC are enforced
- how idempotency prevents duplicate `client_order_id` minting
- how approval snapshots and live caps prevent unsafe execution
- how cancel-by-`client_order_id` works
- which tests prove the path

If it cannot, fix docs or code organization before implementation continues.

## Required Regression Tests

When implementation starts, add focused tests for:

- OpenAPI schema generation
- auth denial
- RBAC denial
- route command classification
- approval mismatch
- idempotent retry
- idempotency conflict
- live cap rejection
- no REST call on guard failure
- cancel by `client_order_id`
- audit row creation for accepted and rejected commands
- WebSocket/HTTP parity

The full backend gate remains:

```powershell
pytest tests/regression/ -v --tb=short
```
