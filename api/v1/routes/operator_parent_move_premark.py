"""Authenticated call-free Goal 14 parent-move premark routes."""

from __future__ import annotations

import os
import re
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_parent_move_premark_models import (
    OperatorParentMoveExecuteRequest,
    OperatorParentMovePremarkPlanRequest,
    OperatorParentMovePremarkReadback,
    OperatorParentMoveSafeCloseoutRequest,
)
from application.admin_api.operator_parent_move_premark_policy import (
    ParentMovePremarkPolicyError,
)
from application.admin_api.operator_parent_move_premark_runtime import (
    OperatorParentMovePremarkApiService,
    get_default_operator_parent_move_premark_api_service,
)
from application.admin_api.operator_parent_move_premark_service import (
    OperatorParentMoveServiceError,
    ParentMoveCommandContext,
    ParentMovePremarkRequest,
)
from core.enums import AdminApiPermission
from database.operator_parent_move_premark import (
    OperatorParentMovePremarkConflict,
    OperatorParentMovePremarkError,
)


OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_PARENT_MOVE_PREMARK_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"
_SAFE_CODE = re.compile(r"^operator_parent_move_[a-z0-9_]{1,75}$")
_AUDIT_NAMESPACE = UUID("94af371a-ca1d-4a28-a8be-4b99349581a0")
_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    409: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def require_operator_parent_move_premark_enabled() -> None:
    if os.environ.get(OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_parent_move_premark_disabled",
        )


router = APIRouter(
    dependencies=[Depends(require_operator_parent_move_premark_enabled)]
)
_SourceId = Annotated[str, Path(pattern=_UUID)]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
]
_CorrelationId = Annotated[
    str,
    Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
]


def get_operator_parent_move_premark_api_service(
) -> OperatorParentMovePremarkApiService:
    try:
        return get_default_operator_parent_move_premark_api_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_parent_move_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorParentMovePremarkApiService,
    Depends(get_operator_parent_move_premark_api_service),
]


def _roles(actor: AdminApiActor) -> tuple[str, ...]:
    return tuple(
        str(getattr(role, "value", role))
        for role in sorted(actor.roles, key=str)
    )


def _can_premark(actor: AdminApiActor) -> bool:
    return actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CANCEL,
    ) and actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CREATE,
    )


def _require_premark_permissions(actor: AdminApiActor) -> None:
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    require_permission(actor, AdminApiPermission.ORDER_CREATE)


def _safe_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code) is not None:
        return code
    return "operator_parent_move_unknown"


def _handle(
    operation,
    *,
    correlation_id: str | None = None,
) -> JSONResponse:
    try:
        response = operation()
    except OperatorParentMovePremarkConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_safe_code(exc),
            headers=(
                {"X-Correlation-Id": correlation_id}
                if correlation_id is not None
                else None
            ),
        ) from None
    except (
        OperatorParentMovePremarkError,
        OperatorParentMoveServiceError,
        ParentMovePremarkPolicyError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_safe_code(exc),
            headers=(
                {"X-Correlation-Id": correlation_id}
                if correlation_id is not None
                else None
            ),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_parent_move_unknown",
            headers=(
                {"X-Correlation-Id": correlation_id}
                if correlation_id is not None
                else None
            ),
        ) from None
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response.model_dump(mode="json"),
        headers=(
            {"X-Correlation-Id": correlation_id}
            if correlation_id is not None
            else {}
        ),
    )


@router.get(
    "/movement-repricing/orders/{client_order_id}/parent-move",
    response_model=OperatorParentMovePremarkReadback,
    responses=_RESPONSES,
    summary="Review one call-free direct-parent move lifecycle",
)
def get_operator_parent_move_premark(
    client_order_id: _SourceId,
    actor: _Actor,
    service: _Service,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.readback(
            client_order_id,
            allow_premark=_can_premark(actor),
        )
    )


@router.post(
    "/movement-repricing/orders/{client_order_id}/parent-move-plans",
    response_model=OperatorParentMovePremarkReadback,
    responses=_RESPONSES,
    summary="Persist one immutable local direct-parent move premark",
)
def premark_operator_parent_move(
    client_order_id: _SourceId,
    body: OperatorParentMovePremarkPlanRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["premark_parent_move"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _require_premark_permissions(actor)
    context = ParentMoveCommandContext(
        actor_id=actor.actor_id,
        roles=_roles(actor),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(
            uuid5(
                _AUDIT_NAMESPACE,
                (
                    "operator_parent_move_premark_lifecycle_v1:"
                    f"{idempotency_key}"
                ),
            )
        ),
        operator_intent=operator_intent,
    )
    request = ParentMovePremarkRequest(
        source_client_order_id=client_order_id,
        requested_limit_price=body.requested_limit_price,
        operator_reason=body.operator_reason,
        confirm_premark=body.confirm_premark,
    )
    return _handle(
        lambda: service.premark(
            context=context,
            request=request,
            allow_premark=True,
        ),
        correlation_id=correlation_id,
    )


def _reject_live_parent_move(
    *,
    actor: AdminApiActor,
    correlation_id: str,
) -> None:
    _require_premark_permissions(actor)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="operator_parent_move_live_authority_terms_incomplete",
        headers={"X-Correlation-Id": correlation_id},
    )


@router.post(
    "/movement-repricing/orders/{client_order_id}/execute-parent-move",
    response_model=OperatorParentMovePremarkReadback,
    responses=_RESPONSES,
    summary="Fail closed until exact parent-move live terms are authorized",
)
def execute_operator_parent_move(
    client_order_id: _SourceId,
    body: OperatorParentMoveExecuteRequest,
    actor: _Actor,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["execute_parent_move"],
        Header(alias="X-Operator-Intent"),
    ],
) -> None:
    _ = (client_order_id, body, idempotency_key, operator_intent)
    _reject_live_parent_move(
        actor=actor,
        correlation_id=correlation_id,
    )


@router.post(
    (
        "/movement-repricing/orders/{client_order_id}"
        "/parent-move-safe-closeout"
    ),
    response_model=OperatorParentMovePremarkReadback,
    responses=_RESPONSES,
    summary="Fail closed until exact successor closeout terms are authorized",
)
def safe_closeout_operator_parent_move(
    client_order_id: _SourceId,
    body: OperatorParentMoveSafeCloseoutRequest,
    actor: _Actor,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["safe_closeout_parent_move_successor"],
        Header(alias="X-Operator-Intent"),
    ],
) -> None:
    _ = (client_order_id, body, idempotency_key, operator_intent)
    _reject_live_parent_move(
        actor=actor,
        correlation_id=correlation_id,
    )


__all__ = [
    "OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV",
    "get_operator_parent_move_premark_api_service",
    "require_operator_parent_move_premark_enabled",
    "router",
]
