"""No-live execution posture evidence for non-create stealth commands."""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminApiMutationFamilyType,
    AdminApiStealthAdmissionContextField,
    AdminApiStealthCommandSuiteGapFamily,
    StealthCommandExecutionBlocker,
    StealthCommandExecutionPrerequisite,
    StealthCommandExecutionPrerequisiteLookupStatus,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthCommandExecutionBlockerChainItem,
    StealthCommandExecutionContractEvidence,
    StealthCommandExecutionPrerequisiteResolverItem,
    StealthCommandExecutionReadinessStageItem,
    StealthExecutionCandidateEvidence,
)
from .live_execution import (
    DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
    DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
    EXECUTION_BOUNDARY_AUTHORITY,
    POST_WRITE_RECONCILIATION_METHOD,
    POST_WRITE_RECONCILIATION_ROUTE,
    POST_WRITE_RECONCILIATION_SOURCE,
    build_live_execution_adapter_contract,
    build_live_execution_service_contract,
)
from .stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
    StealthActivePlacementExchangeTruthProofRecord,
)
from .stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
    StealthMutationClaimSnapshotProofRecord,
)
from .stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
    StealthManagerInvocationPolicyProofRecord,
)
from .stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    StealthCoinbaseExchangeSubmissionPolicyProofRecord,
)
from .stealth_post_write_reconciliation_policy import (
    FileStealthPostWriteReconciliationExecutionPolicyProofStore,
    StealthPostWriteReconciliationExecutionPolicyProofRecord,
)
from .stealth_recovery_proof import (
    FileStealthRecoveryProofStore,
    StealthRecoveryProofRecord,
)
from .stealth_reveal_trigger_proof import (
    FileStealthRevealTriggerProofStore,
    StealthRevealTriggerProofRecord,
)
from .stealth_reconciliation_proof import (
    FileStealthReconciliationProofStore,
    StealthReconciliationProofRecord,
)
from .stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
    StealthCancelReplaceProofRecord,
)
from .stealth_cancel_replace_boundary import (
    build_stealth_active_placement_cancel_replace_contract,
)
from .stealth_command_proof_routes import (
    build_stealth_command_specific_proof_route_contracts,
)
from .stealth_exchange_truth_boundary import (
    EXCHANGE_TRUTH_SURFACES_BY_FAMILY,
    build_stealth_active_placement_exchange_truth_contract,
)
from .stealth_execution_preflight import (
    build_stealth_execution_live_readiness,
    build_stealth_execution_preflight,
    build_stealth_execution_transition_barrier,
)
from .stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    FileStealthPostWriteReconciliationProofStore,
    FileStealthPostWriteReconciliationVerificationStore,
    StealthPostWriteReconciliationProofRecord,
    build_stealth_post_write_completion_verifier_contract,
    build_stealth_post_write_reconciliation_boundary,
    find_matching_post_write_execution_journal_acceptance,
    find_matching_post_write_reconciliation_verification,
    is_safe_stealth_post_write_execution_journal_record,
    is_safe_stealth_post_write_reconciliation_proof_record,
    is_safe_stealth_post_write_reconciliation_verification_record,
)


REQUIRED_STEALTH_COMMAND_EXECUTION_CONTEXT_FIELDS: tuple[str, ...] = tuple(
    field.value for field in AdminApiStealthAdmissionContextField
)


@dataclass(frozen=True)
class StealthCommandExecutionMetadata:
    """Static no-live execution metadata for one stealth command route."""

    mutation_family: AdminApiMutationFamilyType
    route: str
    service_method: str
    manager_methods: tuple[str, ...]
    prerequisites: tuple[StealthCommandExecutionPrerequisite, ...]
    detail: str


COMMON_PREREQUISITES: tuple[StealthCommandExecutionPrerequisite, ...] = (
    StealthCommandExecutionPrerequisite.APPROVAL_SNAPSHOT,
    StealthCommandExecutionPrerequisite.ADMISSION_AUDIT,
    StealthCommandExecutionPrerequisite.CAP_GUARD_DECISION,
    StealthCommandExecutionPrerequisite.RECONCILIATION_PLAN,
)

DISABLED_LIVE_PREREQUISITES: tuple[StealthCommandExecutionPrerequisite, ...] = (
    StealthCommandExecutionPrerequisite.LIVE_EXECUTION_SERVICE,
    StealthCommandExecutionPrerequisite.LIVE_EXECUTION_ADAPTER,
    StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION,
)

EXECUTION_POLICY_PREREQUISITES: tuple[StealthCommandExecutionPrerequisite, ...] = (
    StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY,
    StealthCommandExecutionPrerequisite.COINBASE_EXCHANGE_SUBMISSION_POLICY,
    StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION_EXECUTION_POLICY,
)

BASE_STEALTH_COMMAND_EXECUTION_BLOCKERS: tuple[str, ...] = (
    StealthCommandExecutionBlocker.EXECUTION_CONTRACT_MISSING.value,
    StealthCommandExecutionBlocker.LIVE_EXECUTION_DISABLED.value,
    StealthCommandExecutionBlocker.LIVE_EXECUTION_ADAPTER_DISABLED.value,
    StealthCommandExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED.value,
    StealthCommandExecutionBlocker.ACTIVE_PLACEMENT_CANCEL_REPLACE_DISABLED.value,
    StealthCommandExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED.value,
    StealthCommandExecutionBlocker.COINBASE_ORDER_CANCEL_DISABLED.value,
    StealthCommandExecutionBlocker.COINBASE_READ_DISABLED.value,
    StealthCommandExecutionBlocker.LIFECYCLE_STATE_MUTATION_DISABLED.value,
    StealthCommandExecutionBlocker.ORDER_STATE_MUTATION_DISABLED.value,
    StealthCommandExecutionBlocker.EXCHANGE_STATE_MUTATION_DISABLED.value,
    StealthCommandExecutionBlocker.RECONCILIATION_EXECUTION_DISABLED.value,
)

STEALTH_COMMAND_EXECUTION_METADATA: dict[str, StealthCommandExecutionMetadata] = {
    "reveal_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.STEALTH_REVEAL,
        route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        service_method="reveal_stealth_order_by_stealth_order_id",
        manager_methods=("core/stealth_order_manager.py::reveal_order_slice",),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth reveal execution remains blocked until trigger evidence, "
            "admission prerequisites, the live service/adapter, and post-write "
            "reconciliation are present."
        ),
    ),
    "cancel_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.STEALTH_CANCEL,
        route="/api/v1/stealth/orders/{stealth_order_id}/cancel",
        service_method="cancel_stealth_order_by_stealth_order_id",
        manager_methods=(
            "core/stealth_order_manager.py::cancel_stealth_order",
            "bridges/stealth_order_bridge.py::cancel_stealth_order",
        ),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH,
            StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth cancel execution remains blocked until active-placement "
            "exchange truth and admission prerequisites are present, and the "
            "disabled live cancel/reconciliation path is explicitly enabled."
        ),
    ),
    "move_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.STEALTH_MOVE,
        route="/api/v1/stealth/orders/{stealth_order_id}/move",
        service_method="move_stealth_order_by_stealth_order_id",
        manager_methods=(
            "core/stealth_order_manager.py::build_stealth_move_plan",
            "core/stealth_order_manager.py::execute_stealth_move",
        ),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH,
            StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT,
            StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth move execution remains blocked until active-placement "
            "exchange truth, mutation-claim evidence, and reconciliation "
            "prerequisites are present."
        ),
    ),
    "recover_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.STEALTH_RECOVERY,
        route="/api/v1/stealth/orders/{stealth_order_id}/recovery",
        service_method="recover_stealth_order_by_stealth_order_id",
        manager_methods=("stealth_recovery_service::not_configured",),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH,
            StealthCommandExecutionPrerequisite.RECOVERY_PROOF,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth recovery execution remains blocked until recovery proof, "
            "active-placement evidence, admission prerequisites, and rollback "
            "or repair reconciliation contracts are present."
        ),
    ),
    "reconcile_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.STEALTH_RECONCILIATION,
        route="/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
        service_method="reconcile_stealth_order_by_stealth_order_id",
        manager_methods=(
            "bridges/stealth_order_bridge.py::reconcile_stealth_orders_periodically",
        ),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH,
            StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth reconciliation execution remains blocked until exact "
            "active-placement evidence and reconciliation proof contracts are "
            "present."
        ),
    ),
    "reprice_stealth_order_by_stealth_order_id": StealthCommandExecutionMetadata(
        mutation_family=AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        route="/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        service_method="reprice_stealth_order_by_stealth_order_id",
        manager_methods=(
            "core/stealth_order_manager.py::process_anchor_repricing_for_product",
        ),
        prerequisites=(
            *COMMON_PREREQUISITES,
            *EXECUTION_POLICY_PREREQUISITES,
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH,
            StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT,
            StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF,
            *DISABLED_LIVE_PREREQUISITES,
        ),
        detail=(
            "Stealth reprice execution remains blocked until M56 movement/"
            "repricing claim, active-placement exchange truth, cancel/replace, "
            "and reconciliation contracts are present."
        ),
    ),
}

WORKFLOW_FAMILY_BY_MUTATION_FAMILY: dict[
    AdminApiMutationFamilyType,
    AdminApiStealthCommandSuiteGapFamily,
] = {
    AdminApiMutationFamilyType.STEALTH_REVEAL: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_REVEAL_WORKFLOW
    ),
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_CANCEL_EXCHANGE_HANDLING
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_MOVE_REVEALED_WORKFLOW
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_REPRICE_WORKFLOW
    ),
    AdminApiMutationFamilyType.STEALTH_RECOVERY: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_RECOVERY_WORKFLOW
    ),
    AdminApiMutationFamilyType.STEALTH_RECONCILIATION: (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_RECONCILIATION_WORKFLOW
    ),
}

NEXT_REQUIRED_CONTRACT_BY_PREREQUISITE: dict[
    StealthCommandExecutionPrerequisite,
    str,
] = {
    StealthCommandExecutionPrerequisite.APPROVAL_SNAPSHOT: (
        "POST /api/v1/admin/approvals/requests"
    ),
    StealthCommandExecutionPrerequisite.ADMISSION_AUDIT: (
        "POST /api/v1/admin/admission-audits"
    ),
    StealthCommandExecutionPrerequisite.CAP_GUARD_DECISION: (
        "POST /api/v1/admin/cap-guard/decisions"
    ),
    StealthCommandExecutionPrerequisite.RECONCILIATION_PLAN: (
        "POST /api/v1/admin/reconciliation/plans"
    ),
    StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "active-placement-exchange-truth-proofs"
    ),
    StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "manager-invocation-policy-proofs"
    ),
    StealthCommandExecutionPrerequisite.COINBASE_EXCHANGE_SUBMISSION_POLICY: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "coinbase-exchange-submission-policy-proofs"
    ),
    StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION_EXECUTION_POLICY: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "post-write-reconciliation-execution-policy-proofs"
    ),
    StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs"
    ),
    StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs"
    ),
    StealthCommandExecutionPrerequisite.RECOVERY_PROOF: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs"
    ),
    StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs"
    ),
    StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs"
    ),
    StealthCommandExecutionPrerequisite.LIVE_EXECUTION_SERVICE: (
        "application/admin_api/live_execution.py::"
        "build_live_execution_service_contract"
    ),
    StealthCommandExecutionPrerequisite.LIVE_EXECUTION_ADAPTER: (
        "application/admin_api/live_execution.py::"
        "build_live_execution_adapter_contract"
    ),
    StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "post-write-reconciliation-proofs"
    ),
}


