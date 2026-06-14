# Stealth Command Suite Examples

Run the Admin API locally:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

Read stealth command-suite readiness:

```http
GET /api/v1/stealth/command-suite
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected posture:

```json
{
  "type": "stealth_command_suite",
  "module_id": "stealth_orders",
  "status": "blocked",
  "approved_phase_range": "2041-2060",
  "command_count": 5,
  "blocked_command_count": 5,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "exchange_truth_required": true,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false
}
```

The `commands` array includes live-disabled rows for:

- `/api/v1/stealth/orders`
- `/api/v1/stealth/orders/{stealth_order_id}/reveal`
- `/api/v1/stealth/orders/{stealth_order_id}/move`
- `/api/v1/stealth/orders/{stealth_order_id}/cancel`
- `/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`

Each row uses `stealth_order_id` as `identity_key`. Create is a
`local_state_mutation` draft route with `exchange_truth_required=false`,
`active_placement_evidence_required=false`, `live_execution_status` set to
`live_disabled`, and evidence that `StealthOrderManager` was not invoked.
Reveal is a `live_exchange_place` draft route with
`exchange_truth_required=true`, `active_placement_evidence_required=false`,
and evidence that `reveal_order_slice`, `StealthOrderManager`, Coinbase
submission, and local lifecycle mutation were not invoked. Cancel and reprice
still report `exchange_truth_required=true` and require active-placement
exchange truth before any lifecycle mutation. Move is a
`live_exchange_cancel` draft route with `exchange_truth_required=true`,
`active_placement_evidence_required=true`, and evidence that
`build_stealth_move_plan`, `execute_stealth_move`, `StealthOrderManager`,
Coinbase cancel/submit, cancel/replace, and local lifecycle mutation were not
invoked.

The `coverage_gaps` array includes blocked workflow families for:

- `stealth_create_workflow` with command route `/api/v1/stealth/orders`,
  still blocked on lifecycle-write, guard, admission, and reconciliation
  contracts
- `stealth_reveal_workflow` with command route
  `/api/v1/stealth/orders/{stealth_order_id}/reveal`, still blocked on
  trigger guard, exchange submission adapter, active-placement audit, and
  reconciliation proof
- `stealth_cancel_exchange_handling`
- `stealth_move_revealed_workflow` with command route
  `/api/v1/stealth/orders/{stealth_order_id}/move`, still blocked on
  mutation-claim audit, active-placement cancel/replace handling, and
  reconciliation proof
- `stealth_reprice_workflow`
- `stealth_recovery_workflow`
- `stealth_reconciliation_workflow`

Do not treat this response as command approval. It is readiness evidence only.
It does not create stealth orders, reveal orders, cancel active placements,
move/reprice revealed orders, execute reconciliation, mutate state, read
Coinbase, or call Coinbase.
