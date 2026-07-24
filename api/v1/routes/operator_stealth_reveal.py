"""Authenticated operator reveal and exact-closeout routes."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_stealth_reveal_runtime import (
    get_operator_stealth_reveal_runtime,
)
from application.admin_api.operator_stealth_reveal_service import (
    OperatorStealthCloseoutRequest,
    OperatorStealthResumeAcceptedCreateRequest,
    OperatorStealthRevealExecutionResponse,
    OperatorStealthRevealRequest,
    OperatorStealthRevealService,
    safe_operator_stealth_reveal_code,
)
from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)
from core.enums import AdminApiPermission
from database.operator_stealth_definition import (
    get_default_operator_stealth_definition_repository,
)
from database.operator_stealth_reveal import (
    OperatorStealthRevealConflict,
    OperatorStealthRevealError,
    get_default_operator_stealth_reveal_repository,
)


OPERATOR_STEALTH_REVEAL_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_STEALTH_REVEAL_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"


def require_operator_stealth_reveal_enabled() -> None:
    if os.environ.get(OPERATOR_STEALTH_REVEAL_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_stealth_reveal_disabled",
        )


router = APIRouter(
    dependencies=[Depends(require_operator_stealth_reveal_enabled)]
)
_DefinitionId = Annotated[str, Path(pattern=_UUID)]
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


def get_operator_stealth_reveal_service() -> OperatorStealthRevealService:
    try:
        runtime = get_operator_stealth_reveal_runtime()
        portfolio_id = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip()
        portfolio_label = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL") or "Test"
        ).strip()

        return OperatorStealthRevealService(
            definition_repository=(
                get_default_operator_stealth_definition_repository()
            ),
            reveal_repository=(
                get_default_operator_stealth_reveal_repository()
            ),
            runtime=runtime,
            configured_portfolio_id=portfolio_id,
            configured_portfolio_label=portfolio_label,
            execution_authority_checker=(
                coinbase_execution_authority_enabled
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_stealth_reveal_service_unavailable",
        ) from None


def get_operator_stealth_reveal_read_service() -> OperatorStealthRevealService:
    try:
        portfolio_id = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip()
        return OperatorStealthRevealService(
            definition_repository=(
                get_default_operator_stealth_definition_repository()
            ),
            reveal_repository=(
                get_default_operator_stealth_reveal_repository()
            ),
            runtime=None,
            configured_portfolio_id=portfolio_id,
            configured_portfolio_label="Test",
            execution_authority_checker=(
                coinbase_execution_authority_enabled
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_stealth_reveal_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorStealthRevealService,
    Depends(get_operator_stealth_reveal_service),
]
_ReadService = Annotated[
    OperatorStealthRevealService,
    Depends(get_operator_stealth_reveal_read_service),
]


def _roles(actor: AdminApiActor) -> list[str]:
    return [
        str(getattr(role, "value", role))
        for role in sorted(actor.roles, key=str)
    ]


def _handle(operation):
    try:
        response = operation()
    except OperatorStealthRevealConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=safe_operator_stealth_reveal_code(exc),
        ) from None
    except OperatorStealthRevealError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=safe_operator_stealth_reveal_code(exc),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_stealth_unknown",
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


@router.get(
    "/stealth/definitions/{definition_id}/execution",
    response_model=OperatorStealthRevealExecutionResponse,
    responses=_RESPONSES,
    summary="Review one operator stealth reveal and exact-closeout state",
)
def get_operator_stealth_reveal_execution(
    definition_id: _DefinitionId,
    actor: _Actor,
    service: _ReadService,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.get_execution(
            definition_id,
            roles=_roles(actor),
        )
    )


@router.post(
    "/stealth/definitions/{definition_id}/reveal",
    response_model=OperatorStealthRevealExecutionResponse,
    responses=_RESPONSES,
    summary="Preview and reveal one exact operator stealth definition",
)
def reveal_operator_stealth_definition(
    definition_id: _DefinitionId,
    body: OperatorStealthRevealRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["reveal_operator_stealth_definition"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    return _handle(
        lambda: service.reveal(
            definition_id=definition_id,
            body=body,
            actor_id=actor.actor_id,
            roles=_roles(actor),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/stealth/definitions/{definition_id}/resume-accepted-create",
    response_model=OperatorStealthRevealExecutionResponse,
    responses=_RESPONSES,
    summary="Resume one durable Preview-accepted stealth Create",
)
def resume_operator_stealth_accepted_create(
    definition_id: _DefinitionId,
    body: OperatorStealthResumeAcceptedCreateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["resume_operator_stealth_accepted_create"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    return _handle(
        lambda: service.resume_accepted_create(
            definition_id=definition_id,
            body=body,
            actor_id=actor.actor_id,
            roles=_roles(actor),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/stealth/definitions/{definition_id}/closeout",
    response_model=OperatorStealthRevealExecutionResponse,
    responses=_RESPONSES,
    summary="Safely close out the exact operator stealth placement",
)
def closeout_operator_stealth_placement(
    definition_id: _DefinitionId,
    body: OperatorStealthCloseoutRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["closeout_operator_stealth_placement"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    return _handle(
        lambda: service.closeout(
            definition_id=definition_id,
            body=body,
            actor_id=actor.actor_id,
            roles=_roles(actor),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )
