# Cap/Guard Decision Records

Cap/guard decision records are backend-owned Admin API evidence for command
admission. They persist whether a route-bound command envelope passed or
failed the configured cap and guard checks before any future live adapter may
consider execution.

Use this feature when an operator or backend workflow needs durable evidence
that a command envelope was evaluated against backend cap/guard policy. Do not
use it as a browser guard evaluator, wallet checker, futures margin model, or
spot profitability calculator.

## Routes

- `GET /api/v1/admin/cap-guard/decisions`
- `GET /api/v1/admin/cap-guard/decisions/{decision_id}`
- `POST /api/v1/admin/cap-guard/decisions`

Read routes require `cap_guard:read`. Recording requires `cap_guard:record`,
idempotency, correlation id, operator intent, actor identity, RBAC, and audit
evidence.

## Record Binding

Each record binds:

- route, method, module id, action class, required permission, and backend
  service method
- identity key/value such as `client_order_id`, `stealth_order_id`,
  `campaign_id`, or `position_key`
- actor id, operator intent, command idempotency key, and payload hash
- approval snapshot id, approval cap/guard decision ref, and admission audit id
- cap policy ref, guard policy ref, product scope, submitted notional cap, and
  executed notional cap

Only `allowed=true` with `status=passed` is resolver-eligible for exact
backend admission matching. Blocked and warning records remain durable
fail-closed evidence.

## Boundaries

- No Coinbase order is submitted, cancelled, or modified by these routes.
- No browser or BFF code may evaluate wallet, margin, profitability,
  inventory, account-limit, or product-domain guard rules.
- Spot-specific rules such as no short selling, USDC scope, cost basis, and
  average-cost evidence stay route-specific and must not become futures or
  platform defaults.
- Futures/perpetual guard records require futures-specific position, margin,
  collateral, liquidation, reduce-only, close-only, and funding semantics
  before command enablement.

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Cap/Guard Decision Examples](docs/examples/cap-guard-decisions.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](docs/plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
