"""Movement/repricing read routes and live-disabled command routes."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import AdminApiLiveExecutionService
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminMovementRepricingDetailResponse,
    AdminMovementRepricingListResponse,
    MovementRepriceCommand,
    MovementRepriceRequest,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiPermission,
    AdminMovementRepricingEvidenceType,
)

from .orders import (
    COMMAND_ROUTE_RESPONSES,
    _build_envelope,
    _execute_idempotent_command,
    _idempotency_payload_hash,
    get_audit_store,
    get_approval_store,
    get_cap_guard_store,
    get_command_service,
    get_idempotency_store,
    get_live_execution_service,
    get_reconciliation_store,
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


@router.get(
    "/movement-repricing/evidence",
    response_model=AdminMovementRepricingListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read movement and repricing evidence",
)
def list_movement_repricing_evidence(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    client_order_id: str | None = None,
    stealth_order_id: str | None = None,
    evidence_type: AdminMovementRepricingEvidenceType | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read movement/repricing evidence without creating, moving, or repricing."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        AdminMovementRepricingListResponse,
        service.build_movement_repricing_evidence(
            product_id=product_id,
            client_order_id=client_order_id,
            stealth_order_id=stealth_order_id,
            evidence_type=evidence_type,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/movement-repricing/orders/{client_order_id}",
    response_model=AdminMovementRepricingDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read movement and repricing evidence for one client_order_id",
)
def get_movement_repricing_by_client_order_id(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read movement/repricing evidence linked to one ``client_order_id``."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        AdminMovementRepricingDetailResponse,
        service.build_movement_repricing_order_detail(client_order_id=client_order_id),
    )


@router.get(
    "/movement-repricing/stealth/{stealth_order_id}",
    response_model=AdminMovementRepricingDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read movement and repricing evidence for one stealth_order_id",
)
def get_movement_repricing_by_stealth_order_id(
    stealth_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read movement/repricing evidence linked to one ``stealth_order_id``."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_model_response(
        AdminMovementRepricingDetailResponse,
        service.build_movement_repricing_stealth_detail(
            stealth_order_id=stealth_order_id
        ),
    )


@router.post(
    "/movement-repricing/stealth/{stealth_order_id}/reprice",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Reprice a stealth order by stealth_order_id through the shared command service",
)
def reprice_stealth_order_by_stealth_order_id(
    request: Request,
    body: MovementRepriceRequest,
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
    """Route adapter for live-disabled movement repricing by ``stealth_order_id``."""

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
        service_method="reprice_stealth_order_by_stealth_order_id",
        route_template="/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        module_id="movement_repricing",
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
        stealth_cancel_replace_proof_store=(
            service.dependencies.stealth_cancel_replace_proof_store_getter()
        ),
        stealth_post_write_reconciliation_proof_store=(
            service.dependencies.stealth_post_write_reconciliation_proof_store_getter()
        ),
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.reprice_stealth_order_by_stealth_order_id(
            MovementRepriceCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )
