# Historical Architecture: Enterprise Admin API

> Archived on 2026-10-09. These modules are absent from the current checkout.
> Use [the current architecture](../ARCHITECTURE.md). This is not an active
> runtime, authorization, or deployment contract.

## Enterprise Admin API

The enterprise Admin API is the contract surface for the separate frontend
repository at `C:\coinbase-frontend`. HTTP mutating routes are no-live by
default. Manual Spot order and cancel are the only current route-scoped
configured exceptions, and they may reach the shared backend live branch only
after exact backend auth/RBAC, idempotency, approval, admission-audit,
cap/guard, reconciliation, manual acknowledgement, live-service, REST-client,
and event-stream gates pass. Other mutating HTTP routes remain
live-disabled/fail-closed.

Current modules:
- `api/v1/app.py`: FastAPI app factory.
- `api/v1/routes/admin.py`: read-only backend association, health,
  session/RBAC, capability, guard/risk policy, audit workbench, gate, and
  frontend-fixture routes.
- `api/v1/routes/orders.py`: thin route adapters for `POST /api/v1/orders`,
  `GET /api/v1/orders`, `GET /api/v1/orders/{client_order_id}`,
  `POST /api/v1/orders/{client_order_id}/cancel`, and
  `POST /api/v1/spot/campaign/executions`.
- `api/v1/routes/spot.py`: read-only spot operator routes.
- `api/v1/routes/stealth.py`: read-only stealth lifecycle evidence routes.
- `api/v1/routes/movement_repricing.py`: read-only movement/repricing
  evidence routes over `order_moves`, `stealth_order_moves`, stealth repricing
  state, and runtime-safe claim snapshots.
- `api/v1/routes/futures.py`: read-only futures/perpetual account, risk, and
  position evidence routes keyed by backend `position_key`.
- `application/admin_api/command_service.py`: shared command service used by
  HTTP routes and legacy dashboard compatibility adapters.
- `application/admin_api/auth.py`: fail-closed bearer-token/RBAC bootstrap.
- `application/admin_api/idempotency.py`: durable JSONL idempotency store and
  payload-hash contract.
- `application/admin_api/approval.py`: approval snapshot contract.
- `application/admin_api/audit.py`: durable JSONL command audit store.
- `application/admin_api/read_service.py`: read-only operator status service.
- `application/admin_api/route_inventory.py`: route/message inventory.
- `openapi/coinbase-admin-api.yaml`: generated backend-owned OpenAPI artifact.

Current behavior:
- Admin API mutating routes authenticate, authorize, evaluate idempotency, write
  audit records, and fail closed unless their route has explicit backend
  live-service admission.
- Manual Spot order creation and cancel-by-`client_order_id` are explicit
  configured live-service exceptions. They still require exact backend
  auth/RBAC, idempotency, approval, admission-audit, cap/guard,
  reconciliation, manual acknowledgement, live-service, REST-client, and
  event-stream evidence before calling the shared command-service live branch.
- Other mutating HTTP routes return live-disabled or not-implemented evidence
  and do not submit Coinbase orders, cancel Coinbase orders, or mutate live
  exchange state.
- Admin API OpenAPI includes typed `200` accepted/replayed command response
  schemas for explicit live-enabled states and typed blocked response contracts
  for live-disabled states.
- Legacy dashboard `place_order` and `cancel_order` WebSocket messages delegate
  to `AdminApiCommandService` as compatibility adapters.
- Order read routes are local-evidence reads keyed by `client_order_id`.
  Exchange-native ids are exposed only as `exchange_order_id` evidence.
- Stealth read routes are local-evidence reads keyed by `stealth_order_id`.
  Active placement client ids and exchange-native ids are exposed as evidence
  only. Stealth cancel is modeled as a live-disabled Admin API command keyed
  by `stealth_order_id`.
- Movement/repricing read routes expose durable parent move history, revealed
  stealth move audit rows, anchor repricing state, replacement-slot evidence,
  and runtime mutation claim state when safely observable. Movement reprice is
  modeled as a live-disabled Admin API command keyed by `stealth_order_id`;
  stealth move has a live-disabled Admin API draft keyed by `stealth_order_id`;
  live move execution, premark, and move-revealed command authority is not
  modeled.
- Futures/perpetual read routes expose account, margin, collateral, funding,
  liquidation, close/reduce-side, position, and P/L evidence. `position_key`
  is the position read identity. Configured product scope and observed
  position scope are separate. Close/reduce sides are backend-derived from
  observed position side and are not exchange-observed order flags.
- Guard/risk policy reads expose existing backend action-condition policy,
  configured cap rules, live execution gate posture, product capability
  policy, profitability-validator posture, authority sources, and rejection
  categories as evidence only. They do not fetch Coinbase wallets and do not
  approve browser live execution.
- Audit workbench reads expose route inventory, command audit events,
  correlation ids, request ids, audit ids, module summaries, and exchange
  evidence as a read-only cross-module workbench. They do not mutate audit
  history, fetch Coinbase, replay commands, or approve browser live execution.
- Admin bootstrap, health, session/RBAC, capabilities, release/recovery,
  fill-ledger health, and frontend fixture routes are read-only backend
  association surfaces for `C:\coinbase-frontend`.
- Admin API responses include observability headers and structured error
  payloads for auth, RBAC, and validation failures.
- Read-only spot routes expose readiness, sweep status, sweep P/L, cost-basis
  status, campaign status, and direct-order audit; they are auth/RBAC-gated and
  document `401`/`403` in the generated OpenAPI contract.

Future live behavior must use one path:

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

Legacy dashboard WebSocket live commands that do not pass through equivalent
enterprise gates remain explicitly compatibility-only and excluded from new
frontend workflows.