def build_stealth_command_execution_contract(
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    *,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None = None,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None = None,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ) = None,
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ) = None,
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ) = None,
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None = None,
    stealth_reveal_trigger_proof_store: (
        FileStealthRevealTriggerProofStore | None
    ) = None,
    stealth_reconciliation_proof_store: (
        FileStealthReconciliationProofStore | None
    ) = None,
    stealth_cancel_replace_proof_store: (
        FileStealthCancelReplaceProofStore | None
    ) = None,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ) = None,
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ) = None,
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ) = None,
) -> StealthCommandExecutionContractEvidence | None:
    """Build no-live execution posture evidence for eligible stealth commands."""

    metadata = STEALTH_COMMAND_EXECUTION_METADATA.get(admission_decision.service_method)
    if (
        metadata is None
        or admission_decision.identity_key != "stealth_order_id"
        or not admission_decision.identity_value
    ):
        return None

    resolution = _build_prerequisite_resolution(
        metadata=metadata,
        admission_decision=admission_decision,
        stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        stealth_coinbase_exchange_policy_proof_store=(
            stealth_coinbase_exchange_policy_proof_store
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            stealth_post_write_reconciliation_policy_proof_store
        ),
        stealth_recovery_proof_store=stealth_recovery_proof_store,
        stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
        stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
        stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
        stealth_post_write_reconciliation_proof_store=(
            stealth_post_write_reconciliation_proof_store
        ),
        stealth_post_write_execution_journal_store=(
            stealth_post_write_execution_journal_store
        ),
        stealth_post_write_reconciliation_verification_store=(
            stealth_post_write_reconciliation_verification_store
        ),
    )
    resolved = sorted(
        item.prerequisite.value
        for item in resolution
        if item.resolved
    )
    required = [prerequisite.value for prerequisite in metadata.prerequisites]
    missing = [
        prerequisite
        for prerequisite in required
        if prerequisite not in resolved
    ]
    blockers = list(BASE_STEALTH_COMMAND_EXECUTION_BLOCKERS)
    blockers.extend(f"{prerequisite}_missing" for prerequisite in missing)
    execution_readiness_stages = _build_execution_readiness_stages(
        metadata=metadata,
        resolution=resolution,
    )
    remaining_execution_blockers = _build_remaining_execution_blockers(
        metadata=metadata,
        resolution=resolution,
    )
    post_write_reconciliation_proof_record = (
        _find_matching_post_write_reconciliation_proof(
            store=stealth_post_write_reconciliation_proof_store,
            metadata=metadata,
            admission_decision=admission_decision,
        )
        if stealth_post_write_reconciliation_proof_store is not None
        else None
    )
    post_write_execution_journal_record = (
        find_matching_post_write_execution_journal_acceptance(
            store=stealth_post_write_execution_journal_store,
            proof_record=post_write_reconciliation_proof_record,
        )
        if stealth_post_write_execution_journal_store is not None
        and post_write_reconciliation_proof_record is not None
        else None
    )
    post_write_reconciliation_verification_record = (
        find_matching_post_write_reconciliation_verification(
            store=stealth_post_write_reconciliation_verification_store,
            proof_record=post_write_reconciliation_proof_record,
            execution_journal_record=post_write_execution_journal_record,
        )
        if stealth_post_write_reconciliation_verification_store is not None
        and post_write_reconciliation_proof_record is not None
        and post_write_execution_journal_record is not None
        else None
    )

    execution_candidate = _build_execution_candidate(
        metadata=metadata,
        admission_decision=admission_decision,
        remaining_execution_blockers=remaining_execution_blockers,
    )
    execution_preflight = build_stealth_execution_preflight(execution_candidate)
    execution_transition_barrier = build_stealth_execution_transition_barrier(
        execution_preflight
    )

    return StealthCommandExecutionContractEvidence(
        mutation_family=metadata.mutation_family,
        command_route=metadata.route,
        service_method=metadata.service_method,
        manager_methods=list(metadata.manager_methods),
        stealth_order_id=admission_decision.identity_value,
        action_class=admission_decision.action_class,
        required_permission=admission_decision.required_permission,
        exact_command_context_present=True,
        required_context_fields=list(REQUIRED_STEALTH_COMMAND_EXECUTION_CONTEXT_FIELDS),
        missing_context_fields=[],
        required_prerequisites=required,
        missing_prerequisites=missing,
        resolved_prerequisites=resolved,
        prerequisite_resolver_lookup_ran=True,
        prerequisite_resolution=resolution,
        execution_readiness_stage_count=len(execution_readiness_stages),
        blocked_execution_readiness_stage_count=sum(
            1 for item in execution_readiness_stages if item.blocking
        ),
        passed_execution_readiness_stage_count=sum(
            1 for item in execution_readiness_stages if item.resolved
        ),
        execution_readiness_stages=execution_readiness_stages,
        command_specific_proof_contracts=(
            build_stealth_command_specific_proof_route_contracts(
                mutation_family=metadata.mutation_family,
                command_identity_key="stealth_order_id",
            )
        ),
        blockers=blockers,
        remaining_execution_blocker_count=len(remaining_execution_blockers),
        remaining_execution_blockers=remaining_execution_blockers,
        active_placement_exchange_truth_required=(
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH.value
            in required
        ),
        active_placement_exchange_truth_resolved=(
            StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH.value
            in resolved
        ),
        active_placement_exchange_truth_contract=(
            build_stealth_active_placement_exchange_truth_contract(
                mutation_family=metadata.mutation_family,
                route=metadata.route,
                method=admission_decision.method,
                current_read_evidence_routes=EXCHANGE_TRUTH_SURFACES_BY_FAMILY.get(
                    metadata.mutation_family,
                    (),
                ),
                active_placement_exchange_truth_resolved=(
                    StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH.value
                    in resolved
                ),
                active_placement_exchange_truth_proof_id=next(
                    (
                        item.resolved_evidence_id
                        for item in resolution
                        if item.prerequisite
                        == StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH
                    ),
                    None,
                ),
            )
            if StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH.value
            in required
            else None
        ),
        reveal_trigger_evidence_required=(
            StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE.value in required
        ),
        reveal_trigger_evidence_resolved=(
            StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE.value in resolved
        ),
        manager_invocation_policy_required=(
            StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY.value
            in required
        ),
        manager_invocation_policy_resolved=(
            StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY.value
            in resolved
        ),
        manager_invocation_policy_proof_id=next(
            (
                item.resolved_evidence_id
                for item in resolution
                if item.prerequisite
                == StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY
            ),
            None,
        ),
        mutation_claim_snapshot_required=(
            StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT.value
            in required
        ),
        mutation_claim_snapshot_resolved=(
            StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT.value
            in resolved
        ),
        recovery_proof_required=(
            StealthCommandExecutionPrerequisite.RECOVERY_PROOF.value in required
        ),
        recovery_proof_resolved=(
            StealthCommandExecutionPrerequisite.RECOVERY_PROOF.value in resolved
        ),
        reconciliation_proof_required=(
            StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF.value in required
        ),
        reconciliation_proof_resolved=(
            StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF.value in resolved
        ),
        reconciliation_proof_id=next(
            (
                item.resolved_evidence_id
                for item in resolution
                if item.prerequisite
                == StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF
            ),
            None,
        ),
        cancel_replace_proof_required=(
            StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF.value in required
        ),
        cancel_replace_proof_resolved=(
            StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF.value in resolved
        ),
        cancel_replace_proof_id=next(
            (
                item.resolved_evidence_id
                for item in resolution
                if item.prerequisite
                == StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF
            ),
            None,
        ),
        active_placement_cancel_replace_contract=(
            build_stealth_active_placement_cancel_replace_contract(
                mutation_family=metadata.mutation_family,
                route=metadata.route,
                method=admission_decision.method,
                active_placement_exchange_truth_resolved=(
                    StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH.value
                    in resolved
                ),
                cancel_replace_proof_resolved=(
                    StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF.value
                    in resolved
                ),
                cancel_replace_proof_id=next(
                    (
                        item.resolved_evidence_id
                        for item in resolution
                        if item.prerequisite
                        == StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF
                    ),
                    None,
                ),
            )
        ),
        live_execution_service_source=(
            admission_decision.live_execution_service_source
            or DISABLED_LIVE_EXECUTION_SERVICE_SOURCE
        ),
        live_execution_service_missing_reason=(
            admission_decision.live_execution_service_missing_reason
            or "live_execution_disabled"
        ),
        live_execution_service_contract=build_live_execution_service_contract(
            method=admission_decision.method,
            route=metadata.route,
            module_id=admission_decision.module_id,
            service_method=metadata.service_method,
            action_class=admission_decision.action_class,
        ),
        live_execution_intent_contract=admission_decision.live_execution_intent,
        live_execution_adapter_source=DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
        live_execution_adapter_missing_reason="live_execution_adapter_disabled",
        live_execution_adapter_contract=build_live_execution_adapter_contract(
            method=admission_decision.method,
            route=metadata.route,
            module_id=admission_decision.module_id,
            service_method=metadata.service_method,
            action_class=admission_decision.action_class,
        ),
        post_write_reconciliation_resolved=(
            StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION.value
            in resolved
        ),
        post_write_reconciliation_route=POST_WRITE_RECONCILIATION_ROUTE,
        post_write_reconciliation_method=POST_WRITE_RECONCILIATION_METHOD,
        post_write_reconciliation_source=POST_WRITE_RECONCILIATION_SOURCE,
        post_write_reconciliation_missing_reason=(
            None
            if StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION.value
            in resolved
            else "post_write_reconciliation_missing"
        ),
        post_write_reconciliation_boundary=(
            build_stealth_post_write_reconciliation_boundary(
                mutation_family=metadata.mutation_family,
                command_route=metadata.route,
                service_method=metadata.service_method,
                stealth_order_id=admission_decision.identity_value,
                admission_decision=admission_decision,
            )
        ),
        post_write_completion_verifier_contract=(
            build_stealth_post_write_completion_verifier_contract(
                mutation_family=metadata.mutation_family,
                command_route=metadata.route,
                service_method=metadata.service_method,
                stealth_order_id=admission_decision.identity_value,
                admission_decision=admission_decision,
                proof_record=post_write_reconciliation_proof_record,
                execution_journal_record=post_write_execution_journal_record,
                reconciliation_verification_record=(
                    post_write_reconciliation_verification_record
                ),
            )
        ),
        execution_candidate=execution_candidate,
        execution_preflight=execution_preflight,
        execution_transition_barrier=execution_transition_barrier,
        execution_live_readiness=build_stealth_execution_live_readiness(
            execution_transition_barrier
        ),
        canonical_execution_path=list(metadata.manager_methods),
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Execution posture is backend-owned and no-live.",
            "Prerequisite rows are read-only and no-authority.",
            "This contract does not invoke stealth managers, live adapters, Coinbase, or reconciliation.",
            "Command-specific proof prerequisites remain missing until later approved execution phases.",
        ],
        detail=metadata.detail,
    )


