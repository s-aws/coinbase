"""Authenticated local parent-strategy administration routes."""

from __future__ import annotations

import os
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
)
from application.admin_api.operator_parent_strategy_service import (
    OperatorParentStrategyService,
    ParentStrategyCreateRequest,
    ParentStrategyDeactivateRequest,
    ParentStrategyDeleteRequest,
    ParentStrategyDetailResponse,
    ParentStrategyEditRequest,
    ParentStrategyListResponse,
    ParentStrategyMutationResponse,
    safe_parent_strategy_code,
)
from core.enums import AdminApiPermission
from database.operator_parent_strategy import (
    get_default_operator_parent_strategy_repository,
)


OPERATOR_PARENT_STRATEGIES_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_PARENT_STRATEGIES_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"


def require_operator_parent_strategies_enabled() -> None:
    if os.environ.get(OPERATOR_PARENT_STRATEGIES_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_parent_strategies_disabled",
        )


router = APIRouter(
    dependencies=[Depends(require_operator_parent_strategies_enabled)]
)

_READ_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    404: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}
_MUTATION_RESPONSES = {
    **_READ_RESPONSES,
    400: {"model": ParentStrategyMutationResponse},
    409: {"model": ParentStrategyMutationResponse},
}
_StrategyId = Annotated[str, Path(pattern=_UUID)]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
]
_CorrelationId = Annotated[
    str,
    Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
]


def get_operator_parent_strategy_service(
) -> OperatorParentStrategyService:
    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    try:
        return OperatorParentStrategyService(
            repository=(
                get_default_operator_parent_strategy_repository()
            ),
            configured_spot_portfolio_id=portfolio_id,
        )
    except OperatorParentStrategyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=safe_parent_strategy_code(exc.code),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="parent_strategy_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorParentStrategyService,
    Depends(get_operator_parent_strategy_service),
]


@router.get(
    "/parent-strategies",
    response_model=ParentStrategyListResponse,
    responses=_READ_RESPONSES,
    summary="List backend-owned parent-strategy definitions",
)
def list_operator_parent_strategies(
    actor: _Actor,
    service: _Service,
    lifecycle_state: Annotated[
        Literal["ACTIVE", "DEACTIVATED", "DELETED"] | None,
        Query(),
    ] = None,
    product_id: Annotated[
        str | None,
        Query(pattern=_PRODUCT_ID),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    command_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    command_offset: Annotated[int, Query(ge=0)] = 0,
) -> ParentStrategyListResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return service.list_strategies(
        lifecycle_state=lifecycle_state,
        product_id=product_id,
        limit=limit,
        offset=offset,
        command_limit=command_limit,
        command_offset=command_offset,
    )


@router.get(
    "/parent-strategies/{strategy_id}",
    response_model=ParentStrategyDetailResponse,
    responses=_READ_RESPONSES,
    summary="Review one parent strategy and its local audit events",
)
def get_operator_parent_strategy(
    strategy_id: _StrategyId,
    actor: _Actor,
    service: _Service,
    event_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    event_offset: Annotated[int, Query(ge=0)] = 0,
) -> ParentStrategyDetailResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        return service.get_strategy(
            strategy_id=strategy_id,
            event_limit=event_limit,
            event_offset=event_offset,
        )
    except OperatorParentStrategyError as exc:
        code = safe_parent_strategy_code(exc.code)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if code == "parent_strategy_not_found"
                else status.HTTP_409_CONFLICT
            ),
            detail=code,
        ) from None


def _execute(
    *,
    actor: AdminApiActor,
    service_method: Literal[
        "create_strategy",
        "edit_strategy",
        "deactivate_strategy",
        "delete_strategy",
    ],
    correlation_id: str,
    idempotency_key: str,
    operation: Callable[[], ParentStrategyMutationResponse],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CONFIG_UPDATE)
    try:
        response = operation()
    except OperatorParentStrategyError as exc:
        code = safe_parent_strategy_code(exc.code)
        is_conflict = any(
            token in code
            for token in (
                "conflict",
                "blocked",
                "not_found",
                "deleted",
                "not_enabled",
            )
        )
        response = ParentStrategyMutationResponse(
            status="conflict" if is_conflict else "rejected",
            message=code,
            service_method=service_method,
            strategy=None,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=False,
        )
    return JSONResponse(
        status_code=(
            status.HTTP_409_CONFLICT
            if response.status == "conflict"
            else status.HTTP_400_BAD_REQUEST
            if response.status == "rejected"
            else status.HTTP_200_OK
        ),
        content=response.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id},
    )


@router.post(
    "/parent-strategies",
    response_model=ParentStrategyMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Create one active local parent-strategy definition",
)
def create_operator_parent_strategy(
    body: ParentStrategyCreateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["create_parent_strategy"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="create_strategy",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.create_strategy(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/parent-strategies/{strategy_id}/edit",
    response_model=ParentStrategyMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Edit one exact parent-strategy revision",
)
def edit_operator_parent_strategy(
    strategy_id: _StrategyId,
    body: ParentStrategyEditRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["edit_parent_strategy"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="edit_strategy",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.edit_strategy(
            strategy_id=strategy_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/parent-strategies/{strategy_id}/deactivate",
    response_model=ParentStrategyMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Deactivate one exact parent-strategy revision",
)
def deactivate_operator_parent_strategy(
    strategy_id: _StrategyId,
    body: ParentStrategyDeactivateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["deactivate_parent_strategy"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="deactivate_strategy",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.deactivate_strategy(
            strategy_id=strategy_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/parent-strategies/{strategy_id}/delete",
    response_model=ParentStrategyMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Tombstone one deactivated dependency-free parent strategy",
)
def delete_operator_parent_strategy(
    strategy_id: _StrategyId,
    body: ParentStrategyDeleteRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["delete_parent_strategy"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="delete_strategy",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.delete_strategy(
            strategy_id=strategy_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )
