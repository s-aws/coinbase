"""No-live stealth lifecycle execution-contract evidence builders."""

from __future__ import annotations

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiMutationFamilyType,
    AdminApiStealthCommandSuiteGapFamily,
    AdminApiStealthAdmissionContextField,
    StealthCreateLifecycleExecutionBlocker,
    StealthCreateLifecycleExecutionPrerequisite,
    StealthCreateLifecycleExecutionPrerequisiteLookupStatus,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthCreateLifecycleExecutionBlockerChainItem,
    StealthCreateLifecycleExecutionReadinessStageItem,
    StealthCreateLifecyclePrerequisiteResolverItem,
    StealthCreateLifecycleWriteExecutionContractEvidence,
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
from .stealth_lifecycle_write import (
    FileStealthLifecycleWriteGuardProofStore,
    StealthCreateLifecycleWriteGuardProofRecord,
)
from .stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
    StealthManagerInvocationPolicyProofRecord,
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


STEALTH_CREATE_ROUTE = "/api/v1/stealth/orders"
STEALTH_CREATE_METHOD = "POST"
STEALTH_CREATE_MODULE_ID = "stealth_orders"
STEALTH_CREATE_SERVICE_METHOD = "create_stealth_order"
STEALTH_CREATE_MANAGER_METHOD = "core/stealth_order_manager.py::create_stealth_order"

REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS: tuple[str, ...] = (
    AdminApiStealthAdmissionContextField.ROUTE.value,
    AdminApiStealthAdmissionContextField.METHOD.value,
    AdminApiStealthAdmissionContextField.STEALTH_ORDER_ID.value,
    AdminApiStealthAdmissionContextField.ACTOR_ID.value,
    AdminApiStealthAdmissionContextField.IDEMPOTENCY_KEY.value,
    AdminApiStealthAdmissionContextField.OPERATOR_INTENT.value,
    AdminApiStealthAdmissionContextField.PAYLOAD_HASH.value,
)

REQUIRED_CREATE_EXECUTION_PREREQUISITES: tuple[str, ...] = (
    StealthCreateLifecycleExecutionPrerequisite.APPROVAL_SNAPSHOT.value,
    StealthCreateLifecycleExecutionPrerequisite.ADMISSION_AUDIT.value,
    StealthCreateLifecycleExecutionPrerequisite.CAP_GUARD_DECISION.value,
    StealthCreateLifecycleExecutionPrerequisite.RECONCILIATION_PLAN.value,
    StealthCreateLifecycleExecutionPrerequisite.MANAGER_INVOCATION_POLICY.value,
    StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER.value,
    StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION.value,
)

NEXT_REQUIRED_CREATE_CONTRACT_BY_PREREQUISITE: dict[
    StealthCreateLifecycleExecutionPrerequisite,
    str,
] = {
    StealthCreateLifecycleExecutionPrerequisite.APPROVAL_SNAPSHOT: (
        "POST /api/v1/admin/approvals/requests"
    ),
    StealthCreateLifecycleExecutionPrerequisite.ADMISSION_AUDIT: (
        "POST /api/v1/admin/admission-audits"
    ),
    StealthCreateLifecycleExecutionPrerequisite.CAP_GUARD_DECISION: (
        "POST /api/v1/admin/cap-guard/decisions"
    ),
    StealthCreateLifecycleExecutionPrerequisite.RECONCILIATION_PLAN: (
        "POST /api/v1/admin/reconciliation/plans"
    ),
    StealthCreateLifecycleExecutionPrerequisite.MANAGER_INVOCATION_POLICY: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "manager-invocation-policy-proofs"
    ),
    StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "lifecycle-write-guard-proofs"
    ),
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE: (
        "application/admin_api/live_execution.py::"
        "build_live_execution_service_contract"
    ),
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER: (
        "application/admin_api/live_execution.py::"
        "build_live_execution_adapter_contract"
    ),
    StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION: (
        "POST /api/v1/stealth/orders/{stealth_order_id}/"
        "post-write-reconciliation-proofs"
    ),
}

BASE_CREATE_EXECUTION_BLOCKERS: tuple[str, ...] = (
    StealthCreateLifecycleExecutionBlocker.EXECUTION_CONTRACT_MISSING.value,
    StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_ADAPTER_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.ACTIVE_PLACEMENT_CANCEL_REPLACE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_ROW_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.ORDER_PARENT_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.LIFECYCLE_EVENT_DISPATCH_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_CANCEL_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_READ_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.RECONCILIATION_EXECUTION_DISABLED.value,
)


