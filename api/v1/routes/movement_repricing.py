"""Read-only movement/repricing routes for the Admin API."""

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
    AdminMovementRepricingDetailResponse,
    AdminMovementRepricingListResponse,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import AdminApiPermission, AdminMovementRepricingEvidenceType


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
