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
  "approved_phase_range": "2421-2440",
  "command_count": 7,
  "blocked_command_count": 7,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "exchange_truth_required": true,
  "exchange_truth_check_count": 7,
  "blocking_exchange_truth_check_count": 7,
  "active_placement_exchange_truth_required_count": 5,
  "admission_readiness_count": 7,
  "blocking_admission_readiness_count": 7,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false
}
```

Live-disabled non-create stealth command responses now also include
`stealth_command_execution_contract`. For example, a cancel dry-submit remains
blocked even when exact command-envelope context is present:

```json
{
  "status": "not_implemented",
  "data": {
    "identity_key": "stealth_order_id",
    "stealth_command_execution_contract_available": false,
    "stealth_command_execution_allowed": false,
    "missing_stealth_command_execution_prerequisites": [
      "approval_snapshot",
      "admission_audit",
      "cap_guard_decision",
      "reconciliation_plan",
      "active_placement_exchange_truth",
      "live_execution_service",
      "live_execution_adapter",
      "post_write_reconciliation"
    ]
  },
  "stealth_command_execution_contract": {
    "mutation_family": "stealth_cancel",
    "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
    "identity_key": "stealth_order_id",
    "execution_allowed": false,
    "manager_invocation_ran": false,
    "active_placement_cancel_replace_ran": false,
    "coinbase_order_cancel_submitted": false,
    "live_coinbase_read_ran": false,
    "reconciliation_executed": false,
    "browser_authority": "display_only",
    "bff_authority": "forward_only_no_execution"
  }
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
  "required_gate_chain": [
    "route_inventory_contract",
    "idempotency",
    "operator_intent",
    "payload_hash",
    "approval_snapshot",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "mutation_claim",
    "lifecycle_write_guard",
    "live_execution_adapter",
    "live_execution_service",
    "post_write_reconciliation"
  ],
  "missing_gate_chain": [
    "approval_snapshot",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "lifecycle_write_guard",
    "live_execution_disabled"
  ],
  "proof_route_count": 5,
  "blocking_proof_route_count": 5,
  "proof_records_created": false,
  "approval_store_mutated": false,
  "admission_audit_store_mutated": false,
  "cap_guard_store_mutated": false,
  "reconciliation_plan_store_mutated": false,
  "proof_routes": [
    {
      "gate": "approval",
      "route": "/api/v1/admin/approvals/requests",
      "method": "POST",
      "required_permission": "approval:request",
      "shared_method": "create_approval_request",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    {
      "gate": "approval",
      "route": "/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
      "method": "POST",
      "required_permission": "approval:manage",
      "shared_method": "decide_approval_request",
      "identity_key": "approval_request_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    {
      "gate": "audit",
      "route": "/api/v1/admin/admission-audits",
      "method": "POST",
      "required_permission": "admission_audit:record",
      "shared_method": "record_admission_audit",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    {
      "gate": "cap_guard",
      "route": "/api/v1/admin/cap-guard/decisions",
      "method": "POST",
      "required_permission": "cap_guard:record",
      "shared_method": "record_cap_guard_decision",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    {
      "gate": "reconciliation",
      "route": "/api/v1/admin/reconciliation/plans",
      "method": "POST",
      "required_permission": "reconciliation:record",
      "shared_method": "record_reconciliation_plan",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    {
      "gate": "lifecycle_write_guard",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs",
      "method": "POST",
      "required_permission": "stealth_lifecycle_write:record",
      "shared_method": "record_stealth_create_lifecycle_write_guard_proof",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    }
  ],
  "required_contracts": [
    "stealth_create_guard_contract",
    "stealth_create_admission_audit",
    "stealth_create_reconciliation_plan",
    "stealth_create_lifecycle_write_guard_proof",
    "stealth_create_lifecycle_write_execution_contract"
  ],
  "execution_contract": {
    "execution_contract_available": false,
    "execution_allowed": false,
    "exact_command_context_present": false,
    "missing_context_fields": [
      "route",
      "method",
      "stealth_order_id",
      "actor_id",
      "idempotency_key",
      "operator_intent",
      "payload_hash"
    ],
    "missing_prerequisites": [
      "approval_snapshot",
      "admission_audit",
      "cap_guard_decision",
      "reconciliation_plan",
      "lifecycle_write_guard_proof",
      "live_execution_service",
      "live_execution_adapter",
      "post_write_reconciliation"
    ],
    "resolved_prerequisites": [],
    "prerequisite_resolver_available": true,
    "prerequisite_resolver_lookup_ran": false,
    "prerequisite_resolver_authority": "read_only_no_execution",
    "prerequisite_resolution": [
      {
        "prerequisite": "approval_snapshot",
        "source": "approval_store",
        "route": "/api/v1/stealth/orders",
        "method": "POST",
        "identity_key": "stealth_order_id",
        "identity_value": null,
        "lookup_status": "not_checked",
        "lookup_ran": false,
        "resolved": false,
        "resolved_evidence_id": null,
        "missing_reason": "exact_command_context_missing",
        "authority": "read_only_no_execution",
        "proof_lookup_authority": "none",
        "writes_ran": false,
        "live_coinbase_read_ran": false
      },
      {
        "prerequisite": "lifecycle_write_guard_proof",
        "source": "lifecycle_write_guard_proof_store",
        "route": "/api/v1/stealth/orders",
        "method": "POST",
        "identity_key": "stealth_order_id",
        "identity_value": null,
        "lookup_status": "not_checked",
        "lookup_ran": false,
        "resolved": false,
        "resolved_evidence_id": null,
        "missing_reason": "exact_command_context_missing",
        "authority": "read_only_no_execution",
        "proof_lookup_authority": "none",
        "writes_ran": false,
        "live_coinbase_read_ran": false
      }
    ],
    "manager_invocation_ran": false,
    "stealth_row_write_ran": false,
    "order_parent_write_ran": false,
    "coinbase_order_submit_ran": false,
    "live_coinbase_read_ran": false,
    "reconciliation_executed": false
  }
}
```

The `commands` array includes live-disabled rows for:

- `/api/v1/stealth/orders`
- `/api/v1/stealth/orders/{stealth_order_id}/reveal`
- `/api/v1/stealth/orders/{stealth_order_id}/move`
- `/api/v1/stealth/orders/{stealth_order_id}/cancel`
- `/api/v1/stealth/orders/{stealth_order_id}/recovery`
- `/api/v1/stealth/orders/{stealth_order_id}/reconciliation`
- `/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`

Active-placement exchange-truth evidence is read back from:

```http
GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Snapshot and proof records are written only through backend-owned,
idempotent, RBAC-gated, audited routes:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots
POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs
```

Create lifecycle-write guard evidence is read back and written through:

```http
GET /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof
POST /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs
```

Those lifecycle-write guard proof records are append-only local evidence. They
do not invoke `StealthOrderManager`, write stealth or `order_parent` rows,
dispatch lifecycle events, submit/read Coinbase, execute reconciliation, or
grant browser/BFF execution authority.

`create_lifecycle_write_audit.execution_contract` is also evidence only. It
lists missing exact command context and prerequisites in command-suite
readback. The live-disabled create draft can return the same shape as
`stealth_lifecycle_execution_contract` after the backend has exact command
context, but it remains blocked until every approval, audit, cap, guard,
reconciliation, live-adapter, and post-write prerequisite is resolved.
`prerequisite_resolution` rows are read-only lookup evidence. They can report
`not_checked`, `missing`, `blocked_by_dependency`, `resolved`, or `disabled`
for each prerequisite, but they never write proof records, call Coinbase,
invoke live adapters, execute reconciliation, or grant browser/BFF authority.

These records remain local evidence. They do not read Coinbase, cancel or
replace active placements, execute reconciliation, mutate lifecycle state, or
mark `exchange_truth_verified=true`.

Each row uses `stealth_order_id` as `identity_key`. Create is a
`local_state_mutation` draft route with `exchange_truth_required=false`,
`active_placement_evidence_required=false`, `live_execution_status` set to
`live_disabled`, and evidence that `StealthOrderManager` was not invoked. The
create lifecycle-write audit is command-suite evidence only: it does not write
stealth rows, write `order_parent`, dispatch lifecycle events, execute
reconciliation, submit Coinbase orders, read Coinbase, create approval,
admission-audit, cap/guard, or reconciliation proof records, or grant
browser/BFF lifecycle-write authority. The audit lists the five backend proof
routes required before future create execution can be considered:
approval request, approval decision, admission audit, cap/guard decision, and
reconciliation plan.
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
Recovery and reconciliation are `local_state_mutation` command contracts with
`exchange_truth_required=true` and `active_placement_evidence_required=true`.
They return fail-closed `not_implemented` responses and do not execute
recovery repair, rollback, reconciliation, proof writers, Coinbase reads,
Coinbase orders, `StealthOrderManager` mutations, local lifecycle mutations,
exchange-state mutations, or browser/BFF command authority.

The `exchange_truth_checks` array mirrors those seven command routes as
read-only prerequisites. Each row accepts only `stealth_order_id` as command
identity and rejects `client_order_id`, `active_placement_client_order_id`,
exchange order ids, and `order_id` as command identities. Cancel, move,
recovery, reconciliation, and reprice require active-placement exchange truth
before any future executable backend path can be considered. The fields are
evidence only; they do not read Coinbase, cancel/replace active placements,
execute recovery or reconciliation, or grant browser/BFF exchange-truth
authority.
Each exchange-truth row also includes typed `current_read_evidence` route
metadata:

```json
{
  "mutation_family": "stealth_move",
  "route": "/api/v1/stealth/orders/{stealth_order_id}/move",
  "current_read_evidence_routes": [
    "GET /api/v1/movement-repricing/stealth/{stealth_order_id}",
    "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
    "GET /api/v1/stealth/command-suite"
  ],
  "current_read_evidence": [
    {
      "route": "/api/v1/movement-repricing/stealth/{stealth_order_id}",
      "method": "GET",
      "action_class": "read_only",
      "required_permission": "audit:read",
      "shared_method": "build_movement_repricing_stealth_detail",
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "read_only_forward"
    },
    {
      "route": "/api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
      "method": "GET",
      "action_class": "read_only",
      "required_permission": "audit:read",
      "shared_method": "build_stealth_active_placement_exchange_truth",
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "read_only_forward"
    },
    {
      "route": "/api/v1/stealth/command-suite",
      "method": "GET",
      "action_class": "read_only",
      "required_permission": "analytics:read",
      "shared_method": "build_stealth_command_suite",
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "read_only_forward"
    }
  ]
}
```

These rows do not run Coinbase reads, prove active-placement exchange truth,
cancel/replace placements, reveal orders, execute reconciliation, mutate
state, or authorize browser/BFF command execution.

The `admission_readiness` array binds each command route to the backend-owned
evidence required before execution can ever be considered. A blocked cancel
row has this shape:

```json
{
  "mutation_family": "stealth_cancel",
  "route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
  "method": "POST",
  "identity_key": "stealth_order_id",
  "command_identity_key": "stealth_order_id",
  "status": "blocked",
  "live_execution_status": "live_disabled",
  "admission_allowed": false,
  "executable": false,
  "live_enabled": false,
  "active_placement_exchange_truth_required": true,
  "exchange_truth_verified": false,
  "lifecycle_write_guard_required": false,
  "missing_evidence": [
    "approval_request",
    "approval_decision",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "active_placement_exchange_truth",
    "live_execution_adapter",
    "post_live_reconciliation"
  ],
  "required_context_count": 11,
  "present_context_count": 6,
  "missing_context_count": 5,
  "missing_context": [
    "stealth_order_id",
    "actor_id",
    "idempotency_key",
    "operator_intent",
    "payload_hash"
  ],
  "exact_context_present": false,
  "resolver_lookup_allowed": false,
  "resolver_lookup_ran": false,
  "proof_resolution_attempted": false,
  "coinbase_read_ran": false,
  "coinbase_order_submitted": false,
  "coinbase_order_cancel_submitted": false,
  "active_placement_cancel_replace_ran": false,
  "reconciliation_executed": false,
  "lifecycle_state_mutated": false,
  "order_state_mutated": false,
  "exchange_state_mutated": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution"
}
```

Create and reveal rows use `lifecycle_write_guard` instead of
`active_placement_exchange_truth`. Cancel, move, recovery, reconciliation,
and reprice rows require `active_placement_exchange_truth`. The ledger does
not approve commands, execute commands, read Coinbase, call
`StealthOrderManager`, cancel/replace placements, execute reconciliation,
mutate state, or grant browser/BFF authority.
`context_requirements` separates static route metadata from the exact command
envelope. Route fields are present for display, but `stealth_order_id`,
`actor_id`, `idempotency_key`, `operator_intent`, and `payload_hash` are
missing in the read-only command-suite response. That keeps resolver lookup
and proof resolution disabled.
After a live-disabled stealth command is dry-submitted, the command response
may include a separate `stealth_admission_context` object. In that object the
same fields can be present because the backend has a concrete command
envelope:

```json
{
  "stealth_admission_context": {
    "type": "stealth_command_admission_context",
    "mutation_family": "stealth_cancel",
    "identity_key": "stealth_order_id",
    "required_context_count": 11,
    "present_context_count": 11,
    "missing_context_count": 0,
    "exact_context_present": true,
    "resolver_lookup_allowed": true,
    "proof_resolution_attempted": true,
    "admission_allowed": false,
    "executable": false,
    "live_enabled": false,
    "browser_authority": "display_only",
    "bff_authority": "forward_only_no_execution"
  }
}
```

That response echo is still no-live evidence. It does not approve, execute,
read Coinbase, submit/cancel orders, cancel/replace active placements,
reconcile, mutate state, or grant browser/BFF authority.
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

Coverage gaps also include typed `current_read_evidence` rows. For the
recovery and reconciliation gaps, the current read evidence is existing
backend read-only route evidence only:

```json
[
  {
    "family": "stealth_recovery_workflow",
    "command_route": "/api/v1/stealth/orders/{stealth_order_id}/recovery",
    "current_read_evidence_routes": [
      "GET /api/v1/admin/recovery-gate",
      "GET /api/v1/stealth/orders/{stealth_order_id}",
      "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
      "GET /api/v1/stealth/command-suite"
    ],
    "current_read_evidence": [
      {
        "route": "/api/v1/admin/recovery-gate",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "audit:read",
        "shared_method": "build_recovery_gate",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/stealth/orders/{stealth_order_id}",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "audit:read",
        "shared_method": "build_stealth_order_detail",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "audit:read",
        "shared_method": "build_stealth_active_placement_exchange_truth",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/stealth/command-suite",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "analytics:read",
        "shared_method": "build_stealth_command_suite",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      }
    ]
  },
  {
    "family": "stealth_reconciliation_workflow",
    "command_route": "/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
    "current_read_evidence_routes": [
      "GET /api/v1/admin/reconciliation/plans",
      "GET /api/v1/admin/reconciliation/plans/{plan_id}",
      "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
      "GET /api/v1/stealth/command-suite"
    ],
    "current_read_evidence": [
      {
        "route": "/api/v1/admin/reconciliation/plans",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "reconciliation:read",
        "shared_method": "list_reconciliation_plans",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/admin/reconciliation/plans/{plan_id}",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "reconciliation:read",
        "shared_method": "get_reconciliation_plan",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "audit:read",
        "shared_method": "build_stealth_active_placement_exchange_truth",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      },
      {
        "route": "/api/v1/stealth/command-suite",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "analytics:read",
        "shared_method": "build_stealth_command_suite",
        "backend_owned": true,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward"
      }
    ]
  }
]
```

These evidence rows do not execute recovery or reconciliation, write proof
records, trust browser exchange evidence, mutate stealth/order/exchange state,
or call Coinbase. The dedicated recovery and reconciliation command routes
exist only as live-disabled Admin API contracts until their backend execution
gates are complete.

Do not treat this response as command approval. It is readiness evidence only.
It does not create stealth orders, reveal orders, cancel active placements,
move/reprice revealed orders, execute reconciliation, mutate state, read
Coinbase, or call Coinbase.
