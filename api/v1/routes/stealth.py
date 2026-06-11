"""Read-only stealth order routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminStealthOrderDetailResponse,
    AdminStealthOrderListResponse,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import AdminApiPermission


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