def build_stealth_create_lifecycle_write_execution_contract(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None,
    lifecycle_write_guard_proof_store: (
        FileStealthLifecycleWriteGuardProofStore | None
    ) = None,
    manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ) = None,
    post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ) = None,
    post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ) = None,
    post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ) = None,
    resolved_prerequisites: list[str] | None = None,
) -> StealthCreateLifecycleWriteExecutionContractEvidence:
    """Build blocked execution-contract evidence for stealth create."""

    resolution = _build_prerequisite_resolution(
        stealth_order_id=stealth_order_id,
        exact_command_context_present=exact_command_context_present,
        admission_decision=admission_decision,
        lifecycle_write_guard_proof_store=lifecycle_write_guard_proof_store,
        manager_policy_proof_store=manager_policy_proof_store,
        post_write_reconciliation_proof_store=post_write_reconciliation_proof_store,
        post_write_execution_journal_store=post_write_execution_journal_store,
        post_write_reconciliation_verification_store=(
            post_write_reconciliation_verification_store
        ),
    )
    resolved = {
        item.prerequisite.value
        for item in resolution
        if item.resolved
    }
    resolved.update(resolved_prerequisites or [])
    required_prerequisites = list(REQUIRED_CREATE_EXECUTION_PREREQUISITES)
    missing_prerequisites = [
        prerequisite
        for prerequisite in required_prerequisites
        if prerequisite not in resolved
    ]
    missing_context_fields = (
        []
        if exact_command_context_present
        else list(REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS)
    )
    blockers = list(BASE_CREATE_EXECUTION_BLOCKERS)
    blockers.extend(f"{item}_missing" for item in missing_prerequisites)
    if missing_context_fields:
        blockers.append(
            StealthCreateLifecycleExecutionBlocker.EXACT_COMMAND_CONTEXT_MISSING.value
        )
    execution_readiness_stages = _build_execution_readiness_stages(
        resolution=resolution,
    )
    remaining_execution_blockers = _build_remaining_execution_blockers(
        resolution=resolution,
        exact_command_context_present=exact_command_context_present,
    )
    post_write_reconciliation_proof_record = (
        _find_matching_post_write_reconciliation_proof(
            store=post_write_reconciliation_proof_store,
            stealth_order_id=stealth_order_id,
            admission_decision=admission_decision,
        )
        if post_write_reconciliation_proof_store is not None
        and stealth_order_id
        and admission_decision is not None
        else None
    )
    post_write_execution_journal_record = (
        find_matching_post_write_execution_journal_acceptance(
            store=post_write_execution_journal_store,
            proof_record=post_write_reconciliation_proof_record,
        )
        if post_write_execution_journal_store is not None
        and post_write_reconciliation_proof_record is not None
        else None
    )
    post_write_reconciliation_verification_record = (
        find_matching_post_write_reconciliation_verification(
            store=post_write_reconciliation_verification_store,
            proof_record=post_write_reconciliation_proof_record,
            execution_journal_record=post_write_execution_journal_record,
        )
        if post_write_reconciliation_verification_store is not None
        and post_write_reconciliation_proof_record is not None
        and post_write_execution_journal_record is not None
        else None
    )

    execution_candidate = _build_execution_candidate(
        stealth_order_id=stealth_order_id,
        exact_command_context_present=exact_command_context_present,
        remaining_execution_blockers=remaining_execution_blockers,
    )
    execution_preflight = build_stealth_execution_preflight(execution_candidate)
    execution_transition_barrier = build_stealth_execution_transition_barrier(
        execution_preflight
    )

    return StealthCreateLifecycleWriteExecutionContractEvidence(
        stealth_order_id=stealth_order_id,
        accepted_command_identity_keys=["stealth_order_id"],
        rejected_command_identity_keys=[
            "client_order_id",
            "active_placement_client_order_id",
            "exchange_order_id",
            "order_id",
        ],
        exact_command_context_present=exact_command_context_present,
        required_context_fields=list(REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS),
        missing_context_fields=missing_context_fields,
        required_prerequisites=required_prerequisites,
        missing_prerequisites=missing_prerequisites,
        resolved_prerequisites=sorted(resolved),
        prerequisite_resolver_available=True,
        prerequisite_resolver_lookup_ran=any(item.lookup_ran for item in resolution),
        prerequisite_resolution=resolution,
        execution_readiness_stage_count=len(execution_readiness_stages),
        blocked_execution_readiness_stage_count=sum(
            1 for item in execution_readiness_stages if item.blocking
        ),
        passed_execution_readiness_stage_count=sum(
            1 for item in execution_readiness_stages if item.resolved
        ),
        execution_readiness_stages=execution_readiness_stages,
        blockers=blockers,
        remaining_execution_blocker_count=len(remaining_execution_blockers),
        remaining_execution_blockers=remaining_execution_blockers,
        manager_invocation_policy_required=True,
        manager_invocation_policy_resolved=(
            StealthCreateLifecycleExecutionPrerequisite.MANAGER_INVOCATION_POLICY.value
            in resolved
        ),
        manager_invocation_policy_proof_id=next(
            (
                item.resolved_evidence_id
                for item in resolution
                if item.prerequisite
                == StealthCreateLifecycleExecutionPrerequisite.MANAGER_INVOCATION_POLICY
            ),
            None,
        ),
        lifecycle_write_guard_proof_resolved=(
            StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF.value
            in resolved
        ),
        lifecycle_write_guard_proof_lookup_ran=any(
            item.prerequisite
            == StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF
            and item.lookup_ran
            for item in resolution
        ),
        live_execution_service_source=(
            admission_decision.live_execution_service_source
            if admission_decision is not None
            else DISABLED_LIVE_EXECUTION_SERVICE_SOURCE
        ),
        live_execution_service_missing_reason=(
            admission_decision.live_execution_service_missing_reason
            if admission_decision is not None
            else "live_execution_disabled"
        ),
        live_execution_service_contract=build_live_execution_service_contract(
            method=(
                admission_decision.method
                if admission_decision is not None
                else STEALTH_CREATE_METHOD
            ),
            route=STEALTH_CREATE_ROUTE,
            module_id=(
                admission_decision.module_id
                if admission_decision is not None
                else STEALTH_CREATE_MODULE_ID
            ),
            service_method=STEALTH_CREATE_SERVICE_METHOD,
            action_class=(
                admission_decision.action_class
                if admission_decision is not None
                else AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
        ),
        live_execution_intent_contract=(
            admission_decision.live_execution_intent
            if admission_decision is not None
            else None
        ),
        live_execution_adapter_source=DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
        live_execution_adapter_missing_reason="live_execution_adapter_disabled",
        live_execution_adapter_contract=build_live_execution_adapter_contract(
            method=(
                admission_decision.method
                if admission_decision is not None
                else STEALTH_CREATE_METHOD
            ),
            route=STEALTH_CREATE_ROUTE,
            module_id=(
                admission_decision.module_id
                if admission_decision is not None
                else STEALTH_CREATE_MODULE_ID
            ),
            service_method=STEALTH_CREATE_SERVICE_METHOD,
            action_class=(
                admission_decision.action_class
                if admission_decision is not None
                else AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
        ),
        post_write_reconciliation_route=POST_WRITE_RECONCILIATION_ROUTE,
        post_write_reconciliation_method=POST_WRITE_RECONCILIATION_METHOD,
        post_write_reconciliation_source=POST_WRITE_RECONCILIATION_SOURCE,
        post_write_reconciliation_missing_reason=(
            None
            if (
                StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION.value
                in resolved
            )
            else "post_write_reconciliation_missing"
        ),
        post_write_reconciliation_boundary=(
            build_stealth_post_write_reconciliation_boundary(
                mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
                command_route=STEALTH_CREATE_ROUTE,
                service_method=STEALTH_CREATE_SERVICE_METHOD,
                stealth_order_id=stealth_order_id,
                admission_decision=admission_decision,
            )
        ),
        post_write_completion_verifier_contract=(
            build_stealth_post_write_completion_verifier_contract(
                mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
                command_route=STEALTH_CREATE_ROUTE,
                service_method=STEALTH_CREATE_SERVICE_METHOD,
                stealth_order_id=stealth_order_id,
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
        canonical_execution_path=[
            STEALTH_CREATE_MANAGER_METHOD
        ],
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Execution-contract evidence is backend-owned and no-live.",
            "Prerequisite resolver evidence is read-only and no-authority.",
            "The contract boundary does not invoke StealthOrderManager.",
            "The contract boundary does not write stealth rows, order_parent rows, or lifecycle events.",
            "The contract boundary does not read Coinbase, submit or cancel Coinbase orders, cancel/replace active placements, or execute reconciliation.",
        ],
        detail=(
            "Stealth create execution remains blocked until exact command "
            "context, approval, admission audit, cap/guard, reconciliation "
            "plan, lifecycle-write guard proof, live execution service, live "
            "adapter, and post-write reconciliation evidence are all present."
        ),
    )


def _build_execution_candidate(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    remaining_execution_blockers: list[StealthCreateLifecycleExecutionBlockerChainItem],
) -> StealthExecutionCandidateEvidence:
    """Expose the future create execution candidate without enabling it."""

    return StealthExecutionCandidateEvidence(
        mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
        workflow_family=AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW,
        command_route=STEALTH_CREATE_ROUTE,
        command_method=STEALTH_CREATE_METHOD,
        service_method=STEALTH_CREATE_SERVICE_METHOD,
        manager_methods=[STEALTH_CREATE_MANAGER_METHOD],
        identity_value=stealth_order_id,
        exact_command_context_present=exact_command_context_present,
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
        canonical_execution_path=[STEALTH_CREATE_MANAGER_METHOD],
        detail=(
            "This candidate identifies the backend-owned stealth create path "
            "that may become executable only after every blocker resolves; it "
            "does not invoke StealthOrderManager, Coinbase, reconciliation, or "
            "state writes."
        ),
    )


def _build_execution_readiness_stages(
    *,
    resolution: list[StealthCreateLifecyclePrerequisiteResolverItem],
) -> list[StealthCreateLifecycleExecutionReadinessStageItem]:
    """Summarize stealth create prerequisites as ordered no-live stages."""

    resolution_by_prerequisite = {item.prerequisite: item for item in resolution}
    stages: list[StealthCreateLifecycleExecutionReadinessStageItem] = []
    for stage_order, prerequisite in enumerate(
        StealthCreateLifecycleExecutionPrerequisite,
        start=1,
    ):
        item = resolution_by_prerequisite[prerequisite]
        stages.append(
            StealthCreateLifecycleExecutionReadinessStageItem(
                stage_order=stage_order,
                workflow_family=(
                    AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW
                ),
                mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
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
                next_required_contract=(
                    NEXT_REQUIRED_CREATE_CONTRACT_BY_PREREQUISITE[prerequisite]
                ),
                detail=(
                    f"{prerequisite.value} stage for stealth_create remains "
                    f"{'resolved' if item.resolved else 'blocked'}; this "
                    "stage is evidence only and does not invoke the stealth "
                    "manager, write lifecycle rows, call Coinbase, or mutate "
                    "state."
                ),
            )
        )
    return stages


def _build_remaining_execution_blockers(
    *,
    resolution: list[StealthCreateLifecyclePrerequisiteResolverItem],
    exact_command_context_present: bool,
) -> list[StealthCreateLifecycleExecutionBlockerChainItem]:
    """Expose create execution blockers that remain after prerequisite lookups."""

    resolved = {item.prerequisite for item in resolution if item.resolved}
    by_prerequisite = {item.prerequisite: item for item in resolution}
    blockers: list[tuple[
        StealthCreateLifecycleExecutionBlocker,
        StealthCreateLifecycleExecutionPrerequisite | None,
        str,
        str,
    ]] = [
        (
            StealthCreateLifecycleExecutionBlocker.EXECUTION_CONTRACT_MISSING,
            None,
            "application/admin_api/stealth_lifecycle_execution.py::"
            "build_stealth_create_lifecycle_write_execution_contract",
            "The create response is still contract evidence, not an executable create command.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_DISABLED,
            StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE,
            NEXT_REQUIRED_CREATE_CONTRACT_BY_PREREQUISITE[
                StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE
            ],
            "The shared live execution service remains disabled for stealth create.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_ADAPTER_DISABLED,
            StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER,
            NEXT_REQUIRED_CREATE_CONTRACT_BY_PREREQUISITE[
                StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER
            ],
            "The stealth create live execution adapter remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED,
            None,
            STEALTH_CREATE_MANAGER_METHOD,
            "The StealthOrderManager create method may not be invoked from this contract.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.ACTIVE_PLACEMENT_CANCEL_REPLACE_DISABLED,
            None,
            "core/stealth_order_manager.py active-placement cancel/replace path",
            "The create contract may not cancel or replace active placements.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.STEALTH_ROW_WRITE_DISABLED,
            None,
            "database stealth_orders write path",
            "The stealth_orders row write path remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.ORDER_PARENT_WRITE_DISABLED,
            None,
            "database/order_parent write path",
            "The order_parent write path remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.LIFECYCLE_EVENT_DISPATCH_DISABLED,
            None,
            "stealth lifecycle event dispatch path",
            "Lifecycle event dispatch remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED,
            None,
            "external/coinbase_api.py order submit path",
            "Coinbase order submission remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_CANCEL_DISABLED,
            None,
            "external/coinbase_api.py cancel_order(client_order_id)",
            "Coinbase order cancellation remains disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.COINBASE_READ_DISABLED,
            None,
            "external/coinbase_api.py read/reconcile path",
            "Live Coinbase reads remain disabled.",
        ),
        (
            StealthCreateLifecycleExecutionBlocker.RECONCILIATION_EXECUTION_DISABLED,
            None,
            "application/admin_api reconciliation executor",
            "Post-write reconciliation execution remains disabled.",
        ),
    ]
    if (
        StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION
        not in resolved
    ):
        blockers.append(
            (
                StealthCreateLifecycleExecutionBlocker.POST_WRITE_RECONCILIATION_MISSING,
                StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION,
                NEXT_REQUIRED_CREATE_CONTRACT_BY_PREREQUISITE[
                    StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION
                ],
                "The exact proof, accepted journal, and verification chain has not resolved post-write reconciliation evidence.",
            )
        )
    if not exact_command_context_present:
        blockers.append(
            (
                StealthCreateLifecycleExecutionBlocker.EXACT_COMMAND_CONTEXT_MISSING,
                None,
                "Admin API command envelope",
                "The exact command envelope is missing required route, actor, idempotency, intent, or payload-hash evidence.",
            )
        )

    items: list[StealthCreateLifecycleExecutionBlockerChainItem] = []
    for blocker_order, (blocker, prerequisite, next_contract, detail) in enumerate(
        blockers,
        start=1,
    ):
        source_item = by_prerequisite.get(prerequisite) if prerequisite else None
        items.append(
            StealthCreateLifecycleExecutionBlockerChainItem(
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


def _build_prerequisite_resolution(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    lifecycle_write_guard_proof_store: (
        FileStealthLifecycleWriteGuardProofStore | None
    ),
    manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ),
    post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ),
    post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ),
    post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ),
) -> list[StealthCreateLifecyclePrerequisiteResolverItem]:
    if not exact_command_context_present:
        return [
            _resolver_item(
                prerequisite=prerequisite,
                identity_value=stealth_order_id,
                lookup_status=(
                    StealthCreateLifecycleExecutionPrerequisiteLookupStatus.NOT_CHECKED
                ),
                missing_reason="exact_command_context_missing",
                detail=(
                    "Exact command context is required before prerequisite "
                    "lookup can run."
                ),
            )
            for prerequisite in StealthCreateLifecycleExecutionPrerequisite
        ]
    if admission_decision is None:
        return [
            _resolver_item(
                prerequisite=prerequisite,
                identity_value=stealth_order_id,
                lookup_status=(
                    StealthCreateLifecycleExecutionPrerequisiteLookupStatus.NOT_CHECKED
                ),
                missing_reason="admission_decision_missing",
                detail=(
                    "Command admission evidence is required before prerequisite "
                    "lookup can run."
                ),
            )
            for prerequisite in StealthCreateLifecycleExecutionPrerequisite
        ]

    approval = _resolver_item_from_flag(
        prerequisite=StealthCreateLifecycleExecutionPrerequisite.APPROVAL_SNAPSHOT,
        identity_value=stealth_order_id,
        source=admission_decision.approval_snapshot_source or "approval_store",
        present=admission_decision.approval_snapshot_present,
        evidence_id=admission_decision.approval_snapshot_id,
        missing_reason=admission_decision.approval_snapshot_missing_reason,
        detail="Route-specific approval snapshot resolver evidence.",
    )
    admission = _resolver_item_from_flag(
        prerequisite=StealthCreateLifecycleExecutionPrerequisite.ADMISSION_AUDIT,
        identity_value=stealth_order_id,
        source=admission_decision.admission_audit_source or "admin_api_audit_log",
        present=admission_decision.admission_audit_present,
        evidence_id=admission_decision.admission_audit_id,
        missing_reason=admission_decision.admission_audit_missing_reason,
        dependency_resolved=approval.resolved,
        dependency_missing_reason="approval_snapshot_missing",
        detail="Route-specific admission audit resolver evidence.",
    )
    cap_guard = _resolver_item_from_flag(
        prerequisite=StealthCreateLifecycleExecutionPrerequisite.CAP_GUARD_DECISION,
        identity_value=stealth_order_id,
        source=admission_decision.cap_guard_source or "admin_api_cap_guard_log",
        present=admission_decision.cap_guard_present,
        evidence_id=admission_decision.cap_guard_decision_id,
        missing_reason=admission_decision.cap_guard_missing_reason,
        dependency_resolved=admission.resolved,
        dependency_missing_reason="admission_audit_missing",
        detail="Route-specific cap/guard decision resolver evidence.",
    )
    reconciliation = _resolver_item_from_flag(
        prerequisite=StealthCreateLifecycleExecutionPrerequisite.RECONCILIATION_PLAN,
        identity_value=stealth_order_id,
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
    lifecycle_guard = _resolve_lifecycle_write_guard_proof(
        stealth_order_id=stealth_order_id,
        admission_decision=admission_decision,
        lifecycle_write_guard_proof_store=lifecycle_write_guard_proof_store,
        prerequisites_resolved=(
            approval.resolved
            and admission.resolved
            and cap_guard.resolved
            and reconciliation.resolved
        ),
    )
    manager_policy = _resolve_manager_invocation_policy_proof(
        stealth_order_id=stealth_order_id,
        admission_decision=admission_decision,
        manager_policy_proof_store=manager_policy_proof_store,
        prerequisites_resolved=(
            approval.resolved
            and admission.resolved
            and cap_guard.resolved
            and reconciliation.resolved
        ),
    )

    return [
        approval,
        admission,
        cap_guard,
        reconciliation,
        manager_policy,
        lifecycle_guard,
        _resolver_item(
            prerequisite=(
                StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE
            ),
            identity_value=stealth_order_id,
            source=admission_decision.live_execution_service_source
            or DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.DISABLED,
            missing_reason=admission_decision.live_execution_service_missing_reason
            or "live_execution_disabled",
            detail="Live execution service remains disabled for stealth create.",
        ),
        _resolver_item(
            prerequisite=(
                StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER
            ),
            identity_value=stealth_order_id,
            source=DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.DISABLED,
            missing_reason="live_execution_adapter_disabled",
            detail="Live execution adapter is not enabled for stealth create.",
        ),
        _resolve_post_write_reconciliation_proof(
            stealth_order_id=stealth_order_id,
            admission_decision=admission_decision,
            post_write_reconciliation_proof_store=(
                post_write_reconciliation_proof_store
            ),
            post_write_execution_journal_store=post_write_execution_journal_store,
            post_write_reconciliation_verification_store=(
                post_write_reconciliation_verification_store
            ),
        ),
    ]


def _resolver_item_from_flag(
    *,
    prerequisite: StealthCreateLifecycleExecutionPrerequisite,
    identity_value: str | None,
    source: str,
    present: bool,
    evidence_id: str | None,
    missing_reason: str | None,
    detail: str,
    dependency_resolved: bool = True,
    dependency_missing_reason: str | None = None,
) -> StealthCreateLifecyclePrerequisiteResolverItem:
    if not dependency_resolved:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=identity_value,
            source=source,
            lookup_status=(
                StealthCreateLifecycleExecutionPrerequisiteLookupStatus.BLOCKED_BY_DEPENDENCY
            ),
            missing_reason=dependency_missing_reason,
            detail=detail,
        )
    return _resolver_item(
        prerequisite=prerequisite,
        identity_value=identity_value,
        source=source,
        lookup_status=(
            StealthCreateLifecycleExecutionPrerequisiteLookupStatus.RESOLVED
            if present
            else StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=present,
        resolved_evidence_id=evidence_id if present else None,
        missing_reason=None if present else missing_reason,
        detail=detail,
    )


def _resolve_lifecycle_write_guard_proof(
    *,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    lifecycle_write_guard_proof_store: (
        FileStealthLifecycleWriteGuardProofStore | None
    ),
    prerequisites_resolved: bool,
) -> StealthCreateLifecyclePrerequisiteResolverItem:
    prerequisite = StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF
    if not prerequisites_resolved:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source="admin_api_stealth_lifecycle_write_guard_proof_log",
            lookup_status=(
                StealthCreateLifecycleExecutionPrerequisiteLookupStatus.BLOCKED_BY_DEPENDENCY
            ),
            missing_reason="admission_prerequisites_missing",
            detail=(
                "Lifecycle-write guard proof lookup requires approval, audit, "
                "cap/guard, and reconciliation evidence first."
            ),
        )
    if lifecycle_write_guard_proof_store is None or not stealth_order_id:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source="admin_api_stealth_lifecycle_write_guard_proof_log",
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="lifecycle_write_guard_proof_store_unavailable",
            detail="Lifecycle-write guard proof store was not available.",
        )

    record = _find_matching_lifecycle_write_guard_proof(
        store=lifecycle_write_guard_proof_store,
        stealth_order_id=stealth_order_id,
        admission_decision=admission_decision,
    )
    return _resolver_item(
        prerequisite=prerequisite,
        identity_value=stealth_order_id,
        source="admin_api_stealth_lifecycle_write_guard_proof_log",
        lookup_status=(
            StealthCreateLifecycleExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING
        ),
        lookup_ran=True,
        resolved=record is not None,
        resolved_evidence_id=(
            record.lifecycle_write_guard_proof_id if record is not None else None
        ),
        missing_reason=None if record is not None else "no_matching_lifecycle_write_guard_proof",
        detail="Exact stealth create lifecycle-write guard proof resolver evidence.",
    )


