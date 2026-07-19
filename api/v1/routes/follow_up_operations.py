"""Repository-only read route for the operator follow-up operations queue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminOrderFollowUpOperationsQueueResponse,
)
from application.admin_api.operator_follow_up_operations import (
    OperatorFollowUpOperationsError,
    OperatorFollowUpOperationsService,
    get_default_operator_follow_up_operations_service,
)
from core.enums import (
    AdminApiPermission,
    AdminOrderFollowUpOperationActionability,
    AdminOrderFollowUpOperationState,
)


router = APIRouter()
_FOLLOW_UP_OPERATIONS_QUERY_KEYS = frozenset(
    {"product_id", "state", "actionability", "limit", "offset"}
)

FOLLOW_UP_OPERATIONS_READ_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks audit read permission.",
    },
    503: {
        "model": AdminApiErrorResponse,
        "description": "Local follow-up operations evidence is unavailable.",
    },
}


def get_follow_up_operations_service() -> OperatorFollowUpOperationsService:
    """Compose only the existing local PostgreSQL follow-up repository."""

    return get_default_operator_follow_up_operations_service()


@router.get(
    "/follow-up-operations",
    response_model=AdminOrderFollowUpOperationsQueueResponse,
    responses=FOLLOW_UP_OPERATIONS_READ_RESPONSES,
    summary="Read the backend-classified follow-up operations queue",
)
def list_follow_up_operations(
    request: Request,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFollowUpOperationsService,
        Depends(get_follow_up_operations_service),
    ],
    product_id: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=255,
            pattern=r"^[A-Z0-9][A-Z0-9._-]*$",
        ),
    ] = None,
    state: AdminOrderFollowUpOperationState | None = None,
    actionability: AdminOrderFollowUpOperationActionability | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Return one local SQL page without live reads, clients, or mutations."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    query_keys = [key for key, _value in request.query_params.multi_items()]
    if any(
        key not in _FOLLOW_UP_OPERATIONS_QUERY_KEYS for key in query_keys
    ):
        raise HTTPException(
            status_code=422,
            detail="follow_up_operations_query_parameter_unknown",
        )
    if any(query_keys.count(key) != 1 for key in set(query_keys)):
        raise HTTPException(
            status_code=422,
            detail="follow_up_operations_query_parameter_duplicate",
        )
    try:
        payload = service.list_queue(
            actor=actor,
            product_id=product_id,
            state=state,
            actionability=actionability,
            limit=limit,
            offset=offset,
        )
    except OperatorFollowUpOperationsError as exc:
        raise HTTPException(
            status_code=exc.http_status_code,
            detail=exc.code,
        ) from None
    return JSONResponse(content=jsonable_encoder(payload))