def _build_execution_candidate(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    remaining_execution_blockers: list[StealthCommandExecutionBlockerChainItem],
) -> StealthExecutionCandidateEvidence:
    """Expose the exact future execution candidate without enabling it."""

    return StealthExecutionCandidateEvidence(
        mutation_family=metadata.mutation_family,
        workflow_family=WORKFLOW_FAMILY_BY_MUTATION_FAMILY[metadata.mutation_family],
        command_route=metadata.route,
        command_method=admission_decision.method,
        service_method=metadata.service_method,
        manager_methods=list(metadata.manager_methods),
        identity_value=admission_decision.identity_value,
        exact_command_context_present=True,
        unresolved_blocker_count=len(remaining_execution_blockers),
        unresolved_blockers=[
            item.blocker.value for item in remaining_execution_blockers
        ],
        next_required_contracts=sorted(
            {
                item.next_required_contract
                for item in remaining_execution_blockers
            }
        ),
        canonical_execution_path=list(metadata.manager_methods),
        detail=(
            "This candidate identifies the backend-owned stealth command path "
            "that may become executable only after every blocker resolves; it "
            "does not invoke managers, Coinbase, reconciliation, or state writes."
        ),
    )


def _build_prerequisite_resolution(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ),
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ),
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ),
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None,
    stealth_reveal_trigger_proof_store: FileStealthRevealTriggerProofStore | None,
    stealth_reconciliation_proof_store: FileStealthReconciliationProofStore | None,
    stealth_cancel_replace_proof_store: FileStealthCancelReplaceProofStore | None,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ),
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ),
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ),
) -> list[StealthCommandExecutionPrerequisiteResolverItem]:
    approval = _resolver_item_from_flag(
        prerequisite=StealthCommandExecutionPrerequisite.APPROVAL_SNAPSHOT,
        metadata=metadata,
        admission_decision=admission_decision,
        source=admission_decision.approval_snapshot_source or "approval_store",
        present=admission_decision.approval_snapshot_present,
        evidence_id=admission_decision.approval_snapshot_id,
        missing_reason=admission_decision.approval_snapshot_missing_reason,
        detail="Route-specific approval snapshot resolver evidence.",
    )
    admission = _resolver_item_from_flag(
        prerequisite=StealthCommandExecutionPrerequisite.ADMISSION_AUDIT,
        metadata=metadata,
        admission_decision=admission_decision,
        source=admission_decision.admission_audit_source or "admin_api_audit_log",
        present=admission_decision.admission_audit_present,
        evidence_id=admission_decision.admission_audit_id,
        missing_reason=admission_decision.admission_audit_missing_reason,
        dependency_resolved=approval.resolved,
        dependency_missing_reason="approval_snapshot_missing",
        detail="Route-specific admission audit resolver evidence.",
    )
    cap_guard = _resolver_item_from_flag(
        prerequisite=StealthCommandExecutionPrerequisite.CAP_GUARD_DECISION,
        metadata=metadata,
        admission_decision=admission_decision,
        source=admission_decision.cap_guard_source or "admin_api_cap_guard_log",
        present=admission_decision.cap_guard_present,
        evidence_id=admission_decision.cap_guard_decision_id,
        missing_reason=admission_decision.cap_guard_missing_reason,
        dependency_resolved=admission.resolved,
        dependency_missing_reason="admission_audit_missing",
        detail="Route-specific cap/guard decision resolver evidence.",
    )
    reconciliation = _resolver_item_from_flag(
        prerequisite=StealthCommandExecutionPrerequisite.RECONCILIATION_PLAN,
        metadata=metadata,
        admission_decision=admission_decision,
        source=(
            admission_decision.reconciliation_plan_source
            or "admin_api_reconciliation_plan_log"
        ),
        present=admission_decision.reconciliation_plan_present,
        evidence_id=admission_decision.reconciliation_plan_id,
        missing_reason=admission_decision.reconciliation_plan_missing_reason,
        dependency_resolved=cap_guard.resolved,
        dependency_missing_reason="cap_guard_decision_missing",
        detail="Route-specific reconciliation plan resolver evidence.",
    )
    common = [approval, admission, cap_guard, reconciliation]
    common_resolved = all(item.resolved for item in common)
    command_specific = [
        _command_specific_prerequisite(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            common_resolved=common_resolved,
            stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
            stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
            stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
            stealth_coinbase_exchange_policy_proof_store=(
                stealth_coinbase_exchange_policy_proof_store
            ),
            stealth_post_write_reconciliation_policy_proof_store=(
                stealth_post_write_reconciliation_policy_proof_store
            ),
            stealth_recovery_proof_store=stealth_recovery_proof_store,
            stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
            stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
            stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
            stealth_post_write_reconciliation_proof_store=(
                stealth_post_write_reconciliation_proof_store
            ),
            stealth_post_write_execution_journal_store=(
                stealth_post_write_execution_journal_store
            ),
            stealth_post_write_reconciliation_verification_store=(
                stealth_post_write_reconciliation_verification_store
            ),
        )
        for prerequisite in metadata.prerequisites
        if prerequisite not in COMMON_PREREQUISITES
    ]
    return common + command_specific


def _build_execution_readiness_stages(
    *,
    metadata: StealthCommandExecutionMetadata,
    resolution: list[StealthCommandExecutionPrerequisiteResolverItem],
) -> list[StealthCommandExecutionReadinessStageItem]:
    """Summarize exact command prerequisites as ordered no-live stages."""

    resolution_by_prerequisite = {item.prerequisite: item for item in resolution}
    workflow_family = WORKFLOW_FAMILY_BY_MUTATION_FAMILY[metadata.mutation_family]
    stages: list[StealthCommandExecutionReadinessStageItem] = []
    for stage_order, prerequisite in enumerate(metadata.prerequisites, start=1):
        item = resolution_by_prerequisite[prerequisite]
        stages.append(
            StealthCommandExecutionReadinessStageItem(
                stage_order=stage_order,
                workflow_family=workflow_family,
                mutation_family=metadata.mutation_family,
                prerequisite=prerequisite,
                source=item.source,
                route=item.route,
                method=item.method,
                identity_key=item.identity_key,
                identity_value=item.identity_value,
                lookup_status=item.lookup_status,
                status=(
                    AdminApiGateStatus.PASSED
                    if item.resolved
                    else AdminApiGateStatus.BLOCKED
                ),
                required=True,
                resolved=item.resolved,
                blocking=not item.resolved,
                resolved_evidence_id=item.resolved_evidence_id,
                missing_reason=item.missing_reason,
                next_required_contract=NEXT_REQUIRED_CONTRACT_BY_PREREQUISITE[
                    prerequisite
                ],
                detail=(
                    f"{prerequisite.value} stage for "
                    f"{metadata.mutation_family.value} remains "
                    f"{'resolved' if item.resolved else 'blocked'}; this stage "
                    "is evidence only and does not execute the stealth manager, "
                    "call Coinbase, or mutate state."
                ),
            )
        )
    return stages


