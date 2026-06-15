"""Shared no-live active-placement exchange-truth boundary evidence."""

from __future__ import annotations

from collections.abc import Sequence

from core.enums import AdminApiGateStatus, AdminApiMutationFamilyType

from .models import (
    StealthCommandSuiteCoverageGapEvidenceRouteItem,
    StealthCommandSuiteExchangeTruthItem,
)


EXCHANGE_TRUTH_SURFACES_BY_FAMILY: dict[AdminApiMutationFamilyType, tuple[str, ...]] = {
    AdminApiMutationFamilyType.STEALTH_CREATE: (
        "GET /api/v1/stealth/orders",
        "GET /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof",
        "GET /api/v1/stealth/orders/{stealth_order_id}",
        "GET /api/v1/stealth/command-suite",
    ),
    AdminApiMutationFamilyType.STEALTH_REVEAL: (
        "GET /api/v1/stealth/orders/{stealth_order_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/command-suite",
    ),
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "GET /api/v1/stealth/orders/{stealth_order_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/command-suite",
        "GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "GET /api/v1/movement-repricing/stealth/{stealth_order_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof",
        "GET /api/v1/stealth/command-suite",
    ),
    AdminApiMutationFamilyType.STEALTH_RECOVERY: (
        "GET /api/v1/admin/recovery-gate",
        "GET /api/v1/stealth/orders/{stealth_order_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/command-suite",
    ),
    AdminApiMutationFamilyType.STEALTH_RECONCILIATION: (
        "GET /api/v1/admin/reconciliation/plans",
        "GET /api/v1/admin/reconciliation/plans/{plan_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof",
        "GET /api/v1/stealth/command-suite",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "GET /api/v1/movement-repricing/stealth/{stealth_order_id}",
        "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
        "GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof",
        "GET /api/v1/stealth/command-suite",
    ),
}

EXCHANGE_TRUTH_CONTRACTS_BY_FAMILY: dict[
    AdminApiMutationFamilyType, tuple[str, ...]
] = {
    AdminApiMutationFamilyType.STEALTH_CREATE: (
        "stealth_create_guard_contract",
        "stealth_create_admission_audit",
        "stealth_create_reconciliation_plan",
        "stealth_create_lifecycle_write_guard_proof",
        "stealth_create_lifecycle_write_execution_contract",
    ),
    AdminApiMutationFamilyType.STEALTH_REVEAL: (
        "stealth_reveal_trigger_guard",
        "stealth_reveal_exchange_submission_adapter",
        "stealth_active_placement_audit",
        "stealth_reveal_reconciliation_proof",
    ),
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_cancel_active_placement_cancel_proof",
        "stealth_cancel_exchange_reconciliation_proof",
        "stealth_cancel_state_transition_audit",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_move_active_placement_cancel_replace_proof",
        "stealth_move_mutation_claim_snapshot_contract",
        "stealth_move_reconciliation_proof",
    ),
    AdminApiMutationFamilyType.STEALTH_RECOVERY: (
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_recovery_preview_contract",
        "stealth_recovery_repair_result_contract",
        "stealth_recovery_rollback_contract",
        "stealth_recovery_reconciliation_proof",
    ),
    AdminApiMutationFamilyType.STEALTH_RECONCILIATION: (
        "stealth_reconciliation_plan_contract",
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_reconciliation_executor",
        "stealth_reconciliation_completion_proof",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_cancel_replace_proof_record_contract",
        "stealth_reprice_active_placement_cancel_replace_proof",
        "stealth_reprice_cooldown_claim_contract",
        "stealth_reprice_reconciliation_proof",
    ),
}

