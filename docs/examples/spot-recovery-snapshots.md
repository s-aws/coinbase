# Spot Recovery Snapshot Examples

These examples show the backend-owned Spot recovery exchange-state snapshot
record contract. The route records local evidence only. It does not read
Coinbase, submit orders, cancel orders, mutate order/exchange state, or execute
reconciliation.

## Record A Snapshot Reference

```http
POST /api/v1/spot/recovery/exchange-state-snapshots
Authorization: Bearer <admin-or-trader-token>
Idempotency-Key: spot-recovery-snapshot-demo
X-Correlation-ID: spot-recovery-snapshot-demo
X-Operator-Intent: record spot recovery exchange-state snapshot evidence
Content-Type: application/json

{
  "client_order_id": "00000000-0000-0000-0000-000000000001",
  "product_id": "BTC-USDC",
  "exchange_state_snapshot_id": "snapshot-0001",
  "source_timestamp": "2026-06-13T12:00:00Z",
  "snapshot_source": "manual_import",
  "snapshot_evidence_ref": "operator-reviewed-local-export-0001",
  "reconciliation_plan_id": "reconciliation-plan-0001",
  "reconciliation_proof_id": "reconciliation-proof-0001",
  "completion_id": "completion-0001",
  "approval_snapshot_id": "approval-0001",
  "admission_audit_id": "admission-audit-0001",
  "cap_guard_decision_id": "cap-guard-0001",
  "dry_run": true,
  "operator_reason": "Persist local snapshot evidence for recovery review.",
  "manual_live_acknowledgement": false
}
```

Accepted records return an `accepted` Admin API command response with a
`spot_recovery_exchange_state_snapshot` payload. A request containing a
top-level `order_id` is invalid because internal recovery identity is
`client_order_id`.

## Read Snapshot Evidence Back

```http
GET /api/v1/spot/recovery/reconciliation-proof?client_order_id=00000000-0000-0000-0000-000000000001
Authorization: Bearer <admin-or-trader-token>
```

The response includes `persisted_snapshot_count`, `persisted_snapshots`,
`latest_exchange_state_snapshot_id`, and reconciliation execution-boundary
rows that continue to report `coinbase_live_read_disabled` until a later
approved phase adds live Coinbase read authority and a reconciliation executor.
