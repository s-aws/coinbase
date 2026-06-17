# Stealth State-Mutation Policy Examples

Read state-mutation policy evidence for a stealth order:

```http
GET /api/v1/stealth/orders/stlth_123/state-mutation-policy
```

Expected behavior:

- return backend proof records and latest-proof status as evidence
- show no-state-mutation, no-Coinbase, no-manager, no-reconciliation,
  display-only, and BFF forward-only flags
- keep live command controls disabled unless a separate backend live-enabled
  contract explicitly allows execution
- never compute state-mutation safety in the browser or BFF

Record state-mutation policy proof evidence:

```http
POST /api/v1/stealth/orders/stlth_123/state-mutation-policy-proofs
Idempotency-Key: example-idempotency-key
X-Correlation-Id: example-correlation-id
X-Operator-Intent: record state mutation policy evidence only

{
  "stealth_order_id": "stlth_123",
  "guarded_command_route": "/api/v1/stealth/orders/{stealth_order_id}/move",
  "guarded_command_method": "POST",
  "guarded_service_method": "move_stealth_order_by_stealth_order_id",
  "guarded_mutation_family": "stealth_move",
  "guarded_actor_id": "operator_123",
  "guarded_operator_intent": "stealth_move_execution_review",
  "guarded_idempotency_key": "example-guarded-idempotency-key",
  "guarded_payload_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "state_mutation_policy_ref": "state-mutation-policy-review-123",
  "lifecycle_state_policy_ref": "lifecycle-state-policy-review-123",
  "order_state_policy_ref": "order-state-policy-review-123",
  "exchange_state_policy_ref": "exchange-state-policy-review-123",
  "post_write_reconciliation_policy_ref": "post-write-policy-review-123",
  "evidence_source": "manual_review",
  "reconciliation_plan_id": "reconciliation-plan-123",
  "approval_snapshot_id": "approval-snapshot-123",
  "admission_audit_id": "admission-audit-123",
  "cap_guard_decision_id": "cap-guard-decision-123",
  "state_mutation_policy_proof_id": "state-mutation-policy-proof-123",
  "dry_run": true,
  "operator_reason": "Manual review of state-mutation policy only.",
  "manual_live_acknowledgement": false
}
```

The request must include the exact guarded command context required by the
backend. A successful response is append-only local evidence. It is not
lifecycle/order/exchange-state mutation, Coinbase read, Coinbase
submit/cancel, active-placement cancel/replace, manager invocation,
reconciliation execution, or browser proof approval.
