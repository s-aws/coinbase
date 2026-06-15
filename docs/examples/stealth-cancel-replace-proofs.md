# Stealth Cancel/Replace Proof Examples

These examples show the enterprise Admin API contract for stealth
cancel/replace proof evidence. They are local-state proof examples only. They
do not read Coinbase, submit Coinbase orders, cancel Coinbase orders, invoke
managers, build cancel/replace plans, cancel/replace active placements,
execute reconciliation, or mutate order, exchange, or lifecycle state.

Run the Admin API locally:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

## Record Proof For A Move Command

This example assumes the backend has already recorded the required approval,
admission audit, cap/guard decision, and reconciliation plan evidence for the
proof route itself:

`POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`

The `guarded_*` fields bind this proof to the future guarded move command.
`guarded_payload_hash` is the payload hash of that move command, not the proof
request. Move and movement reprice proof records require
`mutation_claim_evidence_ref`; cancel proof records do not.
The `*_evidence_ref` fields are opaque operator/backend references for this
writer. The service checks presence and guarded-context shape only; it does
not dereference those values, verify another proof-store row, read Coinbase,
or turn them into execution authority.

```powershell
$headers = @{
  Authorization = "Bearer local-admin-token"
  "Content-Type" = "application/json"
  "X-Admin-Actor" = "operator-001"
  "X-Admin-Roles" = "admin"
  "Idempotency-Key" = "stealth-cancel-replace-proof-001"
  "X-Correlation-Id" = "local-cancel-replace-proof-001"
  "X-Operator-Intent" = "stealth_cancel_replace_proof_contract_review"
}

$body = @{
  stealth_order_id = "stealth-cancel-replace-proof-001"
  guarded_command_route = "/api/v1/stealth/orders/{stealth_order_id}/move"
  guarded_command_method = "POST"
  guarded_service_method = "move_stealth_order_by_stealth_order_id"
  guarded_mutation_family = "stealth_move"
  guarded_actor_id = "operator-001"
  guarded_operator_intent = "stealth_move_cancel_replace_review"
  guarded_idempotency_key = "stealth-move-command-001"
  guarded_payload_hash = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  active_placement_evidence_ref = "operator-reviewed-active-placement-001"
  mutation_claim_evidence_ref = "operator-reviewed-mutation-claim-001"
  cancel_replace_evidence_ref = "operator-reviewed-cancel-replace-001"
  evidence_source = "test_evidence"
  reconciliation_plan_id = "stealth-cancel-replace-recon-plan-001"
  approval_snapshot_id = "stealth-cancel-replace-approval-001"
  admission_audit_id = "stealth-cancel-replace-admission-audit-001"
  cap_guard_decision_id = "stealth-cancel-replace-cap-guard-001"
  cancel_replace_proof_id = "stealth-cancel-replace-proof-001"
  dry_run = $true
  operator_reason = "contract evidence only"
  manual_live_acknowledgement = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-cancel-replace-proof-001/cancel-replace-proofs" `
  -Headers $headers `
  -Body $body
```

Expected accepted records include:

```json
{
  "status": "accepted",
  "required_permission": "stealth_cancel_replace:record",
  "stealth_order_id": "stealth-cancel-replace-proof-001",
  "client_order_id": null,
  "coinbase_order_id": null,
  "live_exchange_submitted": false,
  "data": {
    "cancel_replace_proof_id": "stealth-cancel-replace-proof-001",
    "proof_persisted": true,
    "cancel_replace_proof_verified": false,
    "manager_invocation_ran": false,
    "cancel_replace_plan_built": false,
    "coinbase_rest_read_ran": false,
    "coinbase_order_submitted": false,
    "coinbase_order_cancel_submitted": false,
    "active_placement_cancel_replace_ran": false,
    "reconciliation_executed": false,
    "order_state_mutated": false,
    "lifecycle_state_mutated": false,
    "exchange_state_mutated": false
  }
}
```

## Read Back Proof Evidence

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-cancel-replace-proof-001/cancel-replace-proof" `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

The readback response reports persisted proof count, latest proof id,
persisted records, no-live flags, no-cancel/replace flags, and proof-route
metadata. It does not build plans, invoke managers, cancel or replace
placements, execute reconciliation, or call Coinbase.

## Fail-Closed Cases

The proof writer rejects records when:

- The path `stealth_order_id` and body `stealth_order_id` do not match.
- The guarded route/service/family combination is not stealth cancel, stealth
  move, or movement reprice.
- A move or reprice proof is missing `mutation_claim_evidence_ref`.
- `dry_run` is `false`.
- `manual_live_acknowledgement` is `true`.
- Required proof-route gate evidence is missing or does not match the proof
  route.
- The body includes fields not accepted by the request model, including
  exchange-native `order_id`.

Proof readback is also fail-closed as evidence: it does not make cancel, move,
or reprice executable and does not grant browser or BFF execution authority.
