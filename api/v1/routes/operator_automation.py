"""Authenticated, PostgreSQL-backed operator automation control plane.

All routes in this module are local control-plane operations.  They do not
construct an exchange client or dispatch a domain job.  The one-shot route
durably records a blocked adapter-readiness result only.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.automation_models import (
    AutomationControlAction,
    AutomationControlEventListResponse,
    AutomationControlMutationResponse,
    AutomationControlPlaneItem,
    AutomationControlPlaneResponse,
    AutomationControlRequest,
    AutomationDefinitionCreateRequest,
    AutomationDefinitionDetailResponse,
    AutomationDefinitionEventListResponse,
    AutomationDefinitionLifecycleAction,
    AutomationDefinitionLifecycleRequest,
    AutomationDefinitionItem,
    AutomationDefinitionListResponse,
    AutomationDefinitionMutationResponse,
    AutomationDefinitionScheduleRequest,
    AutomationDefinitionState,
    AutomationDomain,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationOneShotRunRequest,
    AutomationRunDetailResponse,
    AutomationRunEventListResponse,
    AutomationRunListResponse,
    AutomationRunMutationResponse,
    AutomationRunState,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_automation import (
    OperatorAutomationError,
    OperatorAutomationService,
    get_default_operator_automation_service,
)
from core.enums import AdminApiPermission


OPERATOR_AUTOMATION_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED"
)
OPERATOR_AUTOMATION_DISABLED = "operator_automation_disabled"
_VISIBLE_ASCII_PATTERN = r"^[\x21-\x7e]+$"
_CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_DEFINITION_QUERY_KEYS = frozenset(
    {"domain", "job_kind", "lifecycle_state", "limit", "offset"}
)
_RUN_QUERY_KEYS = frozenset({"definition_id", "state", "limit", "offset"})
_EVENT_QUERY_KEYS = frozenset({"limit", "offset"})


def require_operator_automation_enabled() -> None:
    """Require the exact opt-in; truthy aliases intentionally do not enable it."""

    if os.environ.get(OPERATOR_AUTOMATION_ENABLED_ENV) != "1":
        raise HTTPException(status_code=503, detail=OPERATOR_AUTOMATION_DISABLED)


router = APIRouter(dependencies=[Depends(require_operator_automation_enabled)])


_READ_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    404: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}
_MUTATION_RESPONSES = {
    **_READ_RESPONSES,
    409: {"model": AdminApiErrorResponse},
}

_EntityId = Annotated[
    str,
    Path(min_length=36, max_length=36, pattern=_CANONICAL_UUID_PATTERN),
]
_IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    ),
]
_CorrelationId = Annotated[
    str,
    Header(
        alias="X-Correlation-Id",
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    ),
]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_CreateIntent = Annotated[
    Literal["create_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_EnableIntent = Annotated[
    Literal["enable_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_DisableIntent = Annotated[
    Literal["disable_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_PauseDefinitionIntent = Annotated[
    Literal["pause_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_ResumeDefinitionIntent = Annotated[
    Literal["resume_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_DrainDefinitionIntent = Annotated[
    Literal["drain_automation_definition"],
    Header(alias="X-Operator-Intent"),
]
_SetScheduleIntent = Annotated[
    Literal["set_automation_definition_schedule"],
    Header(alias="X-Operator-Intent"),
]
_ClearScheduleIntent = Annotated[
    Literal["clear_automation_definition_schedule"],
    Header(alias="X-Operator-Intent"),
]
_PauseControlIntent = Annotated[
    Literal["pause_automation_control_plane"],
    Header(alias="X-Operator-Intent"),
]
_ResumeControlIntent = Annotated[
    Literal["resume_automation_control_plane"],
    Header(alias="X-Operator-Intent"),
]
_DrainControlIntent = Annotated[
    Literal["drain_automation_control_plane"],
    Header(alias="X-Operator-Intent"),
]
_ShutdownControlIntent = Annotated[
    Literal["shutdown_automation_control_plane"],
    Header(alias="X-Operator-Intent"),
]
_ClaimRunIntent = Annotated[
    Literal["claim_automation_one_shot_run"],
    Header(alias="X-Operator-Intent"),
]


def get_operator_automation_service() -> OperatorAutomationService:
    """Resolve only the local durable repository and sanitize failures."""

    try:
        return get_default_operator_automation_service()
    except OperatorAutomationError as exc:
        raise HTTPException(
            status_code=exc.http_status_code,
            detail=exc.code,
        ) from None
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="automation_control_plane_unavailable",
        ) from None


_Service = Annotated[
    OperatorAutomationService,
    Depends(get_operator_automation_service),
]


def _require_query_shape(request: Request, allowed: frozenset[str]) -> None:
    keys = [key for key, _value in request.query_params.multi_items()]
    if any(key not in allowed for key in keys):
        raise HTTPException(
            status_code=422,
            detail="automation_query_parameter_unknown",
        )
    if any(keys.count(key) != 1 for key in set(keys)):
        raise HTTPException(
            status_code=422,
            detail="automation_query_parameter_duplicate",
        )


def _scope_definition_item(
    item: AutomationDefinitionItem,
    actor: AdminApiActor,
) -> AutomationDefinitionItem:
    can_configure = actor_has_permission(
        actor, AdminApiPermission.AUTOMATION_CONFIGURE
    )
    can_trigger = actor_has_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    allowed_actions = [
        action
        for action in item.allowed_actions
        if (action == "RUN_ONCE" and can_trigger)
        or (action != "RUN_ONCE" and can_configure)
    ]
    return item.model_copy(update={"allowed_actions": allowed_actions})


def _scope_control_item(
    item: AutomationControlPlaneItem,
    actor: AdminApiActor,
) -> AutomationControlPlaneItem:
    can_control = actor_has_permission(actor, AdminApiPermission.AUTOMATION_CONTROL)
    can_resume = actor_has_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
    return item.model_copy(
        update={
            "definition_create_allowed": actor_has_permission(
                actor, AdminApiPermission.AUTOMATION_CONFIGURE
            ),
            "allowed_actions": [
                action
                for action in item.allowed_actions
                if (action == "RESUME" and can_resume)
                or (action != "RESUME" and can_control)
            ],
        }
    )


def _scope_payload_for_actor(payload: Any, actor: AdminApiActor) -> Any:
    if isinstance(payload, AutomationControlPlaneResponse):
        return payload.model_copy(
            update={"control_plane": _scope_control_item(payload.control_plane, actor)}
        )
    if isinstance(payload, AutomationControlMutationResponse):
        return payload.model_copy(
            update={"control_plane": _scope_control_item(payload.control_plane, actor)}
        )
    if isinstance(payload, AutomationDefinitionDetailResponse):
        return payload.model_copy(
            update={"definition": _scope_definition_item(payload.definition, actor)}
        )
    if isinstance(payload, AutomationDefinitionMutationResponse):
        return payload.model_copy(
            update={"definition": _scope_definition_item(payload.definition, actor)}
        )
    if isinstance(payload, AutomationDefinitionListResponse):
        return payload.model_copy(
            update={
                "items": [
                    _scope_definition_item(item, actor) for item in payload.items
                ]
            }
        )
    return payload


def _read_result(
    operation: Callable[[], Any],
    *,
    actor: AdminApiActor,
) -> JSONResponse:
    try:
        payload = operation()
    except OperatorAutomationError as exc:
        raise HTTPException(
            status_code=exc.http_status_code,
            detail=exc.code,
        ) from None
    return JSONResponse(
        content=jsonable_encoder(_scope_payload_for_actor(payload, actor))
    )


def _mutation_result(
    operation: Callable[[], Any],
    *,
    actor: AdminApiActor,
) -> JSONResponse:
    try:
        payload = operation()
    except OperatorAutomationError as exc:
        raise HTTPException(
            status_code=exc.http_status_code,
            detail=exc.code,
        ) from None
    payload = _scope_payload_for_actor(payload, actor)
    headers = {"X-Correlation-Id": payload.correlation_id}
    if payload.replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(content=jsonable_encoder(payload), headers=headers)


def _context(
    *,
    actor: AdminApiActor,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> AutomationMutationContext:
    return AutomationMutationContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.get(
    "/automation/control-plane",
    response_model=AutomationControlPlaneResponse,
    responses=_READ_RESPONSES,
    operation_id="get_operator_automation_control_plane",
)
def get_control_plane(
    request: Request,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorAutomationService,
        Depends(get_operator_automation_service),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, frozenset())
    return _read_result(service.get_control_plane, actor=actor)


@router.get(
    "/automation/control-plane/events",
    response_model=AutomationControlEventListResponse,
    responses=_READ_RESPONSES,
    operation_id="list_operator_automation_control_events",
)
def list_control_events(
    request: Request,
    actor: _Actor,
    service: _Service,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, _EVENT_QUERY_KEYS)
    return _read_result(
        lambda: service.list_control_events(limit=limit, offset=offset),
        actor=actor,
    )


@router.get(
    "/automation/definitions",
    response_model=AutomationDefinitionListResponse,
    responses=_READ_RESPONSES,
    operation_id="list_operator_automation_definitions",
)
def list_definitions(
    request: Request,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorAutomationService,
        Depends(get_operator_automation_service),
    ],
    domain: AutomationDomain | None = None,
    job_kind: AutomationJobKind | None = None,
    lifecycle_state: AutomationDefinitionState | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, _DEFINITION_QUERY_KEYS)
    return _read_result(
        lambda: service.list_definitions(
            domain=domain,
            job_kind=job_kind,
            lifecycle_state=lifecycle_state,
            limit=limit,
            offset=offset,
        ),
        actor=actor,
    )


@router.get(
    "/automation/definitions/{definition_id}",
    response_model=AutomationDefinitionDetailResponse,
    responses=_READ_RESPONSES,
    operation_id="get_operator_automation_definition",
)
def get_definition(
    request: Request,
    definition_id: _EntityId,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorAutomationService,
        Depends(get_operator_automation_service),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, frozenset())
    return _read_result(
        lambda: service.get_definition(definition_id),
        actor=actor,
    )


@router.get(
    "/automation/definitions/{definition_id}/events",
    response_model=AutomationDefinitionEventListResponse,
    responses=_READ_RESPONSES,
    operation_id="list_operator_automation_definition_events",
)
def list_definition_events(
    request: Request,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, _EVENT_QUERY_KEYS)
    return _read_result(
        lambda: service.list_definition_events(
            definition_id=definition_id,
            limit=limit,
            offset=offset,
        ),
        actor=actor,
    )


@router.post(
    "/automation/definitions",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="create_operator_automation_definition",
)
def create_definition(
    body: AutomationDefinitionCreateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _CreateIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_CONFIGURE)
    context = _context(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    return _mutation_result(
        lambda: service.create_definition(body, context),
        actor=actor,
    )


def _definition_lifecycle(
    *,
    actor: AdminApiActor,
    service: OperatorAutomationService,
    definition_id: str,
    body: AutomationDefinitionLifecycleRequest,
    action: AutomationDefinitionLifecycleAction,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_CONFIGURE)
    return _mutation_result(
        lambda: service.transition_definition(
            definition_id=definition_id,
            action=action,
            request=body,
            context=_context(
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
        ),
        actor=actor,
    )


@router.post(
    "/automation/definitions/{definition_id}/enable",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="enable_operator_automation_definition",
)
def enable_definition(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _EnableIntent,
) -> JSONResponse:
    return _definition_lifecycle(
        actor=actor,
        service=service,
        definition_id=definition_id,
        body=body,
        action=AutomationDefinitionLifecycleAction.ENABLE,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/disable",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="disable_operator_automation_definition",
)
def disable_definition(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _DisableIntent,
) -> JSONResponse:
    return _definition_lifecycle(
        actor=actor,
        service=service,
        definition_id=definition_id,
        body=body,
        action=AutomationDefinitionLifecycleAction.DISABLE,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/pause",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="pause_operator_automation_definition",
)
def pause_definition(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _PauseDefinitionIntent,
) -> JSONResponse:
    return _definition_lifecycle(
        actor=actor,
        service=service,
        definition_id=definition_id,
        body=body,
        action=AutomationDefinitionLifecycleAction.PAUSE,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/resume",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="resume_operator_automation_definition",
)
def resume_definition(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _ResumeDefinitionIntent,
) -> JSONResponse:
    return _definition_lifecycle(
        actor=actor,
        service=service,
        definition_id=definition_id,
        body=body,
        action=AutomationDefinitionLifecycleAction.RESUME,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/drain",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="drain_operator_automation_definition",
)
def drain_definition(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _DrainDefinitionIntent,
) -> JSONResponse:
    return _definition_lifecycle(
        actor=actor,
        service=service,
        definition_id=definition_id,
        body=body,
        action=AutomationDefinitionLifecycleAction.DRAIN,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/schedule",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="set_operator_automation_definition_schedule",
)
def set_definition_schedule(
    body: AutomationDefinitionScheduleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _SetScheduleIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_CONFIGURE)
    return _mutation_result(
        lambda: service.set_definition_schedule(
            definition_id=definition_id,
            request=body,
            context=_context(
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
        ),
        actor=actor,
    )


@router.post(
    "/automation/definitions/{definition_id}/schedule/clear",
    response_model=AutomationDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="clear_operator_automation_definition_schedule",
)
def clear_definition_schedule(
    body: AutomationDefinitionLifecycleRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _ClearScheduleIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_CONFIGURE)
    return _mutation_result(
        lambda: service.clear_definition_schedule(
            definition_id=definition_id,
            request=body,
            context=_context(
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
        ),
        actor=actor,
    )


def _control_lifecycle(
    *,
    actor: AdminApiActor,
    service: OperatorAutomationService,
    body: AutomationControlRequest,
    action: AutomationControlAction,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> JSONResponse:
    require_permission(
        actor,
        (
            AdminApiPermission.AUTOMATION_RESUME
            if action is AutomationControlAction.RESUME
            else AdminApiPermission.AUTOMATION_CONTROL
        ),
    )
    return _mutation_result(
        lambda: service.transition_control_posture(
            action=action,
            request=body,
            context=_context(
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
        ),
        actor=actor,
    )


@router.post(
    "/automation/control-plane/pause",
    response_model=AutomationControlMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="pause_operator_automation_control_plane",
)
def pause_control_plane(
    body: AutomationControlRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _PauseControlIntent,
) -> JSONResponse:
    return _control_lifecycle(
        actor=actor,
        service=service,
        body=body,
        action=AutomationControlAction.PAUSE,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/control-plane/resume",
    response_model=AutomationControlMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="resume_operator_automation_control_plane",
)
def resume_control_plane(
    body: AutomationControlRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _ResumeControlIntent,
) -> JSONResponse:
    return _control_lifecycle(
        actor=actor,
        service=service,
        body=body,
        action=AutomationControlAction.RESUME,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/control-plane/drain",
    response_model=AutomationControlMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="drain_operator_automation_control_plane",
)
def drain_control_plane(
    body: AutomationControlRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _DrainControlIntent,
) -> JSONResponse:
    return _control_lifecycle(
        actor=actor,
        service=service,
        body=body,
        action=AutomationControlAction.DRAIN,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/control-plane/shutdown",
    response_model=AutomationControlMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="shutdown_operator_automation_control_plane",
)
def shutdown_control_plane(
    body: AutomationControlRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _ShutdownControlIntent,
) -> JSONResponse:
    return _control_lifecycle(
        actor=actor,
        service=service,
        body=body,
        action=AutomationControlAction.SHUTDOWN,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/automation/definitions/{definition_id}/runs",
    response_model=AutomationRunMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="claim_operator_automation_one_shot_run",
)
def claim_one_shot_run(
    body: AutomationOneShotRunRequest,
    definition_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _ClaimRunIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    return _mutation_result(
        lambda: service.claim_one_shot_run(
            definition_id=definition_id,
            request=body,
            context=_context(
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
        ),
        actor=actor,
    )


@router.get(
    "/automation/runs",
    response_model=AutomationRunListResponse,
    responses=_READ_RESPONSES,
    operation_id="list_operator_automation_runs",
)
def list_runs(
    request: Request,
    actor: _Actor,
    service: _Service,
    definition_id: Annotated[
        str | None,
        Query(pattern=_CANONICAL_UUID_PATTERN),
    ] = None,
    state: AutomationRunState | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, _RUN_QUERY_KEYS)
    return _read_result(
        lambda: service.list_runs(
            definition_id=definition_id,
            state=state,
            limit=limit,
            offset=offset,
        ),
        actor=actor,
    )


@router.get(
    "/automation/runs/{run_id}",
    response_model=AutomationRunDetailResponse,
    responses=_READ_RESPONSES,
    operation_id="get_operator_automation_run",
)
def get_run(
    request: Request,
    run_id: _EntityId,
    actor: _Actor,
    service: _Service,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, frozenset())
    return _read_result(lambda: service.get_run(run_id), actor=actor)


@router.get(
    "/automation/runs/{run_id}/events",
    response_model=AutomationRunEventListResponse,
    responses=_READ_RESPONSES,
    operation_id="list_operator_automation_run_events",
)
def list_run_events(
    request: Request,
    run_id: _EntityId,
    actor: _Actor,
    service: _Service,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    _require_query_shape(request, _EVENT_QUERY_KEYS)
    return _read_result(
        lambda: service.list_run_events(
            run_id=run_id,
            limit=limit,
            offset=offset,
        ),
        actor=actor,
    )
