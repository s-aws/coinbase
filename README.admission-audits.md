# Admission Audit Records

Admission audit records are backend-owned Admin API evidence for command
admission. They append an immutable audit row that binds a future live-shaped
command envelope to approval, expected cap/guard, expected reconciliation, and
disabled live-intent evidence before any adapter may execute.

Use this feature when a backend workflow needs durable proof that a command
attempt was recorded against the exact route, identity, payload hash,
idempotency key, actor, and operator intent. Do not use it as a browser audit
store, approval engine, guard evaluator, reconciliation runner, or Coinbase
execution path.

## Routes

- `GET /api/v1/admin/admission-audits`
- `GET /api/v1/admin/admission-audits/{admission_audit_id}`
- `POST /api/v1/admin/admission-audits`

Read routes require `admission_audit:read`. Recording requires
`admission_audit:record`, idempotency, correlation id, operator intent, actor
identity, RBAC, and the existing append-only Admin API audit store.

## Record Binding

Each record binds:

- route, method, module id, action class, required permission, and backend
  service method
- identity key/value such as `client_order_id`, `stealth_order_id`,
  `campaign_id`, or `position_key`
- actor id, operator intent, command idempotency key, and payload hash
- approval snapshot id and optional approval actor/expiry evidence
- expected cap/guard decision ref from the approval snapshot
- expected reconciliation plan ref from the approval snapshot
- disabled live execution intent ref for the shared command service method

The writer intentionally rejects `allowed=true` or `status=passed`. An
admission audit record is resolver-eligible for exact proof matching, but it
does not authorize live execution by itself.

## Boundaries

- No Coinbase order is submitted, cancelled, or modified by these routes.
- No browser or BFF code may write audit history as authority.
- The route does not evaluate wallet, margin, profitability, inventory,
  account-limit, spot-only, futures, or stealth lifecycle rules.
- Cap/guard and reconciliation records remain separate backend-owned proofs.
- Spot-specific rules such as no short selling, USDC scope, cost basis, and
  average-cost evidence stay route-specific and must not become platform audit
  defaults.

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Admission Audit Examples](docs/examples/admission-audits.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](docs/plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
