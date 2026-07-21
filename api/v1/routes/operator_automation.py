"""Authenticated, PostgreSQL-backed operator Automation control plane.

Definition, lifecycle, claim, and ordinary read routes are local. The exact-run
authorization and safe-closeout routes delegate only through the backend-owned
single-child coordinators. Controlled-live capability is necessary but never
sufficient: each request must still pass exact run/action authority, RBAC,
explicit confirmation, immutable plan, approved Test-portfolio, eight-category
eligibility, cap, idempotency, audit, reconciliation, and one-use call gates.
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
from application.admin_api.command_runtime import (
    build_admin_api_command_runtime_readiness,
)
from application.admin_api.live_execution import (
    get_decision_backed_live_execution_service,
    operator_mvp_live_service_state_allows_route_admission,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_CREATE_ROUTE,
    OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
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
    AutomationEligibilityCycleMutationResponse,
    AutomationEligibilityRefreshRequest,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationOneShotRunRequest,
    AutomationRunDetailResponse,
    AutomationRunEventListResponse,
    AutomationRunItem,
    AutomationRunListResponse,
    AutomationRunMutationResponse,
    AutomationRunState,
    AutomationSingleChildAuthorizationRequest,
    AutomationSingleChildSafeCloseoutRequest,
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
_AUTOMATION_LIVE_ACTION_ROUTES = {
    "AUTHORIZE_SINGLE_CHILD": (
        "POST",
        OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_CREATE_ROUTE,
    ),
    "SAFE_CLOSEOUT_CHILD": (
        "POST",
        OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
    ),
}


def _operator_automation_live_action_ready(action: str) -> bool:
    """Require exact outer-route service admission and canonical runtime readiness."""

    target = _AUTOMATION_LIVE_ACTION_ROUTES.get(action)
    try:
        runtime = build_admin_api_command_runtime_readiness()
    except Exception:
        return False
    if not runtime.runtime_ready:
        return False
    if action == "REFRESH_ELIGIBILITY":
        return True
    if target is None:
        return False
    method, route = target
    try:
        service_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
    except Exception:
        return False
    return operator_mvp_live_service_state_allows_route_admission(
            service_state,
            method=method,
            route=route,
        )


def _require_operator_automation_action_ready(action: str) -> None:
    if not _operator_automation_live_action_ready(action):
        raise HTTPException(
            status_code=503,
            detail="operator_automation_action_runtime_unavailable",
        )


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
_AuthorizeSingleChildIntent = Annotated[
    Literal["authorize_automation_single_child_create"],
    Header(alias="X-Operator-Intent"),
]
_RefreshEligibilityIntent = Annotated[
    Literal["refresh_automation_spot_eligibility"],
    Header(alias="X-Operator-Intent"),
]
_SafeCloseoutSingleChildIntent = Annotated[
    Literal["safe_closeout_automation_single_child"],
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


def _scope_run_item(
    item: AutomationRunItem,
    actor: AdminApiActor,
) -> AutomationRunItem:
    can_trigger = actor_has_permission(
        actor, AdminApiPermission.AUTOMATION_TRIGGER
    )
    permissions = {
        "REFRESH_ELIGIBILITY": can_trigger
        and actor_has_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
        and actor_has_permission(
            actor,
            AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        ),
        "AUTHORIZE_SINGLE_CHILD": can_trigger
        and actor_has_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
        and actor_has_permission(
            actor,
            AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        )
        and actor_has_permission(actor, AdminApiPermission.ORDER_CREATE),
        "SAFE_CLOSEOUT_CHILD": can_trigger
        and actor_has_permission(actor, AdminApiPermission.ORDER_CANCEL),
    }
    allowed_actions = [
        action
        for action in item.allowed_actions
        if permissions.get(action, False)
        and _operator_automation_live_action_ready(action)
    ]
    can_live_execute = bool(
        {"AUTHORIZE_SINGLE_CHILD", "SAFE_CLOSEOUT_CHILD"}
        & set(allowed_actions)
    )
    return item.model_copy(
        update={
            "allowed_actions": allowed_actions,
            "live_execution_available": bool(
                item.live_execution_available and can_live_execute
            ),
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
    if isinstance(payload, AutomationRunDetailResponse):
        return payload.model_copy(
            update={"run": _scope_run_item(payload.run, actor)}
        )
    if isinstance(payload, AutomationRunMutationResponse):
        return payload.model_copy(
            update={"run": _scope_run_item(payload.run, actor)}
        )
    if isinstance(payload, AutomationEligibilityCycleMutationResponse):
        return payload.model_copy(
            update={"run": _scope_run_item(payload.run, actor)}
        )
    if isinstance(payload, AutomationRunListResponse):
        return payload.model_copy(
            update={
                "items": [
                    _scope_run_item(item, actor) for item in payload.items
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


@router.post(
    "/automation/runs/{run_id}/eligibility-cycles",
    response_model=AutomationEligibilityCycleMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="refresh_operator_automation_spot_eligibility",
)
def refresh_spot_eligibility(
    request: Request,
    body: AutomationEligibilityRefreshRequest,
    run_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _RefreshEligibilityIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    require_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
    require_permission(actor, AdminApiPermission.ACCOUNT_REALITY_REFRESH)
    _require_query_shape(request, frozenset())
    _require_operator_automation_action_ready("REFRESH_ELIGIBILITY")
    return _mutation_result(
        lambda: service.refresh_spot_eligibility(
            run_id=run_id,
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
    "/automation/runs/{run_id}/authorize-single-child",
    response_model=AutomationRunMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="authorize_operator_automation_single_child",
)
def authorize_single_child(
    request: Request,
    body: AutomationSingleChildAuthorizationRequest,
    run_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _AuthorizeSingleChildIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    require_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
    require_permission(actor, AdminApiPermission.ACCOUNT_REALITY_REFRESH)
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    _require_query_shape(request, frozenset())
    _require_operator_automation_action_ready("AUTHORIZE_SINGLE_CHILD")
    return _mutation_result(
        lambda: service.authorize_single_child(
            run_id=run_id,
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
    "/automation/runs/{run_id}/safe-closeout-child",
    response_model=AutomationRunMutationResponse,
    responses=_MUTATION_RESPONSES,
    operation_id="safe_closeout_operator_automation_single_child",
)
def safe_closeout_single_child(
    request: Request,
    body: AutomationSingleChildSafeCloseoutRequest,
    run_id: _EntityId,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: _SafeCloseoutSingleChildIntent,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    _require_query_shape(request, frozenset())
    _require_operator_automation_action_ready("SAFE_CLOSEOUT_CHILD")
    return _mutation_result(
        lambda: service.safe_closeout_single_child(
            run_id=run_id,
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
