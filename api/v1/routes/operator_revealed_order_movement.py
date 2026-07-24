"""Authenticated review and exact execution for one revealed-order move."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_revealed_order_movement_runtime import (
    get_operator_revealed_order_movement_runtime,
)
from application.admin_api.operator_revealed_order_movement_service import (
    OperatorRevealedOrderMoveExecuteRequest,
    OperatorRevealedOrderMovementConflict,
    OperatorRevealedOrderMovementError,
    OperatorRevealedOrderMovementResponse,
    OperatorRevealedOrderMovePlanRequest,
    OperatorRevealedOrderMovementService,
    safe_operator_revealed_order_movement_code,
)
from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)
from core.enums import AdminApiPermission
from database.operator_revealed_order_movement import (
    get_default_operator_revealed_order_movement_repository,
)
from database.operator_stealth_definition import (
    get_default_operator_stealth_definition_repository,
)


OPERATOR_REVEALED_ORDER_MOVEMENT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_REVEALED_ORDER_MOVEMENT_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"


def require_operator_revealed_order_movement_enabled() -> None:
    if (
        os.environ.get(OPERATOR_REVEALED_ORDER_MOVEMENT_ENABLED_ENV)
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_move_disabled",
        )


router = APIRouter(
    dependencies=[
        Depends(require_operator_revealed_order_movement_enabled)
    ]
)
_StealthId = Annotated[str, Path(pattern=_UUID)]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
]
_CorrelationId = Annotated[
    str,
    Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
]
_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    404: {"model": AdminApiErrorResponse},
    409: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def get_operator_revealed_order_movement_service(
) -> OperatorRevealedOrderMovementService:
    try:
        return OperatorRevealedOrderMovementService(
            definition_repository=(
                get_default_operator_stealth_definition_repository()
            ),
            repository=(
                get_default_operator_revealed_order_movement_repository()
            ),
            runtime=get_operator_revealed_order_movement_runtime(),
            execution_authority_checker=(
                coinbase_execution_authority_enabled
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_move_service_unavailable",
        ) from None


def get_operator_revealed_order_movement_read_service(
) -> OperatorRevealedOrderMovementService:
    try:
        return OperatorRevealedOrderMovementService(
            definition_repository=(
                get_default_operator_stealth_definition_repository()
            ),
            repository=(
                get_default_operator_revealed_order_movement_repository()
            ),
            runtime=None,
            execution_authority_checker=(
                coinbase_execution_authority_enabled
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_move_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorRevealedOrderMovementService,
    Depends(get_operator_revealed_order_movement_service),
]
_ReadService = Annotated[
    OperatorRevealedOrderMovementService,
    Depends(get_operator_revealed_order_movement_read_service),
]


def _roles(actor: AdminApiActor) -> list[str]:
    return [
        str(getattr(role, "value", role))
        for role in sorted(actor.roles, key=str)
    ]


def _handle(operation) -> JSONResponse:
    try:
        response = operation()
    except OperatorRevealedOrderMovementConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=safe_operator_revealed_order_movement_code(exc),
        ) from None
    except OperatorRevealedOrderMovementError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=safe_operator_revealed_order_movement_code(exc),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_move_unknown",
        ) from None
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response.model_dump(mode="json"),
        headers=(
            {"X-Correlation-Id": response.correlation_id}
            if response.correlation_id
            else {}
        ),
    )


def _require_move_permissions(actor: AdminApiActor) -> None:
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    require_permission(actor, AdminApiPermission.ORDER_CREATE)


@router.get(
    "/movement-repricing/stealth/{stealth_order_id}/move-execution",
    response_model=OperatorRevealedOrderMovementResponse,
    responses=_RESPONSES,
    summary="Review one exact revealed-order movement",
)
def get_operator_revealed_order_movement(
    stealth_order_id: _StealthId,
    actor: _Actor,
    service: _ReadService,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.get_execution(
            stealth_order_id,
            roles=_roles(actor),
        )
    )


@router.post(
    "/movement-repricing/stealth/{stealth_order_id}/move-plans",
    response_model=OperatorRevealedOrderMovementResponse,
    responses=_RESPONSES,
    summary="Prepare one immutable revealed-order movement plan",
)
def prepare_operator_revealed_order_movement(
    stealth_order_id: _StealthId,
    body: OperatorRevealedOrderMovePlanRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["prepare_revealed_order_move"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _require_move_permissions(actor)
    return _handle(
        lambda: service.prepare_plan(
            stealth_order_id=stealth_order_id,
            body=body,
            actor_id=actor.actor_id,
            roles=_roles(actor),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
        )
    )


@router.post(
    "/movement-repricing/stealth/{stealth_order_id}/execute-move",
    response_model=OperatorRevealedOrderMovementResponse,
    responses=_RESPONSES,
    summary="Execute one exact Cancel then replacement Create",
)
def execute_operator_revealed_order_movement(
    stealth_order_id: _StealthId,
    body: OperatorRevealedOrderMoveExecuteRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["execute_revealed_order_cancel_then_replace"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _require_move_permissions(actor)
    return _handle(
        lambda: service.execute_move(
            stealth_order_id=stealth_order_id,
            body=body,
            actor_id=actor.actor_id,
            roles=_roles(actor),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
        )
    )
