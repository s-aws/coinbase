"""Read-only futures/perpetual routes for the Admin API."""

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
    AdminFuturesAccountReadResponse,
    AdminFuturesCommandSuiteResponse,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
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
    "/futures/command-suite",
    response_model=AdminFuturesCommandSuiteResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual command contract readiness",
)
def get_futures_command_suite(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read blocked M57 futures/perpetual command contract evidence."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesCommandSuiteResponse,
        service.build_futures_command_suite(),
    )


@router.get(
    "/futures/account",
    response_model=AdminFuturesAccountReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual account risk evidence",
)
def get_futures_account(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read futures/perpetual account evidence without mutating exchange state."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesAccountReadResponse,
        service.build_futures_account(),
    )


@router.get(
    "/futures/positions",
    response_model=AdminFuturesPositionListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual positions",
)
def list_futures_positions(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    position_side: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read futures/perpetual positions by position identity."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesPositionListResponse,
        service.build_futures_positions(
            product_id=product_id,
            position_side=position_side,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/futures/positions/{position_key}",
    response_model=AdminFuturesPositionDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one futures or perpetual position by position_key",
)
def get_futures_position_by_position_key(
    position_key: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read one futures/perpetual position by backend-defined position key."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesPositionDetailResponse,
        service.build_futures_position_detail(position_key=position_key),
    )
