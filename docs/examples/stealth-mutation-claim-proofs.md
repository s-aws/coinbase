# Stealth Mutation-Claim Snapshot Proof Examples

These examples show the enterprise Admin API contract for mutation-claim
snapshot proof evidence. They are local-state proof examples only. They do not
read Coinbase, submit Coinbase orders, cancel Coinbase orders, acquire or
release mutation claims, invoke the stealth manager, cancel/replace active
placements, execute reconciliation, or mutate order, exchange, or lifecycle
state.

Run the Admin API locally:

```powershell
python3.13 tools/run_admin_api.py --dev-token local-admin-token
```

## Record Proof For A Move Command

This example assumes the backend has already recorded the required approval,
admission audit, cap/guard decision, and reconciliation plan evidence for the
proof route itself:

`POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs`

The `guarded_*` fields bind this proof to the future guarded move command.
`guarded_payload_hash` is the payload hash of that move command, not the proof
request.

```powershell
$headers = @{
  Authorization = "Bearer local-admin-token"
  "Content-Type" = "application/json"
  "X-Admin-Actor" = "operator-001"
  "X-Admin-Roles" = "admin"
  "Idempotency-Key" = "stealth-mutation-claim-proof-001"
  "X-Correlation-Id" = "local-mutation-claim-proof-001"
  "X-Operator-Intent" = "stealth_mutation_claim_contract_review"
}

$body = @{
  stealth_order_id = "stealth-mutation-claim-001"
  guarded_command_route = "/api/v1/stealth/orders/{stealth_order_id}/move"
  guarded_command_method = "POST"
  guarded_service_method = "move_stealth_order_by_stealth_order_id"
  guarded_actor_id = "operator-001"
  guarded_operator_intent = "stealth_move_execution_review"
  guarded_idempotency_key = "stealth-move-command-001"
  guarded_payload_hash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  mutation_kind = "move"
  claim_reader_source = "stealth_manager.snapshot_mutation_claims"
  runtime_claims_observed = $true
  runtime_claim_count = 3
  active_claim_count = 0
  evidence_source = "test_evidence"
  snapshot_evidence_ref = "local-mutation-claim-snapshot-ref-001"
  reconciliation_plan_id = "stealth-mutation-claim-recon-plan-001"
  approval_snapshot_id = "stealth-mutation-claim-approval-001"
  admission_audit_id = "stealth-mutation-claim-admission-audit-001"
  cap_guard_decision_id = "stealth-mutation-claim-cap-guard-001"
  mutation_claim_proof_id = "stealth-mutation-claim-proof-001"
  dry_run = $true
  operator_reason = "contract evidence only"
  manual_live_acknowledgement = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-mutation-claim-001/mutation-claim-proofs" `
  -Headers $headers `
  -Body $body
```

Expected accepted records include:

```json
{
  "status": "accepted",
  "required_permission": "stealth_mutation_claim:record",
  "stealth_order_id": "stealth-mutation-claim-001",
  "client_order_id": null,
  "coinbase_order_id": null,
  "live_exchange_submitted": false,
  "data": {
    "mutation_claim_proof_id": "stealth-mutation-claim-proof-001",
    "proof_persisted": true,
    "runtime_claims_observed": true,
    "active_claim_count": 0,
    "manager_invocation_ran": false,
    "claim_acquire_ran": false,
    "claim_release_ran": false,
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

## Record Proof For Movement/Reprice

For the movement/repricing command route, keep the same proof route and path
identity, but bind the guarded command context to the movement/repricing
command:

```json
{
  "guarded_command_route": "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
  "guarded_command_method": "POST",
  "guarded_service_method": "reprice_stealth_order_by_stealth_order_id",
  "mutation_kind": "reprice"
}
```

All other exact guarded context fields still need to match the future command:
actor id, operator intent, idempotency key, and payload hash.

## Read Back Proof Evidence

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/stealth/orders/stealth-mutation-claim-001/mutation-claim-proof" `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

The readback response reports persisted proof count, latest proof id,
persisted records, no-live flags, and proof-route metadata. It does not
re-read runtime claims or call Coinbase.

## Fail-Closed Cases

The proof writer rejects records when:

- The path `stealth_order_id` and body `stealth_order_id` do not match.
- The guarded route/service pair is not move or movement/reprice.
- `runtime_claims_observed` is `false`.
- `active_claim_count` is not `0`.
- Required proof-route gate evidence is missing or does not match the proof
  route.
- The body includes fields not accepted by the request model, including
  exchange-native `order_id`.

The command-posture resolver also fails closed. It reads the latest proof for
the same `stealth_order_id`; if that latest proof is unsafe, stale, or bound
to different guarded command context, `mutation_claim_snapshot` remains
missing even when an older proof would have matched.

## Command Resolution

After an accepted proof exists, a move or movement/reprice dry-submit can show
the `mutation_claim_snapshot` prerequisite as resolved only when all common
backend prerequisites are present and the latest proof exactly matches the
command admission context.

The command still remains non-executable until all other execution blockers
are cleared, including active-placement exchange-truth evidence, live service
enablement, live adapter enablement, and post-write reconciliation. Proof
resolution does not grant browser or BFF execution authority.
