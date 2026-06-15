"""No-live stealth lifecycle execution-contract evidence builders."""

from __future__ import annotations

from core.enums import (
    AdminApiActionClass,
    AdminApiMutationFamilyType,
    AdminApiStealthAdmissionContextField,
    StealthCreateLifecycleExecutionBlocker,
    StealthCreateLifecycleExecutionPrerequisite,
    StealthCreateLifecycleExecutionPrerequisiteLookupStatus,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthCreateLifecyclePrerequisiteResolverItem,
    StealthCreateLifecycleWriteExecutionContractEvidence,
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
from .stealth_post_write_reconciliation import (
    build_stealth_post_write_reconciliation_boundary,
)


STEALTH_CREATE_ROUTE = "/api/v1/stealth/orders"
STEALTH_CREATE_METHOD = "POST"
STEALTH_CREATE_MODULE_ID = "stealth_orders"
STEALTH_CREATE_SERVICE_METHOD = "create_stealth_order"

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
    StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER.value,
    StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION.value,
)

BASE_CREATE_EXECUTION_BLOCKERS: tuple[str, ...] = (
    StealthCreateLifecycleExecutionBlocker.EXECUTION_CONTRACT_MISSING.value,
    StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_ROW_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.ORDER_PARENT_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.LIFECYCLE_EVENT_DISPATCH_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_READ_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.POST_WRITE_RECONCILIATION_MISSING.value,
)


def build_stealth_create_lifecycle_write_execution_contract(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None,
    lifecycle_write_guard_proof_store: (
        FileStealthLifecycleWriteGuardProofStore | None
    ) = None,
    resolved_prerequisites: list[str] | None = None,
) -> StealthCreateLifecycleWriteExecutionContractEvidence:
    """Build blocked execution-contract evidence for stealth create."""

    resolution = _build_prerequisite_resolution(
        stealth_order_id=stealth_order_id,
        exact_command_context_present=exact_command_context_present,
        admission_decision=admission_decision,
        lifecycle_write_guard_proof_store=lifecycle_write_guard_proof_store,
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
        blockers=blockers,
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
            "post_write_reconciliation_missing"
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
        canonical_execution_path=[
            "core/stealth_order_manager.py::create_stealth_order"
        ],
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Execution-contract evidence is backend-owned and no-live.",
            "Prerequisite resolver evidence is read-only and no-authority.",
            "The contract boundary does not invoke StealthOrderManager.",
            "The contract boundary does not write stealth rows, order_parent rows, or lifecycle events.",
            "The contract boundary does not read Coinbase, submit Coinbase orders, or execute reconciliation.",
        ],
        detail=(
            "Stealth create execution remains blocked until exact command "
            "context, approval, admission audit, cap/guard, reconciliation "
            "plan, lifecycle-write guard proof, live execution service, live "
            "adapter, and post-write reconciliation evidence are all present."
        ),
    )


def _build_prerequisite_resolution(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    lifecycle_write_guard_proof_store: (
        FileStealthLifecycleWriteGuardProofStore | None
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

    return [
        approval,
        admission,
        cap_guard,
        reconciliation,
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
        _resolver_item(
            prerequisite=(
                StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION
            ),
            identity_value=stealth_order_id,
            source=POST_WRITE_RECONCILIATION_SOURCE,
            lookup_status=StealthCreateLifecycleExecutionPrerequisiteLookupStatus.DISABLED,
            missing_reason="post_write_reconciliation_missing",
            detail="Post-write reconciliation proof is required before execution.",
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
        detail=detail,
    )
