# Audit Workbench Examples

These examples read backend audit evidence. They do not submit orders, cancel
orders, move or reprice orders, read Coinbase, mutate audit history, or approve
live execution.

## Read Recent Cross-Module Evidence

```http
GET /api/v1/admin/audit-workbench?limit=25&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8787/api/v1/admin/audit-workbench?limit=25&offset=0" `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "auditor"
  }
```

Expected posture:

```json
{
  "type": "admin_audit_workbench",
  "read_only": true,
  "command_routes_mode": "evidence_only",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false
}
```

Command audit rows may include persisted admission evidence:

```json
{
  "module": "orders",
  "route": "/api/v1/orders/{client_order_id}/cancel",
  "client_order_id": "client-order-001",
  "admission_decision": {
    "status": "blocked",
    "route": "/api/v1/orders/{client_order_id}/cancel",
    "identity_key": "client_order_id",
    "blockers": ["admission_audit_missing", "cap_guard_missing"],
    "live_exchange_submitted": false
  }
}
```

This evidence is read-only. It does not mean the route is live-enabled, and it
does not replace approval, cap, guard, exchange, or reconciliation evidence.

## Read One Order's Audit Evidence

Use `client_order_id` for order-linked evidence:

```http
GET /api/v1/admin/audit-workbench?module=orders&client_order_id=client-order-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

If the backend knows an exchange-native id, the response may include
`exchange_order_id` with `exchange_order_id_evidence_only=true`. Do not use
that exchange id as a frontend tracking key or cancellation key.

## Read Correlation Evidence

Use `correlation_id` or `audit_id` when linking from frontend audit anchors:

```http
GET /api/v1/admin/audit-workbench?correlation_id=corr-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

## What Not To Build

Do not use this route as a command replay, cancel, movement, repricing, or
approval endpoint. A future command UI must submit intent through the relevant
Admin API command route, where the backend command service enforces auth,
RBAC, idempotency, approval, caps, guards, audit, and the actual live-disabled
or live-enabled execution boundary.
