# Admission Audit Examples

These examples show backend-owned admission audit records. They are local
state and audit evidence only; they do not submit, cancel, reconcile, or call
Coinbase.

## List Admission Audits

```http
GET /api/v1/admin/admission-audits?admission_status=blocked&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

## Read One Admission Audit

```http
GET /api/v1/admin/admission-audits/audit-admission-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

## Record Admission Audit Proof

```http
POST /api/v1/admin/admission-audits
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: admission-audit-record-001
X-Correlation-Id: corr-admission-audit-001
X-Operator-Intent: record_manual_order_admission_audit
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
  "actor_id": "operator-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_snapshot_approved_by_actor_id": "approver-001",
  "approval_snapshot_requested_by_actor_id": "operator-001",
  "approval_snapshot_expires_at": "2026-06-12T19:00:00+00:00",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "allowed": false,
  "status": "blocked",
  "reason": "backend admission audit proof recorded before cap/guard and reconciliation proofs"
}
```

The response includes `admission_audit.admission_audit_id`. That id can be
linked by later cap/guard and reconciliation proof records. Reusing the same
`Idempotency-Key` with the same payload replays the same response; reusing it
with a changed payload returns conflict.

The writer rejects records that claim `allowed=true` or `status=passed`,
because the audit record is proof that admission was logged, not proof that
live execution is authorized.
