# Stealth Coinbase Exchange Policy Examples

Read Coinbase exchange policy evidence for a stealth order:

```http
GET /api/v1/stealth/orders/stlth_123/coinbase-exchange-submission-policy
```

Expected behavior:

- return backend proof records and latest-proof status as evidence
- show no-live, no-Coinbase-submit, no-Coinbase-cancel, no-Coinbase-read, and
  no-reconciliation flags
- keep Coinbase order activity and live command controls disabled unless a
  separate backend live-enabled contract explicitly allows execution
- never compute Coinbase exchange policy safety in the browser or BFF

Record Coinbase exchange policy proof evidence:

```http
POST /api/v1/stealth/orders/stlth_123/coinbase-exchange-submission-policy-proofs
Idempotency-Key: example-idempotency-key
X-Correlation-Id: example-correlation-id
X-Operator-Intent: record Coinbase exchange policy evidence only

{
  "stealth_order_id": "stlth_123",
  "guarded_command_route": "/api/v1/stealth/orders/{stealth_order_id}/reveal",
  "guarded_command_method": "POST",
  "guarded_service_method": "reveal_stealth_order_by_stealth_order_id",
  "guarded_mutation_family": "stealth_reveal",
  "guarded_actor_id": "operator_123",
  "guarded_operator_intent": "stealth_reveal_execution_review",
  "guarded_idempotency_key": "example-guarded-idempotency-key",
  "guarded_payload_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "exchange_submission_policy_ref": "coinbase-submit-policy-review-123",
  "coinbase_cancel_policy_ref": "coinbase-cancel-policy-review-123",
  "live_coinbase_read_policy_ref": "coinbase-read-policy-review-123",
  "live_cap_evidence_ref": "live-cap-review-123",
  "evidence_source": "manual_review",
  "reconciliation_plan_id": "reconciliation-plan-123",
  "approval_snapshot_id": "approval-snapshot-123",
  "admission_audit_id": "admission-audit-123",
  "cap_guard_decision_id": "cap-guard-decision-123",
  "coinbase_exchange_policy_proof_id": "coinbase-exchange-policy-proof-123",
  "dry_run": true,
  "operator_reason": "Manual review of Coinbase exchange submission policy only.",
  "manual_live_acknowledgement": false
}
```

The request must include the exact guarded command context required by the
backend. A successful response is append-only local evidence. It is not
Coinbase read, Coinbase submit/cancel, active-placement cancel/replace,
manager invocation, reconciliation, order/lifecycle/exchange mutation, or
browser proof approval.
