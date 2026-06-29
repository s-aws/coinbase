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
- source inventory rows for backend evidence stores and read-service adapters
- backend-owned correlation scope categories for command attempts, approvals,
  admission audits, cap/guard/wallet decisions, exchange intent, fills, and
  reconciliation status
- command timelines that project command-audit events into request, approval,
  admission, cap/guard, live-intent, exchange-evidence, and result stages
- read and command route counts
- durable command audit events when available
- persisted command admission decisions on command audit events when available,
  including backend status, route, identity key, and blockers
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
- `correlation_scope` describes what evidence the operator should expect. It
  is not an execution plan and carries no-browser, no-BFF-execution,
  no-reconciliation-execution, and no-state-mutation flags.
- `source_inventory` describes where evidence can come from. It is not a
  fallback command engine and carries the same no-authority posture plus
  `live_coinbase_orders_ran=false` and `live_coinbase_read_ran=false`.
- `command_timelines` are derived from returned command-audit events. They
  are read-only operator trace projections, not replay instructions.
- Exchange `order_id` values are evidence only. They are not internal tracking
  ids or cancellation keys.
- Command acceptance, cancellation, movement, repricing, guard evaluation, and
  live approval remain in their real backend command paths.
- Persisted admission decisions are evidence only. They prove what the backend
  decided before a command could reach Coinbase; they do not approve live
  execution or replace cap, guard, exchange, or reconciliation checks.

## Examples

See [Audit Workbench Examples](docs/examples/audit-workbench.md).

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin API Contract Agent](docs/agents/AGENT_ADMIN_API_CONTRACT.md)
