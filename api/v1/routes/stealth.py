"""Stealth order route adapters for the Admin API."""

from __future__ import annotations

import uuid
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.live_execution import AdminApiLiveExecutionService
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminStealthOrderDetailResponse,
    AdminStealthOrderListResponse,
    StealthActivePlacementExchangeTruthProofCommand,
    StealthActivePlacementExchangeTruthProofRequest,
    StealthActivePlacementExchangeTruthReadResponse,
    StealthActivePlacementExchangeTruthSnapshotCommand,
    StealthActivePlacementExchangeTruthSnapshotRequest,
    StealthCoinbaseExchangeSubmissionPolicyProofCommand,
    StealthCoinbaseExchangeSubmissionPolicyProofRequest,
    StealthCoinbaseExchangeSubmissionPolicyReadResponse,
    StealthCreateLifecycleWriteGuardProofCommand,
    StealthCreateLifecycleWriteGuardProofRequest,
    StealthCreateLifecycleWriteGuardReadResponse,
    StealthManagerInvocationPolicyProofCommand,
    StealthManagerInvocationPolicyProofRequest,
    StealthManagerInvocationPolicyReadResponse,
    StealthCancelReplaceProofCommand,
    StealthCancelReplaceProofReadResponse,
    StealthCancelReplaceProofRequest,
    StealthMutationClaimSnapshotProofCommand,
    StealthMutationClaimSnapshotProofRequest,
    StealthMutationClaimSnapshotReadResponse,
    StealthCommandSuiteResponse,
    StealthOperatorScopeResponse,
    StealthCancelCommand,
    StealthCancelRequest,
    StealthCreateCommand,
    StealthCreateRequest,
    StealthMoveCommand,
    StealthMoveRequest,
    StealthPostWriteExecutionJournalCommand,
    StealthPostWriteExecutionJournalReadResponse,
    StealthPostWriteExecutionJournalRequest,
    StealthPostWriteReconciliationExecutionPolicyProofCommand,
    StealthPostWriteReconciliationExecutionPolicyProofRequest,
    StealthPostWriteReconciliationExecutionPolicyReadResponse,
    StealthPostWriteReconciliationProofCommand,
    StealthPostWriteReconciliationProofReadResponse,
    StealthPostWriteReconciliationProofRequest,
    StealthPostWriteReconciliationVerificationCommand,
    StealthPostWriteReconciliationVerificationReadResponse,
    StealthPostWriteReconciliationVerificationRequest,
    StealthStateMutationPolicyProofCommand,
    StealthStateMutationPolicyProofRequest,
    StealthStateMutationPolicyReadResponse,
    StealthRecoveryCommand,
    StealthRecoveryProofCommand,
    StealthRecoveryProofReadResponse,
    StealthRecoveryProofRequest,
    StealthRecoveryRequest,
    StealthRevealTriggerProofCommand,
    StealthRevealTriggerProofReadResponse,
    StealthRevealTriggerProofRequest,
    StealthReconciliationProofCommand,
    StealthReconciliationProofReadResponse,
    StealthReconciliationProofRequest,
    StealthReconciliationCommand,
    StealthReconciliationRequest,
    StealthRevealCommand,
    StealthRevealRequest,
)
from application.admin_api.read_service import (
    AdminApiReadService,
    stealth_command_suite_api_payload,
)
from core.enums import AdminApiActionClass, AdminApiPermission

from .orders import (
    COMMAND_ROUTE_RESPONSES,
    get_audit_store,
    get_approval_store,
    get_cap_guard_store,
    get_command_service,
    get_idempotency_store,
    get_live_execution_service,
    get_reconciliation_store,
    _build_envelope,
    _execute_idempotent_command,
    _idempotency_payload_hash,
)


router = APIRouter()

READ_ONLY_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


TReadModel = TypeVar("TReadModel", bound=BaseModel)


def _read_model_response(model: type[TReadModel], payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(model.model_validate(payload)))


