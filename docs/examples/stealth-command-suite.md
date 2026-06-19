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
  "approved_phase_range": "4561-4580",
  "command_count": 7,
  "blocked_command_count": 7,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "exchange_truth_required": true,
  "exchange_truth_check_count": 7,
  "blocking_exchange_truth_check_count": 7,
  "active_placement_exchange_truth_required_count": 5,
  "cancel_replace_boundary_count": 3,
  "blocking_cancel_replace_boundary_count": 3,
  "admission_readiness_count": 7,
  "blocking_admission_readiness_count": 7,
  "blocker_closure_count": 6,
  "blocking_blocker_closure_count": 6,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "live_coinbase_orders_ran": false,
  "live_coinbase_read_ran": false
}
```

The same read-only response includes an M55 blocker-closure ledger. It names
the concrete backend blockers that still prevent future live stealth
execution, but it does not enable any of them:

In the current 4561-4580 range, the reveal route may show both a configured
dry-run adapter and a configured dry-run live-service contract with
`live_execution_status="approval_required"`. That is readback evidence only;
`live_enabled`, `executable`, manager invocation, Coinbase submission/cancel/read,
reconciliation execution, and state mutation all remain false.

```json
{
  "blocker_closure_summary": {
    "status": "blocked",
    "blocker_count": 6,
    "blocking_count": 6,
    "resolved_count": 0,
    "partial_evidence_count": 2,
    "partial_evidence_closure_ids": [
      "m55_live_service_enablement",
      "m55_live_adapter_construction"
    ],
    "partial_evidence_refs": [
      "m55_stealth_reveal_backend_dry_run",
      "m55_stealth_reveal_service_dry_run"
    ],
    "execution_allowed": false,
    "live_coinbase_orders_ran": false,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "browser_authority": "display_only",
    "bff_authority": "forward_only_no_execution",
    "blocker_names": [
      "live_service_enablement_missing",
      "live_adapter_construction_missing",
      "active_placement_cancel_replace_execution_disabled",
      "live_reveal_exchange_submission_disabled",
      "live_repair_rollback_execution_disabled",
      "post_write_reconciliation_execution_disabled"
    ]
  },
  "blocker_closures": [
    {
      "closure_id": "m55_live_adapter_construction",
      "blocker": "live_adapter_construction_missing",
      "category": "live_execution_adapter",
      "status": "blocked",
      "blocking": true,
      "resolved": false,
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "required_contracts": [
        "application/admin_api/live_execution.py::build_live_execution_adapter_contract"
      ],
      "missing_contracts": [
        "application/admin_api/live_execution.py::build_live_execution_adapter_contract"
      ],
      "partial_evidence_present": true,
      "partial_evidence_refs": [
        "m55_stealth_reveal_backend_dry_run",
        "POST /api/v1/stealth/orders/{stealth_order_id}/reveal::live_execution_adapter"
      ],
      "partial_evidence_contracts": [
        "application/admin_api/live_execution.py::build_live_execution_adapter_contract",
        "application/admin_api/stealth_command_execution.py::live_execution_adapter resolver"
      ],
      "partial_evidence_detail": "The reveal route has backend-owned dry-run adapter readback evidence, but no live adapter has been constructed.",
      "next_backend_step": "Build the route-bound live execution adapter contract in backend code.",
      "live_service_enabled": false,
      "live_adapter_constructed": false,
      "manager_invocation_allowed": false,
      "coinbase_submit_allowed": false,
      "coinbase_cancel_allowed": false,
      "coinbase_read_allowed": false,
      "active_placement_cancel_replace_allowed": false,
      "repair_execution_allowed": false,
      "rollback_execution_allowed": false,
      "reconciliation_execution_allowed": false,
      "state_mutation_allowed": false,
      "live_coinbase_orders_ran": false,
      "submitted_notional_usdc": "0",
      "executed_notional_usdc": "0"
    }
  ]
}
```

All six `blocker_closures` rows follow that same authority model. They are
backend-owned evidence for missing implementation work only. They do not call
`StealthOrderManager`, construct live adapters, submit/cancel/read Coinbase
orders, cancel/replace active placements, execute repair or rollback, execute
reconciliation, mutate lifecycle/order/exchange state, or grant browser/BFF
execution authority.

Live-disabled non-create stealth command responses now also include
`stealth_command_execution_contract`. For example, a cancel dry-submit remains
blocked even when exact command-envelope context is present:

The JSON below abbreviates repeated readiness and clearance action rows for
readability. When a summary reports counts greater than the visible row count,
those counts refer to the complete backend payload; the listed summary refs
still match the complete `blocked_clearance_refs` sequence shown in the same
handoff.

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
      "cancel_replace_proof",
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
    "live_execution_service_source": "disabled_backend_service",
    "live_execution_service_missing_reason": "live_execution_disabled",
    "live_execution_service_contract": {
      "required": true,
      "present": true,
      "enabled": false,
      "backend_owned": true,
      "route_bound": true,
      "final_boundary": true,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "module_id": "stealth_orders",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "service_reference": "DisabledAdminApiLiveExecutionService.admission_state",
      "action_class": "live_exchange_cancel",
      "executable": false,
      "live_exchange_submission_allowed": false,
      "live_exchange_submitted": false,
      "latest_service_decision_available": true,
      "latest_service_decision_id": "live-service-decision-readback-001",
      "latest_service_decision_recorded_artifacts": ["explicit_backend_live_enablement_decision"],
      "latest_service_decision_recorded_artifacts_satisfy_enablement": false,
      "latest_service_decision_satisfied_enablement_artifacts": [],
      "latest_service_decision_unsatisfied_enablement_artifacts": [
        "explicit_backend_live_enablement_decision",
        "configured_admin_api_live_execution_service",
        "runtime_live_service_configuration",
        "deployment_live_service_enablement_record"
      ],
      "latest_service_decision_resolves_enablement": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "forbidden_methods": ["create_order", "cancel_order", "execute", "submit", "coinbase_client"]
    },
    "live_execution_intent_contract": {
      "required": true,
      "prepared": false,
      "backend_owned": true,
      "route_bound": true,
      "payload_bound": true,
      "idempotency_bound": true,
      "executable": false,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "method": "POST",
      "identity_key": "stealth_order_id",
      "identity_value": "stealth-123",
      "adapter_reference": "AdminApiCommandService.cancel_stealth_order_by_stealth_order_id",
      "actor_id": "operator-001",
      "idempotency_key": "idem-stealth-cancel-001",
      "operator_intent": "cancel_stealth_order",
      "payload_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "live_exchange_submitted": false
    },
    "active_placement_cancel_replace_contract": {
      "mutation_family": "stealth_cancel",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "method": "POST",
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "status": "blocked",
      "cancel_replace_required": true,
      "cancel_replace_allowed": false,
      "cancel_replace_ran": false,
      "cancel_replace_proof_required": true,
      "cancel_replace_proof_resolved": false,
      "cancel_replace_proof_id": null,
      "active_placement_exchange_truth_required": true,
      "active_placement_exchange_truth_resolved": false,
      "accepted_command_identity_keys": ["stealth_order_id"],
      "rejected_command_identity_keys": [
        "client_order_id",
        "active_placement_client_order_id",
        "exchange_order_id",
        "order_id"
      ],
      "missing_contracts": [
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_cancel_active_placement_cancel_proof",
        "stealth_cancel_exchange_reconciliation_proof",
        "stealth_cancel_state_transition_audit"
      ],
      "manager_invocation_ran": false,
      "coinbase_cancel_ran": false,
      "coinbase_submit_ran": false,
      "coinbase_read_ran": false,
      "reconciliation_executed": false,
      "lifecycle_state_mutated": false,
      "order_state_mutated": false,
      "exchange_state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    "command_specific_proof_contracts": [],
    "execution_readiness_stage_count": 4,
    "blocked_execution_readiness_stage_count": 4,
    "passed_execution_readiness_stage_count": 0,
    "execution_readiness_stages": [
      {
        "stage_order": 1,
        "workflow_family": "stealth_cancel_exchange_handling",
        "mutation_family": "stealth_cancel",
        "prerequisite": "approval_snapshot",
        "lookup_status": "missing",
        "status": "blocked",
        "next_required_contract": "POST /api/v1/admin/approvals/requests",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      }
    ],
    "live_execution_adapter_source": "disabled_stealth_command_live_adapter",
    "live_execution_adapter_status": "live_disabled",
    "live_execution_adapter_missing_reason": "live_execution_adapter_disabled",
    "live_execution_adapter_contract": {
      "required": true,
      "configured": false,
      "backend_owned": true,
      "route_bound": true,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "module_id": "stealth_orders",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "adapter_reference": "AdminApiCommandService.cancel_stealth_order_by_stealth_order_id",
      "action_class": "live_exchange_cancel",
      "executable": false,
      "route_mapping_satisfies_construction": false,
      "adapter_configuration_satisfies_construction": false,
      "construction_satisfaction_authority": "backend_live_adapter_construction_only",
      "satisfied_construction_artifacts": [],
      "unsatisfied_construction_artifacts": [
        "route_bound_stealth_live_execution_adapter",
        "shared_command_service_adapter",
        "route_inventory_execution_binding"
      ],
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "forbidden_methods": ["create_order", "cancel_order", "execute", "submit", "coinbase_client"]
    },
    "remaining_execution_blocker_count": 13,
    "remaining_execution_blockers": [
      {
        "blocker_order": 1,
        "blocker": "stealth_command_execution_contract_missing",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "application/admin_api/stealth_command_execution.py::build_stealth_command_execution_contract",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 2,
        "blocker": "live_execution_disabled",
        "source_prerequisite": "live_execution_service",
        "status": "blocked",
        "blocking": true,
        "missing_reason": "live_execution_disabled",
        "next_required_contract": "application/admin_api/live_execution.py::build_live_execution_service_contract",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 3,
        "blocker": "live_execution_adapter_disabled",
        "source_prerequisite": "live_execution_adapter",
        "status": "blocked",
        "blocking": true,
        "missing_reason": "live_execution_adapter_disabled",
        "next_required_contract": "application/admin_api/live_execution.py::build_live_execution_adapter_contract",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 4,
        "blocker": "stealth_manager_invocation_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "core/stealth_order_manager.py::cancel_stealth_order",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 5,
        "blocker": "active_placement_cancel_replace_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "core/stealth_order_manager.py active-placement cancel/replace path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 6,
        "blocker": "coinbase_order_submit_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "external/coinbase_api.py order submit path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 7,
        "blocker": "coinbase_order_cancel_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "external/coinbase_api.py cancel_order(client_order_id)",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 8,
        "blocker": "coinbase_read_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "external/coinbase_api.py read/reconcile path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 9,
        "blocker": "lifecycle_state_mutation_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "database stealth lifecycle write path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 10,
        "blocker": "order_state_mutation_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "database/order.py state write path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 11,
        "blocker": "exchange_state_mutation_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "exchange state reconciliation write path",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 12,
        "blocker": "reconciliation_execution_disabled",
        "source_prerequisite": null,
        "status": "blocked",
        "blocking": true,
        "next_required_contract": "application/admin_api reconciliation executor",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      },
      {
        "blocker_order": 13,
        "blocker": "post_write_reconciliation_missing",
        "source_prerequisite": "post_write_reconciliation",
        "status": "blocked",
        "blocking": true,
        "missing_reason": "no_matching_post_write_execution_journal",
        "next_required_contract": "POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "no_live_execution": true
      }
    ],
    "execution_candidate": {
      "mutation_family": "stealth_cancel",
      "workflow_family": "stealth_cancel_exchange_handling",
      "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "command_method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "manager_methods": [
        "core/stealth_order_manager.py::cancel_stealth_order",
        "bridges/stealth_order_bridge.py::cancel_stealth_order"
      ],
      "identity_key": "stealth_order_id",
      "identity_value": "stealth-123",
      "status": "blocked",
      "execution_candidate_available": true,
      "execution_allowed": false,
      "executable": false,
      "unresolved_blocker_count": 13,
      "unresolved_blockers": [
        "stealth_command_execution_contract_missing",
        "live_execution_disabled",
        "live_execution_adapter_disabled",
        "stealth_manager_invocation_disabled",
        "active_placement_cancel_replace_disabled",
        "coinbase_order_submit_disabled",
        "coinbase_order_cancel_disabled",
        "coinbase_read_disabled",
        "lifecycle_state_mutation_disabled",
        "order_state_mutation_disabled",
        "exchange_state_mutation_disabled",
        "reconciliation_execution_disabled",
        "post_write_reconciliation_missing"
      ],
      "canonical_execution_path": [
        "core/stealth_order_manager.py::cancel_stealth_order",
        "bridges/stealth_order_bridge.py::cancel_stealth_order"
      ],
      "manager_invocation_ran": false,
      "coinbase_order_submitted": false,
      "coinbase_order_cancel_submitted": false,
      "live_coinbase_read_ran": false,
      "reconciliation_executed": false,
      "state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "no_live_execution": true
    },
    "execution_preflight": {
      "mutation_family": "stealth_cancel",
      "workflow_family": "stealth_cancel_exchange_handling",
      "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "command_method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "identity_key": "stealth_order_id",
      "identity_value": "stealth-123",
      "status": "blocked",
      "preflight_available": true,
      "preflight_authority": "read_only_candidate_preflight",
      "candidate_ref": "execution_candidate",
      "candidate_executable": false,
      "candidate_execution_allowed": false,
      "all_blockers_resolved": false,
      "unresolved_blocker_count": 13,
      "check_count": 9,
      "blocking_check_count": 9,
      "passed_check_count": 0,
      "preflight_checks": [
        {
          "name": "execution_candidate",
          "category": "execution_candidate",
          "status": "blocked",
          "blocking": true,
          "owner": "admin_api_contract"
        },
        {
          "name": "live_execution_adapter",
          "category": "live_execution_adapter",
          "status": "blocked",
          "blocking": true,
          "owner": "admin_api_contract"
        },
        {
          "name": "coinbase_exchange",
          "category": "coinbase_exchange",
          "status": "blocked",
          "blocking": true,
          "owner": "exchange_integration"
        }
      ],
      "manager_invocation_ran": false,
      "coinbase_order_submitted": false,
      "coinbase_order_cancel_submitted": false,
      "live_coinbase_read_ran": false,
      "reconciliation_executed": false,
      "state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "no_live_execution": true
    },
    "execution_transition_barrier": {
      "mutation_family": "stealth_cancel",
      "workflow_family": "stealth_cancel_exchange_handling",
      "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "command_method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "identity_key": "stealth_order_id",
      "identity_value": "stealth-123",
      "status": "blocked",
      "transition_available": true,
      "transition_authority": "read_only_transition_barrier",
      "source_ref": "execution_preflight",
      "candidate_ref": "execution_candidate",
      "transition_allowed": false,
      "transition_executable": false,
      "all_preflight_checks_passed": false,
      "first_blocking_check": "execution_candidate",
      "first_blocking_category": "execution_candidate",
      "required_clearance_order": [
        "execution_candidate",
        "remaining_blocker_chain",
        "live_execution_service",
        "live_execution_adapter",
        "manager_invocation",
        "coinbase_exchange",
        "post_write_reconciliation",
        "state_mutation",
        "browser_bff_authority"
      ],
      "preflight_check_count": 9,
      "blocking_check_count": 9,
      "passed_check_count": 0,
      "unresolved_blocker_count": 13,
      "manager_invocation_ran": false,
      "coinbase_order_submitted": false,
      "coinbase_order_cancel_submitted": false,
      "live_coinbase_read_ran": false,
      "reconciliation_executed": false,
      "state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "no_live_execution": true
    },
    "execution_live_readiness": {
      "mutation_family": "stealth_cancel",
      "workflow_family": "stealth_cancel_exchange_handling",
      "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "command_method": "POST",
      "service_method": "cancel_stealth_order_by_stealth_order_id",
      "identity_key": "stealth_order_id",
      "identity_value": "stealth-123",
      "status": "blocked",
      "readiness_available": true,
      "readiness_authority": "read_only_m55_live_readiness",
      "source_ref": "execution_transition_barrier",
      "transition_barrier_passed": false,
      "m55_completion_claim_allowed": false,
      "live_enablement_decision_required": true,
      "live_execution_allowed": false,
      "executable": false,
      "handoff_blocker_count": 9,
      "handoff_blockers": [
        "execution_candidate",
        "remaining_blocker_chain",
        "live_execution_service",
        "live_execution_adapter",
        "manager_invocation",
        "coinbase_exchange",
        "post_write_reconciliation",
        "state_mutation",
        "browser_bff_authority"
      ],
      "required_backend_decisions": [
        "explicit_live_enablement_decision",
        "backend_live_service_configuration",
        "backend_live_adapter_construction",
        "manager_invocation_policy",
        "coinbase_exchange_submission_policy",
        "post_write_reconciliation_execution_policy",
        "state_mutation_policy"
      ],
      "backend_decision_count": 7,
      "backend_decisions": [
        {
          "decision": "explicit_live_enablement_decision",
          "status": "blocked",
          "resolved": false,
          "owner": "admin_api_contract",
          "required_artifact": "explicit_backend_live_enablement_decision",
          "missing_reason": "explicit_live_enablement_decision_missing",
          "resolution_authority": "backend_contract_required",
          "resolution_required": true,
          "resolution_allowed": false,
          "resolution_resolved": false,
          "resolution_artifacts": [
            "explicit_backend_live_enablement_decision",
            "route_bound_approval_snapshot"
          ],
          "missing_resolution_artifacts": [
            "explicit_backend_live_enablement_decision",
            "route_bound_approval_snapshot"
          ],
          "resolution_contract_refs": [
            "POST /api/v1/admin/approvals/requests"
          ],
          "resolution_evidence_refs": [
            "execution_live_readiness"
          ],
          "resolver_allowed": false,
          "resolver_ran": false,
          "decision_write_allowed": false,
          "decision_written": false,
          "resolution_plan_required": true,
          "resolution_plan_available": true,
          "resolution_plan_status": "blocked",
          "resolution_plan_authority": "backend_planning_only_no_resolution",
          "resolution_plan_steps": [
            "capture_route_bound_operator_approval",
            "verify_admission_audit_cap_guard_and_reconciliation_plan",
            "record_backend_live_enablement_decision"
          ],
          "missing_resolution_plan_steps": [
            "capture_route_bound_operator_approval",
            "verify_admission_audit_cap_guard_and_reconciliation_plan",
            "record_backend_live_enablement_decision"
          ],
          "resolution_dependency_refs": [
            "route_bound_approval_snapshot",
            "route_bound_admission_audit",
            "route_bound_cap_guard_decision",
            "route_bound_reconciliation_plan"
          ],
          "resolution_verification_gates": [
            "approval_snapshot_approved",
            "cap_guard_within_configured_limits",
            "admission_audit_recorded_for_exact_context",
            "reconciliation_plan_present_before_live_enablement"
          ],
          "resolution_readiness_items": [
            {
              "item_type": "plan_step",
              "item_name": "capture_route_bound_operator_approval",
              "item_order": 1,
              "status": "blocked",
              "required": true,
              "resolved": false,
              "source_ref": "resolution_plan_steps",
              "missing_reason": "resolution_plan_step_missing",
              "readiness_authority": "backend_planning_only_no_resolution",
              "execution_allowed": false,
              "executed": false,
              "resolver_allowed": false,
              "resolver_ran": false,
              "decision_write_allowed": false,
              "decision_written": false,
              "no_live_execution": true,
              "backend_owned": true,
              "route_bound": true,
              "command_context_bound": true,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "resolution_readiness_summary": {
            "source_ref": "resolution_readiness_items",
            "status": "blocked",
            "total_item_count": 11,
            "required_item_count": 11,
            "resolved_item_count": 0,
            "blocked_item_count": 11,
            "plan_step_count": 3,
            "dependency_count": 4,
            "verification_gate_count": 4,
            "blocking_item_names": [
              "capture_route_bound_operator_approval",
              "verify_admission_audit_cap_guard_and_reconciliation_plan",
              "record_backend_live_enablement_decision",
              "route_bound_approval_snapshot",
              "route_bound_admission_audit",
              "route_bound_cap_guard_decision",
              "route_bound_reconciliation_plan",
              "approval_snapshot_approved",
              "cap_guard_within_configured_limits",
              "admission_audit_recorded_for_exact_context",
              "reconciliation_plan_present_before_live_enablement"
            ],
            "missing_reasons": [
              "resolution_plan_step_missing",
              "resolution_dependency_missing",
              "resolution_verification_gate_missing"
            ],
            "first_blocking_item_name": "capture_route_bound_operator_approval",
            "summary_authority": "backend_derived_from_readiness_items",
            "execution_allowed": false,
            "executed": false,
            "resolver_allowed": false,
            "resolver_ran": false,
            "decision_write_allowed": false,
            "decision_written": false,
            "no_live_execution": true,
            "backend_owned": true,
            "route_bound": true,
            "command_context_bound": true,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution"
          },
          "resolution_handoff": {
            "source_ref": "resolution_readiness_summary",
            "status": "blocked",
            "decision": "explicit_live_enablement_decision",
            "owner": "admin_api_contract",
            "required_artifact": "explicit_backend_live_enablement_decision",
            "handoff_authority": "backend_planning_only_no_resolution",
            "clearance_categories": [
              "approval",
              "audit",
              "cap_guard",
              "reconciliation",
              "browser_authority"
            ],
            "blocked_clearance_refs": [
              "capture_route_bound_operator_approval",
              "verify_admission_audit_cap_guard_and_reconciliation_plan",
              "record_backend_live_enablement_decision",
              "route_bound_approval_snapshot",
              "route_bound_admission_audit",
              "route_bound_cap_guard_decision",
              "route_bound_reconciliation_plan",
              "approval_snapshot_approved",
              "cap_guard_within_configured_limits",
              "admission_audit_recorded_for_exact_context",
              "reconciliation_plan_present_before_live_enablement"
            ],
            "clearance_actions": [
              {
                "source_ref": "resolution_handoff",
                "status": "blocked",
                "decision": "explicit_live_enablement_decision",
                "clearance_category": "approval",
                "clearance_ref": "capture_route_bound_operator_approval",
                "readiness_item_type": "plan_step",
                "readiness_item_order": 1,
                "clearance_sequence": 1,
                "required_predecessor_refs": [],
                "blocking_successor_refs": [
                  "verify_admission_audit_cap_guard_and_reconciliation_plan",
                  "record_backend_live_enablement_decision",
                  "route_bound_approval_snapshot",
                  "route_bound_admission_audit",
                  "route_bound_cap_guard_decision",
                  "route_bound_reconciliation_plan",
                  "approval_snapshot_approved",
                  "cap_guard_within_configured_limits",
                  "admission_audit_recorded_for_exact_context",
                  "reconciliation_plan_present_before_live_enablement"
                ],
                "owner": "admin_api_contract",
                "required_artifact": "explicit_backend_live_enablement_decision",
                "required_backend_contract": "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                "required_backend_route": "/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                "required_backend_method": "POST",
                "required_backend_service": "AdminApprovalService",
                "required_evidence_ref": "route_bound_approval_snapshot",
                "dependency_authority": "backend_derived_from_readiness_item_order",
                "dependency_ready": false,
                "action_authority": "backend_planning_only_no_clearance",
                "clearance_ready": false,
                "resolver_allowed": false,
                "resolver_ran": false,
                "decision_write_allowed": false,
                "decision_written": false,
                "execution_allowed": false,
                "executed": false,
                "no_live_execution": true,
                "backend_owned": true,
                "route_bound": true,
                "command_context_bound": true,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution"
              }
            ],
            "clearance_dependency_summary": {
              "source_ref": "resolution_handoff.clearance_actions",
              "status": "blocked",
              "decision": "explicit_live_enablement_decision",
              "total_action_count": 11,
              "blocked_action_count": 11,
              "ready_action_count": 0,
              "dependency_ready_count": 0,
              "dependency_blocked_count": 11,
              "predecessor_edge_count": 55,
              "successor_edge_count": 55,
              "dependency_blocked_refs": [
                "capture_route_bound_operator_approval",
                "verify_admission_audit_cap_guard_and_reconciliation_plan",
                "record_backend_live_enablement_decision",
                "route_bound_approval_snapshot",
                "route_bound_admission_audit",
                "route_bound_cap_guard_decision",
                "route_bound_reconciliation_plan",
                "approval_snapshot_approved",
                "cap_guard_within_configured_limits",
                "admission_audit_recorded_for_exact_context",
                "reconciliation_plan_present_before_live_enablement"
              ],
              "clearable_action_refs": [],
              "terminal_action_refs": [
                "reconciliation_plan_present_before_live_enablement"
              ],
              "first_clearance_ref": "capture_route_bound_operator_approval",
              "first_dependency_blocked_ref": "capture_route_bound_operator_approval",
              "summary_authority": "backend_derived_from_clearance_actions",
              "dependency_graph_ready": false,
              "clearance_allowed": false,
              "execution_allowed": false,
              "executed": false,
              "resolver_allowed": false,
              "resolver_ran": false,
              "decision_write_allowed": false,
              "decision_written": false,
              "no_live_execution": true,
              "backend_owned": true,
              "route_bound": true,
              "command_context_bound": true,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            },
            "first_clearance_category": "approval",
            "first_clearance_ref": "capture_route_bound_operator_approval",
            "resolution_ready": false,
            "execution_allowed": false,
            "executed": false,
            "resolver_allowed": false,
            "resolver_ran": false,
            "decision_write_allowed": false,
            "decision_written": false,
            "no_live_execution": true,
            "backend_owned": true,
            "route_bound": true,
            "command_context_bound": true,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": "Resolution handoff is backend planning evidence only and cannot resolve decisions or enable execution."
          },
          "resolution_plan_execution_allowed": false,
          "resolution_plan_executed": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "no_live_execution": true
        }
      ],
      "forbidden_execution_claims": [
        "frontend_approval_as_authority",
        "bff_execution_authority",
        "route_local_executor"
      ],
      "manager_invocation_ran": false,
      "coinbase_order_submitted": false,
      "coinbase_order_cancel_submitted": false,
      "live_coinbase_read_ran": false,
      "reconciliation_executed": false,
      "state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "no_live_execution": true
    },
    "post_write_reconciliation_route": "/api/v1/admin/reconciliation/plans",
    "post_write_reconciliation_method": "POST",
    "post_write_reconciliation_source": "post_write_reconciliation_contract",
    "post_write_reconciliation_missing_reason": "post_write_reconciliation_missing",
    "post_write_reconciliation_boundary": {
      "boundary_type": "stealth_post_write_reconciliation_plan_boundary",
      "mutation_family": "stealth_cancel",
      "command_route": "/api/v1/stealth/orders/{stealth_order_id}/cancel",
      "post_write_reconciliation_route": "/api/v1/admin/reconciliation/plans",
      "post_write_reconciliation_method": "POST",
      "post_write_reconciliation_source": "post_write_reconciliation_contract",
      "required_evidence": [
        "route_bound_reconciliation_plan",
        "post_write_execution_journal",
        "post_write_completion_proof"
      ],
      "missing_evidence": [
        "route_bound_reconciliation_plan",
        "post_write_execution_journal",
        "post_write_completion_proof"
      ],
      "plan_write_ran": false,
      "reconciliation_executed": false,
      "coinbase_order_cancel_submitted": false,
      "live_coinbase_read_ran": false,
      "lifecycle_state_mutated": false,
      "order_state_mutated": false,
      "exchange_state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    "canonical_execution_path": [
      "core/stealth_order_manager.py::cancel_stealth_order",
      "bridges/stealth_order_bridge.py::cancel_stealth_order"
    ],
    "execution_boundary_authority": "backend_contract_only_no_execution",
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

Actual `execution_live_readiness` payloads also include
`backend_decisions`. Each row is blocked, required, unresolved, backend-owned,
route-bound, command-context-bound, browser `display_only`, and BFF
`forward_only_no_execution`, and names the decision owner, required artifact,
missing reason, resolution artifacts, missing resolution artifacts, backend
contract refs, evidence refs, disabled resolver flags, and disabled writer
flags. They also include ordered resolution plan steps, missing plan steps,
dependency refs, verification gates, `resolution_plan_execution_allowed=false`,
`resolution_plan_executed=false`, and `resolution_readiness_items` rows for
each plan step, dependency, and verification gate. These rows are not decision
resolution, decision writes, plan execution, readiness execution, or live
authority. They also include `resolution_readiness_summary`, a backend-derived
aggregate over those rows with counts, first-blocker, missing reasons, and
disabled execution/resolver/writer flags for display only. They also include
`resolution_handoff`, a backend-derived classification over the summary with
clearance categories, blocked clearance refs, first clearance evidence, and
disabled resolution/execution/writer flags. The handoff also includes
`clearance_actions` rows naming source readiness item type/order, clearance
sequence, predecessor refs, successor refs, backend contract, route, method,
service, artifact, evidence ref, dependency authority, dependency readiness,
action authority, and disabled resolver/writer/execution flags for each
blocked ref. The handoff and action rows are not a resolver, writer, live switch, adapter, manager path, Coinbase path,
reconciliation executor, state mutation path, browser authority, or BFF
execution authority.
`clearance_dependency_summary` aggregates those action rows with blocked/ready
counts, predecessor/successor edge counts, dependency-blocked refs, clearable
refs, terminal refs, and disabled graph/clearance/resolver/writer/execution
flags. It is not a resolver, writer, live switch, adapter, manager path,
Coinbase path, reconciliation executor, state mutation path, browser
authority, or BFF execution authority.
`backend_decision_resolution_summary` aggregates the full backend decision
ledger with blocked decision counts, owners, required artifacts, missing
reasons, first blocker, clearance action totals, and disabled
resolver/writer/completion/execution flags. It is also display-only backend
evidence and is not a resolver, writer, live switch, adapter, manager path,
Coinbase path, reconciliation executor, state mutation path, browser
authority, or BFF execution authority.
`backend_decision_resolution_work_items` and
`backend_decision_resolution_work_queue_summary` expose the first blocked
clearance action for each unresolved backend decision as a cross-decision work
queue. They name owners, artifacts, backend contracts, optional route/method/
service values, evidence refs, dependency state, and disabled
resolver/writer/execution flags. They are not a resolver, writer, live switch,
adapter, manager path, Coinbase path, reconciliation executor, state mutation
path, browser authority, or BFF execution authority.
`forbidden_execution_claim_evidence` and
`forbidden_execution_claim_summary` map each raw forbidden execution claim to
the backend decision, clearance category/ref, work queue ref, backend
contract/route/method/service, evidence ref, and disabled
claim-cleared/resolver/writer/execution flags that keep the claim blocked.
The summary aggregates blocked/cleared counts, blocking decisions, owners,
clearance refs, work queue refs, first claim evidence, and false
all-cleared/M55/live/executable flags. These fields are traceability only;
they are not a claim clearer, resolver, writer, live switch, adapter, manager
path, Coinbase path, reconciliation executor, state mutation path, browser
authority, or BFF execution authority.

Exact non-create command responses also include
`execution_readiness_stages`. These ordered rows are derived from the backend
prerequisite resolver and show the workflow family, prerequisite, lookup
status, next required contract, and no-live authority boundary. They are
display-only evidence; they do not record proofs, read Coinbase, invoke
managers, execute recovery/reconciliation, mutate state, or authorize
browser/BFF execution.
Stealth create dry-submit responses expose the same stage pattern under
`stealth_lifecycle_execution_contract.execution_readiness_stages`. These rows
show the create prerequisite chain and no-write/no-live posture, but they do
not authorize lifecycle writes, Coinbase submit/read, reconciliation
execution, manager invocation, or browser/BFF execution.

Reveal, move, reprice, recovery, and reconciliation responses use the same
field for their command-specific blocked proof routes. For reveal:

```json
{
  "command_specific_proof_contracts": [
    {
      "gate": "reveal_trigger",
      "route": "/api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
      "method": "POST",
      "action_class": "local_state_mutation",
      "required_permission": "stealth_reveal_trigger:record",
      "shared_method": "record_stealth_reveal_trigger_proof",
      "status": "blocked",
      "required": true,
      "blocking": true,
      "identity_key": "stealth_order_id",
      "command_identity_key": "stealth_order_id",
      "backend_owned": true,
      "route_bound": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    }
  ]
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
  "execution_contract": {
    "execution_allowed": false,
    "live_execution_service_source": "disabled_backend_service",
    "live_execution_service_missing_reason": "live_execution_disabled",
    "live_execution_service_contract": {
      "required": true,
      "present": true,
      "enabled": false,
      "backend_owned": true,
      "route_bound": true,
      "final_boundary": true,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "module_id": "stealth_orders",
      "route": "/api/v1/stealth/orders",
      "method": "POST",
      "service_method": "create_stealth_order",
      "service_reference": "DisabledAdminApiLiveExecutionService.admission_state",
      "action_class": "local_state_mutation",
      "executable": false,
      "live_exchange_submission_allowed": false,
      "live_exchange_submitted": false,
      "latest_service_decision_available": true,
      "latest_service_decision_id": "live-service-decision-readback-001",
      "latest_service_decision_recorded_artifacts": ["explicit_backend_live_enablement_decision"],
      "latest_service_decision_recorded_artifacts_satisfy_enablement": false,
      "latest_service_decision_satisfied_enablement_artifacts": [],
      "latest_service_decision_unsatisfied_enablement_artifacts": [
        "explicit_backend_live_enablement_decision",
        "configured_admin_api_live_execution_service",
        "runtime_live_service_configuration",
        "deployment_live_service_enablement_record"
      ],
      "latest_service_decision_resolves_enablement": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "forbidden_methods": ["create_order", "cancel_order", "execute", "submit", "coinbase_client"]
    },
    "live_execution_intent_contract": null,
    "live_execution_adapter_source": "disabled_stealth_command_live_adapter",
    "live_execution_adapter_status": "live_disabled",
    "live_execution_adapter_missing_reason": "live_execution_adapter_disabled",
    "live_execution_adapter_contract": {
      "required": true,
      "configured": false,
      "backend_owned": true,
      "route_bound": true,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "module_id": "stealth_orders",
      "route": "/api/v1/stealth/orders",
      "method": "POST",
      "service_method": "create_stealth_order",
      "adapter_reference": "AdminApiCommandService.create_stealth_order",
      "action_class": "local_state_mutation",
      "executable": false,
      "route_mapping_satisfies_construction": false,
      "adapter_configuration_satisfies_construction": false,
      "construction_satisfaction_authority": "backend_live_adapter_construction_only",
      "satisfied_construction_artifacts": [],
      "unsatisfied_construction_artifacts": [
        "route_bound_stealth_live_execution_adapter",
        "shared_command_service_adapter",
        "route_inventory_execution_binding"
      ],
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "forbidden_methods": ["create_order", "cancel_order", "execute", "submit", "coinbase_client"]
    },
    "post_write_reconciliation_route": "/api/v1/admin/reconciliation/plans",
    "post_write_reconciliation_method": "POST",
    "post_write_reconciliation_source": "post_write_reconciliation_contract",
    "post_write_reconciliation_missing_reason": "post_write_reconciliation_missing",
    "post_write_reconciliation_boundary": {
      "boundary_type": "stealth_post_write_reconciliation_plan_boundary",
      "mutation_family": "stealth_create",
      "command_route": "/api/v1/stealth/orders",
      "post_write_reconciliation_route": "/api/v1/admin/reconciliation/plans",
      "post_write_reconciliation_method": "POST",
      "post_write_reconciliation_source": "post_write_reconciliation_contract",
      "required_evidence": [
        "route_bound_reconciliation_plan",
        "post_write_execution_journal",
        "post_write_completion_proof"
      ],
      "missing_evidence": [
        "route_bound_reconciliation_plan",
        "post_write_execution_journal",
        "post_write_completion_proof"
      ],
      "plan_write_ran": false,
      "reconciliation_executed": false,
      "coinbase_order_submitted": false,
      "live_coinbase_read_ran": false,
      "lifecycle_state_mutated": false,
      "order_state_mutated": false,
      "exchange_state_mutated": false,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    },
    "canonical_execution_path": [
      "core/stealth_order_manager.py::create_stealth_order"
    ],
    "execution_boundary_authority": "backend_contract_only_no_execution",
    "manager_invocation_ran": false,
    "coinbase_order_submit_ran": false,
    "live_coinbase_read_ran": false,
    "reconciliation_executed": false
  },
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
  "proof_route_count": 6,
  "blocking_proof_route_count": 6,
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

Post-write reconciliation proof evidence is read back and written through:

```http
GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof
POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs
```

Those post-write proof records are append-only local evidence. They can bind a
guarded stealth command family to reviewed route-bound plan, post-write
journal, and completion references, but they do not satisfy the execution
prerequisite, invoke `StealthOrderManager`, call Coinbase, execute
reconciliation, cancel/replace active placements, mutate lifecycle/order/
exchange state, or grant browser/BFF execution authority.

Post-write execution-journal acceptance evidence is read back and written
through one path:

```http
GET /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals
POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals
```

The POST route is backend-owned append-only evidence only. It requires the
safe matching post-write proof, exact guarded command context, idempotency,
operator intent, admission/audit/cap prerequisites, and `reconciliation:record`.
It does not execute or verify reconciliation, call Coinbase, invoke managers,
cancel/replace active placements, mutate lifecycle/order/exchange state, or
grant browser/BFF execution authority.

Post-write reconciliation verification evidence is read back and written
through one path:

```http
GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications
POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications
```

The POST route is backend-owned append-only evidence only. It requires the
safe matching post-write proof, accepted execution journal, exact guarded
command context, idempotency, operator intent, admission/audit/cap
prerequisites, and `reconciliation:record`. It may participate in resolving
only the `post_write_reconciliation` prerequisite evidence as part of the
exact safe proof, accepted journal, and verification chain. It does not execute
reconciliation, call Coinbase, invoke managers, cancel/replace active
placements, mutate lifecycle/order/exchange state, or grant browser/BFF
execution authority.

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
    "cancel_replace_proof",
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
and reprice rows require `active_placement_exchange_truth`; cancel, move, and
reprice also require `cancel_replace_proof`. The ledger does not approve
commands, execute commands, read Coinbase, call `StealthOrderManager`,
cancel/replace placements, execute reconciliation, mutate state, or grant
browser/BFF authority.

The `cancel_replace_boundaries` array gives cancel, move, and reprice one
shared blocked evidence shape. It is not a cancel/replace executor:

```json
{
  "mutation_family": "stealth_move",
  "route": "/api/v1/stealth/orders/{stealth_order_id}/move",
  "method": "POST",
  "identity_key": "stealth_order_id",
  "command_identity_key": "stealth_order_id",
  "status": "blocked",
  "cancel_replace_required": true,
  "cancel_replace_allowed": false,
  "cancel_replace_ran": false,
  "cancel_replace_proof_required": true,
  "cancel_replace_proof_resolved": false,
  "cancel_replace_proof_id": null,
  "active_placement_exchange_truth_required": true,
  "active_placement_exchange_truth_resolved": false,
  "accepted_command_identity_keys": ["stealth_order_id"],
  "rejected_command_identity_keys": [
    "client_order_id",
    "active_placement_client_order_id",
    "exchange_order_id",
    "order_id"
  ],
  "required_gate_chain": [
    "idempotency",
    "operator_intent",
    "payload_hash",
    "approval_snapshot",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "active_placement_exchange_truth",
    "cancel_replace_proof",
    "post_live_reconciliation"
  ],
  "missing_contracts": [
    "stealth_active_placement_exchange_truth_proof_contract",
    "stealth_move_mutation_claim_snapshot_contract",
    "stealth_cancel_replace_proof_record_contract",
    "stealth_move_active_placement_cancel_replace_proof",
    "stealth_move_reconciliation_proof"
  ],
  "canonical_behavior_path": [
    "api/v1/routes/stealth.py::move_stealth_order_by_stealth_order_id",
    "application/admin_api/command_service.py::move_stealth_order_by_stealth_order_id",
    "core/stealth_order_manager.py::build_stealth_move_plan",
    "core/stealth_order_manager.py::execute_stealth_move",
    "existing cancel/replace path only after mutation claim and active-placement proof"
  ],
  "manager_invocation_allowed": false,
  "manager_invocation_ran": false,
  "coinbase_cancel_ran": false,
  "coinbase_submit_ran": false,
  "coinbase_read_ran": false,
  "reconciliation_executed": false,
  "lifecycle_state_mutated": false,
  "order_state_mutated": false,
  "exchange_state_mutated": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution"
}
```

These rows only describe the future backend-owned boundary. They do not call
Coinbase, invoke `StealthOrderManager`, build or execute move/reprice plans,
cancel/replace active placements, mutate state, execute reconciliation, or
grant browser/BFF authority.
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
Mutation-claim proof persistence and resolver examples live in
[Stealth Mutation-Claim Snapshot Proof Examples](stealth-mutation-claim-proofs.md).
The resolver reads the latest proof for the same `stealth_order_id` and fails
closed if that latest proof is unsafe, stale, or bound to different guarded
command context, even when an older proof would have matched.
Recovery proof persistence and resolver examples live in
[Stealth Recovery Proof Examples](stealth-recovery-proofs.md). The resolver
reads the latest proof for the same `stealth_order_id` and fails closed if
that latest proof is unsafe, stale, or bound to different guarded recovery
command context.
Reconciliation proof persistence and resolver examples live in
[Stealth Reconciliation Proof Examples](stealth-reconciliation-proofs.md). The
resolver reads the latest proof for the same `stealth_order_id` and fails
closed if that latest proof is unsafe, stale, or bound to different guarded
reconciliation command context.
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
      "GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof",
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
        "route": "/api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof",
        "method": "GET",
        "action_class": "read_only",
        "required_permission": "audit:read",
        "shared_method": "build_stealth_reconciliation_proof",
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
