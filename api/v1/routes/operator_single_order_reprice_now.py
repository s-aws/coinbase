"""Authenticated call-free Goal 15 single-order Reprice Now routes."""

from __future__ import annotations

import os
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowExecuteRequest,
    OperatorSingleOrderRepriceNowIntentRequest,
    OperatorSingleOrderRepriceNowReadback,
)
from application.admin_api.operator_single_order_reprice_now_policy import (
    OperatorSingleOrderRepriceNowPolicyError,
)
from application.admin_api.operator_single_order_reprice_now_runtime import (
    get_operator_single_order_reprice_now_source_resolver,
)
from application.admin_api.operator_single_order_reprice_now_service import (
    OperatorSingleOrderRepriceNowCommandContext,
    OperatorSingleOrderRepriceNowConflict,
    OperatorSingleOrderRepriceNowError,
    OperatorSingleOrderRepriceNowService,
)
from core.enums import AdminApiPermission
from database.operator_single_order_reprice_now import (
    OperatorSingleOrderRepriceNowConflict as RepositoryConflict,
    OperatorSingleOrderRepriceNowError as RepositoryError,
    get_default_operator_single_order_reprice_now_repository,
)
from database.operator_stealth_definition import (
    get_default_operator_stealth_definition_repository,
)


OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"
_SAFE_CODE = re.compile(r"^operator_reprice_now_[a-z0-9_]{1,75}$")
_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    409: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def require_operator_single_order_reprice_now_enabled() -> None:
    if (
        os.environ.get(OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV)
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_reprice_now_disabled",
        )


router = APIRouter(
    dependencies=[
        Depends(require_operator_single_order_reprice_now_enabled)
    ]
)
_StealthId = Annotated[str, Path(pattern=_UUID)]
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


def get_operator_single_order_reprice_now_service(
) -> OperatorSingleOrderRepriceNowService:
    try:
        return OperatorSingleOrderRepriceNowService(
            definition_repository=(
                get_default_operator_stealth_definition_repository()
            ),
            repository=(
                get_default_operator_single_order_reprice_now_repository()
            ),
            source_resolver=(
                get_operator_single_order_reprice_now_source_resolver()
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_reprice_now_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorSingleOrderRepriceNowService,
    Depends(get_operator_single_order_reprice_now_service),
]


def _roles(actor: AdminApiActor) -> tuple[str, ...]:
    return tuple(
        str(getattr(role, "value", role))
        for role in sorted(actor.roles, key=str)
    )


def _can_prepare(actor: AdminApiActor) -> bool:
    return actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CANCEL,
    ) and actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CREATE,
    )


def _require_reprice_permissions(actor: AdminApiActor) -> None:
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    require_permission(actor, AdminApiPermission.ORDER_CREATE)


def _safe_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code) is not None:
        return code
    return "operator_reprice_now_unknown"


def _handle(
    operation,
    *,
    correlation_id: str | None = None,
) -> JSONResponse:
    try:
        response = operation()
    except (
        OperatorSingleOrderRepriceNowConflict,
        RepositoryConflict,
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
    except (
        OperatorSingleOrderRepriceNowError,
        OperatorSingleOrderRepriceNowPolicyError,
        RepositoryError,
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
            detail="operator_reprice_now_unknown",
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


_BASE_PATH = (
    "/movement-repricing/stealth/{stealth_order_id}"
    "/placements/{client_order_id}"
)


@router.get(
    f"{_BASE_PATH}/reprice-now",
    response_model=OperatorSingleOrderRepriceNowReadback,
    responses=_RESPONSES,
    summary="Review one call-free exact Reprice Now intent",
)
def get_single_order_reprice_now(
    stealth_order_id: _StealthId,
    client_order_id: _SourceId,
    actor: _Actor,
    service: _Service,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.get_single_order_reprice_now(
            stealth_order_id=stealth_order_id,
            source_client_order_id=client_order_id,
            allow_prepare=_can_prepare(actor),
        )
    )


@router.post(
    f"{_BASE_PATH}/reprice-now-intents",
    response_model=OperatorSingleOrderRepriceNowReadback,
    responses=_RESPONSES,
    summary="Persist one immutable local Reprice Now intent",
)
def prepare_reprice_now_intent(
    stealth_order_id: _StealthId,
    client_order_id: _SourceId,
    body: OperatorSingleOrderRepriceNowIntentRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["prepare_single_order_reprice_now"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _require_reprice_permissions(actor)
    return _handle(
        lambda: service.prepare_reprice_now_intent(
            stealth_order_id=stealth_order_id,
            source_client_order_id=client_order_id,
            body=body,
            context=OperatorSingleOrderRepriceNowCommandContext(
                actor_id=actor.actor_id,
                roles=_roles(actor),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operator_intent=operator_intent,
            ),
        ),
        correlation_id=correlation_id,
    )


@router.post(
    f"{_BASE_PATH}/execute-reprice-now",
    response_model=OperatorSingleOrderRepriceNowReadback,
    responses=_RESPONSES,
    summary="Fail closed until exact Reprice Now live terms are authorized",
)
def execute_reprice_now(
    stealth_order_id: _StealthId,
    client_order_id: _SourceId,
    body: OperatorSingleOrderRepriceNowExecuteRequest,
    actor: _Actor,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["execute_single_order_reprice_now"],
        Header(alias="X-Operator-Intent"),
    ],
) -> None:
    _ = (
        stealth_order_id,
        client_order_id,
        body,
        idempotency_key,
        operator_intent,
    )
    _require_reprice_permissions(actor)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="operator_reprice_now_live_authority_terms_incomplete",
        headers={"X-Correlation-Id": correlation_id},
    )


__all__ = [
    "OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV",
    "get_operator_single_order_reprice_now_service",
    "require_operator_single_order_reprice_now_enabled",
    "router",
]
