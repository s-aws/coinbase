# Futures/Perpetuals Examples

These examples use the enterprise Admin API. They are read-only examples and
do not place, close, cancel, or modify Coinbase orders.

Start the local Admin API:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

## Command-Suite Contract Evidence

The active 5341-5360 range adds read-only M57 futures/perpetual risk proof
payload field and validation contract evidence to the existing command-suite
evidence. Each readiness decision, ordered closure step, risk proof
requirement, proof contract, payload field, and acceptance criterion is
derived from backend-owned
prerequisites, request fields, semantic guards, evidence routes, missing
evidence refs, and missing backend contracts. It is not a command route,
enabled proof writer, registered payload validator, command draft surface, or
execution approval.

```http
GET /api/v1/futures/command-suite
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

```json
{
  "type": "admin_futures_command_suite",
  "module_id": "futures_perpetuals",
  "approved_phase_range": "5341-5360",
  "status": "blocked",
  "command_count": 4,
  "blocked_command_count": 4,
  "executable_command_count": 0,
  "command_route_count": 0,
  "command_draft_allowed_count": 0,
  "request_field_count": 22,
  "required_request_field_count": 22,
  "blocking_request_field_count": 22,
  "semantic_guard_count": 33,
  "blocking_semantic_guard_count": 33,
  "risk_semantic_guard_count": 12,
  "readiness_decision_count": 4,
  "blocked_readiness_decision_count": 4,
  "ready_readiness_decision_count": 0,
  "readiness_closure_step_count": 28,
  "blocking_readiness_closure_step_count": 28,
  "risk_proof_requirement_count": 20,
  "blocking_risk_proof_requirement_count": 20,
  "risk_proof_contract_count": 40,
  "blocking_risk_proof_contract_count": 40,
  "registered_risk_proof_route_count": 0,
  "enabled_risk_proof_writer_count": 0,
  "risk_proof_payload_field_count": 200,
  "blocking_risk_proof_payload_field_count": 200,
  "present_risk_proof_payload_field_count": 0,
  "registered_risk_proof_payload_validation_count": 0,
  "risk_proof_acceptance_criterion_count": 100,
  "blocking_risk_proof_acceptance_criterion_count": 100,
  "accepted_risk_proof_acceptance_criterion_count": 0,
  "forbidden_spot_assumptions": [
    "spot_wallet_available",
    "spot_no_shorting",
    "spot_usdc_quote_required",
    "spot_average_cost_basis",
    "spot_inventory_lot_authority"
  ],
  "commands": [
    {
      "command": "futures_place",
      "status": "blocked",
      "action_class": "live_exchange_place",
      "route": null,
      "service_method": "place_futures_order_contract_required",
      "identity_key": "product_id",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::place_futures_order",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "missing_backend_contracts": [
        "application/admin_api/futures_command_service.py::place_futures_order",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "request_field_count": 7,
      "blocking_request_field_count": 7,
      "semantic_guard_count": 10,
      "blocking_semantic_guard_count": 10,
      "risk_semantic_guard_count": 4,
      "request_fields": [
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "size",
          "status": "blocked",
          "identity_field": false,
          "risk_field": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        }
      ],
      "semantic_guards": [
        {
          "semantic_guard": "product_scope",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/futures/positions"
          ],
          "evidence_route_count": 2,
          "missing_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "missing_evidence_count": 2,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "identity_semantic": true,
          "risk_semantic": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "semantic_guard": "margin_collateral",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/admin/cap-guard/decisions"
          ],
          "evidence_route_count": 2,
          "missing_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "missing_evidence_count": 2,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "identity_semantic": false,
          "risk_semantic": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "semantic_guard": "live_execution_boundary",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/admin/live-enablement",
            "/api/v1/admin/live-execution/service-decisions",
            "/api/v1/admin/live-execution/adapter-decisions"
          ],
          "evidence_route_count": 3,
          "missing_evidence_refs": [
            "futures_live_enablement_precondition_contract",
            "futures_live_service_decision_contract",
            "futures_live_adapter_decision_contract"
          ],
          "missing_evidence_count": 3,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "execution_semantic": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "ready": false,
        "blocker_count": 30,
        "blocking_prerequisite_count": 1,
        "blocking_request_field_count": 7,
        "blocking_semantic_guard_count": 10,
        "missing_backend_contract_count": 3,
        "missing_evidence_ref_count": 13,
        "evidence_route_count": 6,
        "first_blocker": "prerequisite:product_scope",
        "next_required_backend_contract": "application/admin_api/futures_command_service.py::place_futures_order",
        "command_route_registered": false,
        "command_draft_allowed": false,
        "execution_allowed": false,
        "backend_owned": true,
        "read_only": true,
        "spot_rule_authority": false,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution"
      },
      "readiness_closure_step_count": 7,
      "blocking_readiness_closure_step_count": 7,
      "readiness_closure_steps": [
        {
          "step": "resolve_prerequisite_contracts",
          "sequence": 1,
          "status": "blocked",
          "blocking": true,
          "required_evidence_refs": ["product_scope"],
          "command_route_registered": false,
          "command_draft_allowed": false,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "step": "define_backend_command_service",
          "sequence": 4,
          "status": "blocked",
          "required_backend_contract": "application/admin_api/futures_command_service.py::place_futures_order",
          "required_evidence_refs": [
            "application/admin_api/futures_command_service.py::place_futures_order",
            "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
            "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
          ],
          "required_evidence_count": 3,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        },
        {
          "step": "run_contextless_review_gate",
          "sequence": 7,
          "status": "blocked",
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "risk_proof_requirement_count": 6,
      "blocking_risk_proof_requirement_count": 6,
      "risk_proof_contract_count": 12,
      "blocking_risk_proof_contract_count": 12,
      "registered_risk_proof_route_count": 0,
      "enabled_risk_proof_writer_count": 0,
      "risk_proof_acceptance_criterion_count": 30,
      "blocking_risk_proof_acceptance_criterion_count": 30,
      "accepted_risk_proof_acceptance_criterion_count": 0,
      "risk_proof_requirements": [
        {
          "proof_kind": "product_scope",
          "sequence": 1,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "product_scope",
          "applies_to_fields": ["product_id"],
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/futures/positions"
          ],
          "required_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "missing_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "runtime_evidence_observed": false,
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "proof_contract_count": 2,
          "blocking_proof_contract_count": 2,
          "registered_proof_route_count": 0,
          "enabled_proof_writer_count": 0,
          "proof_contracts": [
            {
              "contract_kind": "proof_route",
              "required_backend_contract": "application/admin_api/futures_proof_routes.py::post_futures_place_product_scope_proof",
              "required_route_path": "/api/v1/futures/proofs/futures_place/product_scope",
              "required_method": "POST",
              "required_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "missing_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "route_registered": false,
              "writer_enabled": false,
              "execution_allowed": false
            },
            {
              "contract_kind": "proof_writer",
              "required_backend_contract": "application/admin_api/futures_proof_writer.py::write_futures_place_product_scope_proof",
              "required_route_path": null,
              "required_method": "LOCAL",
              "required_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "route_registered": false,
              "writer_enabled": false,
              "execution_allowed": false
            }
          ],
          "payload_field_count": 10,
          "blocking_payload_field_count": 10,
          "present_payload_field_count": 0,
          "registered_payload_validation_count": 0,
          "payload_fields": [
            {
              "field": "command",
              "payload_path": "proof_payload.command",
              "validation_rule": "Must equal futures_place.",
              "required_evidence_ref": "futures_place_product_scope_payload_command_validated",
              "missing_evidence_ref": "futures_place_product_scope_payload_command_validated",
              "payload_field_present": false,
              "validation_registered": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            },
            {
              "field": "identity_key",
              "payload_path": "proof_payload.identity.key",
              "validation_rule": "Must equal product_id.",
              "required_evidence_ref": "futures_place_product_scope_payload_identity_key_validated",
              "missing_evidence_ref": "futures_place_product_scope_payload_identity_key_validated",
              "payload_field_present": false,
              "validation_registered": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "acceptance_criterion_count": 5,
          "blocking_acceptance_criterion_count": 5,
          "accepted_acceptance_criterion_count": 0,
          "acceptance_criteria": [
            {
              "check": "required_evidence_present",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_product_scope_readback",
              "missing_evidence_ref": "futures_product_scope_readback",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "command_route_registered": false,
              "command_draft_allowed": false,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            },
            {
              "check": "proof_route_registered",
              "sequence": 2,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "missing_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false
            },
            {
              "check": "proof_writer_reviewed",
              "sequence": 3,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false
            },
            {
              "check": "spot_rule_boundary_reviewed",
              "sequence": 4,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_spot_rule_boundary_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_spot_rule_boundary_reviewed",
              "negative_check": true,
              "accepted": false,
              "satisfies_risk_proof": false,
              "spot_rule_authority": false
            },
            {
              "check": "browser_bff_authority_reviewed",
              "sequence": 5,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_browser_bff_authority_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_browser_bff_authority_reviewed",
              "negative_check": true,
              "accepted": false,
              "satisfies_risk_proof": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "all_acceptance_criteria_accepted": false,
          "satisfies_risk_proof": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "proof_kind": "margin_collateral",
          "sequence": 2,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "margin_collateral",
          "applies_to_fields": ["margin_mode", "leverage"],
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/admin/cap-guard/decisions"
          ],
          "required_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "missing_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "runtime_evidence_observed": true,
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "proof_kind": "reconciliation_plan",
          "sequence": 6,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "reconciliation_plan",
          "applies_to_fields": ["client_order_id"],
          "evidence_routes": ["/api/v1/admin/reconciliation/plans"],
          "required_evidence_refs": [
            "futures_reconciliation_plan_contract"
          ],
          "missing_evidence_refs": [
            "futures_reconciliation_plan_contract"
          ],
          "runtime_evidence_observed": false,
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_close_reduce",
      "status": "blocked",
      "action_class": "live_exchange_place",
      "route": null,
      "service_method": "close_or_reduce_futures_position_contract_required",
      "identity_key": "position_key",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "missing_backend_contracts": [
        "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 33,
        "missing_backend_contract_count": 3,
        "next_required_backend_contract": "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
        "command_route_registered": false,
        "command_draft_allowed": false,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 7,
      "blocking_readiness_closure_step_count": 7,
      "readiness_closure_steps": [
        {
          "step": "define_backend_command_service",
          "sequence": 4,
          "status": "blocked",
          "required_backend_contract": "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
          "required_evidence_refs": [
            "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
            "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
            "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
          ],
          "required_evidence_count": 3,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_cancel",
      "status": "blocked",
      "action_class": "live_exchange_cancel",
      "route": null,
      "service_method": "cancel_futures_order_contract_required",
      "identity_key": "client_order_id",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::cancel_futures_order",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "missing_backend_contracts": [
        "application/admin_api/futures_command_service.py::cancel_futures_order",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
      ],
      "semantic_guard_count": 5,
      "blocking_semantic_guard_count": 5,
      "risk_semantic_guard_count": 0,
      "request_fields": [
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "detail": "Futures cancel must call the project wrapper with client_order_id; exchange order_id is exchange evidence only."
        },
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": false
        },
        {
          "field": "operator_notes",
          "status": "blocked",
          "identity_field": false
        }
      ],
      "semantic_guards": [
        {
          "semantic_guard": "idempotency",
          "status": "blocked",
          "identity_semantic": true,
          "detail": "Futures cancel must call cancel_order with client_order_id; exchange order_id is exchange evidence only."
        },
        {
          "semantic_guard": "admission_audit",
          "status": "blocked",
          "audit_semantic": true,
          "spot_rule_authority": false
        }
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 18,
        "missing_backend_contract_count": 2,
        "next_required_backend_contract": "application/admin_api/futures_command_service.py::cancel_futures_order",
        "command_route_registered": false,
        "command_draft_allowed": false,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 7,
      "blocking_readiness_closure_step_count": 7,
      "readiness_closure_steps": [
        {
          "step": "define_backend_command_service",
          "sequence": 4,
          "status": "blocked",
          "required_backend_contract": "application/admin_api/futures_command_service.py::cancel_futures_order",
          "required_evidence_refs": [
            "application/admin_api/futures_command_service.py::cancel_futures_order",
            "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"
          ],
          "required_evidence_count": 2,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_reconcile",
      "status": "blocked",
      "action_class": "local_state_mutation",
      "route": null,
      "service_method": "record_futures_reconciliation_contract_required",
      "identity_key": "position_key",
      "required_backend_contracts": [
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation"
      ],
      "missing_backend_contracts": [
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation"
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 25,
        "missing_backend_contract_count": 2,
        "next_required_backend_contract": "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "command_route_registered": false,
        "command_draft_allowed": false,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 7,
      "blocking_readiness_closure_step_count": 7,
      "readiness_closure_steps": [
        {
          "step": "define_backend_command_service",
          "sequence": 4,
          "status": "blocked",
          "required_backend_contract": "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
          "required_evidence_refs": [
            "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
            "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation"
          ],
          "required_evidence_count": 2,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    }
  ],
  "spot_rule_authority": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "live_coinbase_orders_ran": false,
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0"
}
```

Spot wallet, no-shorting, USDC, cost-basis, and inventory-lot rules are forbidden
as futures/perpetual command authority. Readiness decisions report blocker
counts and the next missing backend contract; they do not make any command
ready while `command_route_registered=false`, `command_draft_allowed=false`,
and `execution_allowed=false`.

## Account Evidence

```http
GET /api/v1/futures/account
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

```json
{
  "type": "admin_futures_account",
  "configured_product_scope": ["BIP-20DEC30-CDE"],
  "observed_position_scope": ["BIP-20DEC30-CDE"],
  "collateral": {
    "name": "collateral",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "margin": {
    "name": "margin",
    "status": "observed",
    "source": "fee_manager",
    "value": {"margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"}
  },
  "funding": {
    "name": "funding",
    "status": "not_modeled",
    "source": "backend_contract"
  },
  "liquidation": {
    "name": "liquidation",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "reduce_only_close_only": {
    "name": "reduce_only_close_only",
    "status": "observed",
    "source": "position_side_derivation"
  },
  "position_pnl": {
    "name": "position_pnl",
    "status": "observed",
    "source": "runtime_positions"
  },
  "position_count": 1,
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position List

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Rows are keyed by `position_key`:

```json
{
  "type": "admin_futures_positions",
  "filters": {
    "product_id": "BIP-20DEC30-CDE",
    "position_side": "LONG",
    "limit": 50,
    "offset": 0
  },
  "count": 1,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "returned_count": 1,
    "total_matching_count": 1,
    "next_offset": null,
    "has_more": false
  },
  "items": [
    {
      "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
      "product_id": "BIP-20DEC30-CDE",
      "product_type": "FUTURE",
      "position_side": "LONG",
      "close_order_side": "SELL",
      "source": "runtime_orderbook"
    }
  ],
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position Detail

```http
GET /api/v1/futures/positions/futures_position%3Aruntime%3ABIP-20DEC30-CDE
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The path uses `position_key`. Do not replace it with `client_order_id` or
Coinbase `order_id`.

## Operator Rules

- Treat `configured_product_scope` as configured metadata coverage.
- Treat `observed_position_scope` as observed runtime position coverage.
- Treat close/reduce sides as backend-derived from position side, not as
  exchange-observed order flags.
- Treat `funding.status="not_modeled"` as unsupported until the backend
  contract is extended.
- Live Coinbase execution for these examples: not run; notional `$0`.
