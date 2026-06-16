# Stealth Post-Write Reconciliation Execution Policy Examples

Read post-write reconciliation execution-policy evidence for a stealth order:

```http
GET /api/v1/stealth/orders/stlth_123/post-write-reconciliation-execution-policy
```

Expected behavior:

- return backend proof records and latest-proof status as evidence
- show no-reconciliation-execution, no-Coinbase, no-manager, no-state-mutation,
  display-only, and BFF forward-only flags
- keep live command controls disabled unless a separate backend live-enabled
  contract explicitly allows execution
- never compute reconciliation execution safety in the browser or BFF

Record post-write reconciliation execution-policy proof evidence:

```http
POST /api/v1/stealth/orders/stlth_123/post-write-reconciliation-execution-policy-proofs
Idempotency-Key: example-idempotency-key
X-Correlation-Id: example-correlation-id
X-Operator-Intent: record post-write reconciliation execution policy evidence only

{
  "stealth_order_id": "stlth_123",
  "guarded_command_route": "/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
  "guarded_command_method": "POST",
  "guarded_service_method": "reconcile_stealth_order_by_stealth_order_id",
  "guarded_mutation_family": "stealth_reconciliation",
  "guarded_actor_id": "operator_123",
  "guarded_operator_intent": "stealth_reconciliation_execution_review",
  "guarded_idempotency_key": "example-guarded-idempotency-key",
  "guarded_payload_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "post_write_reconciliation_execution_policy_ref": "post-write-reconciliation-execution-policy-review-123",
  "route_bound_reconciliation_plan_ref": "route-bound-reconciliation-plan-review-123",
  "post_write_execution_journal_policy_ref": "post-write-execution-journal-policy-review-123",
  "post_write_reconciliation_verification_policy_ref": "post-write-reconciliation-verification-policy-review-123",
  "safe_reconciliation_chain_ref": "safe-reconciliation-chain-review-123",
  "evidence_source": "manual_review",
  "reconciliation_plan_id": "reconciliation-plan-123",
  "approval_snapshot_id": "approval-snapshot-123",
  "admission_audit_id": "admission-audit-123",
  "cap_guard_decision_id": "cap-guard-decision-123",
  "post_write_reconciliation_policy_proof_id": "post-write-reconciliation-execution-policy-proof-123",
  "dry_run": true,
  "operator_reason": "Manual review of post-write reconciliation execution policy only.",
  "manual_live_acknowledgement": false
}
```

The request must include the exact guarded command context required by the
backend. A successful response is append-only local evidence. It is not
reconciliation execution, Coinbase read, Coinbase submit/cancel,
active-placement cancel/replace, manager invocation, order/lifecycle/exchange
mutation, or browser proof approval.
