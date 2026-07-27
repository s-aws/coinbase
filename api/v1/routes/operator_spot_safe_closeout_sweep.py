"""Authenticated local-only Goal 16 Spot safe-closeout sweep routes."""

from __future__ import annotations

import os
import re
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    status,
)
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_spot_safe_closeout_sweep_models import (
    LIVE_AUTHORITY_BLOCKER,
    OperatorSpotSafeCloseoutCandidatePage,
    OperatorSpotSafeCloseoutSweepActionRequest,
    OperatorSpotSafeCloseoutSweepAdvanceRequest,
    OperatorSpotSafeCloseoutSweepCreateRequest,
    OperatorSpotSafeCloseoutSweepReadback,
)
from application.admin_api.operator_spot_safe_closeout_sweep_policy import (
    OperatorSpotSafeCloseoutSweepPolicyError,
)
from application.admin_api.operator_spot_safe_closeout_sweep_runtime import (
    get_default_operator_spot_safe_closeout_sweep_service,
)
from application.admin_api.operator_spot_safe_closeout_sweep_service import (
    OperatorSpotSafeCloseoutSweepCommandContext,
    OperatorSpotSafeCloseoutSweepConflict,
    OperatorSpotSafeCloseoutSweepError,
    OperatorSpotSafeCloseoutSweepService,
)
from core.enums import AdminApiPermission
from database.operator_spot_safe_closeout_sweep import (
    OperatorSpotSafeCloseoutSweepConflict as RepositoryConflict,
    OperatorSpotSafeCloseoutSweepError as RepositoryError,
)


OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"
_SAFE_CODE = re.compile(r"^operator_spot_sweep_[a-z0-9_]{1,75}$")
_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    409: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def require_operator_spot_safe_closeout_sweep_enabled() -> None:
    if (
        os.environ.get(
            OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED_ENV
        )
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_spot_sweep_disabled",
        )


router = APIRouter(
    dependencies=[
        Depends(require_operator_spot_safe_closeout_sweep_enabled)
    ]
)
_SweepId = Annotated[str, Path(pattern=_UUID)]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
]
_CorrelationId = Annotated[
    str,
    Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
]


def get_operator_spot_safe_closeout_sweep_service(
) -> OperatorSpotSafeCloseoutSweepService:
    try:
        return get_default_operator_spot_safe_closeout_sweep_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_spot_sweep_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorSpotSafeCloseoutSweepService,
    Depends(get_operator_spot_safe_closeout_sweep_service),
]


def _roles(actor: AdminApiActor) -> tuple[str, ...]:
    return tuple(
        str(getattr(role, "value", role))
        for role in sorted(actor.roles, key=str)
    )


def _can_mutate(actor: AdminApiActor) -> bool:
    return actor_has_permission(
        actor,
        AdminApiPermission.SPOT_SWEEP_EXECUTE,
    ) and actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CANCEL,
    )


def _require_mutation_permissions(actor: AdminApiActor) -> None:
    require_permission(actor, AdminApiPermission.SPOT_SWEEP_EXECUTE)
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)


def _safe_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code) is not None:
        return code
    return "operator_spot_sweep_unknown"


