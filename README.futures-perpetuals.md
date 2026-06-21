# Futures/Perpetuals Admin Reads

This feature exposes read-only futures and perpetual account, risk, and
position evidence through the enterprise Admin API. It is a separate module,
not a Spot variant.

## When To Use

Use these routes when an operator or admin frontend needs to inspect futures
or perpetual state without creating, closing, moving, or cancelling exchange
orders.

Current routes:

- `GET /api/v1/futures/command-suite`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`

All routes require Admin API auth/RBAC and `analytics:read`. They return
`read_only=true`, `command_routes_mode="not_modeled"`, and
`live_coinbase_orders_ran=false`.

## Key Concepts

- `position_key` is the read identity for positions. It is not
  `client_order_id`, and it is not Coinbase `order_id`.
- `configured_product_scope` lists futures/perpetual products known from
  backend metadata.
- `observed_position_scope` lists products with observed runtime position
  evidence.
- Collateral, margin, funding, liquidation, reduce/close-side, and P/L values
  are evidence cells with explicit `status` and `source`.
- Close/reduce order sides are backend-derived from observed position side.
  They are not exchange-observed reduce-only or close-only order flags.
- `GET /api/v1/futures/command-suite` reports blocked M57 command-contract
  evidence for placement, close/reduce, cancel, and reconciliation. It does
  not register futures command routes, create command drafts, call Coinbase,
  mutate state, or grant browser/BFF authority.
- The command-suite route also exposes request-field contract metadata for
  each planned command family. These fields are blocked backend contract
  evidence only; they are not accepted payloads and do not create executable
  routes.
- Spot wallet, no-shorting, USDC quote scope, average/cost-basis, and
  inventory-lot assumptions are explicitly forbidden as futures/perpetual
  command authority.

## Sources

The read service prefers runtime orderbook position snapshots. Dashboard
engine-state positions are a labeled fallback. Coinbase REST futures reads are
not called by default from these Admin API routes.

Collateral and liquidation evidence remains `unavailable` unless the runtime
retains a futures balance summary snapshot. Funding-rate evidence is
`not_modeled` in this milestone.

## Safety Constraints

- Do not import Spot wallet, no-shorting, cost-basis, known-profitable
  inventory, or average-cost rules into this module.
- Do not add futures command routes until backend guard/risk policy evidence,
  command contracts, approval/cap/audit gates, and contextless review are in
  place.
- Do not treat command-suite request fields as browser-side form authority.
  The backend must own validation, audit, idempotency, risk checks, and future
  service mapping before any command can become executable.
- Do not use browser code to calculate margin, liquidation, funding, close
  eligibility, or P/L authority.
- Do not treat exchange-native ids as futures position identity.

## Examples

See [Futures/Perpetuals Examples](docs/examples/futures-perpetuals.md).

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Documentation Index](docs/README.md)