def _find_matching_lifecycle_write_guard_proof(
    *,
    store: FileStealthLifecycleWriteGuardProofStore,
    stealth_order_id: str,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthCreateLifecycleWriteGuardProofRecord | None:
    for record in store.read_for_stealth_order_id(stealth_order_id, limit=500):
        if (
            record.guarded_command_route == "/api/v1/stealth/orders"
            and record.guarded_command_method == "POST"
            and record.guarded_service_method == "create_stealth_order"
            and record.guarded_actor_id == admission_decision.actor_id
            and record.guarded_operator_intent == admission_decision.operator_intent
            and record.guarded_idempotency_key == admission_decision.idempotency_key
            and record.guarded_payload_hash == admission_decision.payload_hash
            and record.approval_snapshot_id == admission_decision.approval_snapshot_id
            and record.admission_audit_id == admission_decision.admission_audit_id
            and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
            and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
            and record.manager_invocation_ran is False
            and record.stealth_row_write_ran is False
            and record.order_parent_write_ran is False
            and record.lifecycle_event_dispatch_ran is False
            and record.coinbase_read_attempted is False
            and record.coinbase_order_submitted is False
            and record.reconciliation_executed is False
        ):
            return record
    return None


def _resolve_manager_invocation_policy_proof(
    *,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ),
    prerequisites_resolved: bool,
) -> StealthCreateLifecyclePrerequisiteResolverItem:
    prerequisite = StealthCreateLifecycleExecutionPrerequisite.MANAGER_INVOCATION_POLICY
    source = "admin_api_stealth_manager_invocation_policy_log"
    if not prerequisites_resolved:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=(
                StealthCreateLifecycleExecutionPrerequisiteLookupStatus.BLOCKED_BY_DEPENDENCY
            ),
            missing_reason="admission_prerequisites_missing",
            detail=(
                "Manager-invocation policy proof lookup requires approval, "
                "audit, cap/guard, and reconciliation evidence first."
            ),
        )
    if manager_policy_proof_store is None or not stealth_order_id:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="manager_invocation_policy_proof_store_unavailable",
            detail="Manager-invocation policy proof store was not available.",
        )

    record = _find_latest_manager_invocation_policy_proof(
        store=manager_policy_proof_store,
        stealth_order_id=stealth_order_id,
    )
    if record is not None and not _is_safe_manager_invocation_policy_proof(
        record,
        admission_decision=admission_decision,
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=record.manager_policy_proof_id,
            missing_reason="manager_invocation_policy_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest manager-invocation policy proof was found but is not "
                "safe exact-context no-live/no-mutation evidence for stealth "
                "create execution posture."
            ),
        )
    return _resolver_item(
        prerequisite=prerequisite,
        identity_value=stealth_order_id,
        source=source,
        lookup_status=(
            StealthCreateLifecycleExecutionPrerequisiteLookupStatus.RESOLVED
            if record is not None
            else StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING
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
            "and does not invoke managers, call Coinbase, write lifecycle "
            "state, execute reconciliation, or authorize execution."
        ),
    )


def _find_latest_manager_invocation_policy_proof(
    *,
    store: FileStealthManagerInvocationPolicyProofStore,
    stealth_order_id: str,
) -> StealthManagerInvocationPolicyProofRecord | None:
    records = store.read_for_stealth_order_id(stealth_order_id, limit=1)
    return records[0] if records else None


def _is_safe_manager_invocation_policy_proof(
    record: StealthManagerInvocationPolicyProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        _manager_invocation_policy_proof_matches_admission(
            record,
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


def _manager_invocation_policy_proof_matches_admission(
    record: StealthManagerInvocationPolicyProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == STEALTH_CREATE_ROUTE
        and record.guarded_command_method == STEALTH_CREATE_METHOD
        and record.guarded_service_method == STEALTH_CREATE_SERVICE_METHOD
        and record.guarded_mutation_family == AdminApiMutationFamilyType.STEALTH_CREATE
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _resolve_post_write_reconciliation_proof(
    *,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ),
    post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ),
    post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ),
) -> StealthCreateLifecyclePrerequisiteResolverItem:
    prerequisite = StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION
    source = "admin_api_stealth_post_write_reconciliation_proof_log"
    if post_write_reconciliation_proof_store is None or not stealth_order_id:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            missing_reason="post_write_reconciliation_proof_store_unavailable",
            detail="Post-write reconciliation proof store was not available.",
        )

    proof_record = _find_matching_post_write_reconciliation_proof(
        store=post_write_reconciliation_proof_store,
        stealth_order_id=stealth_order_id,
        admission_decision=admission_decision,
    )
    if proof_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            missing_reason="no_matching_post_write_reconciliation_proof",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Backend-owned post-write reconciliation proof lookup found no "
                "exact stealth-create command-context record and did not "
                "execute reconciliation."
            ),
        )

    if not is_safe_stealth_post_write_reconciliation_proof_record(proof_record):
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="post_write_reconciliation_proof_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Latest exact-context stealth-create post-write reconciliation "
                "proof was found but is not safe no-live/no-mutation evidence."
            ),
        )

    if post_write_execution_journal_store is None:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="post_write_execution_journal_store_unavailable",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact stealth-create post-write reconciliation proof was found, "
                "but the execution-journal store was unavailable. No manager, "
                "Coinbase, reconciliation, write, or state mutation ran."
            ),
        )

    journal_record = find_matching_post_write_execution_journal_acceptance(
        store=post_write_execution_journal_store,
        proof_record=proof_record,
    )
    if journal_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=proof_record.post_write_reconciliation_proof_id,
            missing_reason="no_matching_post_write_execution_journal",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact stealth-create post-write reconciliation proof was found, "
                "but no matching accepted execution-journal evidence was found. "
                "Execution remains blocked without running reconciliation."
            ),
        )
    if not is_safe_stealth_post_write_execution_journal_record(journal_record):
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="post_write_execution_journal_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Matching stealth-create post-write execution-journal evidence "
                "was found but is not safe no-live/no-mutation evidence."
            ),
        )

    if post_write_reconciliation_verification_store is None:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.UNAVAILABLE,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="post_write_reconciliation_verification_store_unavailable",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact stealth-create proof and accepted execution-journal "
                "evidence were found, but the reconciliation-verification store "
                "was unavailable. No manager, Coinbase, reconciliation, write, "
                "or state mutation ran."
            ),
        )

    verification_record = find_matching_post_write_reconciliation_verification(
        store=post_write_reconciliation_verification_store,
        proof_record=proof_record,
        execution_journal_record=journal_record,
    )
    if verification_record is None:
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=journal_record.execution_journal_acceptance_id,
            missing_reason="no_matching_post_write_reconciliation_verification",
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Exact stealth-create proof and accepted execution-journal "
                "evidence were found, but no matching post-write reconciliation "
                "verification was found. Execution remains blocked without "
                "running reconciliation."
            ),
        )
    if not is_safe_stealth_post_write_reconciliation_verification_record(
        verification_record
    ):
        return _resolver_item(
            prerequisite=prerequisite,
            identity_value=stealth_order_id,
            source=source,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.MISSING,
            lookup_ran=True,
            resolved_evidence_id=(
                verification_record.reconciliation_verification_id
            ),
            missing_reason="post_write_reconciliation_verification_not_safe",
            stale_or_invalid=True,
            proof_lookup_authority="backend_store_read_only_no_execution",
            detail=(
                "Matching stealth-create post-write reconciliation verification "
                "was found but is not safe no-live/no-mutation evidence."
            ),
        )

    return _resolver_item(
        prerequisite=prerequisite,
        identity_value=stealth_order_id,
        source=source,
        lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.RESOLVED,
        lookup_ran=True,
        resolved=True,
        resolved_evidence_id=verification_record.reconciliation_verification_id,
        proof_lookup_authority="backend_store_read_only_no_execution",
        detail=(
            "Exact safe stealth-create post-write reconciliation proof, "
            "accepted execution-journal evidence, and post-write reconciliation "
            "verification were found. This resolves only prerequisite evidence; "
            "live execution service, live adapter, manager invocation, "
            "Coinbase calls, reconciliation execution, active-placement "
            "cancel/replace, writes, and state mutation remain disabled."
        ),
    )


def _find_matching_post_write_reconciliation_proof(
    *,
    store: FileStealthPostWriteReconciliationProofStore,
    stealth_order_id: str,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthPostWriteReconciliationProofRecord | None:
    for record in store.read_for_stealth_order_id(stealth_order_id, limit=500):
        if _post_write_reconciliation_proof_matches_admission(
            record,
            admission_decision=admission_decision,
        ):
            return record
    return None


def _post_write_reconciliation_proof_matches_admission(
    record: StealthPostWriteReconciliationProofRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> bool:
    return (
        record.guarded_command_route == STEALTH_CREATE_ROUTE
        and record.guarded_command_method == STEALTH_CREATE_METHOD
        and record.guarded_service_method == STEALTH_CREATE_SERVICE_METHOD
        and record.guarded_mutation_family == AdminApiMutationFamilyType.STEALTH_CREATE
        and record.guarded_actor_id == admission_decision.actor_id
        and record.guarded_operator_intent == admission_decision.operator_intent
        and record.guarded_idempotency_key == admission_decision.idempotency_key
        and record.guarded_payload_hash == admission_decision.payload_hash
        and record.reconciliation_plan_id == admission_decision.reconciliation_plan_id
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
        and record.cap_guard_decision_id == admission_decision.cap_guard_decision_id
    )


def _resolver_item(
    *,
    prerequisite: StealthCreateLifecycleExecutionPrerequisite,
    identity_value: str | None,
    lookup_status: StealthCreateLifecycleExecutionPrerequisiteLookupStatus,
    detail: str,
    source: str = "backend_resolver",
    lookup_ran: bool = False,
    resolved: bool = False,
    resolved_evidence_id: str | None = None,
    missing_reason: str | None = None,
    stale_or_invalid: bool = False,
    proof_lookup_authority: str = "none",
) -> StealthCreateLifecyclePrerequisiteResolverItem:
    return StealthCreateLifecyclePrerequisiteResolverItem(
        prerequisite=prerequisite,
        source=source,
        identity_value=identity_value,
        lookup_status=lookup_status,
        lookup_ran=lookup_ran,
        resolved=resolved,
        resolved_evidence_id=resolved_evidence_id,
        missing_reason=missing_reason,
        stale_or_invalid=stale_or_invalid,
        proof_lookup_authority=proof_lookup_authority,
        detail=detail,
    )
