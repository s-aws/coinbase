# Spot Recovery Proof Examples

These examples assume the Admin API is running locally and authenticated with a
backend token. They are no-live local-state mutations only.

## Exchange-State Proof

```powershell
$headers = @{
  Authorization = "Bearer local-admin-token"
  "Idempotency-Key" = "spot-recovery-exchange-proof-001"
  "X-Correlation-Id" = "corr-spot-recovery-proof"
  "X-Operator-Intent" = "spot_recovery_contract_review"
  "X-Admin-Actor" = "operator-001"
  "X-Admin-Roles" = "trader"
}

$body = @{
  client_order_id = "client-order-preview"
  exchange_state_proof_id = "exchange-state-proof-001"
  exchange_state_evidence_ref = "audit-workbench-ref-001"
  reconciliation_plan_id = "reconciliation-plan-exchange-001"
  approval_snapshot_id = "approval-exchange-001"
  admission_audit_id = "admission-audit-exchange-001"
  cap_guard_decision_id = "cap-guard-exchange-001"
  dry_run = $true
  operator_reason = "contract evidence only"
  manual_live_acknowledgement = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/api/v1/spot/recovery/exchange-state-proofs" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

## Reconciliation Proof

```powershell
$headers["Idempotency-Key"] = "spot-recovery-reconciliation-proof-001"

$body = @{
  client_order_id = "client-order-preview"
  exchange_state_proof_id = "exchange-state-proof-001"
  reconciliation_proof_id = "reconciliation-proof-001"
  recovery_apply_audit_id = "recovery-apply-audit-001"
  reconciliation_plan_id = "reconciliation-plan-proof-001"
  approval_snapshot_id = "approval-proof-001"
  admission_audit_id = "admission-audit-proof-001"
  cap_guard_decision_id = "cap-guard-proof-001"
  dry_run = $true
  operator_reason = "contract evidence only"
  manual_live_acknowledgement = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/api/v1/spot/recovery/reconciliation-proofs" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

## Readback

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8787/api/v1/spot/recovery/reconciliation-proof?client_order_id=client-order-preview" `
  -Headers @{ Authorization = "Bearer local-admin-token"; "X-Admin-Roles" = "viewer" }
```

The response includes `persisted_proof_count`, `persisted_proofs`,
`latest_exchange_state_proof_id`, and `latest_reconciliation_proof_id`. It does
not execute recovery, execute reconciliation, mutate order/exchange state, read
Coinbase, or submit Coinbase orders.
