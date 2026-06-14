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
  "approved_phase_range": "1981-2000",
  "command_count": 2,
  "blocked_command_count": 2,
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

- `/api/v1/stealth/orders/{stealth_order_id}/cancel`
- `/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`

Each row uses `stealth_order_id` as `identity_key`, reports
`exchange_truth_required=true`, and includes
`active_placement_exchange_truth` in the required gate chain.

The `coverage_gaps` array includes blocked workflow families for:

- `stealth_create_workflow`
- `stealth_reveal_workflow`
- `stealth_cancel_exchange_handling`
- `stealth_move_revealed_workflow`
- `stealth_reprice_workflow`
- `stealth_recovery_workflow`
- `stealth_reconciliation_workflow`

Do not treat this response as command approval. It is readiness evidence only.
It does not create stealth orders, reveal orders, cancel active placements,
move/reprice revealed orders, execute reconciliation, mutate state, read
Coinbase, or call Coinbase.
