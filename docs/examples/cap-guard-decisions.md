# Cap/Guard Decision Record Examples

These examples cover backend-owned cap/guard decision evidence. They are
no-live examples and do not call Coinbase.

## List Decisions

```http
GET /api/v1/admin/cap-guard/decisions?decision_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

## Read One Decision

```http
GET /api/v1/admin/cap-guard/decisions/cap-guard-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

## Record A Passed Decision

```http
POST /api/v1/admin/cap-guard/decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: cap-guard-record-001
X-Correlation-Id: corr-cap-guard-001
X-Operator-Intent: record_manual_order_cap_guard
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "admin-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "admission_audit_id": "audit-admission-001",
  "allowed": true,
  "status": "passed",
  "cap_policy_ref": "submitted_notional_cap:3.10",
  "guard_policy_ref": "action_condition_guard:manual_order",
  "product_scope": "BTC-USDC",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend cap and guard inputs accepted the route-bound envelope"
}
```

## Fail-Closed Cases

- `allowed=true` with `status=blocked` is rejected.
- `allowed=false` with `status=passed` is rejected.
- Route, permission, module, action class, or service-method drift is
  rejected against `ADMIN_API_ROUTE_INVENTORY`.
- Duplicate decision ids are rejected.
- Browser-computed guard, wallet, inventory, profitability, or margin evidence
  is not authoritative.