def _handle(
    operation,
    *,
    correlation_id: str | None = None,
) -> JSONResponse:
    try:
        response = operation()
    except (
        OperatorSpotSafeCloseoutSweepConflict,
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
        OperatorSpotSafeCloseoutSweepError,
        OperatorSpotSafeCloseoutSweepPolicyError,
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
            detail="operator_spot_sweep_unknown",
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


_BASE = "/spot/safe-closeout-sweeps"


@router.get(
    f"{_BASE}/candidates",
    response_model=OperatorSpotSafeCloseoutCandidatePage,
    responses=_RESPONSES,
    summary="List call-free canonical Spot closeout candidates",
)
def list_safe_closeout_candidates(
    actor: _Actor,
    service: _Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[
        Literal["PENDING", "OPEN", "QUEUED"] | None,
        Query(alias="status"),
    ] = None,
    ownership_provenance_filter: Annotated[
        Literal[
            "ADMIN_FILL_FOLLOW_UP",
            "ADMIN_HOTPOINT_CHILD",
        ]
        | None,
        Query(alias="ownership_provenance"),
    ] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.list_safe_closeout_candidates(
            limit=limit,
            offset=offset,
            status_filter=status_filter,
            ownership_provenance_filter=(
                ownership_provenance_filter
            ),
            can_mutate=_can_mutate(actor),
        )
    )


@router.post(
    _BASE,
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Persist one immutable max-three Cancel-only sweep",
)
def create_safe_closeout_sweep(
    body: OperatorSpotSafeCloseoutSweepCreateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["create_operator_spot_safe_closeout_sweep"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _require_mutation_permissions(actor)
    return _handle(
        lambda: service.create_safe_closeout_sweep(
            body=body,
            context=OperatorSpotSafeCloseoutSweepCommandContext(
                actor_id=actor.actor_id,
                roles=_roles(actor),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operator_intent=operator_intent,
            ),
        ),
        correlation_id=correlation_id,
    )


@router.get(
    f"{_BASE}/current",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Read the call-free goal-global current closeout sweep",
)
def get_current_safe_closeout_sweep(
    actor: _Actor,
    service: _Service,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.get_current_safe_closeout_sweep(
            can_mutate=_can_mutate(actor),
        )
    )


@router.get(
    f"{_BASE}/{{sweep_id}}",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Read one local Spot safe-closeout sweep",
)
def get_safe_closeout_sweep(
    sweep_id: _SweepId,
    actor: _Actor,
    service: _Service,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _handle(
        lambda: service.get_safe_closeout_sweep(
            sweep_id=sweep_id,
            can_mutate=_can_mutate(actor),
        )
    )


def _local_action(
    *,
    action: str,
    sweep_id: str,
    body: OperatorSpotSafeCloseoutSweepActionRequest,
    actor: AdminApiActor,
    service: OperatorSpotSafeCloseoutSweepService,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> JSONResponse:
    _require_mutation_permissions(actor)
    method = {
        "PAUSE": service.pause_safe_closeout_sweep,
        "RESUME": service.resume_safe_closeout_sweep,
        "ABORT": service.abort_safe_closeout_sweep,
    }[action]
    return _handle(
        lambda: method(
            sweep_id=sweep_id,
            body=body,
            context=OperatorSpotSafeCloseoutSweepCommandContext(
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
    f"{_BASE}/{{sweep_id}}/pause",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Pause one local Spot safe-closeout sweep",
)
def pause_safe_closeout_sweep(
    sweep_id: _SweepId,
    body: OperatorSpotSafeCloseoutSweepActionRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["pause_operator_spot_safe_closeout_sweep"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    return _local_action(
        action="PAUSE",
        sweep_id=sweep_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    f"{_BASE}/{{sweep_id}}/resume",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Resume one paused local Spot safe-closeout sweep",
)
def resume_safe_closeout_sweep(
    sweep_id: _SweepId,
    body: OperatorSpotSafeCloseoutSweepActionRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["resume_operator_spot_safe_closeout_sweep"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    return _local_action(
        action="RESUME",
        sweep_id=sweep_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    f"{_BASE}/{{sweep_id}}/abort",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Abort one local Spot safe-closeout sweep",
)
def abort_safe_closeout_sweep(
    sweep_id: _SweepId,
    body: OperatorSpotSafeCloseoutSweepActionRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["abort_operator_spot_safe_closeout_sweep"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    return _local_action(
        action="ABORT",
        sweep_id=sweep_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    f"{_BASE}/{{sweep_id}}/advance",
    response_model=OperatorSpotSafeCloseoutSweepReadback,
    responses=_RESPONSES,
    summary="Fail closed before any Goal 16 live-read dependency",
)
def advance_safe_closeout_sweep(
    sweep_id: _SweepId,
    body: OperatorSpotSafeCloseoutSweepAdvanceRequest,
    actor: _Actor,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["advance_operator_spot_safe_closeout_sweep"],
        Header(alias="X-Operator-Intent"),
    ],
) -> None:
    _ = (sweep_id, body, idempotency_key, operator_intent)
    _require_mutation_permissions(actor)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=LIVE_AUTHORITY_BLOCKER,
        headers={"X-Correlation-Id": correlation_id},
    )


__all__ = [
    "OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED_ENV",
    "OperatorSpotSafeCloseoutCandidatePage",
    "get_operator_spot_safe_closeout_sweep_service",
    "require_operator_spot_safe_closeout_sweep_enabled",
    "router",
]
