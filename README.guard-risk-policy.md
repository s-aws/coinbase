# Guard/Risk Policy Admin Reads

Guard/risk policy reads expose backend-owned admission and risk posture for the
enterprise Admin API. They are display evidence only. They do not place orders,
cancel orders, fetch Coinbase wallets, or decide that a browser action may run
live.

## Route

- `GET /api/v1/admin/guard-risk-policy`

Optional query:

- `product_id`: when supplied, the backend includes product capability
  decisions for that product.

The route is authenticated and RBAC-gated with `analytics:read`.

## What It Shows

- configured action-condition guard policy
- configured limit/cap rules
- current HTTP live-execution gate posture
- product capability policy and optional per-product decisions
- profitability-validator posture and known contract gaps
- wallet, planned-budget, spot inventory, and position authority sources
- backend rejection categories such as `wallet_available`,
  `planned_budget_available`, `known_inventory_available`,
  `max_notional`, and `max_base_size`

## Safety Rules

- The route is read-only and reports `live_coinbase_orders_ran=false`.
- The route reports `live_coinbase_read_ran=false`; it does not fetch Coinbase
  wallet balances.
- Command acceptance/rejection remains in the real command path.
- The browser may render evidence but must not calculate wallet, margin,
  profitability, cap, approval, or live execution authority.
- Spot wallet, average-cost, cost-basis, no-shorting, and lot authority remain
  spot-specific. Futures/perpetuals use their own position and risk evidence.

## Examples

See [Guard/Risk Policy Examples](docs/examples/guard-risk-policy.md).

## Related Docs

- [Admin API](README.admin-api.md)
- [Action Condition Guards](README.action-condition-guards.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