def _build_remaining_execution_blockers(
    *,
    metadata: StealthCommandExecutionMetadata,
    resolution: list[StealthCommandExecutionPrerequisiteResolverItem],
) -> list[StealthCommandExecutionBlockerChainItem]:
    """Expose execution blockers that remain after prerequisite lookups."""

    resolved = {item.prerequisite for item in resolution if item.resolved}
    by_prerequisite = {item.prerequisite: item for item in resolution}
    blockers: list[tuple[
        StealthCommandExecutionBlocker,
        StealthCommandExecutionPrerequisite | None,
        str,
        str,
    ]] = [
        (
            StealthCommandExecutionBlocker.EXECUTION_CONTRACT_MISSING,
            None,
            "application/admin_api/stealth_command_execution.py::"
            "build_stealth_command_execution_contract",
            "The exact command response is still contract evidence, not an executable command.",
        ),
        (
            StealthCommandExecutionBlocker.LIVE_EXECUTION_DISABLED,
            StealthCommandExecutionPrerequisite.LIVE_EXECUTION_SERVICE,
            NEXT_REQUIRED_CONTRACT_BY_PREREQUISITE[
                StealthCommandExecutionPrerequisite.LIVE_EXECUTION_SERVICE
            ],
            "The shared live execution service remains disabled for this stealth command.",
        ),
        (
            StealthCommandExecutionBlocker.LIVE_EXECUTION_ADAPTER_DISABLED,
            StealthCommandExecutionPrerequisite.LIVE_EXECUTION_ADAPTER,
            NEXT_REQUIRED_CONTRACT_BY_PREREQUISITE[
                StealthCommandExecutionPrerequisite.LIVE_EXECUTION_ADAPTER
            ],
            "The stealth live execution adapter remains disabled for this command.",
        ),
        (
            StealthCommandExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED,
            None,
            ", ".join(metadata.manager_methods),
            "No StealthOrderManager method may be invoked from this contract.",
        ),
        (
            StealthCommandExecutionBlocker.ACTIVE_PLACEMENT_CANCEL_REPLACE_DISABLED,
            None,
            "core/stealth_order_manager.py active-placement cancel/replace path",
            "Active Coinbase placements cannot be cancelled or replaced by this evidence surface.",
        ),
        (
            StealthCommandExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED,
            None,
            "external/coinbase_api.py order submit path",
            "Coinbase order submission remains disabled.",
        ),
        (
            StealthCommandExecutionBlocker.COINBASE_ORDER_CANCEL_DISABLED,
            None,
            "external/coinbase_api.py cancel_order(client_order_id)",
            "Coinbase order cancellation remains disabled.",
        ),
        (
            StealthCommandExecutionBlocker.COINBASE_READ_DISABLED,
            None,
            "external/coinbase_api.py read/reconcile path",
            "Live Coinbase reads remain disabled.",
        ),
        (
            StealthCommandExecutionBlocker.LIFECYCLE_STATE_MUTATION_DISABLED,
            None,
            "database stealth lifecycle write path",
            "Lifecycle state mutation remains disabled.",
        ),
        (
            StealthCommandExecutionBlocker.ORDER_STATE_MUTATION_DISABLED,
            None,
            "database/order.py state write path",
            "Order state mutation remains disabled.",
        ),
        (
            StealthCommandExecutionBlocker.EXCHANGE_STATE_MUTATION_DISABLED,
            None,
            "exchange state reconciliation write path",
            "Exchange-state mutation remains disabled.",
        ),
        (
            StealthCommandExecutionBlocker.RECONCILIATION_EXECUTION_DISABLED,
            None,
            "application/admin_api reconciliation executor",
            "Post-write reconciliation execution remains disabled.",
        ),
    ]
    if (
        StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION
        not in resolved
    ):
        blockers.append(
            (
                StealthCommandExecutionBlocker.POST_WRITE_RECONCILIATION_MISSING,
                StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION,
                NEXT_REQUIRED_CONTRACT_BY_PREREQUISITE[
                    StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION
                ],
                "The exact proof, accepted journal, and verification chain has not resolved post-write reconciliation evidence.",
            )
        )

    items: list[StealthCommandExecutionBlockerChainItem] = []
    for blocker_order, (blocker, prerequisite, next_contract, detail) in enumerate(
        blockers,
        start=1,
    ):
        source_item = by_prerequisite.get(prerequisite) if prerequisite else None
        items.append(
            StealthCommandExecutionBlockerChainItem(
                blocker_order=blocker_order,
                blocker=blocker,
                source_prerequisite=prerequisite,
                resolved_evidence_id=(
                    source_item.resolved_evidence_id if source_item else None
                ),
                missing_reason=(
                    source_item.missing_reason
                    if source_item and source_item.missing_reason
                    else blocker.value
                ),
                next_required_contract=next_contract,
                detail=(
                    f"{detail} Browser authority is display-only, BFF authority "
                    "is forward-only with no execution, and this blocker chain "
                    "is derived from read-only prerequisite evidence."
                ),
            )
        )
    return items


def _resolver_item_from_flag(
    *,
    prerequisite: StealthCommandExecutionPrerequisite,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    source: str,
    present: bool,
    evidence_id: str | None,
    missing_reason: str | None,
    detail: str,
    dependency_resolved: bool = True,
    dependency_missing_reason: str | None = None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    if not dependency_resolved:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=source,
            lookup_status=(
                StealthCommandExecutionPrerequisiteLookupStatus.BLOCKED_BY_DEPENDENCY
            ),
            missing_reason=dependency_missing_reason,
            detail=detail,
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=source,
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if present
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=present,
        resolved_evidence_id=evidence_id if present else None,
        missing_reason=None if present else missing_reason,
        detail=detail,
    )


def _command_specific_prerequisite(
    *,
    prerequisite: StealthCommandExecutionPrerequisite,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    common_resolved: bool,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ),
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ),
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ),
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None,
    stealth_reveal_trigger_proof_store: FileStealthRevealTriggerProofStore | None,
    stealth_reconciliation_proof_store: FileStealthReconciliationProofStore | None,
    stealth_cancel_replace_proof_store: FileStealthCancelReplaceProofStore | None,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ),
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ),
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    if prerequisite == StealthCommandExecutionPrerequisite.LIVE_EXECUTION_SERVICE:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=(
                admission_decision.live_execution_service_source
                or DISABLED_LIVE_EXECUTION_SERVICE_SOURCE
            ),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.DISABLED,
            missing_reason=(
                admission_decision.live_execution_service_missing_reason
                or "live_execution_disabled"
            ),
            lookup_ran=True,
            detail="Live execution service remains disabled for this stealth command.",
        )
    if prerequisite == StealthCommandExecutionPrerequisite.LIVE_EXECUTION_ADAPTER:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.DISABLED,
            missing_reason="live_execution_adapter_disabled",
            lookup_ran=True,
            detail="Live execution adapter is not enabled for this stealth command.",
        )
    if prerequisite == StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION:
        return _resolve_post_write_reconciliation_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_post_write_reconciliation_proof_store=(
                stealth_post_write_reconciliation_proof_store
            ),
            stealth_post_write_execution_journal_store=(
                stealth_post_write_execution_journal_store
            ),
            stealth_post_write_reconciliation_verification_store=(
                stealth_post_write_reconciliation_verification_store
            ),
        )
    if not common_resolved:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=(
                StealthCommandExecutionPrerequisiteLookupStatus.BLOCKED_BY_DEPENDENCY
            ),
            missing_reason="admission_prerequisites_missing",
            detail=(
                "Command-specific proof lookup requires approval, audit, "
                "cap/guard, and reconciliation evidence first."
            ),
        )
    if prerequisite == StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY:
        return _resolve_manager_invocation_policy_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        )
    if (
        prerequisite
        == StealthCommandExecutionPrerequisite.COINBASE_EXCHANGE_SUBMISSION_POLICY
    ):
        return _resolve_coinbase_exchange_submission_policy_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_coinbase_exchange_policy_proof_store=(
                stealth_coinbase_exchange_policy_proof_store
            ),
        )
    if (
        prerequisite
        == StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION_EXECUTION_POLICY
    ):
        return _resolve_post_write_reconciliation_execution_policy_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_post_write_reconciliation_policy_proof_store=(
                stealth_post_write_reconciliation_policy_proof_store
            ),
        )
    if prerequisite == StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH:
        return _resolve_active_placement_exchange_truth(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        )
    if prerequisite == StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT:
        return _resolve_mutation_claim_snapshot(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        )
    if prerequisite == StealthCommandExecutionPrerequisite.RECOVERY_PROOF:
        return _resolve_recovery_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_recovery_proof_store=stealth_recovery_proof_store,
        )
    if prerequisite == StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE:
        return _resolve_reveal_trigger_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
        )
    if prerequisite == StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF:
        return _resolve_reconciliation_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
        )
    if prerequisite == StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF:
        return _resolve_cancel_replace_proof(
            metadata=metadata,
            admission_decision=admission_decision,
            stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
        missing_reason=f"{prerequisite.value}_not_resolved",
        detail="Command-specific proof prerequisite is missing and no execution ran.",
    )