def _stealth_create_with_backend_identity(
    *,
    body: StealthCreateRequest,
    actor: AdminApiActor,
    endpoint: str,
    idempotency_key: str,
    payload_hash: str,
) -> StealthCreateRequest:
    """Attach a stable backend-owned stealth id before admission checks."""

    if body.stealth_order_id:
        return body

    material = "|".join(
        [
            "coinbase-admin-api",
            "stealth-create",
            endpoint,
            actor.actor_id,
            idempotency_key,
            payload_hash,
        ]
    )
    return body.model_copy(
        update={"stealth_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, material))}
    )


@router.get(
    "/stealth/orders",
    response_model=AdminStealthOrderListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth order lifecycle evidence",
)
def list_stealth_orders(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    stealth_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read local stealth order evidence without mutating lifecycle state."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        AdminStealthOrderListResponse,
        service.build_stealth_order_list(
            product_id=product_id,
            status=stealth_status,
            limit=limit,
            offset=offset,
        ),
    )


@router.post(
    "/stealth/orders",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Create a stealth order through the shared command service",
)
def create_stealth_order(
    request: Request,
    body: StealthCreateRequest,
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
    """Route adapter for live-disabled stealth create by ``stealth_order_id``."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
    body = _stealth_create_with_backend_identity(
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
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="create_stealth_order",
        route_template="/api/v1/stealth/orders",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=body.stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=body.stealth_order_id,
        command_runner_with_admission=lambda admission_decision: service.create_stealth_order(
            StealthCreateCommand(
                envelope=envelope,
                request=body,
                admission_decision=admission_decision,
            )
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}",
    response_model=AdminStealthOrderDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one stealth order by stealth_order_id",
)
def get_stealth_order_by_stealth_order_id(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read one local stealth order row by ``stealth_order_id``."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        AdminStealthOrderDetailResponse,
        service.build_stealth_order_detail(stealth_order_id=stealth_order_id),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof",
    response_model=StealthActivePlacementExchangeTruthReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth active-placement exchange-truth evidence by stealth_order_id",
)
def get_stealth_active_placement_exchange_truth_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read active-placement evidence without calling Coinbase."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthActivePlacementExchangeTruthReadResponse,
        service.build_stealth_active_placement_exchange_truth(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof",
    response_model=StealthCreateLifecycleWriteGuardReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth create lifecycle-write guard evidence by stealth_order_id",
)
def get_stealth_create_lifecycle_write_guard_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read lifecycle-write guard evidence without lifecycle or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthCreateLifecycleWriteGuardReadResponse,
        service.build_stealth_create_lifecycle_write_guard(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/mutation-claim-proof",
    response_model=StealthMutationClaimSnapshotReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth mutation-claim snapshot proof evidence by stealth_order_id",
)
def get_stealth_mutation_claim_snapshot_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read mutation-claim proof evidence without claim or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthMutationClaimSnapshotReadResponse,
        service.build_stealth_mutation_claim_snapshot(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/recovery-proof",
    response_model=StealthRecoveryProofReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth recovery proof evidence by stealth_order_id",
)
def get_stealth_recovery_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read recovery proof evidence without repair, rollback, or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthRecoveryProofReadResponse,
        service.build_stealth_recovery_proof(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/reveal-trigger-proof",
    response_model=StealthRevealTriggerProofReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth reveal-trigger proof evidence by stealth_order_id",
)
def get_stealth_reveal_trigger_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read reveal-trigger proof evidence without trigger or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthRevealTriggerProofReadResponse,
        service.build_stealth_reveal_trigger_proof(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/manager-invocation-policy",
    response_model=StealthManagerInvocationPolicyReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth manager-invocation policy evidence by stealth_order_id",
)
def get_stealth_manager_invocation_policy(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read manager policy proof evidence without manager or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthManagerInvocationPolicyReadResponse,
        service.build_stealth_manager_invocation_policy(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy",
    response_model=StealthCoinbaseExchangeSubmissionPolicyReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth Coinbase exchange submission-policy evidence",
)
def get_stealth_coinbase_exchange_submission_policy(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read Coinbase exchange policy proof evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthCoinbaseExchangeSubmissionPolicyReadResponse,
        service.build_stealth_coinbase_exchange_submission_policy(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/state-mutation-policy",
    response_model=StealthStateMutationPolicyReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth state-mutation policy evidence",
)
def get_stealth_state_mutation_policy(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read state-mutation policy proof evidence without mutating state."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthStateMutationPolicyReadResponse,
        service.build_stealth_state_mutation_policy(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/reconciliation-proof",
    response_model=StealthReconciliationProofReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth reconciliation proof evidence by stealth_order_id",
)
def get_stealth_reconciliation_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read reconciliation proof evidence without reconciliation or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthReconciliationProofReadResponse,
        service.build_stealth_reconciliation_proof(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/cancel-replace-proof",
    response_model=StealthCancelReplaceProofReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth cancel/replace proof evidence by stealth_order_id",
)
def get_stealth_cancel_replace_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read cancel/replace proof evidence without manager or Coinbase writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthCancelReplaceProofReadResponse,
        service.build_stealth_cancel_replace_proof(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof",
    response_model=StealthPostWriteReconciliationProofReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth post-write reconciliation proof evidence by stealth_order_id",
)
def get_stealth_post_write_reconciliation_proof(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read post-write reconciliation proof evidence without execution."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthPostWriteReconciliationProofReadResponse,
        service.build_stealth_post_write_reconciliation_proof(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy",
    response_model=StealthPostWriteReconciliationExecutionPolicyReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth post-write reconciliation execution-policy evidence by stealth_order_id",
)
def get_stealth_post_write_reconciliation_execution_policy(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read post-write reconciliation policy evidence without execution."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthPostWriteReconciliationExecutionPolicyReadResponse,
        service.build_stealth_post_write_reconciliation_execution_policy(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/post-write-execution-journals",
    response_model=StealthPostWriteExecutionJournalReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth post-write execution-journal acceptance evidence by stealth_order_id",
)
def get_stealth_post_write_execution_journals(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read post-write execution-journal acceptance evidence without execution."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthPostWriteExecutionJournalReadResponse,
        service.build_stealth_post_write_execution_journals(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications",
    response_model=StealthPostWriteReconciliationVerificationReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth post-write reconciliation verification evidence by stealth_order_id",
)
def get_stealth_post_write_reconciliation_verifications(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read post-write reconciliation verification evidence without execution."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        StealthPostWriteReconciliationVerificationReadResponse,
        service.build_stealth_post_write_reconciliation_verifications(
            stealth_order_id=stealth_order_id
        ),
    )


@router.get(
    "/stealth/command-suite",
    response_model=StealthCommandSuiteResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth command-suite readiness coverage",
)
def stealth_command_suite(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read M55 stealth command readiness without mutating lifecycle state."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        StealthCommandSuiteResponse,
        stealth_command_suite_api_payload(service.build_stealth_command_suite()),
    )


@router.get(
    "/stealth/operator-scope",
    response_model=StealthOperatorScopeResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read stealth lifecycle operator scope",
)
def stealth_operator_scope(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read stealth operator scope without mutating lifecycle state."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        StealthOperatorScopeResponse,
        service.build_stealth_operator_scope(),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/reveal",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Reveal a stealth order by stealth_order_id through the shared command service",
)
def reveal_stealth_order_by_stealth_order_id(
    request: Request,
    body: StealthRevealRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for live-disabled stealth reveal by ``stealth_order_id``."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
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
        service_method="reveal_stealth_order_by_stealth_order_id",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_exchange_truth_proof_store=(
            service.dependencies.stealth_exchange_truth_proof_store_getter()
        ),
        stealth_mutation_claim_proof_store=(
            service.dependencies.stealth_mutation_claim_proof_store_getter()
        ),
        stealth_manager_policy_proof_store=(
            service.dependencies.stealth_manager_policy_proof_store_getter()
        ),
        stealth_coinbase_exchange_policy_proof_store=(
            service.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
        ),
        stealth_state_mutation_policy_proof_store=(
            service.dependencies.stealth_state_mutation_policy_proof_store_getter()
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
        ),
        stealth_reveal_trigger_proof_store=(
            service.dependencies.stealth_reveal_trigger_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.reveal_stealth_order_by_stealth_order_id(
            StealthRevealCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/move",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Move a revealed stealth order by stealth_order_id through the shared command service",
)
def move_stealth_order_by_stealth_order_id(
    request: Request,
    body: StealthMoveRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for live-disabled stealth move by ``stealth_order_id``."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
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
        service_method="move_stealth_order_by_stealth_order_id",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/move",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_exchange_truth_proof_store=(
            service.dependencies.stealth_exchange_truth_proof_store_getter()
        ),
        stealth_mutation_claim_proof_store=(
            service.dependencies.stealth_mutation_claim_proof_store_getter()
        ),
        stealth_manager_policy_proof_store=(
            service.dependencies.stealth_manager_policy_proof_store_getter()
        ),
        stealth_coinbase_exchange_policy_proof_store=(
            service.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
        ),
        stealth_state_mutation_policy_proof_store=(
            service.dependencies.stealth_state_mutation_policy_proof_store_getter()
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
        ),
        stealth_cancel_replace_proof_store=(
            service.dependencies.stealth_cancel_replace_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.move_stealth_order_by_stealth_order_id(
            StealthMoveCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Cancel a stealth order by stealth_order_id through the shared command service",
)
def cancel_stealth_order_by_stealth_order_id(
    request: Request,
    body: StealthCancelRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for live-disabled stealth cancel by ``stealth_order_id``."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
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
        service_method="cancel_stealth_order_by_stealth_order_id",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/cancel",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_exchange_truth_proof_store=(
            service.dependencies.stealth_exchange_truth_proof_store_getter()
        ),
        stealth_mutation_claim_proof_store=(
            service.dependencies.stealth_mutation_claim_proof_store_getter()
        ),
        stealth_manager_policy_proof_store=(
            service.dependencies.stealth_manager_policy_proof_store_getter()
        ),
        stealth_coinbase_exchange_policy_proof_store=(
            service.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
        ),
        stealth_state_mutation_policy_proof_store=(
            service.dependencies.stealth_state_mutation_policy_proof_store_getter()
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
        ),
        stealth_cancel_replace_proof_store=(
            service.dependencies.stealth_cancel_replace_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.cancel_stealth_order_by_stealth_order_id(
            StealthCancelCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/recovery",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary=(
        "Evaluate live-disabled stealth recovery prerequisites by "
        "stealth_order_id through the shared command service"
    ),
)
def recover_stealth_order_by_stealth_order_id(
    request: Request,
    body: StealthRecoveryRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for live-disabled stealth recovery prerequisite evidence."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_RECOVERY_EXECUTE,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="recover_stealth_order_by_stealth_order_id",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/recovery",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_exchange_truth_proof_store=(
            service.dependencies.stealth_exchange_truth_proof_store_getter()
        ),
        stealth_mutation_claim_proof_store=(
            service.dependencies.stealth_mutation_claim_proof_store_getter()
        ),
        stealth_manager_policy_proof_store=(
            service.dependencies.stealth_manager_policy_proof_store_getter()
        ),
        stealth_coinbase_exchange_policy_proof_store=(
            service.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
        ),
        stealth_state_mutation_policy_proof_store=(
            service.dependencies.stealth_state_mutation_policy_proof_store_getter()
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
        ),
        stealth_recovery_proof_store=(
            service.dependencies.stealth_recovery_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.recover_stealth_order_by_stealth_order_id(
            StealthRecoveryCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/reconciliation",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Reconcile stealth order state by stealth_order_id through the shared command service",
)
def reconcile_stealth_order_by_stealth_order_id(
    request: Request,
    body: StealthReconciliationRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for live-disabled stealth reconciliation by ``stealth_order_id``."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_RECONCILIATION_EXECUTE,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="reconcile_stealth_order_by_stealth_order_id",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_exchange_truth_proof_store=(
            service.dependencies.stealth_exchange_truth_proof_store_getter()
        ),
        stealth_mutation_claim_proof_store=(
            service.dependencies.stealth_mutation_claim_proof_store_getter()
        ),
        stealth_manager_policy_proof_store=(
            service.dependencies.stealth_manager_policy_proof_store_getter()
        ),
        stealth_coinbase_exchange_policy_proof_store=(
            service.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
        ),
        stealth_state_mutation_policy_proof_store=(
            service.dependencies.stealth_state_mutation_policy_proof_store_getter()
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
        ),
        stealth_reconciliation_proof_store=(
            service.dependencies.stealth_reconciliation_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_post_write_execution_journal_store=(
            service.dependencies.stealth_post_write_execution_journal_store_getter()
        ),
        stealth_post_write_reconciliation_verification_store=(
            service.dependencies.stealth_post_write_reconciliation_verification_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.reconcile_stealth_order_by_stealth_order_id(
            StealthReconciliationCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth active-placement exchange-truth snapshot evidence",
)
def record_stealth_active_placement_exchange_truth_snapshot(
    request: Request,
    body: StealthActivePlacementExchangeTruthSnapshotRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live active-placement snapshots."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_active_placement_exchange_truth_snapshot",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-snapshots"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_active_placement_exchange_truth_snapshot(
                StealthActivePlacementExchangeTruthSnapshotCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth active-placement exchange-truth proof evidence",
)
def record_stealth_active_placement_exchange_truth_proof(
    request: Request,
    body: StealthActivePlacementExchangeTruthProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live active-placement proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_active_placement_exchange_truth_proof",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_active_placement_exchange_truth_proof(
                StealthActivePlacementExchangeTruthProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth create lifecycle-write guard proof evidence",
)
def record_stealth_create_lifecycle_write_guard_proof(
    request: Request,
    body: StealthCreateLifecycleWriteGuardProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live lifecycle-write guard proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_create_lifecycle_write_guard_proof",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "lifecycle-write-guard-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_create_lifecycle_write_guard_proof(
                StealthCreateLifecycleWriteGuardProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/mutation-claim-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth mutation-claim snapshot proof evidence",
)
def record_stealth_mutation_claim_snapshot_proof(
    request: Request,
    body: StealthMutationClaimSnapshotProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live mutation-claim proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_mutation_claim_snapshot_proof",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_mutation_claim_snapshot_proof(
                StealthMutationClaimSnapshotProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/recovery-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth recovery proof evidence",
)
def record_stealth_recovery_proof(
    request: Request,
    body: StealthRecoveryProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live recovery proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_RECOVERY_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_recovery_proof",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/recovery-proofs",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_recovery_proof(
                StealthRecoveryProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth reveal-trigger proof evidence",
)
def record_stealth_reveal_trigger_proof(
    request: Request,
    body: StealthRevealTriggerProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live reveal-trigger proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_REVEAL_TRIGGER_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_reveal_trigger_proof",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_reveal_trigger_proof(
                StealthRevealTriggerProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/manager-invocation-policy-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth manager-invocation policy proof evidence",
)
def record_stealth_manager_invocation_policy_proof(
    request: Request,
    body: StealthManagerInvocationPolicyProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live manager-policy proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_MANAGER_POLICY_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_manager_invocation_policy_proof",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "manager-invocation-policy-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_manager_invocation_policy_proof(
                StealthManagerInvocationPolicyProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth Coinbase exchange submission-policy proof evidence",
)
def record_stealth_coinbase_exchange_submission_policy_proof(
    request: Request,
    body: StealthCoinbaseExchangeSubmissionPolicyProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live Coinbase exchange policy proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=(
            "record_stealth_coinbase_exchange_submission_policy_proof"
        ),
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "coinbase-exchange-submission-policy-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_coinbase_exchange_submission_policy_proof(
                StealthCoinbaseExchangeSubmissionPolicyProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/state-mutation-policy-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth state-mutation policy proof evidence",
)
def record_stealth_state_mutation_policy_proof(
    request: Request,
    body: StealthStateMutationPolicyProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live state-mutation policy proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_STATE_MUTATION_POLICY_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_state_mutation_policy_proof",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "state-mutation-policy-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_state_mutation_policy_proof(
                StealthStateMutationPolicyProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/reconciliation-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth reconciliation proof evidence",
)
def record_stealth_reconciliation_proof(
    request: Request,
    body: StealthReconciliationProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live reconciliation proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_RECONCILIATION_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_reconciliation_proof",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_reconciliation_proof(
                StealthReconciliationProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/cancel-replace-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth cancel/replace proof evidence",
)
def record_stealth_cancel_replace_proof(
    request: Request,
    body: StealthCancelReplaceProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live cancel/replace proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_cancel_replace_proof",
        route_template="/api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs",
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_cancel_replace_proof(
                StealthCancelReplaceProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth post-write reconciliation proof evidence",
)
def record_stealth_post_write_reconciliation_proof(
    request: Request,
    body: StealthPostWriteReconciliationProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live post-write proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_post_write_reconciliation_proof",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_post_write_reconciliation_proof(
                StealthPostWriteReconciliationProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth post-write reconciliation execution-policy proof evidence",
)
def record_stealth_post_write_reconciliation_execution_policy_proof(
    request: Request,
    body: StealthPostWriteReconciliationExecutionPolicyProofRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for no-live post-write reconciliation policy proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=(
            AdminApiPermission.STEALTH_POST_WRITE_RECONCILIATION_POLICY_RECORD
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=(
            "record_stealth_post_write_reconciliation_execution_policy_proof"
        ),
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-execution-policy-proofs"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_post_write_reconciliation_execution_policy_proof(
                StealthPostWriteReconciliationExecutionPolicyProofCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/post-write-execution-journals",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth post-write execution-journal acceptance evidence",
)
def record_stealth_post_write_execution_journal(
    request: Request,
    body: StealthPostWriteExecutionJournalRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live execution-journal acceptances."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_stealth_post_write_execution_journal",
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-execution-journals"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_post_write_execution_journal(
                StealthPostWriteExecutionJournalCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record stealth post-write reconciliation verification evidence",
)
def record_stealth_post_write_reconciliation_verification(
    request: Request,
    body: StealthPostWriteReconciliationVerificationRequest,
    stealth_order_id: Annotated[str, Path(min_length=1)],
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
    """Route adapter for backend-owned no-live post-write verification."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
        path_params={"stealth_order_id": stealth_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=(
            "record_stealth_post_write_reconciliation_verification"
        ),
        route_template=(
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-verifications"
        ),
        module_id="stealth_orders",
        identity_key="stealth_order_id",
        identity_value=stealth_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        stealth_order_id=stealth_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.record_stealth_post_write_reconciliation_verification(
                StealthPostWriteReconciliationVerificationCommand(
                    envelope=envelope,
                    stealth_order_id=stealth_order_id,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )
