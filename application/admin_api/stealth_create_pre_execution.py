"""Shared pre-execution contract evidence for stealth create commands."""

from __future__ import annotations

from core.enums import (
    ActionConditionType,
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveApprovalSnapshotField,
    AdminApiLivePreflightCategory,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    ProductCapability,
    StealthCreatePreExecutionContractSection,
)

from .models import (
    AdminApiCommandEnvelope,
    StealthCommandSuiteEnablementCandidateReviewItem,
    StealthCreatePreExecutionContractEvidence,
    StealthCreatePreExecutionContractSectionItem,
    StealthCreateRequest,
)


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def build_stealth_create_pre_execution_contract(
    *,
    selected_candidate: StealthCommandSuiteEnablementCandidateReviewItem | None = None,
    command_envelope: AdminApiCommandEnvelope | None = None,
    request: StealthCreateRequest | None = None,
    exact_command_context_present: bool = False,
) -> StealthCreatePreExecutionContractEvidence | None:
    """Build no-live stealth-create pre-execution evidence from one code path."""

    if (
        selected_candidate is not None
        and selected_candidate.mutation_family != AdminApiMutationFamilyType.STEALTH_CREATE
    ):
        return None

    payload_model_required_fields = [
        field_name
        for field_name, field_info in StealthCreateRequest.model_fields.items()
        if field_info.is_required()
    ]
    payload_required_fields = _ordered_unique(
        ["stealth_order_id", *payload_model_required_fields]
    )
    payload_optional_fields = [
        field_name
        for field_name in StealthCreateRequest.model_fields
        if field_name not in payload_required_fields
    ]
    payload_fields_present = (
        [
            field_name
            for field_name in StealthCreateRequest.model_fields
            if request is not None and getattr(request, field_name, None) is not None
        ]
        if request is not None
        else []
    )
    approval_fields = [
        AdminApiLiveApprovalSnapshotField.ROUTE,
        AdminApiLiveApprovalSnapshotField.METHOD,
        AdminApiLiveApprovalSnapshotField.MODULE_ID,
        AdminApiLiveApprovalSnapshotField.IDENTITY_KEY,
        AdminApiLiveApprovalSnapshotField.IDENTITY_VALUE,
        AdminApiLiveApprovalSnapshotField.ACTION_CLASS,
        AdminApiLiveApprovalSnapshotField.REQUIRED_PERMISSION,
        AdminApiLiveApprovalSnapshotField.REQUESTED_BY_ACTOR_ID,
        AdminApiLiveApprovalSnapshotField.OPERATOR_INTENT,
        AdminApiLiveApprovalSnapshotField.IDEMPOTENCY_KEY,
        AdminApiLiveApprovalSnapshotField.PAYLOAD_HASH,
        AdminApiLiveApprovalSnapshotField.CAP_GUARD_DECISION_REF,
        AdminApiLiveApprovalSnapshotField.RECONCILIATION_PLAN_REF,
    ]
    required_admission_refs = [
        "approval_snapshot_id",
        "admission_audit_id",
        "cap_guard_decision_id",
        "reconciliation_plan_id",
        "payload_hash",
        "audit_id",
    ]
    required_lifecycle_writes = [
        "stealth_orders.insert",
        "order_parent.insert",
        "stealth_lifecycle_event.dispatch",
        "anchor_repricing_state.initialize",
    ]
    manager_path = [
        "api/v1/routes/stealth.py::create_stealth_order",
        "application/admin_api/command_service.py::create_stealth_order",
        "bridges/stealth_order_bridge.py",
        "core/stealth_order_manager.py::create_stealth_order",
    ]
    guard_condition_refs = [
        ActionConditionType.WALLET_AVAILABLE.value,
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
        ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value,
        ProductCapability.STEALTH_PLANNING.value,
        ProductCapability.SIZE_VALIDATION.value,
        ProductCapability.PROFITABILITY.value,
        "account_artificial_cap_policy",
        "product_capability_policy",
    ]
    reconciliation_refs = [
        "POST /api/v1/admin/reconciliation/plans",
        "post_write_reconciliation_policy",
        "stealth_create_reconciliation_plan",
    ]
    route = (
        selected_candidate.route
        if selected_candidate is not None
        else "/api/v1/stealth/orders"
    )
    method = selected_candidate.method if selected_candidate is not None else "POST"
    service_method = (
        selected_candidate.service_method
        if selected_candidate is not None
        else "create_stealth_order"
    )
    action_class = (
        selected_candidate.action_class
        if selected_candidate is not None
        else AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    required_permission: AdminApiPermission | str = (
        selected_candidate.required_permission
        if selected_candidate is not None
        else AdminApiPermission.ORDER_CREATE
    )
    candidate_id = (
        selected_candidate.candidate_id
        if selected_candidate is not None
        else "m55_selected_candidate::stealth_create::command_response"
    )
    identity_value = request.stealth_order_id if request is not None else None

    def section(
        *,
        name: StealthCreatePreExecutionContractSection,
        category: AdminApiLivePreflightCategory,
        source_ref: str,
        detail: str,
        required_backend_contracts: list[str] | None = None,
        required_fields: list[str] | None = None,
        missing_backend_contracts: list[str] | None = None,
        evidence: list[str] | None = None,
        status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED,
        blocking: bool = True,
        resolved: bool = False,
    ) -> StealthCreatePreExecutionContractSectionItem:
        return StealthCreatePreExecutionContractSectionItem(
            section=name,
            category=category,
            status=status,
            blocking=blocking,
            resolved=resolved,
            source_ref=source_ref,
            required_backend_contracts=list(required_backend_contracts or []),
            required_fields=list(required_fields or []),
            missing_backend_contracts=list(
                missing_backend_contracts
                if missing_backend_contracts is not None
                else required_backend_contracts or []
            ),
            evidence=list(evidence or []),
            detail=detail,
        )

    route_evidence = [route, method, service_method]
    if identity_value is not None:
        route_evidence.append(f"identity_value={identity_value}")

    idempotency_evidence = [
        "Replay/conflict posture must be decided by backend idempotency evidence."
    ]
    if command_envelope is not None:
        idempotency_evidence.extend(
            [
                f"correlation_id={command_envelope.correlation_id}",
                f"idempotency_key={command_envelope.idempotency_key}",
                f"actor_id={command_envelope.actor.actor_id}",
                f"operator_intent={command_envelope.operator_intent}",
            ]
        )

    payload_evidence = [
        "Browser validation is display-only and cannot satisfy backend execution admission.",
        "A backend payload hash must bind the exact request before future execution.",
    ]
    if payload_fields_present:
        payload_evidence.append(
            "payload_fields_present=" + ",".join(payload_fields_present)
        )

    sections = [
        section(
            name=StealthCreatePreExecutionContractSection.SELECTED_CANDIDATE_SCOPE,
            category=AdminApiLivePreflightCategory.EXECUTION_CANDIDATE,
            source_ref="enablement_candidate_review_summary",
            status=AdminApiGateStatus.PASSED,
            blocking=False,
            resolved=True,
            evidence=[
                candidate_id,
                "Only stealth_create is in scope for this pre-execution contract batch.",
            ],
            detail=(
                "The selected create candidate is a planning target only. Reveal, "
                "cancel, move, reprice, recovery, and reconciliation remain behind "
                "their own candidate-review blockers."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.ROUTE_IDENTITY_CONTRACT,
            category=AdminApiLivePreflightCategory.AUTHORIZATION,
            source_ref="route_inventory",
            status=AdminApiGateStatus.PASSED,
            blocking=False,
            resolved=True,
            required_backend_contracts=manager_path[:2],
            missing_backend_contracts=[],
            required_fields=[
                "route",
                "method",
                "module_id",
                "mutation_family",
                "service_method",
                "identity_key",
                "operator_intent",
            ],
            evidence=route_evidence,
            detail=(
                "The route identity is single-sourced from the Admin API route "
                "inventory and selected candidate evidence."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.PAYLOAD_CONTRACT,
            category=AdminApiLivePreflightCategory.IDEMPOTENCY,
            source_ref="StealthCreateRequest",
            required_backend_contracts=[
                "application/admin_api/models.py::StealthCreateRequest",
                "application/admin_api/command_service.py::create_stealth_order",
            ],
            required_fields=payload_required_fields,
            evidence=payload_evidence,
            detail=(
                "Create payload fields are defined by the backend request model. "
                "The identity value may be supplied or backend-generated, but it "
                "must be bound before lifecycle writes."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.APPROVAL_ADMISSION_PRECONDITIONS,
            category=AdminApiLivePreflightCategory.APPROVAL,
            source_ref="approval_and_admission_gates",
            required_backend_contracts=[
                "POST /api/v1/admin/approvals/requests",
                "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                "POST /api/v1/admin/admission-audits",
            ],
            required_fields=[field.value for field in approval_fields],
            evidence=[
                "Approval, decision, and admission audit rows must match the exact route, actor, idempotency key, operator intent, payload hash, and stealth_order_id.",
            ],
            detail=(
                "Approval and admission evidence must be backend-owned and "
                "route-bound before a future create path can reach the manager."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.LIFECYCLE_WRITE_BOUNDARY,
            category=AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD,
            source_ref="stealth_create_lifecycle_write_guard",
            required_backend_contracts=[
                "POST /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs",
                "application/admin_api/stealth_lifecycle_execution.py",
            ],
            required_fields=required_lifecycle_writes,
            evidence=[
                "Lifecycle writes remain named only; no stealth_orders, order_parent, or event rows are written by this path.",
            ],
            detail=(
                "Future create execution would write stealth/order lifecycle "
                "state, but this contract keeps every write blocked until proof "
                "and locks are complete."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.MANAGER_INVOCATION_BOUNDARY,
            category=AdminApiLivePreflightCategory.MANAGER_INVOCATION,
            source_ref="canonical_manager_path",
            required_backend_contracts=manager_path,
            evidence=[
                "The existing StealthOrderManager create path is the only future owner.",
                "The Admin API path does not invoke the manager.",
            ],
            detail=(
                "This evidence names the canonical manager path for orientation "
                "only and rejects route-local execution."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.IDEMPOTENCY_AUDIT_BOUNDARY,
            category=AdminApiLivePreflightCategory.AUDIT,
            source_ref="command_envelope",
            required_backend_contracts=[
                "application/admin_api/idempotency.py",
                "application/admin_api/audit.py",
            ],
            required_fields=[
                "request_id",
                "correlation_id",
                "idempotency_key",
                "actor_id",
                "operator_intent",
                "audit_id",
                "payload_hash",
            ],
            evidence=idempotency_evidence,
            detail=(
                "Idempotency and audit data must be durable and exact-context-"
                "bound before any future lifecycle write."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.GUARD_ACCOUNT_CONDITION_BOUNDARY,
            category=AdminApiLivePreflightCategory.CAP_GUARD,
            source_ref="guard_risk_policy",
            required_backend_contracts=[
                "application/admin_api/read_service.py::build_guard_risk_policy",
                "core/action_condition_guard.py",
                "core/product_capability_policy.py",
            ],
            required_fields=guard_condition_refs,
            evidence=[
                "Action-condition guards, artificial account caps, and product capability checks are backend-owned.",
                "Spot wallet rules apply only when the backend product policy classifies the proposed stealth plan as spot.",
            ],
            detail=(
                "The create route must use backend condition guards and configured "
                "account caps; browser wallet or profitability checks cannot "
                "grant authority."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.RECONCILIATION_PLANNING_BOUNDARY,
            category=AdminApiLivePreflightCategory.RECONCILIATION,
            source_ref="post_write_reconciliation_policy",
            required_backend_contracts=reconciliation_refs,
            required_fields=required_admission_refs,
            evidence=[
                "A post-write reconciliation plan must exist before create execution can be considered complete.",
            ],
            detail=(
                "Reconciliation remains a required backend post-write contract; "
                "this path does not execute it."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.COINBASE_NON_INTERACTION_PROOF,
            category=AdminApiLivePreflightCategory.COINBASE_EXCHANGE,
            source_ref="no_live_coinbase_evidence",
            status=AdminApiGateStatus.PASSED,
            blocking=False,
            resolved=True,
            evidence=[
                "coinbase_order_submitted=false",
                "coinbase_order_cancel_submitted=false",
                "live_coinbase_read_ran=false",
                "submitted_notional_usdc=0",
                "executed_notional_usdc=0",
            ],
            detail=(
                "The selected-create contract does not read, submit, cancel, or "
                "replace Coinbase orders."
            ),
        ),
        section(
            name=StealthCreatePreExecutionContractSection.FRONTEND_BFF_AUTHORITY_BOUNDARY,
            category=AdminApiLivePreflightCategory.BROWSER_AUTHORITY,
            source_ref="frontend_boundary",
            status=AdminApiGateStatus.PASSED,
            blocking=False,
            resolved=True,
            evidence=[
                "browser_authority=display_only",
                "bff_authority=forward_only_no_execution",
            ],
            detail=(
                "Frontend and BFF layers may display this evidence but cannot "
                "create orders, approve live execution, or satisfy backend guards."
            ),
        ),
    ]
    return StealthCreatePreExecutionContractEvidence(
        candidate_id=candidate_id,
        exact_command_context_present=exact_command_context_present,
        command_context_bound=exact_command_context_present,
        identity_value=identity_value,
        correlation_id=(
            command_envelope.correlation_id if command_envelope is not None else None
        ),
        idempotency_key=(
            command_envelope.idempotency_key if command_envelope is not None else None
        ),
        actor_id=command_envelope.actor.actor_id if command_envelope is not None else None,
        operator_intent=(
            command_envelope.operator_intent if command_envelope is not None else None
        ),
        payload_fields_present=payload_fields_present,
        payload_field_count=len(payload_fields_present),
        service_method=service_method,
        action_class=action_class,
        required_permission=required_permission,
        payload_required_fields=payload_required_fields,
        payload_optional_fields=payload_optional_fields,
        required_approval_fields=approval_fields,
        required_admission_refs=required_admission_refs,
        required_lifecycle_writes=required_lifecycle_writes,
        manager_path=manager_path,
        guard_condition_refs=guard_condition_refs,
        reconciliation_refs=reconciliation_refs,
        excluded_mutation_families=[
            AdminApiMutationFamilyType.STEALTH_REVEAL,
            AdminApiMutationFamilyType.STEALTH_CANCEL,
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
            AdminApiMutationFamilyType.STEALTH_RECOVERY,
            AdminApiMutationFamilyType.STEALTH_RECONCILIATION,
        ],
        section_count=len(sections),
        blocking_section_count=sum(1 for item in sections if item.blocking),
        passed_section_count=sum(
            1 for item in sections if item.status == AdminApiGateStatus.PASSED
        ),
        sections=sections,
        detail=(
            "Selected stealth_create pre-execution evidence is read-only and "
            "backend-owned. It records the route, payload, approval, admission, "
            "guard, lifecycle-write, manager, audit, idempotency, reconciliation, "
            "and Coinbase non-interaction boundaries required before any future "
            "create execution can exist."
        ),
    )
