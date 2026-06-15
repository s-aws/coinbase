"""Shared no-live active-placement cancel/replace boundary evidence."""

from __future__ import annotations

from core.enums import AdminApiGateStatus, AdminApiMutationFamilyType

from .models import StealthCommandSuiteCancelReplaceBoundaryItem


CANCEL_REPLACE_REQUIRED_CONTRACTS_BY_FAMILY: dict[
    AdminApiMutationFamilyType, tuple[str, ...]
] = {
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_cancel_active_placement_cancel_proof",
        "stealth_cancel_exchange_reconciliation_proof",
        "stealth_cancel_state_transition_audit",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_move_mutation_claim_snapshot_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_move_active_placement_cancel_replace_proof",
        "stealth_move_reconciliation_proof",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_reprice_cooldown_claim_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_reprice_active_placement_cancel_replace_proof",
        "stealth_reprice_reconciliation_proof",
    ),
}

CANCEL_REPLACE_BEHAVIOR_PATHS_BY_FAMILY: dict[
    AdminApiMutationFamilyType, tuple[str, ...]
] = {
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "api/v1/routes/stealth.py::cancel_stealth_order_by_stealth_order_id",
        "application/admin_api/command_service.py::cancel_stealth_order_by_stealth_order_id",
        "bridges/stealth_order_bridge.py",
        "core/stealth_order_manager.py",
        "CoinbaseClient.cancel_order(client_order_id) only after backend-owned admission and active-placement proof",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "api/v1/routes/stealth.py::move_stealth_order_by_stealth_order_id",
        "application/admin_api/command_service.py::move_stealth_order_by_stealth_order_id",
        "core/stealth_order_manager.py::build_stealth_move_plan",
        "core/stealth_order_manager.py::execute_stealth_move",
        "existing cancel/replace path only after mutation claim and active-placement proof",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "api/v1/routes/movement_repricing.py::reprice_stealth_order_by_stealth_order_id",
        "application/admin_api/command_service.py::reprice_stealth_order_by_stealth_order_id",
        "bridges/stealth_order_bridge.py",
        "core/stealth_order_manager.py",
        "existing repricing path only after cooldown/claim and active-placement proof",
    ),
}

CANCEL_REPLACE_DETAILS_BY_FAMILY: dict[AdminApiMutationFamilyType, str] = {
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "Stealth cancel must prove the active placement was cancelled "
        "or otherwise reconciled before a revealed stealth order can "
        "be locally cancelled. This row is boundary evidence only."
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "Stealth move must prove mutation-claim ownership and active "
        "placement cancel/replace completion before invoking the "
        "existing move execution path. This row is boundary evidence only."
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "Movement reprice must prove cooldown/claim authority and active "
        "placement cancel/replace completion before repricing execution. "
        "This row is boundary evidence only."
    ),
}

CANCEL_REPLACE_DOCUMENTATION_REFS_BY_FAMILY: dict[
    AdminApiMutationFamilyType, tuple[str, ...]
] = {
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "README.stealth-command-suite.md",
        "docs/agents/INVARIANTS.md",
        "docs/COMMAND_WORKFLOWS.md",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "README.stealth-command-suite.md",
        "README.movement-repricing.md",
        "docs/agents/INVARIANTS.md",
        "docs/COMMAND_WORKFLOWS.md",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "README.movement-repricing.md",
        "README.stealth-command-suite.md",
        "docs/agents/INVARIANTS.md",
        "docs/COMMAND_WORKFLOWS.md",
    ),
}


def build_stealth_active_placement_cancel_replace_contract(
    *,
    mutation_family: AdminApiMutationFamilyType,
    route: str,
    method: str = "POST",
    identity_key: str = "stealth_order_id",
    active_placement_exchange_truth_resolved: bool = False,
    cancel_replace_proof_resolved: bool = False,
    cancel_replace_proof_id: str | None = None,
) -> StealthCommandSuiteCancelReplaceBoundaryItem | None:
    """Build no-live cancel/replace boundary evidence for supported commands."""

    required_contracts = CANCEL_REPLACE_REQUIRED_CONTRACTS_BY_FAMILY.get(
        mutation_family
    )
    if required_contracts is None:
        return None

    missing_contracts = list(required_contracts)
    if active_placement_exchange_truth_resolved:
        missing_contracts = [
            contract
            for contract in missing_contracts
            if contract != "stealth_active_placement_exchange_truth_proof_contract"
        ]
    if cancel_replace_proof_resolved:
        missing_contracts = [
            contract
            for contract in missing_contracts
            if contract != "stealth_cancel_replace_proof_record_contract"
        ]

    return StealthCommandSuiteCancelReplaceBoundaryItem(
        mutation_family=mutation_family,
        route=route,
        method=method,
        identity_key=identity_key,
        command_identity_key="stealth_order_id",
        status=AdminApiGateStatus.BLOCKED,
        cancel_replace_required=True,
        cancel_replace_allowed=False,
        cancel_replace_ran=False,
        cancel_replace_proof_required=True,
        cancel_replace_proof_resolved=cancel_replace_proof_resolved,
        cancel_replace_proof_id=cancel_replace_proof_id,
        active_placement_exchange_truth_required=True,
        active_placement_exchange_truth_resolved=(
            active_placement_exchange_truth_resolved
        ),
        accepted_command_identity_keys=["stealth_order_id"],
        rejected_command_identity_keys=[
            "client_order_id",
            "active_placement_client_order_id",
            "exchange_order_id",
            "order_id",
        ],
        active_placement_client_order_id_authority="evidence_only",
        exchange_order_id_authority="evidence_only",
        required_gate_chain=[
            "idempotency",
            "operator_intent",
            "payload_hash",
            "approval_snapshot",
            "admission_audit",
            "cap_guard_decision",
            "reconciliation_plan",
            "active_placement_exchange_truth",
            "cancel_replace_proof",
            "post_live_reconciliation",
        ],
        required_contracts=list(required_contracts),
        missing_contracts=missing_contracts,
        canonical_behavior_path=list(
            CANCEL_REPLACE_BEHAVIOR_PATHS_BY_FAMILY[mutation_family]
        ),
        backend_owned=True,
        route_bound=True,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        manager_invocation_allowed=False,
        manager_invocation_ran=False,
        coinbase_cancel_ran=False,
        coinbase_submit_ran=False,
        coinbase_read_ran=False,
        reconciliation_required=True,
        reconciliation_executed=False,
        lifecycle_state_mutated=False,
        order_state_mutated=False,
        exchange_state_mutated=False,
        documentation_refs=list(
            CANCEL_REPLACE_DOCUMENTATION_REFS_BY_FAMILY[mutation_family]
        ),
        detail=CANCEL_REPLACE_DETAILS_BY_FAMILY[mutation_family],
    )
