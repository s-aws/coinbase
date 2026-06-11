# Guard/Risk Policy Examples

These examples read backend guard/risk evidence. They do not submit orders,
cancel orders, fetch Coinbase wallets, or approve live execution.

## Read Current Policy

```http
GET /api/v1/admin/guard-risk-policy
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8787/api/v1/admin/guard-risk-policy `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

Expected posture:

```json
{
  "type": "admin_guard_risk_policy",
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false,
  "live_execution_gate": {
    "name": "live_execution_gate",
    "status": "fail_closed",
    "source": "live_execution_gate"
  }
}
```

## Read Product Capability Evidence

Pass `product_id` when a UI needs backend-owned capability decisions for a
specific product:

```http
GET /api/v1/admin/guard-risk-policy?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

The response includes `product_capability_decisions`. These are evidence only;
they are not enough to submit a live Coinbase order.

## What Not To Build

Do not use this route as a browser preflight approval endpoint. A future
command UI must still submit intent through the Admin API command route, where
the backend command service enforces auth, RBAC, idempotency, approval, caps,
guards, audit, and the actual live-disabled or live-enabled execution boundary.

Do not call Coinbase wallet APIs from this route. Wallet availability remains a
backend command-boundary guard. The route should continue to report
`live_coinbase_read_ran=false`.
