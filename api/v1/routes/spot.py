"""Read-only spot operator routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, Callable, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.cap_guard_service import AdminApiCapGuardDecisionService
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    SpotPnlCheckpointCreateRequest,
    SpotPnlCheckpointItem,
    SpotPnlCheckpointListResponse,
    SpotPnlCheckpointResponse,
    SpotCampaignStatusResponse,
    SpotCancelOrderProofChainRequest,
    SpotCancelOrderProofChainResponse,
    SpotCommandSuiteResponse,
    SpotCostBasisStatusResponse,
    SpotDirectOrderAuditResponse,
    SpotManualOrderProofChainRequest,
    SpotManualOrderProofChainResponse,
    SpotReadinessResponse,
    SpotRecoveryApplyReviewResponse,
    SpotRecoveryPreviewResponse,
    SpotRecoveryReconciliationProofResponse,
    SpotRecoveryRollbackPlanResponse,
    SpotSweepPnlResponse,
    SpotSweepStatusResponse,
)
from application.admin_api.pnl_checkpoint import FileSpotPnlCheckpointStore
from application.admin_api.mvp_service import AdminMvpRequestContext, get_admin_mvp_service
from application.admin_api.pnl_checkpoint_service import (
    AdminApiSpotPnlCheckpointService,
    SpotPnlCheckpointError,
)
from application.admin_api.read_service import AdminApiReadService
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
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

PNL_CHECKPOINT_ROUTE_RESPONSES = {
    200: {
        "model": SpotPnlCheckpointResponse,
        "description": "Spot P/L checkpoint mutation accepted or replayed.",
    },
    400: {
        "model": SpotPnlCheckpointResponse,
        "description": "Spot P/L checkpoint mutation rejected.",
    },
    401: READ_ONLY_ROUTE_RESPONSES[401],
    403: READ_ONLY_ROUTE_RESPONSES[403],
    404: {
        "model": AdminApiErrorResponse,
        "description": "Spot P/L checkpoint was not found.",
    },
    409: {
        "model": SpotPnlCheckpointResponse,
        "description": "Idempotency key conflict.",
    },
}

PNL_CHECKPOINT_DETAIL_ROUTE_RESPONSES = {
    200: {
        "model": SpotPnlCheckpointResponse,
        "description": "Spot P/L checkpoint detail loaded.",
    },
    401: READ_ONLY_ROUTE_RESPONSES[401],
    403: READ_ONLY_ROUTE_RESPONSES[403],
    404: {
        "model": AdminApiErrorResponse,
        "description": "Spot P/L checkpoint was not found.",
    },
}


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService(mvp_service=get_admin_mvp_service())


def get_spot_pnl_checkpoint_service() -> AdminApiSpotPnlCheckpointService:
    """Return the backend-owned Spot P/L checkpoint service."""

    return AdminApiSpotPnlCheckpointService()


def get_spot_pnl_checkpoint_store() -> FileSpotPnlCheckpointStore:
    """Return durable Spot P/L checkpoint storage."""

    return FileSpotPnlCheckpointStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for Spot local mutations."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for Spot local mutations."""

    return FileAdminApiAuditStore()


def get_approval_store() -> FileAdminApiApprovalStore:
    """Return canonical approval storage for composite Spot proofs."""

    return FileAdminApiApprovalStore()


def get_cap_guard_store() -> FileAdminApiCapGuardStore:
    """Return canonical cap/guard storage for composite Spot proofs."""

    return FileAdminApiCapGuardStore()


def get_reconciliation_store() -> FileAdminApiReconciliationStore:
    """Return canonical reconciliation storage for composite Spot proofs."""

    return FileAdminApiReconciliationStore()


def get_composite_proof_cap_guard_service() -> AdminApiCapGuardDecisionService:
    """Return backend-authoritative wallet/cap resolution for composite proofs."""

    return AdminApiCapGuardDecisionService()


TReadModel = TypeVar("TReadModel", bound=BaseModel)


def _read_model_response(model: type[TReadModel], payload: dict) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(model.model_validate(payload)))


def _http_status_for_checkpoint(response: SpotPnlCheckpointResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _checkpoint_response(
    response: SpotPnlCheckpointResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status_for_checkpoint(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _admin_mvp_context(
    actor: AdminApiActor,
    *,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=idempotency_key.strip(),
        correlation_id=correlation_id.strip(),
        operator_intent=operator_intent.strip(),
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
    )


def _checkpoint_payload_hash(
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


def _record_checkpoint_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: SpotPnlCheckpointResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": (
            "idempotency"
            if response.status == AdminApiCommandStatus.CONFLICT
            else (
                "spot_pnl_checkpoint"
                if response.status == AdminApiCommandStatus.REJECTED
                else None
            )
        ),
        "message": response.message,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _execute_idempotent_spot_pnl_checkpoint(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], SpotPnlCheckpointItem],
    rehydrate_checkpoint: Callable[[SpotPnlCheckpointItem], SpotPnlCheckpointItem] | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.SPOT_PNL_RECORD)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        return _checkpoint_response(
            SpotPnlCheckpointResponse.model_validate(payload),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = SpotPnlCheckpointResponse(
            status=AdminApiCommandStatus.CONFLICT,
            required_permission=AdminApiPermission.SPOT_PNL_RECORD,
            service_method="record_spot_pnl_checkpoint",
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_checkpoint_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _checkpoint_response(response)

    try:
        audit_id = str(uuid4())
        checkpoint = operation(audit_id)
        response = SpotPnlCheckpointResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            required_permission=AdminApiPermission.SPOT_PNL_RECORD,
            service_method="record_spot_pnl_checkpoint",
            message="Spot P/L checkpoint accepted.",
            checkpoint=checkpoint,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
        )
    except SpotPnlCheckpointError as exc:
        response = SpotPnlCheckpointResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=AdminApiPermission.SPOT_PNL_RECORD,
            service_method="record_spot_pnl_checkpoint",
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    response.audit_id = _record_checkpoint_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        if response.checkpoint is not None and rehydrate_checkpoint is not None:
            response.checkpoint = rehydrate_checkpoint(response.checkpoint)
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=endpoint,
            )
        )
    return _checkpoint_response(response)


