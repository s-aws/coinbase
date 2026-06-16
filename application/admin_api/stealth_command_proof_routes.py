"""Shared no-live proof-route contracts for stealth commands."""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLivePreflightCategory,
    AdminApiMutationFamilyType,
    AdminApiPermission,
)

from .models import StealthCommandSuiteProofRouteItem


@dataclass(frozen=True)
class StealthCommandProofRouteSpec:
    """Static backend-owned proof route required by a stealth command family."""

    gate: AdminApiLivePreflightCategory
    mutation_families: tuple[AdminApiMutationFamilyType, ...]
    route: str
    required_permission: AdminApiPermission
    shared_method: str
    documentation_refs: tuple[str, ...]
    detail: str
    method: str = "POST"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    identity_key: str = "stealth_order_id"


STEALTH_COMMAND_PROOF_ROUTE_SPECS: tuple[StealthCommandProofRouteSpec, ...] = (
    StealthCommandProofRouteSpec(
        gate=AdminApiLivePreflightCategory.MANAGER_INVOCATION,
        mutation_families=(
            AdminApiMutationFamilyType.STEALTH_CREATE,
            AdminApiMutationFamilyType.STEALTH_REVEAL,
            AdminApiMutationFamilyType.STEALTH_CANCEL,
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
            AdminApiMutationFamilyType.STEALTH_RECOVERY,
            AdminApiMutationFamilyType.STEALTH_RECONCILIATION,
        ),
        route=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "manager-invocation-policy-proofs"
        ),
        required_permission=AdminApiPermission.STEALTH_MANAGER_POLICY_RECORD,
        shared_method="record_stealth_manager_invocation_policy_proof",
        documentation_refs=(
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/STEALTH_ORDER_READS.md",
        ),
        detail=(
            "Record backend-owned manager-invocation policy evidence for the "
            "guarded stealth command. This does not invoke StealthOrderManager, "
            "call Coinbase, cancel or replace placements, mutate state, or "
            "execute reconciliation."
        ),
    ),
    StealthCommandProofRouteSpec(
        gate=AdminApiLivePreflightCategory.MUTATION_CLAIM,
        mutation_families=(
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        ),
        route="/api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs",
        required_permission=AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD,
        shared_method="record_stealth_mutation_claim_snapshot_proof",
        documentation_refs=(
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/STEALTH_ORDER_READS.md",
        ),
        detail=(
            "Record backend-owned mutation-claim snapshot proof for stealth "
            "move or reprice commands. This does not invoke the stealth "
            "manager, acquire or release claims, cancel or replace placements, "
            "call Coinbase, or execute reconciliation."
        ),
    ),
    StealthCommandProofRouteSpec(
        gate=AdminApiLivePreflightCategory.RECOVERY_PROOF,
        mutation_families=(AdminApiMutationFamilyType.STEALTH_RECOVERY,),
        route="/api/v1/stealth/orders/{stealth_order_id}/recovery-proofs",
        required_permission=AdminApiPermission.STEALTH_RECOVERY_RECORD,
        shared_method="record_stealth_recovery_proof",
        documentation_refs=(
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/STEALTH_ORDER_READS.md",
        ),
        detail=(
            "Record backend-owned recovery proof for the stealth recovery "
            "command. This does not invoke managers, repair state, roll back "
            "state, call Coinbase, cancel or replace placements, mutate state, "
            "or execute reconciliation."
        ),
    ),
    StealthCommandProofRouteSpec(
        gate=AdminApiLivePreflightCategory.REVEAL_TRIGGER,
        mutation_families=(AdminApiMutationFamilyType.STEALTH_REVEAL,),
        route="/api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
        required_permission=AdminApiPermission.STEALTH_REVEAL_TRIGGER_RECORD,
        shared_method="record_stealth_reveal_trigger_proof",
        documentation_refs=(
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/STEALTH_ORDER_READS.md",
        ),
        detail=(
            "Record backend-owned reveal-trigger proof for the stealth reveal "
            "command. This does not evaluate triggers, call "
            "should_trigger_reveal, call reveal_order_slice, invoke managers, "
            "call Coinbase, mutate state, or execute reconciliation."
        ),
    ),
    StealthCommandProofRouteSpec(
        gate=AdminApiLivePreflightCategory.RECONCILIATION_PROOF,
        mutation_families=(AdminApiMutationFamilyType.STEALTH_RECONCILIATION,),
        route="/api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs",
        required_permission=AdminApiPermission.STEALTH_RECONCILIATION_RECORD,
        shared_method="record_stealth_reconciliation_proof",
        documentation_refs=(
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/STEALTH_ORDER_READS.md",
        ),
        detail=(
            "Record backend-owned reconciliation proof for the stealth "
            "reconciliation command. This does not execute reconciliation, "
            "invoke managers, call Coinbase, cancel or replace placements, "
            "mutate exchange state, or mutate lifecycle state."
        ),
    ),
)


def build_stealth_command_specific_proof_route_contracts(
    *,
    mutation_family: AdminApiMutationFamilyType,
    command_identity_key: str = "stealth_order_id",
) -> list[StealthCommandSuiteProofRouteItem]:
    """Return no-live proof-route contracts required by one stealth command."""

    return [
        StealthCommandSuiteProofRouteItem(
            gate=spec.gate,
            route=spec.route,
            method=spec.method,
            action_class=spec.action_class,
            required_permission=spec.required_permission,
            shared_method=spec.shared_method,
            status=AdminApiGateStatus.BLOCKED,
            required=True,
            blocking=True,
            identity_key=spec.identity_key,
            command_identity_key=command_identity_key,
            backend_owned=True,
            route_bound=True,
            browser_authority="display_only",
            bff_authority="forward_only_no_execution",
            documentation_refs=list(spec.documentation_refs),
            detail=spec.detail,
        )
        for spec in STEALTH_COMMAND_PROOF_ROUTE_SPECS
        if mutation_family in spec.mutation_families
    ]
