# Stealth Recovery Proof Examples

These examples show the enterprise Admin API contract for stealth recovery
proof evidence. They are local-state proof examples only. They do not read
Coinbase, submit Coinbase orders, cancel Coinbase orders, invoke managers,
repair state, roll back state, cancel/replace active placements, execute
reconciliation, or mutate order, exchange, or lifecycle state.

Run the Admin API locally:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

## Record Proof For A Recovery Command

This example assumes the backend has already recorded the required approval,
admission audit, cap/guard decision, and reconciliation plan evidence for the
proof route itself:

`POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs`

The `guarded_*` fields bind this proof to the future guarded recovery command.
`guarded_payload_hash` is the payload hash of that recovery command, not the
proof request.

```powershell
$headers = @{
  Authorization = "Bearer local-admin-token"
  "Content-Type" = "application/json"
  "X-Admin-Actor" = "operator-001"
  "X-Admin-Roles" = "admin"
  "Idempotency-Key" = "stealth-recovery-proof-001"
  "X-Correlation-Id" = "local-recovery-proof-001"
  "X-Operator-Intent" = "stealth_recovery_proof_contract_review"
}

$body = @{
  stealth_order_id = "stealth-recovery-proof-001"
  guarded_command_route = "/api/v1/stealth/orders/{stealth_order_id}/recovery"
  guarded_command_method = "POST"
  guarded_service_method = "recover_stealth_order_by_stealth_order_id"
  guarded_actor_id = "operator-001"
  guarded_operator_intent = "stealth_recovery_execution_review"
  guarded_idempotency_key = "stealth-recovery-command-001"
  guarded_payload_hash = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  recovery_evidence_ref = "operator-reviewed-recovery-evidence-001"
  recovery_plan_ref = "operator-reviewed-recovery-plan-001"
  evidence_source = "test_evidence"
  reconciliation_plan_id = "stealth-recovery-proof-recon-plan-001"
  approval_snapshot_id = "stealth-recovery-proof-approval-001"
  admission_audit_id = "stealth-recovery-proof-admission-audit-001"
  cap_guard_decision_id = "stealth-recovery-proof-cap-guard-001"
  recovery_proof_id = "stealth-recovery-proof-001"
  dry_run = $true
  operator_reason = "contract evidence only"
  manual_live_acknowledgement = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-recovery-proof-001/recovery-proofs" `
  -Headers $headers `
  -Body $body
```

Expected accepted records include:

```json
{
  "status": "accepted",
  "required_permission": "stealth_recovery:record",
  "stealth_order_id": "stealth-recovery-proof-001",
  "client_order_id": null,
  "coinbase_order_id": null,
  "live_exchange_submitted": false,
  "data": {
    "recovery_proof_id": "stealth-recovery-proof-001",
    "proof_persisted": true,
    "recovery_proof_verified": false,
    "manager_invocation_ran": false,
    "recovery_plan_built": false,
    "recovery_repair_executed": false,
    "rollback_executed": false,
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
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-recovery-proof-001/recovery-proof" `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

The readback response reports persisted proof count, latest proof id,
persisted records, no-live flags, and proof-route metadata. It does not build
or run recovery plans and does not call Coinbase.

## Fail-Closed Cases

The proof writer rejects records when:

- The path `stealth_order_id` and body `stealth_order_id` do not match.
- The guarded route/service pair is not stealth recovery.
- `dry_run` is `false`.
- `manual_live_acknowledgement` is `true`.
- Required proof-route gate evidence is missing or does not match the proof
  route.
- The body includes fields not accepted by the request model, including
  exchange-native `order_id`.

The command-posture resolver also fails closed. It reads the latest proof for
the same `stealth_order_id`; if that latest proof is unsafe, stale, or bound
to different guarded command context, `recovery_proof` remains missing even
when an older proof would have matched.

## Command Resolution

After an accepted proof exists, a recovery dry-submit can show the
`recovery_proof` prerequisite as resolved only when all common backend
prerequisites are present, active-placement exchange-truth evidence is present,
and the latest proof exactly matches the command admission context.

The command still remains non-executable until all other execution blockers
are cleared, including live service enablement, live adapter enablement, and
post-write reconciliation. Proof resolution does not grant browser or BFF
execution authority.