def _resolve_manager_invocation_policy_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY
    if (
        stealth_manager_policy_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="manager_invocation_policy_proof_store_unavailable",
            detail="Manager-invocation policy proof store was not available.",
        )

    record = _find_latest_manager_invocation_policy_proof(
        store=stealth_manager_policy_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_manager_invocation_policy_proof(
        record,
        metadata=metadata,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="manager_invocation_policy_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest manager-invocation policy proof was found but is not "
                "safe exact-context no-live/no-mutation evidence for command "
                "execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.manager_policy_proof_id if record is not None else None
        ),
        missing_reason=(
            None if record is not None else "no_matching_manager_invocation_policy_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned manager-invocation policy proof lookup is read-only "
            "and does not invoke managers, call Coinbase, cancel or replace "
            "active placements, execute reconciliation, mutate state, or "
            "authorize execution."
        ),
    )


def _find_latest_manager_invocation_policy_proof(
    *,
    store: FileStealthManagerInvocationPolicyProofStore,
    stealth_order_id: str,
) -> StealthManagerInvocationPolicyProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_coinbase_exchange_submission_policy_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.COINBASE_EXCHANGE_SUBMISSION_POLICY
    if (
        stealth_coinbase_exchange_policy_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="coinbase_exchange_policy_proof_store_unavailable",
            detail="Coinbase exchange submission-policy proof store was unavailable.",
        )

    record = _find_latest_coinbase_exchange_submission_policy_proof(
        store=stealth_coinbase_exchange_policy_proof_store,
        stealth_order_id=admission_decision.identity_value,
        metadata=metadata,
        admission_decision=admission_decision,
    )
    if record is not None and not _is_safe_coinbase_exchange_submission_policy_proof(
        record,
        metadata=metadata,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=record.coinbase_exchange_policy_proof_id,
            missing_reason="coinbase_exchange_submission_policy_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest exact-command Coinbase exchange submission-policy "
                "proof was found but is not safe exact-context "
                "no-live/no-mutation evidence for command execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.coinbase_exchange_policy_proof_id if record is not None else None
        ),
        missing_reason=(
            None
            if record is not None
            else "no_matching_coinbase_exchange_submission_policy_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned Coinbase exchange submission-policy proof lookup is "
            "read-only and does not submit, cancel, read Coinbase, invoke "
            "managers, cancel or replace active placements, execute "
            "reconciliation, mutate state, or authorize execution."
        ),
    )


def _find_latest_coinbase_exchange_submission_policy_proof(
    *,
    store: FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    stealth_order_id: str,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthCoinbaseExchangeSubmissionPolicyProofRecord | None:
    for record in store.read_for_stealth_order_id(stealth_order_id, limit=500):
        if _coinbase_exchange_submission_policy_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        ):
            return record
    return None


def _resolve_post_write_reconciliation_execution_policy_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = (
        StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION_EXECUTION_POLICY
    )
    if (
        stealth_post_write_reconciliation_policy_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason=(
                "post_write_reconciliation_execution_policy_proof_store_unavailable"
            ),
            detail=(
                "Post-write reconciliation execution-policy proof store was "
                "unavailable."
            ),
        )

    record = _find_latest_post_write_reconciliation_execution_policy_proof(
        store=stealth_post_write_reconciliation_policy_proof_store,
        stealth_order_id=admission_decision.identity_value,
        metadata=metadata,
        admission_decision=admission_decision,
    )
    if record is not None and not (
        _is_safe_post_write_reconciliation_execution_policy_proof(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        )
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=record.post_write_reconciliation_policy_proof_id,
            missing_reason=(
                "post_write_reconciliation_execution_policy_proof_not_safe"
            ),
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest exact-command post-write reconciliation "
                "execution-policy proof was found but is not safe "
                "exact-context no-live/no-mutation evidence for command "
                "execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.post_write_reconciliation_policy_proof_id
            if record is not None
            else None
        ),
        missing_reason=(
            None
            if record is not None
            else "no_matching_post_write_reconciliation_execution_policy_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned post-write reconciliation execution-policy proof "
            "lookup is read-only and does not execute reconciliation, invoke "
            "managers, call Coinbase, cancel or replace active placements, "
            "mutate state, or authorize execution."
        ),
    )


def _find_latest_post_write_reconciliation_execution_policy_proof(
    *,
    store: FileStealthPostWriteReconciliationExecutionPolicyProofStore,
    stealth_order_id: str,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthPostWriteReconciliationExecutionPolicyProofRecord | None:
    for record in store.read_for_stealth_order_id(stealth_order_id, limit=500):
        if _post_write_reconciliation_execution_policy_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        ):
            return record
    return None


def _resolve_active_placement_exchange_truth(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH
    if stealth_exchange_truth_proof_store is None or not admission_decision.identity_value:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="active_placement_exchange_truth_proof_store_unavailable",
            detail="Active-placement exchange-truth proof store was not available.",
        )

    record = _find_latest_active_placement_exchange_truth_proof(
        store=stealth_exchange_truth_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_active_placement_exchange_truth_proof(record):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="active_placement_exchange_truth_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest active-placement proof was found but is not safe "
                "no-live/no-mutation evidence for command execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.exchange_truth_proof_id if record is not None else None
        ),
        missing_reason=(
            None
            if record is not None
            else "no_matching_active_placement_exchange_truth_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned active-placement exchange-truth proof lookup is "
            "read-only and does not verify Coinbase or authorize execution."
        ),
    )


def _find_latest_active_placement_exchange_truth_proof(
    *,
    store: FileStealthExchangeTruthProofStore,
    stealth_order_id: str,
) -> StealthActivePlacementExchangeTruthProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_mutation_claim_snapshot(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT
    if stealth_mutation_claim_proof_store is None or not admission_decision.identity_value:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="mutation_claim_proof_store_unavailable",
            detail="Mutation-claim proof store was not available.",
        )

    record = _find_latest_mutation_claim_snapshot_proof(
        store=stealth_mutation_claim_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_mutation_claim_snapshot_proof(
        record,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="mutation_claim_snapshot_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest mutation-claim proof was found but is not safe "
                "exact-context no-live/no-mutation evidence for command execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.mutation_claim_proof_id if record is not None else None
        ),
        missing_reason=(
            None if record is not None else "no_matching_mutation_claim_snapshot_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned mutation-claim snapshot proof lookup is read-only "
            "and does not acquire claims, mutate state, verify Coinbase, or "
            "authorize execution."
        ),
    )


def _find_latest_mutation_claim_snapshot_proof(
    *,
    store: FileStealthMutationClaimProofStore,
    stealth_order_id: str,
) -> StealthMutationClaimSnapshotProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_recovery_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.RECOVERY_PROOF
    if stealth_recovery_proof_store is None or not admission_decision.identity_value:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="recovery_proof_store_unavailable",
            detail="Recovery proof store was not available.",
        )

    record = _find_latest_recovery_proof(
        store=stealth_recovery_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_recovery_proof(
        record,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="recovery_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest recovery proof was found but is not safe exact-context "
                "no-live/no-mutation evidence for command execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=record.recovery_proof_id if record is not None else None,
        missing_reason=None if record is not None else "no_matching_recovery_proof",
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned recovery proof lookup is read-only and does not "
            "repair state, roll back state, mutate lifecycle state, verify "
            "Coinbase, or authorize execution."
        ),
    )