@router.get(
    "/spot/readiness",
    response_model=SpotReadinessResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read local value-blind spot readiness evidence",
)
def spot_readiness(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_ids: Annotated[list[str] | None, Query(alias="product_id")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        SpotReadinessResponse,
        service.build_spot_readiness(product_ids=product_ids),
    )


@router.get(
    "/spot/command-suite",
    response_model=SpotCommandSuiteResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot command-suite readiness coverage",
)
def spot_command_suite(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        SpotCommandSuiteResponse,
        service.build_spot_command_suite().model_dump(mode="json"),
    )


@router.get(
    "/spot/recovery/preview",
    response_model=SpotRecoveryPreviewResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Preview spot recovery candidates without applying recovery",
)
def spot_recovery_preview(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
    run_id: str | None = None,
    config_id: str | None = None,
    client_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        SpotRecoveryPreviewResponse,
        service.build_spot_recovery_preview(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        ).model_dump(mode="json"),
    )


@router.get(
    "/spot/recovery/apply-review",
    response_model=SpotRecoveryApplyReviewResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Review spot recovery apply contract evidence without applying recovery",
)
def spot_recovery_apply_review(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
    run_id: str | None = None,
    config_id: str | None = None,
    client_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        SpotRecoveryApplyReviewResponse,
        service.build_spot_recovery_apply_review(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        ).model_dump(mode="json"),
    )


@router.get(
    "/spot/recovery/rollback-plan",
    response_model=SpotRecoveryRollbackPlanResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot recovery rollback-plan evidence without rollback authority",
)
def spot_recovery_rollback_plan(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
    run_id: str | None = None,
    config_id: str | None = None,
    client_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        SpotRecoveryRollbackPlanResponse,
        service.build_spot_recovery_rollback_plan(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        ).model_dump(mode="json"),
    )


@router.get(
    "/spot/recovery/reconciliation-proof",
    response_model=SpotRecoveryReconciliationProofResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot recovery reconciliation-proof evidence without proof writing",
)
def spot_recovery_reconciliation_proof(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
    run_id: str | None = None,
    config_id: str | None = None,
    client_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        SpotRecoveryReconciliationProofResponse,
        service.build_spot_recovery_reconciliation_proof(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        ).model_dump(mode="json"),
    )


@router.get(
    "/spot/sweep/status",
    response_model=SpotSweepStatusResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot sweep status",
)
def spot_sweep_status(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        SpotSweepStatusResponse,
        service.build_spot_sweep_status(state_file=state_file),
    )


@router.get(
    "/spot/sweep/pnl",
    response_model=SpotSweepPnlResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read local value-blind spot P/L availability evidence",
)
def spot_sweep_pnl(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_ids: Annotated[list[str] | None, Query(alias="product_id")] = None,
    include_coinbase_average_cost: bool = False,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        SpotSweepPnlResponse,
        service.build_spot_sweep_pnl(
            product_ids=product_ids,
            include_coinbase_average_cost=include_coinbase_average_cost,
        ),
    )


@router.post(
    "/spot/manual-order/proof-chain",
    response_model=SpotManualOrderProofChainResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Record backend-owned spot manual-order proof-chain evidence",
)
def record_spot_manual_order_proof_chain(
    body: SpotManualOrderProofChainRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    command_idempotency_store: Annotated[
        FileIdempotencyStore,
        Depends(get_idempotency_store),
    ],
    approval_store: Annotated[
        FileAdminApiApprovalStore,
        Depends(get_approval_store),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_cap_guard_store),
    ],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    cap_guard_service: Annotated[
        AdminApiCapGuardDecisionService,
        Depends(get_composite_proof_cap_guard_service),
    ],
) -> JSONResponse:
    require_permission(
        actor,
        AdminApiPermission.SPOT_MANUAL_ORDER_PROOF_RECORD,
    )
    result = get_admin_mvp_service().record_spot_manual_order_proof_chain(
        body.model_dump(mode="json"),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
        command_idempotency_store=command_idempotency_store,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        cap_guard_service=cap_guard_service,
    )
    response_body = (
        SpotManualOrderProofChainResponse.model_validate(result.body)
        if result.status_code == status.HTTP_200_OK
        else result.body
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(response_body),
        headers=result.headers,
    )


@router.post(
    "/spot/cancel-order/proof-chain",
    response_model=SpotCancelOrderProofChainResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Record backend-owned spot cancel-order proof-chain evidence",
)
def record_spot_cancel_order_proof_chain(
    body: SpotCancelOrderProofChainRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    command_idempotency_store: Annotated[
        FileIdempotencyStore,
        Depends(get_idempotency_store),
    ],
    approval_store: Annotated[
        FileAdminApiApprovalStore,
        Depends(get_approval_store),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_cap_guard_store),
    ],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    cap_guard_service: Annotated[
        AdminApiCapGuardDecisionService,
        Depends(get_composite_proof_cap_guard_service),
    ],
) -> JSONResponse:
    require_permission(
        actor,
        AdminApiPermission.SPOT_ORDER_CANCEL_PROOF_RECORD,
    )
    result = get_admin_mvp_service().record_spot_cancel_order_proof_chain(
        body.model_dump(mode="json"),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
        command_idempotency_store=command_idempotency_store,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        cap_guard_service=cap_guard_service,
    )
    response_body = (
        SpotCancelOrderProofChainResponse.model_validate(result.body)
        if result.status_code == status.HTTP_200_OK
        else result.body
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(response_body),
        headers=result.headers,
    )


