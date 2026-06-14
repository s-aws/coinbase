# Reconciliation Plan Records

Reconciliation plan records are backend-owned Admin API evidence for command
admission. They persist the exact post-submit reconciliation policy expected
for a future live-shaped command before any live adapter may consider
execution.

Use this feature when an operator or backend workflow needs durable evidence
that a command envelope has an exact route-bound reconciliation plan. Do not
use it as a browser reconciliation runner, BFF proof writer, exchange-state
repair tool, order-state mutation path, or Coinbase execution path.

## Routes

- `GET /api/v1/admin/reconciliation/plans`
- `GET /api/v1/admin/reconciliation/plans/{plan_id}`
- `POST /api/v1/admin/reconciliation/plans`

Read routes require `reconciliation:read`. Recording requires
`reconciliation:record`, idempotency, correlation id, operator intent, actor
identity, RBAC, and audit evidence.

## Record Binding

Each record binds:

- route, method, module id, action class, required permission, and backend
  service method
- identity key/value such as `client_order_id`, `stealth_order_id`,
  `campaign_id`, or `position_key`
- actor id, operator intent, command idempotency key, and payload hash
- approval snapshot id, approval reconciliation plan ref, admission audit id,
  and cap/guard decision id
- reconciliation policy ref, product scope, exchange-submission requirement,
  post-submit reconciliation requirement, retained-inventory requirement, and
  submitted/executed notional caps

Only `allowed=true` with `status=passed` is resolver-eligible for exact
backend admission matching. Blocked and warning records remain durable
fail-closed evidence.

## Boundaries

- No Coinbase order is submitted, cancelled, moved, or modified by these
  routes.
- No reconciliation execution runs from these routes.
- No browser or BFF code may mark exchange state reconciled, create
  reconciliation proof, or mutate order state.
- Plans may be recorded for live-shaped command routes in
  `ADMIN_API_ROUTE_INVENTORY`. The local-state mutation exceptions are Spot
  recovery proof and snapshot recording with `spot_recovery:record`; other
  read-only and local-state routes are rejected.
- Spot-specific reconciliation details such as USDC scope, retained inventory,
  fill-ledger checks, cost basis, and no-shorting evidence stay route-specific
  and must not become futures, stealth, movement/repricing, or platform
  defaults.

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Reconciliation Plan Examples](docs/examples/reconciliation-plans.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](docs/plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