def _find_latest_recovery_proof(
    *,
    store: FileStealthRecoveryProofStore,
    stealth_order_id: str,
) -> StealthRecoveryProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_reveal_trigger_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_reveal_trigger_proof_store: FileStealthRevealTriggerProofStore | None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE
    if (
        stealth_reveal_trigger_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="reveal_trigger_proof_store_unavailable",
            detail="Reveal-trigger proof store was not available.",
        )

    record = _find_latest_reveal_trigger_proof(
        store=stealth_reveal_trigger_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_reveal_trigger_proof(
        record,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="reveal_trigger_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest reveal-trigger proof was found but is not safe "
                "exact-context no-live/no-mutation evidence for command "
                "execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.reveal_trigger_proof_id if record is not None else None
        ),
        missing_reason=(
            None if record is not None else "no_matching_reveal_trigger_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned reveal-trigger proof lookup is read-only and does "
            "not evaluate triggers, call should_trigger_reveal, call "
            "reveal_order_slice, mutate lifecycle state, verify Coinbase, or "
            "authorize execution."
        ),
    )


def _find_latest_reveal_trigger_proof(
    *,
    store: FileStealthRevealTriggerProofStore,
    stealth_order_id: str,
) -> StealthRevealTriggerProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_reconciliation_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_reconciliation_proof_store: (
        FileStealthReconciliationProofStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF
    if (
        stealth_reconciliation_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="reconciliation_proof_store_unavailable",
            detail="Reconciliation proof store was not available.",
        )

    record = _find_latest_reconciliation_proof(
        store=stealth_reconciliation_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_reconciliation_proof(
        record,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="reconciliation_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest reconciliation proof was found but is not safe "
                "exact-context no-live/no-mutation evidence for command "
                "execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.reconciliation_proof_id if record is not None else None
        ),
        missing_reason=(
            None if record is not None else "no_matching_reconciliation_proof"
        ),
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned reconciliation proof lookup is read-only and does "
            "not execute reconciliation, invoke managers, cancel or replace "
            "active placements, mutate exchange state, verify Coinbase, or "
            "authorize execution."
        ),
    )


def _find_latest_reconciliation_proof(
    *,
    store: FileStealthReconciliationProofStore,
    stealth_order_id: str,
) -> StealthReconciliationProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_cancel_replace_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_cancel_replace_proof_store: FileStealthCancelReplaceProofStore | None,
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF
    if (
        stealth_cancel_replace_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="cancel_replace_proof_store_unavailable",
            detail="Cancel/replace proof store was not available.",
        )

    record = _find_latest_cancel_replace_proof(
        store=stealth_cancel_replace_proof_store,
        stealth_order_id=admission_decision.identity_value,
    )
    if record is not None and not _is_safe_cancel_replace_proof(
        record,
        metadata=metadata,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="cancel_replace_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest cancel/replace proof was found but is not safe "
                "exact-context no-live/no-mutation evidence for command "
                "execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=(
            StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCommandExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.cancel_replace_proof_id if record is not None else None
        ),
        missing_reason=None if record is not None else "no_matching_cancel_replace_proof",
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Backend-owned cancel/replace proof lookup is read-only and does "
            "not build cancel/replace plans, invoke managers, call Coinbase, "
            "cancel or replace active placements, mutate state, or authorize "
            "execution."
        ),
    )


def _find_latest_cancel_replace_proof(
    *,
    store: FileStealthCancelReplaceProofStore,
    stealth_order_id: str,
) -> StealthCancelReplaceProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _resolve_post_write_reconciliation_proof(
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ),
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ),
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ),
) -> StealthCommandExecutionPrerequisiteResolverItem:
    prerequisite = StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION
    if (
        stealth_post_write_reconciliation_proof_store is None
        or not admission_decision.identity_value
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="post_write_reconciliation_proof_store_unavailable",
            detail="Post-write reconciliation proof store was not available.",
        )

    proof_record = _find_matching_post_write_reconciliation_proof(
        store=stealth_post_write_reconciliation_proof_store,
        metadata=metadata,
        admission_decision=admission_decision,
    )
    if proof_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="no_matching_post_write_reconciliation_proof",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Backend-owned post-write reconciliation proof lookup found no "
                "exact command-context record and did not execute reconciliation."
            ),
        )

    if not is_safe_stealth_post_write_reconciliation_proof_record(proof_record):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="post_write_reconciliation_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest exact-context post-write reconciliation proof was found "
                "but is not safe no-live/no-mutation evidence."
            ),
        )

    if stealth_post_write_execution_journal_store is None:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="post_write_execution_journal_store_unavailable",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact post-write reconciliation proof was found, but the "
                "execution-journal store was unavailable. No reconciliation "
                "execution, Coinbase call, manager call, or state mutation ran."
            ),
        )

    journal_record = find_matching_post_write_execution_journal_acceptance(
        store=stealth_post_write_execution_journal_store,
        proof_record=proof_record,
    )
    if journal_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="no_matching_post_write_execution_journal",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact post-write reconciliation proof was found, but no "
                "matching accepted execution-journal evidence was found. "
                "Execution remains blocked without running reconciliation."
            ),
        )
    if not is_safe_stealth_post_write_execution_journal_record(journal_record):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="post_write_execution_journal_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Matching post-write execution-journal evidence was found but "
                "is not safe no-live/no-mutation evidence."
            ),
        )

    if stealth_post_write_reconciliation_verification_store is None:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="post_write_reconciliation_verification_store_unavailable",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact proof and accepted execution-journal evidence were found, "
                "but the reconciliation-verification store was unavailable. "
                "No reconciliation execution, Coinbase call, manager call, or "
                "state mutation ran."
            ),
        )

    verification_record = find_matching_post_write_reconciliation_verification(
        store=stealth_post_write_reconciliation_verification_store,
        proof_record=proof_record,
        execution_journal_record=journal_record,
    )
    if verification_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="no_matching_post_write_reconciliation_verification",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact proof and accepted execution-journal evidence were found, "
                "but no matching post-write reconciliation verification was "
                "found. Execution remains blocked without running reconciliation."
            ),
        )
    if not is_safe_stealth_post_write_reconciliation_verification_record(
        verification_record
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            metadata=metadata,
            admission_decision=admission_decision,
            source=_source_for_command_specific_prerequisite(prerequisite),
            lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=(
                verification_record.reconciliation_verification_id
            ),
            missing_reason="post_write_reconciliation_verification_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Matching post-write reconciliation verification was found but "
                "is not safe no-live/no-mutation evidence."
            ),
        )

    return _resolver_item(
        prerequisite=prerequisite,
        metadata=metadata,
        admission_decision=admission_decision,
        source=_source_for_command_specific_prerequisite(prerequisite),
        lookup_status=StealthCommandExecutionPrerequisiteLookupStatus.RESOLVED,
        lookup_ran=True,
        resolved=True,
        resolved_evidence_id=verification_record.reconciliation_verification_id,
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Exact safe post-write reconciliation proof, accepted "
            "execution-journal evidence, and post-write reconciliation "
            "verification were found. This resolves only prerequisite evidence; "
            "live execution service, live adapter, manager invocation, "
            "Coinbase calls, reconciliation execution, active-placement "
            "cancel/replace, and state mutation boundaries remain disabled."
        ),
    )


def _find_matching_post_write_reconciliation_proof(
    *,
    store: FileStealthPostWriteReconciliationProofStore,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthPostWriteReconciliationProofRecord | None:
    for record in store.read_for_stealth_order_id(
        admission_decision.identity_value or "",
        limit=500,
    ):
        if _post_write_reconciliation_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        ):
            return record
    return None


