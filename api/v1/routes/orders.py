"""Order command route adapters for the Admin API."""

from __future__ import annotations

import uuid
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.approval import (
    FileAdminApiApprovalStore,
    evaluate_command_live_admission,
)
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_runtime import build_admin_api_command_service
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.live_execution import (
    AdminApiLiveExecutionService,
    get_decision_backed_live_execution_service,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
)
from application.admin_api.stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
)
from application.admin_api.stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
)
from application.admin_api.stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
)
from application.admin_api.stealth_post_write_reconciliation_policy import (
    FileStealthPostWriteReconciliationExecutionPolicyProofStore,
)
from application.admin_api.stealth_state_mutation_policy import (
    FileStealthStateMutationPolicyProofStore,
)
from application.admin_api.stealth_recovery_proof import (
    FileStealthRecoveryProofStore,
)
from application.admin_api.stealth_reveal_trigger_proof import (
    FileStealthRevealTriggerProofStore,
)
from application.admin_api.stealth_reconciliation_proof import (
    FileStealthReconciliationProofStore,
)
from application.admin_api.stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
)
from application.admin_api.stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    FileStealthPostWriteReconciliationProofStore,
    FileStealthPostWriteReconciliationVerificationStore,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminLiveAdmissionDecisionEvidence,
    AdminOrderDetailResponse,
    AdminOrderListResponse,
    CampaignExecutionCommand,
    CampaignExecutionRequest,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
    SpotRecoveryApplyExecutionCommand,
    SpotRecoveryApplyExecutionRequest,
    SpotRecoveryExchangeStateProofCommand,
    SpotRecoveryExchangeStateProofRequest,
    SpotRecoveryExchangeStateSnapshotCommand,
    SpotRecoveryExchangeStateSnapshotRequest,
    SpotRecoveryReconciliationExecutionCommand,
    SpotRecoveryReconciliationExecutionRequest,
    SpotRecoveryReconciliationProofRecordCommand,
    SpotRecoveryReconciliationProofRecordRequest,
    SpotRecoveryRollbackExecutionCommand,
    SpotRecoveryRollbackExecutionRequest,
    SpotSweepAutomationRunCommand,
    SpotSweepAutomationRunRequest,
    StealthCommandAdmissionContextEvidence,
    StealthCommandSuiteAdmissionContextItem,
)
from application.admin_api.stealth_command_execution import (
    build_stealth_command_execution_contract,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    AdminApiStealthAdmissionContextField,
)


router = APIRouter()

COMMAND_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": "Command accepted or replayed after all backend gates pass.",
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": "Command rejected before live exchange execution.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
    501: {
        "model": AdminApiCommandResponse,
        "description": "Live HTTP execution is not implemented for this command.",
    },
}

SPOT_RECOVERY_PROOF_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": "Spot recovery proof record accepted or replayed after all backend prerequisites match.",
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": "Spot recovery proof record rejected before local proof persistence.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required spot recovery proof-record permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
}

SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": (
            "Spot recovery execution journal accepted or replayed after all "
            "backend prerequisites match."
        ),
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": (
            "Spot recovery execution rejected before local journal persistence."
        ),
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required spot recovery execute permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
}

READ_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}


def get_command_service() -> AdminApiCommandService:
    """Return the shared command service boundary."""

    return build_admin_api_command_service()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for command routes."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable command audit storage."""

    return FileAdminApiAuditStore()


def get_approval_store() -> FileAdminApiApprovalStore:
    """Return durable approval storage for command admission evidence."""

    return FileAdminApiApprovalStore()


def get_cap_guard_store() -> FileAdminApiCapGuardStore:
    """Return durable cap/guard decision storage for admission evidence."""

    return FileAdminApiCapGuardStore()


def get_reconciliation_store() -> FileAdminApiReconciliationStore:
    """Return durable reconciliation plan storage for admission evidence."""

    return FileAdminApiReconciliationStore()


def get_live_execution_service() -> AdminApiLiveExecutionService:
    """Return the backend-owned live execution service boundary."""

    return get_decision_backed_live_execution_service()


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _build_envelope(
    *,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
) -> AdminApiCommandEnvelope:
    return AdminApiCommandEnvelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )


def _http_status_for(response: AdminApiCommandResponse) -> int:
    if response.status == AdminApiCommandStatus.NOT_IMPLEMENTED:
        return status.HTTP_501_NOT_IMPLEMENTED
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _command_response(
    response: AdminApiCommandResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status_for(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


STEALTH_COMMAND_CONTEXT_MUTATION_FAMILIES = {
    "create_stealth_order": AdminApiMutationFamilyType.STEALTH_CREATE,
    "reveal_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_REVEAL
    ),
    "move_stealth_order_by_stealth_order_id": AdminApiMutationFamilyType.STEALTH_MOVE,
    "cancel_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_CANCEL
    ),
    "recover_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_RECOVERY
    ),
    "reconcile_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_RECONCILIATION
    ),
    "reprice_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.MOVEMENT_REPRICE
    ),
}


def _stealth_command_context_requirement(
    *,
    field_name: AdminApiStealthAdmissionContextField,
    source: str,
    detail: str,
) -> StealthCommandSuiteAdmissionContextItem:
    return StealthCommandSuiteAdmissionContextItem(
        field_name=field_name,
        source=source,
        required=True,
        present=True,
        blocking=False,
        backend_owned=True,
        route_bound=True,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=detail,
    )


def _build_stealth_command_admission_context(
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthCommandAdmissionContextEvidence | None:
    mutation_family = STEALTH_COMMAND_CONTEXT_MUTATION_FAMILIES.get(
        admission_decision.service_method
    )
    if (
        mutation_family is None
        or admission_decision.identity_key != "stealth_order_id"
        or not admission_decision.identity_value
    ):
        return None

    requirements = [
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ROUTE,
            source="route_inventory",
            detail="Route is present from the exact backend command route.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.METHOD,
            source="route_inventory",
            detail="Method is present from the exact backend command route.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.MODULE_ID,
            source="route_inventory",
            detail="Module id is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.MUTATION_FAMILY,
            source="command_metadata",
            detail="Mutation family is present from backend command metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ACTION_CLASS,
            source="route_inventory",
            detail="Action class is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.REQUIRED_PERMISSION,
            source="route_inventory",
            detail="Required permission is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.STEALTH_ORDER_ID,
            source="command_envelope",
            detail="Stealth order id is present from the exact command path or request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ACTOR_ID,
            source="command_envelope",
            detail="Actor id is present from authenticated backend request context.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.IDEMPOTENCY_KEY,
            source="command_envelope",
            detail="Idempotency key is present from the mutating command request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.OPERATOR_INTENT,
            source="command_envelope",
            detail="Operator intent is present from the mutating command request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.PAYLOAD_HASH,
            source="command_envelope",
            detail="Payload hash is computed by the backend for the exact request body.",
        ),
    ]
    return StealthCommandAdmissionContextEvidence(
        mutation_family=mutation_family,
        route=admission_decision.route,
        method=admission_decision.method,
        module_id=admission_decision.module_id,
        identity_value=admission_decision.identity_value,
        action_class=admission_decision.action_class,
        required_permission=admission_decision.required_permission,
        service_method=admission_decision.service_method,
        required_context_count=len(requirements),
        present_context_count=len(requirements),
        missing_context_count=0,
        missing_context=[],
        context_requirements=requirements,
        exact_context_present=True,
        resolver_lookup_allowed=True,
        resolver_lookup_ran=True,
        proof_resolution_attempted=True,
        admission_decision_attached=True,
        admission_allowed=admission_decision.allowed,
        executable=False,
        live_enabled=False,
        coinbase_read_ran=False,
        coinbase_order_submitted=False,
        coinbase_order_cancel_submitted=False,
        active_placement_cancel_replace_ran=False,
        reconciliation_executed=False,
        lifecycle_state_mutated=False,
        order_state_mutated=False,
        exchange_state_mutated=False,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Exact command-envelope context is present for backend admission "
            "evidence lookup, but live execution remains blocked."
        ),
    )


def _attach_stealth_execution_posture(
    response: AdminApiCommandResponse,
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
    stealth_state_mutation_policy_proof_store: (
        FileStealthStateMutationPolicyProofStore | None
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
) -> None:
    """Attach typed no-live execution posture for eligible stealth commands."""

    contract = build_stealth_command_execution_contract(
        admission_decision,
        stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        stealth_coinbase_exchange_policy_proof_store=(
            stealth_coinbase_exchange_policy_proof_store
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            stealth_post_write_reconciliation_policy_proof_store
        ),
        stealth_state_mutation_policy_proof_store=(
            stealth_state_mutation_policy_proof_store
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
    response.stealth_command_execution_contract = contract
    if contract is None or not isinstance(response.data, dict):
        return
    response.data.update({
        "stealth_command_execution_contract_available": (
            contract.execution_contract_available
        ),
        "stealth_command_execution_allowed": contract.execution_allowed,
        "stealth_command_execution_blockers": contract.blockers,
        "resolved_stealth_command_execution_prerequisites": (
            contract.resolved_prerequisites
        ),
        "missing_stealth_command_execution_prerequisites": (
            contract.missing_prerequisites
        ),
    })


def _record_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminApiCommandResponse,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "approval_id": (
            response.admission_decision.approval_snapshot_id
            if response.admission_decision is not None
            else None
        ),
        "client_order_id": response.client_order_id,
        "stealth_order_id": response.stealth_order_id,
        "coinbase_order_id": response.coinbase_order_id,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "admission_decision": response.admission_decision,
    }
    if response.audit_id is not None:
        event_fields["audit_id"] = response.audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _idempotency_payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
    path_params: dict | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
        "path_params": path_params or {},
    })


