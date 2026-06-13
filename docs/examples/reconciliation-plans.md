# Reconciliation Plan Record Examples

These examples cover backend-owned reconciliation plan evidence. They are
local state and resolver evidence only; they do not submit, cancel, reconcile,
mutate order state, or call Coinbase.

## List Plans

```http
GET /api/v1/admin/reconciliation/plans?plan_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

## Read One Plan

```http
GET /api/v1/admin/reconciliation/plans/reconciliation-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

## Record A Passed Plan

```http
POST /api/v1/admin/reconciliation/plans
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: reconciliation-plan-record-001
X-Correlation-Id: corr-reconciliation-plan-001
X-Operator-Intent: record_manual_order_reconciliation_plan
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
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "admission_audit_id": "audit-admission-001",
  "cap_guard_decision_id": "cap-guard-001",
  "allowed": true,
  "status": "passed",
  "reconciliation_policy_ref": "post_submit_reconciliation:manual_order",
  "product_scope": "BTC-USDC",
  "exchange_submission_required": true,
  "post_submit_reconciliation_required": true,
  "retained_inventory_required": true,
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend reconciliation plan accepted the route-bound envelope"
}
```

The response includes `plan.plan_id`. A resolver-eligible plan removes only
the `reconciliation_plan_missing` blocker from live-disabled command admission
evidence. It does not authorize live execution by itself.

## Fail-Closed Cases

- `allowed=true` with `status=blocked` is rejected.
- `allowed=false` with `status=passed` is rejected.
- Route, permission, module, action class, or service-method drift is
  rejected against `ADMIN_API_ROUTE_INVENTORY`.
- Read-only and local-state routes are rejected; plans apply only to
  live-shaped command routes.
- Duplicate plan ids are rejected.
- Browser/BFF-created reconciliation proof, exchange-state mutation, or order
  state mutation is not authoritative.