@router.get(
    "/spot/pnl/checkpoints",
    response_model=SpotPnlCheckpointListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned Spot P/L checkpoint records",
)
def list_spot_pnl_checkpoints(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiSpotPnlCheckpointService,
        Depends(get_spot_pnl_checkpoint_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    checkpoint_store: Annotated[
        FileSpotPnlCheckpointStore,
        Depends(get_spot_pnl_checkpoint_store),
    ],
    checkpoint_status: AdminApiGateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    checkpoints = service.list_checkpoints(
        store=checkpoint_store,
        audit_store=audit_store,
        status_filter=checkpoint_status,
        limit=limit,
    )
    all_checkpoints = service.list_checkpoints(
        store=checkpoint_store,
        audit_store=audit_store,
        limit=500,
    )
    counts = {status_value: 0 for status_value in AdminApiGateStatus}
    for item in all_checkpoints:
        counts[item.review_status] += 1
    payload = SpotPnlCheckpointListResponse(
        checkpoints=checkpoints,
        returned_count=len(checkpoints),
        total_count=len(all_checkpoints),
        passed_count=counts[AdminApiGateStatus.PASSED],
        blocked_count=counts[AdminApiGateStatus.BLOCKED],
        warning_count=counts[AdminApiGateStatus.WARNING],
        average_cost_review_count=sum(
            1 for item in all_checkpoints if item.average_cost_reviewed
        ),
        audit_linked_count=sum(1 for item in all_checkpoints if item.audit_linked),
        recovery_linked_count=sum(
            1 for item in all_checkpoints if item.recovery_linked
        ),
        reconciliation_linked_count=sum(
            1 for item in all_checkpoints if item.reconciliation_linked
        ),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/spot/pnl/checkpoints/{checkpoint_id}",
    response_model=SpotPnlCheckpointResponse,
    responses=PNL_CHECKPOINT_DETAIL_ROUTE_RESPONSES,
    summary="Read one backend-owned Spot P/L checkpoint record",
)
def get_spot_pnl_checkpoint(
    checkpoint_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiSpotPnlCheckpointService,
        Depends(get_spot_pnl_checkpoint_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    checkpoint_store: Annotated[
        FileSpotPnlCheckpointStore,
        Depends(get_spot_pnl_checkpoint_store),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        checkpoint = service.get_checkpoint(
            store=checkpoint_store,
            checkpoint_id=checkpoint_id,
            audit_store=audit_store,
        )
    except SpotPnlCheckpointError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = SpotPnlCheckpointResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.ANALYTICS_READ,
        service_method="get_spot_pnl_checkpoint",
        message="Spot P/L checkpoint detail loaded.",
        checkpoint=checkpoint,
        read_only=True,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/spot/pnl/checkpoints",
    response_model=SpotPnlCheckpointResponse,
    responses=PNL_CHECKPOINT_ROUTE_RESPONSES,
    summary="Record a backend-owned Spot P/L checkpoint",
)
def record_spot_pnl_checkpoint(
    request: Request,
    body: SpotPnlCheckpointCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiSpotPnlCheckpointService,
        Depends(get_spot_pnl_checkpoint_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    checkpoint_store: Annotated[
        FileSpotPnlCheckpointStore,
        Depends(get_spot_pnl_checkpoint_store),
    ],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _checkpoint_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_spot_pnl_checkpoint(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.record_checkpoint(
            store=checkpoint_store,
            body=body,
            actor_id=actor.actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        ),
        rehydrate_checkpoint=lambda checkpoint: service.get_checkpoint(
            store=checkpoint_store,
            checkpoint_id=checkpoint.checkpoint_id,
            audit_store=audit_store,
        ),
    )


@router.get(
    "/spot/cost-basis/status",
    response_model=SpotCostBasisStatusResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot cost-basis status",
)
def spot_cost_basis_status(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        SpotCostBasisStatusResponse,
        service.build_spot_cost_basis_status(state_file=state_file),
    )


@router.get(
    "/spot/campaign/status",
    response_model=SpotCampaignStatusResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot campaign status",
)
def spot_campaign_status(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    state_file: str | None = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_READ)
    return _read_model_response(
        SpotCampaignStatusResponse,
        service.build_spot_campaign_status(state_file=state_file),
    )


@router.get(
    "/spot/direct-orders/{client_order_id}/audit",
    response_model=SpotDirectOrderAuditResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read direct spot order audit by client_order_id",
)
def spot_direct_order_audit(
    client_order_id: str,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    include_events: bool = True,
    include_fills: bool = True,
    event_limit: int = 100,
    fill_limit: int = 1000,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        SpotDirectOrderAuditResponse,
        service.build_spot_direct_order_audit(
            client_order_id=client_order_id,
            include_events=include_events,
            include_fills=include_fills,
            event_limit=event_limit,
            fill_limit=fill_limit,
        ),
    )
