"""Read-only spot operator routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    SpotCampaignStatusResponse,
    SpotCostBasisStatusResponse,
    SpotDirectOrderAuditResponse,
    SpotReadinessResponse,
    SpotSweepPnlResponse,
    SpotSweepStatusResponse,
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


def _read_model_response(model: type[TReadModel], payload: dict) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(model.model_validate(payload)))


@router.get(
    "/spot/readiness",
    response_model=SpotReadinessResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read spot trading readiness",
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
    summary="Read spot sweep P/L",
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