def _is_safe_mutation_claim_snapshot_proof(
    record: StealthMutationClaimSnapshotProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _mutation_claim_proof_matches_admission(record, admission_decision)
        and record.proof_persisted is True
        and record.runtime_claims_observed is True
        and record.active_claim_count == 0
        and record.manager_invocation_ran is False
        and record.claim_acquire_ran is False
        and record.claim_release_ran is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_manager_invocation_policy_proof(
    record: StealthManagerInvocationPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _manager_invocation_policy_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        )
        and record.proof_persisted is True
        and record.manager_policy_verified is False
        and record.manager_invocation_allowed is False
        and record.manager_invocation_ran is False
        and record.mutation_lock_policy_verified is False
        and record.exchange_reality_policy_verified is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_coinbase_exchange_submission_policy_proof(
    record: StealthCoinbaseExchangeSubmissionPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _coinbase_exchange_submission_policy_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        )
        and record.proof_persisted is True
        and record.exchange_submission_policy_verified is False
        and record.coinbase_submit_allowed is False
        and record.coinbase_cancel_allowed is False
        and record.live_coinbase_read_allowed is False
        and record.live_cap_verified is False
        and record.manager_invocation_ran is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_post_write_reconciliation_execution_policy_proof(
    record: StealthPostWriteReconciliationExecutionPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _post_write_reconciliation_execution_policy_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        )
        and record.proof_persisted is True
        and record.post_write_reconciliation_execution_policy_verified is False
        and record.post_write_reconciliation_execution_allowed is False
        and record.route_bound_reconciliation_plan_required is True
        and record.execution_journal_required is True
        and record.reconciliation_verification_required is True
        and record.safe_reconciliation_chain_verified is False
        and record.manager_invocation_ran is False
        and record.reconciliation_plan_built is False
        and record.reconciliation_execution_ran is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_recovery_proof(
    record: StealthRecoveryProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _recovery_proof_matches_admission(record, admission_decision)
        and record.proof_persisted is True
        and record.recovery_proof_verified is False
        and record.manager_invocation_ran is False
        and record.recovery_plan_built is False
        and record.recovery_repair_executed is False
        and record.rollback_executed is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_reveal_trigger_proof(
    record: StealthRevealTriggerProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _reveal_trigger_proof_matches_admission(record, admission_decision)
        and record.proof_persisted is True
        and record.reveal_trigger_verified is False
        and record.manager_invocation_ran is False
        and record.trigger_evaluation_ran is False
        and record.should_trigger_reveal_called is False
        and record.reveal_order_slice_called is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_reconciliation_proof(
    record: StealthReconciliationProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _reconciliation_proof_matches_admission(record, admission_decision)
        and record.proof_persisted is True
        and record.reconciliation_proof_verified is False
        and record.manager_invocation_ran is False
        and record.reconciliation_plan_built is False
        and record.reconciliation_execution_ran is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _is_safe_cancel_replace_proof(
    record: StealthCancelReplaceProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _cancel_replace_proof_matches_admission(
            record,
            metadata=metadata,
            admission_decision=admission_decision,
        )
        and record.proof_persisted is True
        and record.cancel_replace_proof_verified is False
        and record.manager_invocation_ran is False
        and record.cancel_replace_plan_built is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _mutation_claim_proof_matches_admission(
    record: StealthMutationClaimSnapshotProofRecord,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
    )


def _manager_invocation_policy_proof_matches_admission(
    record: StealthManagerInvocationPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_mutation_family == metadata.mutation_family
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _coinbase_exchange_submission_policy_proof_matches_admission(
    record: StealthCoinbaseExchangeSubmissionPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_mutation_family == metadata.mutation_family
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _post_write_reconciliation_execution_policy_proof_matches_admission(
    record: StealthPostWriteReconciliationExecutionPolicyProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_mutation_family == metadata.mutation_family
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _recovery_proof_matches_admission(
    record: StealthRecoveryProofRecord,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
    )


def _reveal_trigger_proof_matches_admission(
    record: StealthRevealTriggerProofRecord,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
    )


def _reconciliation_proof_matches_admission(
    record: StealthReconciliationProofRecord,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
    )


def _cancel_replace_proof_matches_admission(
    record: StealthCancelReplaceProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_mutation_family == metadata.mutation_family
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
    )


def _post_write_reconciliation_proof_matches_admission(
    record: StealthPostWriteReconciliationProofRecord,
    *,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == admission_decision.route
        and record.guarded_command_method == admission_decision.method
        and record.guarded_service_method == admission_decision.service_method
        and record.guarded_mutation_family == metadata.mutation_family
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _is_safe_active_placement_exchange_truth_proof(
    record: StealthActivePlacementExchangeTruthProofRecord,
) -> bool:
    return (
        record.proof_persisted is True
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def _source_for_command_specific_prerequisite(
    prerequisite: StealthCommandExecutionPrerequisite,
) -> str:
    return {
        StealthCommandExecutionPrerequisite.ACTIVE_PLACEMENT_EXCHANGE_TRUTH: (
            "admin_api_stealth_exchange_truth_proof_log"
        ),
        StealthCommandExecutionPrerequisite.MANAGER_INVOCATION_POLICY: (
            "admin_api_stealth_manager_invocation_policy_log"
        ),
        StealthCommandExecutionPrerequisite.COINBASE_EXCHANGE_SUBMISSION_POLICY: (
            "admin_api_stealth_coinbase_exchange_submission_policy_log"
        ),
        StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION_EXECUTION_POLICY: (
            "admin_api_stealth_post_write_reconciliation_execution_policy_log"
        ),
        StealthCommandExecutionPrerequisite.REVEAL_TRIGGER_EVIDENCE: (
            "admin_api_stealth_reveal_trigger_proof_log"
        ),
        StealthCommandExecutionPrerequisite.MUTATION_CLAIM_SNAPSHOT: (
            "stealth_manager_mutation_claim_snapshot"
        ),
        StealthCommandExecutionPrerequisite.RECOVERY_PROOF: (
            "admin_api_stealth_recovery_proof_log"
        ),
        StealthCommandExecutionPrerequisite.RECONCILIATION_PROOF: (
            "admin_api_stealth_reconciliation_proof_log"
        ),
        StealthCommandExecutionPrerequisite.CANCEL_REPLACE_PROOF: (
            "admin_api_stealth_cancel_replace_proof_log"
        ),
        StealthCommandExecutionPrerequisite.POST_WRITE_RECONCILIATION: (
            "admin_api_stealth_post_write_reconciliation_proof_log"
        ),
    }.get(prerequisite, "backend_resolver")


def _resolver_item(
    *,
    prerequisite: StealthCommandExecutionPrerequisite,
    metadata: StealthCommandExecutionMetadata,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    lookup_status: StealthCommandExecutionPrerequisiteLookupStatus,
    detail: str,
    source: str = "backend_resolver",
    lookup_ran: bool = False,
    resolved: bool = False,
    resolved_evidence_id: str | None = None,
    missing_reason: str | None = None,
    stale_or_invalid: bool = False,
    proof_lookup_authority: str = "none",
) -> StealthCommandExecutionPrerequisiteResolverItem:
    return StealthCommandExecutionPrerequisiteResolverItem(
        prerequisite=prerequisite,
        source=source,
        route=metadata.route,
        identity_value=admission_decision.identity_value,
        lookup_status=lookup_status,
        lookup_ran=lookup_ran,
        resolved=resolved,
        resolved_evidence_id=resolved_evidence_id,
        missing_reason=missing_reason,
        stale_or_invalid=stale_or_invalid,
        proof_lookup_authority=proof_lookup_authority,
        detail=detail,
    )
