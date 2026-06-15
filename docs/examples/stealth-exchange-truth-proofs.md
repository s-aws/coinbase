# Stealth Active-Placement Exchange-Truth Examples

These examples show the backend-owned stealth active-placement exchange-truth
snapshot and proof record contracts. The routes record local evidence only.
They do not read Coinbase, submit orders, cancel orders, cancel/replace active
placements, mutate order/exchange/lifecycle state, verify exchange truth, or
execute reconciliation.

## Record A Snapshot Reference

```http
POST /api/v1/stealth/orders/stealth-order-0001/active-placement/exchange-truth-snapshots
Authorization: Bearer <admin-token>
Idempotency-Key: stealth-exchange-truth-snapshot-demo
X-Correlation-ID: stealth-exchange-truth-snapshot-demo
X-Operator-Intent: record stealth active-placement snapshot evidence
Content-Type: application/json

{
  "active_placement_client_order_id": "placement-client-0001",
  "active_exchange_order_id": "coinbase-order-0001",
  "product_id": "BTC-USDC",
  "source_timestamp": "2026-06-13T12:00:00Z",
  "evidence_source": "manual_import",
  "snapshot_evidence_ref": "operator-reviewed-active-placement-export-0001",
  "reconciliation_plan_id": "reconciliation-plan-0001",
  "approval_snapshot_id": "approval-0001",
  "admission_audit_id": "admission-audit-0001",
  "cap_guard_decision_id": "cap-guard-0001",
  "exchange_truth_snapshot_id": "stealth-exchange-truth-snapshot-0001",
  "dry_run": true,
  "operator_reason": "Persist local active-placement snapshot evidence for review.",
  "manual_live_acknowledgement": false
}
```

Accepted records return an `accepted` Admin API command response with a
`stealth_active_placement_exchange_truth_snapshot` payload. A request containing
top-level `order_id`, `client_order_id`, or another command identity is invalid
because the route identity is the path `stealth_order_id`.

## Record A Proof Reference

```http
POST /api/v1/stealth/orders/stealth-order-0001/active-placement/exchange-truth-proofs
Authorization: Bearer <admin-token>
Idempotency-Key: stealth-exchange-truth-proof-demo
X-Correlation-ID: stealth-exchange-truth-proof-demo
X-Operator-Intent: record stealth active-placement proof evidence
Content-Type: application/json

{
  "exchange_truth_snapshot_id": "stealth-exchange-truth-snapshot-0001",
  "active_placement_client_order_id": "placement-client-0001",
  "active_exchange_order_id": "coinbase-order-0001",
  "exchange_truth_evidence_ref": "operator-reviewed-active-placement-proof-0001",
  "reconciliation_plan_id": "reconciliation-plan-0001",
  "approval_snapshot_id": "approval-0001",
  "admission_audit_id": "admission-audit-0001",
  "cap_guard_decision_id": "cap-guard-0001",
  "exchange_truth_proof_id": "stealth-exchange-truth-proof-0001",
  "dry_run": true,
  "operator_reason": "Persist local active-placement proof evidence for review.",
  "manual_live_acknowledgement": false
}
```

Proof records are accepted only when the referenced snapshot exists for the
same `stealth_order_id` and the Admin API admission evidence matches the proof
route.

## Read Evidence Back

```http
GET /api/v1/stealth/orders/stealth-order-0001/active-placement/exchange-truth-proof
Authorization: Bearer <viewer-token>
```

The response includes `persisted_snapshot_count`, `persisted_snapshots`,
`persisted_proof_count`, `persisted_proofs`,
`latest_exchange_truth_snapshot_id`, and `latest_exchange_truth_proof_id`.
It continues to report `exchange_truth_verified=false` and no-live Coinbase
flags until a later approved phase adds backend-owned Coinbase read authority
and a reconciliation executor.
