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
  "approved_phase_range": "2181-2200",
  "command_count": 5,
  "blocked_command_count": 5,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "exchange_truth_required": true,
  "exchange_truth_check_count": 5,
  "blocking_exchange_truth_check_count": 5,
  "active_placement_exchange_truth_required_count": 3,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false
}
```

The response also includes `create_lifecycle_write_audit` for the
live-disabled create workflow:

```json
{
  "command_route": "/api/v1/stealth/orders",
  "service_method": "create_stealth_order",
  "manager_method": "core/stealth_order_manager.py::create_stealth_order",
  "identity_key": "stealth_order_id",
  "accepted_command_identity_keys": ["stealth_order_id"],
  "rejected_command_identity_keys": [
    "client_order_id",
    "active_placement_client_order_id",
    "exchange_order_id",
    "order_id"
  ],
  "lifecycle_write_required": true,
  "lifecycle_write_contract_configured": false,
  "manager_invocation_ran": false,
  "stealth_row_write_ran": false,
  "order_parent_write_ran": false,
  "local_lifecycle_mutation_ran": false,
  "coinbase_order_submit_ran": false,
  "live_coinbase_read_ran": false,
  "reconciliation_executed": false,
  "required_contracts": [
    "stealth_create_guard_contract",
    "stealth_create_admission_audit",
    "stealth_create_reconciliation_plan",
    "stealth_create_lifecycle_write_contract"
  ]
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
`live_disabled`, and evidence that `StealthOrderManager` was not invoked. The
create lifecycle-write audit is command-suite evidence only: it does not write
stealth rows, write `order_parent`, dispatch lifecycle events, execute
reconciliation, submit Coinbase orders, read Coinbase, or grant browser/BFF
lifecycle-write authority.
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

The `exchange_truth_checks` array mirrors those five command routes as
read-only prerequisites. Each row accepts only `stealth_order_id` as command
identity and rejects `client_order_id`, `active_placement_client_order_id`,
exchange order ids, and `order_id` as command identities. Cancel, move, and
reprice require active-placement exchange truth before any future executable
backend path can be considered. The fields are evidence only; they do not
read Coinbase, cancel/replace active placements, execute reconciliation, or
grant browser/BFF exchange-truth authority.
For per-order active-placement evidence, read
`GET /api/v1/stealth/orders/{stealth_order_id}` and inspect
`active_placement_audit`. That detail payload reports local active placement
presence, active placement client id, exchange-id evidence, required mutation
families, missing contracts, and no-live Coinbase flags. It is not a command
input source and does not prove exchange truth by itself.
The same detail payload may include `mutation_claim_audit`. That panel reports
safely observable runtime mutation-claim snapshot state, active claim count,
required move/reprice claim contracts, missing claim contracts, and no-live
Coinbase flags. It is evidence only: it does not acquire, release, clear, or
prove claims, and command workflows must not use it as mutation authority.
The same detail payload may include `reveal_trigger_audit`. That panel reports
local reveal-condition presence, condition type/payload, required
reveal-trigger guard contracts, missing contracts, and no-live Coinbase flags.
It is evidence only: it does not evaluate triggers, call
`should_trigger_reveal`, call `reveal_order_slice`, submit Coinbase orders, or
prove reveal authority, and command workflows must not use it as browser/BFF
trigger authority.
The same detail payload may include `reveal_submission_audit`. That panel
reports the future backend reveal route, shared service method, manager
method, local active-placement evidence, required submission/reconciliation
contracts, missing contracts, and no-live Coinbase flags. It is evidence only:
it does not call `reveal_order_slice`, create active placements, submit or
cancel Coinbase orders, read Coinbase, execute reconciliation, or prove reveal
authority, and command workflows must not use it as browser/BFF submission
authority.
The same detail payload may include `reveal_reconciliation_audit`. That panel
reports required reconciliation plan/proof posture, local active-placement
evidence, read-evidence routes, missing proof contracts, and no-live flags. It
is evidence only: it does not read Coinbase, write proof records, execute
reconciliation, mutate order/lifecycle state, or prove reveal authority, and
command workflows must not use it as browser/BFF reconciliation authority.

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