def _manual_order_with_backend_identity(
    *,
    body: ManualOrderRequest,
    actor: AdminApiActor,
    endpoint: str,
    idempotency_key: str,
    payload_hash: str,
) -> ManualOrderRequest:
    """Attach a stable backend-owned client id before admission checks."""

    if body.client_order_id:
        return body

    material = "|".join(
        [
            "coinbase-admin-api",
            "manual-order",
            endpoint,
            actor.actor_id,
            idempotency_key,
            payload_hash,
        ]
    )
    return body.model_copy(
        update={"client_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, material))}
    )


def _should_retry_non_live_manual_order_after_admission(
    *,
    record: IdempotencyRecord,
    response: AdminApiCommandResponse,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    endpoint: str,
    payload_hash: str,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
    service_method: str,
    route_template: str,
    module_id: str,
    identity_key: str,
) -> bool:
    """Return whether a prior blocked manual order can run after admission passes."""

    previous_admission = response.admission_decision
    return (
        endpoint == "POST /api/v1/orders"
        and route_template == "/api/v1/orders"
        and service_method == "place_manual_order"
        and module_id == "spot_operations"
        and identity_key == "client_order_id"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
        and permission == AdminApiPermission.ORDER_CREATE
        and record.endpoint == endpoint
        and record.payload_hash == payload_hash
        and record.status == AdminApiCommandStatus.NOT_IMPLEMENTED
        and response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
        and response.action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
        and response.required_permission == AdminApiPermission.ORDER_CREATE
        and response.service_method == "place_manual_order"
        and response.live_exchange_submitted is False
        and response.live_coinbase_orders_ran is False
        and previous_admission is not None
        and previous_admission.allowed is False
        and admission_decision.allowed is True
        and admission_decision.route == route_template
        and admission_decision.method == "POST"
        and admission_decision.module_id == module_id
        and admission_decision.identity_key == identity_key
        and admission_decision.action_class == action_class
        and admission_decision.required_permission == permission
        and admission_decision.service_method == service_method
        and admission_decision.live_exchange_submitted is False
    )


def _execute_idempotent_command(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    permission: AdminApiPermission,
    action_class: AdminApiActionClass,
    service_method: str,
    route_template: str,
    module_id: str,
    identity_key: str,
    identity_value: str | None,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    approval_store: FileAdminApiApprovalStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    live_execution_service: AdminApiLiveExecutionService,
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
    stealth_state_mutation_policy_proof_store: (
        FileStealthStateMutationPolicyProofStore | None
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
    command_runner: Callable[[], AdminApiCommandResponse] | None = None,
    command_runner_with_admission: Callable[
        [AdminLiveAdmissionDecisionEvidence],
        AdminApiCommandResponse,
    ] | None = None,
    client_order_id: str | None = None,
    stealth_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, permission)
    admission_decision = evaluate_command_live_admission(
        route=route_template,
        method=endpoint.split(" ", 1)[0],
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        actor_id=actor.actor_id,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
    )
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        response = AdminApiCommandResponse.model_validate(payload)
        if not _should_retry_non_live_manual_order_after_admission(
            record=check.record,
            response=response,
            admission_decision=admission_decision,
            endpoint=endpoint,
            payload_hash=payload_hash,
            action_class=action_class,
            permission=permission,
            service_method=service_method,
            route_template=route_template,
            module_id=module_id,
            identity_key=identity_key,
        ):
            return _command_response(response, replayed=True)
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminApiCommandResponse(
            status=AdminApiCommandStatus.CONFLICT,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            client_order_id=client_order_id,
            stealth_order_id=stealth_order_id,
            admission_decision=admission_decision,
            failure_stage="idempotency",
        )
        response.stealth_admission_context = _build_stealth_command_admission_context(
            admission_decision
        )
        _attach_stealth_execution_posture(
            response,
            admission_decision,
            stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
            stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
            stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
            stealth_coinbase_exchange_policy_proof_store=(
                stealth_coinbase_exchange_policy_proof_store
            ),
            stealth_post_write_reconciliation_policy_proof_store=(
                stealth_post_write_reconciliation_policy_proof_store
            ),
            stealth_state_mutation_policy_proof_store=(
                stealth_state_mutation_policy_proof_store
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
        response.audit_id = _record_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _command_response(response)

    if command_runner_with_admission is not None:
        response = command_runner_with_admission(admission_decision)
    elif command_runner is not None:
        response = command_runner()
    else:
        raise ValueError("A command runner is required.")
    response.admission_decision = admission_decision
    response.stealth_admission_context = _build_stealth_command_admission_context(
        admission_decision
    )
    _attach_stealth_execution_posture(
        response,
        admission_decision,
        stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        stealth_coinbase_exchange_policy_proof_store=(
            stealth_coinbase_exchange_policy_proof_store
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            stealth_post_write_reconciliation_policy_proof_store
        ),
        stealth_state_mutation_policy_proof_store=(
            stealth_state_mutation_policy_proof_store
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
    if response.guard is None:
        response.guard = {}
    response.guard["admission_decision"] = admission_decision.model_dump(mode="json")
    response.audit_id = _record_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
    )
    idempotency_store.put_record(
        IdempotencyRecord(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            client_order_id=response.client_order_id,
            stealth_order_id=response.stealth_order_id,
            status=response.status,
            response=response.model_dump(mode="json"),
            actor_id=actor.actor_id,
            endpoint=endpoint,
        )
    )
    return _command_response(response)


@router.get(
    "/orders",
    response_model=AdminOrderListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read local orders keyed by client_order_id",
)
def list_orders(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    order_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read local order_parent evidence without contacting Coinbase."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_order_list(
            product_id=product_id,
            status=order_status,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/orders/{client_order_id}",
    response_model=AdminOrderDetailResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one local order by client_order_id",
)
def get_order_by_client_order_id(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read one local order row by client_order_id."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(service.build_order_detail(client_order_id=client_order_id))


@router.post(
    "/orders",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Create a manual order through the shared command service",
)
def create_manual_order(
    request: Request,
    body: ManualOrderRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for manual placement.

    The route is authenticated, idempotent, audited, and still live-disabled
    until enterprise approval/cap gates are completed.
    """

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    body = _manual_order_with_backend_identity(
        body=body,
        actor=actor,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CREATE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="place_manual_order",
        route_template="/api/v1/orders",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=body.client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=body.client_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.place_manual_order(
                ManualOrderCommand(
                    envelope=envelope,
                    request=body,
                    allow_live_execution=admission_decision.allowed,
                )
            )
        ),
    )


@router.post(
    "/orders/{client_order_id}/cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Cancel an order by client_order_id through the shared command service",
)
def cancel_order_by_client_order_id(
    request: Request,
    body: CancelOrderRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for cancel-by-client-order-id."""

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        path_params={"client_order_id": client_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CANCEL,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        service_method="cancel_order_by_client_order_id",
        route_template="/api/v1/orders/{client_order_id}/cancel",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=client_order_id,
        command_runner=lambda: service.cancel_order_by_client_order_id(
            CancelOrderCommand(
                envelope=envelope,
                client_order_id=client_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/spot/campaign/executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Execute a spot campaign through the shared command service",
)
def execute_spot_campaign(
    request: Request,
    body: CampaignExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future campaign execution.

    The route has the command envelope, idempotency, audit, RBAC, and fail-closed
    live gate, but it does not submit Coinbase orders.
    """

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="execute_spot_campaign",
        route_template="/api/v1/spot/campaign/executions",
        module_id="spot_operations",
        identity_key="campaign_id",
        identity_value=body.campaign_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda: service.execute_spot_campaign(
            CampaignExecutionCommand(envelope=envelope, request=body)
        ),
    )


@router.post(
    "/spot/sweep/automation-runs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Run a spot sweep automation through the shared command service",
)
def run_spot_sweep_automation(
    request: Request,
    body: SpotSweepAutomationRunRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot sweep automation execution.

    The route has the command envelope, idempotency, audit, RBAC, and fail-closed
    live gate, but it does not run sweep tools or submit Coinbase orders.
    """

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="run_spot_sweep_automation",
        route_template="/api/v1/spot/sweep/automation-runs",
        module_id="spot_operations",
        identity_key="sweep_config_id",
        identity_value=body.sweep_config_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda: service.run_spot_sweep_automation(
            SpotSweepAutomationRunCommand(envelope=envelope, request=body)
        ),
    )


def _execute_spot_recovery_contract(
    *,
    request: Request,
    body: (
        SpotRecoveryApplyExecutionRequest
        | SpotRecoveryRollbackExecutionRequest
        | SpotRecoveryExchangeStateProofRequest
        | SpotRecoveryExchangeStateSnapshotRequest
        | SpotRecoveryReconciliationExecutionRequest
        | SpotRecoveryReconciliationProofRecordRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    permission: AdminApiPermission,
    service_method: str,
    route_template: str,
    service: AdminApiCommandService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    approval_store: FileAdminApiApprovalStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    live_execution_service: AdminApiLiveExecutionService,
    command_runner: Callable[[AdminApiCommandEnvelope], AdminApiCommandResponse],
    command_runner_with_admission: Callable[
        [AdminApiCommandEnvelope, AdminLiveAdmissionDecisionEvidence],
        AdminApiCommandResponse,
    ] | None = None,
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=permission,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=service_method,
        route_template=route_template,
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=body.client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=(
            None
            if command_runner_with_admission is not None
            else lambda: command_runner(envelope)
        ),
        command_runner_with_admission=(
            (
                lambda admission_decision: command_runner_with_admission(
                    envelope,
                    admission_decision,
                )
            )
            if command_runner_with_admission is not None
            else None
        ),
        client_order_id=body.client_order_id,
    )


@router.post(
    "/spot/recovery/apply-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary="Apply a spot recovery plan through the shared command service",
)
def execute_spot_recovery_apply(
    request: Request,
    body: SpotRecoveryApplyExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery apply execution."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_apply",
        route_template="/api/v1/spot/recovery/apply-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_apply(
            SpotRecoveryApplyExecutionCommand(envelope=envelope, request=body)
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_apply(
                SpotRecoveryApplyExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/rollback-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary="Rollback a spot recovery apply through the shared command service",
)
def execute_spot_recovery_rollback(
    request: Request,
    body: SpotRecoveryRollbackExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery rollback execution."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_rollback",
        route_template="/api/v1/spot/recovery/rollback-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_rollback(
            SpotRecoveryRollbackExecutionCommand(envelope=envelope, request=body)
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_rollback(
                SpotRecoveryRollbackExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/reconciliation-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary=(
        "Attempt spot recovery reconciliation execution through the shared "
        "command service"
    ),
)
def execute_spot_recovery_reconciliation(
    request: Request,
    body: SpotRecoveryReconciliationExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route-bound reconciliation execution boundary; executor remains disabled."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_reconciliation",
        route_template="/api/v1/spot/recovery/reconciliation-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_reconciliation(
            SpotRecoveryReconciliationExecutionCommand(
                envelope=envelope,
                request=body,
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_reconciliation(
                SpotRecoveryReconciliationExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/exchange-state-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery exchange-state proof through the shared command service",
)
def record_spot_recovery_exchange_state_proof(
    request: Request,
    body: SpotRecoveryExchangeStateProofRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery exchange-state proof writing."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_exchange_state_proof",
        route_template="/api/v1/spot/recovery/exchange-state-proofs",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.record_spot_recovery_exchange_state_proof(
            SpotRecoveryExchangeStateProofCommand(
                envelope=envelope,
                request=body,
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_exchange_state_proof(
                SpotRecoveryExchangeStateProofCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/exchange-state-snapshots",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery exchange-state snapshot through the shared command service",
)
def record_spot_recovery_exchange_state_snapshot(
    request: Request,
    body: SpotRecoveryExchangeStateSnapshotRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for backend-owned no-live exchange-state snapshots."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_exchange_state_snapshot",
        route_template="/api/v1/spot/recovery/exchange-state-snapshots",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: (
            service.record_spot_recovery_exchange_state_snapshot(
                SpotRecoveryExchangeStateSnapshotCommand(
                    envelope=envelope,
                    request=body,
                )
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_exchange_state_snapshot(
                SpotRecoveryExchangeStateSnapshotCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/reconciliation-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery reconciliation proof through the shared command service",
)
def record_spot_recovery_reconciliation_proof(
    request: Request,
    body: SpotRecoveryReconciliationProofRecordRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery reconciliation-proof writing."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_reconciliation_proof",
        route_template="/api/v1/spot/recovery/reconciliation-proofs",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: (
            service.record_spot_recovery_reconciliation_proof(
                SpotRecoveryReconciliationProofRecordCommand(
                    envelope=envelope,
                    request=body,
                )
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_reconciliation_proof(
                SpotRecoveryReconciliationProofRecordCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )
