"""Stealth order route adapters for the Admin API."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminStealthOrderDetailResponse,
    AdminStealthOrderListResponse,
    StealthCancelCommand,
    StealthCancelRequest,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import AdminApiActionClass, AdminApiPermission

from .orders import (
    COMMAND_ROUTE_RESPONSES,
    get_audit_store,
    get_approval_store,
    get_command_service,
    get_idempotency_store,
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
        stealth_order_id=stealth_order_id,
        command_runner=lambda: service.cancel_stealth_order_by_stealth_order_id(
            StealthCancelCommand(
                envelope=envelope,
                stealth_order_id=stealth_order_id,
                request=body,
            )
        ),
    )
