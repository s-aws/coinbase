# Audit Workbench Admin Reads

Audit workbench reads expose backend-owned cross-module evidence for the
enterprise Admin API. They are display evidence only. They do not place orders,
cancel orders, move or reprice orders, mutate audit history, read Coinbase, or
approve live execution.

## Route

- `GET /api/v1/admin/audit-workbench`

Optional query:

- `module`: scopes evidence to a backend module such as `orders`, `stealth`,
  `movement_repricing`, `futures_perpetuals`, `guard_risk`, or `campaigns`.
- `product_id`: scopes product-linked evidence.
- `client_order_id`: scopes order-linked evidence.
- `correlation_id`: scopes correlation-linked evidence.
- `audit_id`: scopes durable audit-linked evidence.
- `limit`: pagination limit.
- `offset`: pagination offset.

The route is authenticated and RBAC-gated with `audit:read`.

## What It Shows

- module route summaries
- read and command route counts
- durable command audit events when available
- order, stealth, movement/repricing, futures/perpetual, and guard/risk
  evidence where backend read models already expose it
- campaign route summaries and command-audit rows; spot campaign-status
  aggregation remains in the spot campaign read route
- request ids, correlation ids, audit ids, actor ids, and permissions
- module-specific identity: `client_order_id`, `stealth_order_id`, or
  `position_key`
- exchange-native ids only as exchange evidence

## Safety Rules

- The route is read-only and reports `live_coinbase_orders_ran=false`.
- The route reports `live_coinbase_read_ran=false`; it does not fetch Coinbase
  account, wallet, order, or fill data.
- Command routes are represented as `command_routes_mode="evidence_only"`.
- Exchange `order_id` values are evidence only. They are not internal tracking
  ids or cancellation keys.
- Command acceptance, cancellation, movement, repricing, guard evaluation, and
  live approval remain in their real backend command paths.

## Examples

See [Audit Workbench Examples](docs/examples/audit-workbench.md).

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin API Contract Agent](docs/agents/AGENT_ADMIN_API_CONTRACT.md)