EXCHANGE_TRUTH_DETAILS_BY_FAMILY: dict[AdminApiMutationFamilyType, str] = {
    AdminApiMutationFamilyType.STEALTH_CREATE: (
        "Create does not consume an active placement, but it still needs "
        "backend lifecycle-write guard, admission, and reconciliation evidence "
        "before it can invoke the manager."
    ),
    AdminApiMutationFamilyType.STEALTH_REVEAL: (
        "Reveal creates a placement and therefore needs trigger, submission, "
        "active-placement audit, and reconciliation evidence before it can call "
        "the existing reveal path."
    ),
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "Cancel must prove active placement reality before any local stealth "
        "state transition can be recorded."
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "Move must prove mutation-claim ownership and active-placement "
        "cancel/replace exchange truth before it can call the existing move "
        "plan or execute path."
    ),
    AdminApiMutationFamilyType.STEALTH_RECOVERY: (
        "Recovery must prove active-placement exchange truth, repair and "
        "rollback contracts, and reconciliation evidence before any local "
        "lifecycle recovery action."
    ),
    AdminApiMutationFamilyType.STEALTH_RECONCILIATION: (
        "Reconciliation must prove plan/proof evidence and active-placement "
        "exchange truth before it can compare or repair local stealth lifecycle "
        "state."
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "Reprice must prove cooldown/claim authority and active-placement "
        "cancel/replace exchange truth before any repricing execution."
    ),
}


def build_stealth_active_placement_exchange_truth_contract(
    *,
    mutation_family: AdminApiMutationFamilyType,
    route: str,
    method: str = "POST",
    identity_key: str = "stealth_order_id",
    exchange_truth_required: bool = True,
    active_placement_evidence_required: bool = True,
    current_read_evidence_routes: Sequence[str] | None = None,
    current_read_evidence: Sequence[StealthCommandSuiteCoverageGapEvidenceRouteItem]
    | None = None,
    active_placement_exchange_truth_resolved: bool = False,
    active_placement_exchange_truth_proof_id: str | None = None,
) -> StealthCommandSuiteExchangeTruthItem | None:
    """Build no-live exchange-truth boundary evidence for a stealth command."""

    required_contracts = EXCHANGE_TRUTH_CONTRACTS_BY_FAMILY.get(mutation_family)
    if required_contracts is None:
        return None

    required_gate_chain = [
        "route_inventory_contract",
        "idempotency",
        "operator_intent",
        "payload_hash",
        "approval_snapshot",
        "admission_audit",
        "cap_guard_decision",
        "reconciliation_plan",
        "mutation_claim",
    ]
    required_gate_chain.append(
        "active_placement_exchange_truth"
        if active_placement_evidence_required
        else "lifecycle_write_guard"
    )
    required_gate_chain.extend(
        [
            "live_execution_adapter",
            "live_execution_service",
            "post_live_reconciliation",
        ]
    )

    missing_contracts = list(required_contracts)
    if active_placement_exchange_truth_resolved:
        missing_contracts = [
            contract
            for contract in missing_contracts
            if contract != "stealth_active_placement_exchange_truth_proof_contract"
        ]

    return StealthCommandSuiteExchangeTruthItem(
        mutation_family=mutation_family,
        route=route,
        method=method,
        identity_key=identity_key,
        command_identity_key="stealth_order_id",
        status=AdminApiGateStatus.BLOCKED,
        exchange_truth_required=exchange_truth_required,
        active_placement_evidence_required=active_placement_evidence_required,
        active_placement_exchange_truth_resolved=(
            active_placement_exchange_truth_resolved
        ),
        active_placement_exchange_truth_proof_id=(
            active_placement_exchange_truth_proof_id
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
        current_read_evidence_routes=list(current_read_evidence_routes or ()),
        current_read_evidence=list(current_read_evidence or ()),
        required_gate_chain=required_gate_chain,
        required_contracts=list(required_contracts),
        missing_contracts=missing_contracts,
        backend_owned=True,
        route_bound=True,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        live_enabled=False,
        executable=False,
        live_coinbase_orders_ran=False,
        live_coinbase_read_ran=False,
        detail=EXCHANGE_TRUTH_DETAILS_BY_FAMILY[mutation_family],
    )
