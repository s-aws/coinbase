"""Authenticated Hotpoint Operations control and one-child proof routes."""

from __future__ import annotations

import os
from typing import Annotated, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from application.admin_api.auth import (
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.command_runtime import (
    build_admin_api_command_runtime_readiness,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.live_execution import (
    get_decision_backed_live_execution_service,
    operator_mvp_live_service_state_allows_route_admission,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
)
from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_CONTROL_OPERATOR_INTENT,
    HOTPOINT_RUN_OPERATOR_INTENT,
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
    OperatorHotpointControlError,
    OperatorHotpointControlRecord,
    OperatorHotpointControlService,
    OperatorHotpointRequestContext,
)
from application.admin_api.operator_hotpoint_models import (
    OperatorHotpointControlRequest,
    OperatorHotpointMutationResponse,
    OperatorHotpointParentItem,
    OperatorHotpointParentListResponse,
    OperatorHotpointRateLimitReadback,
    OperatorHotpointRecentPlacementReadback,
    OperatorHotpointReadback,
    OperatorHotpointRunRequest,
    OperatorHotpointSafeCloseoutRequest,
)
from application.admin_api.operator_hotpoint_runtime import (
    get_default_operator_hotpoint_control_services,
)
from core.enums import AdminApiPermission


OPERATOR_HOTPOINT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED"
)
_VISIBLE_ASCII = r"^[\x21-\x7e]+$"


def require_operator_hotpoint_enabled() -> None:
    if os.environ.get(OPERATOR_HOTPOINT_ENABLED_ENV) != "1":
        raise HTTPException(status_code=503, detail="operator_hotpoint_disabled")


router = APIRouter(
    dependencies=[Depends(require_operator_hotpoint_enabled)]
)

_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_Services = Annotated[
    Mapping[str, OperatorHotpointControlService],
    Depends(get_default_operator_hotpoint_control_services),
]
_IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII,
    ),
]
_CorrelationId = Annotated[
    str,
    Header(
        alias="X-Correlation-Id",
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII,
    ),
]
_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    409: {"model": AdminApiErrorResponse},
    422: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def _allowed_actions(
    record: OperatorHotpointControlRecord,
    service: OperatorHotpointControlService,
) -> list[str]:
    actions: list[str] = []
    if not bool(getattr(service, "control_available", True)):
        return actions
    if record.goal_create_claim_consumed:
        if record.kill_switch_state is HotpointKillSwitchState.ENABLED:
            actions.append("DISABLE")
        if (
            record.goal_create_claim_domain == service.policy.domain
            and record.create_state is HotpointCreateState.ACCEPTED
            and record.cancel_state is HotpointCancelState.NOT_CLAIMED
            and service.cancel_execution_available
        ):
            actions.append("SAFE_CLOSEOUT")
        return actions
    if record.kill_switch_state is HotpointKillSwitchState.DISABLED:
        if record.window_id is None:
            actions.append("ENABLE")
        return actions
    actions.append("DISABLE")
    if (
        record.window_state is HotpointWindowState.NONE
        and record.window_id is None
    ):
        actions.append("ARM")
    elif record.window_state is HotpointWindowState.ARMED:
        actions.append("DISARM")
        if service.placement_execution_available:
            actions.append("RUN_ONCE")
    if (
        record.create_state is HotpointCreateState.ACCEPTED
        and record.cancel_state is HotpointCancelState.NOT_CLAIMED
    ):
        if service.cancel_execution_available:
            actions.append("SAFE_CLOSEOUT")
    return actions


def _readback(
    record: OperatorHotpointControlRecord,
    service: OperatorHotpointControlService,
) -> OperatorHotpointReadback:
    policy = service.policy
    recent_placement = None
    if (
        record.create_state is not HotpointCreateState.NOT_CLAIMED
        and record.parent_client_order_id
        and record.updated_at
        and not record.updated_at.startswith("1970-01-01")
    ):
        recent_placement = OperatorHotpointRecentPlacementReadback(
            domain=policy.domain,
            parent_client_order_id=record.parent_client_order_id,
            child_client_order_id=record.child_client_order_id,
            create_state=record.create_state.value,
            create_exchange_invoked=record.create_exchange_invoked,
            diagnostic_code=record.diagnostic_code,
            updated_at=record.updated_at,
        )
    return OperatorHotpointReadback(
        domain=policy.domain,
        revision=record.revision,
        environment=os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "local"),
        portfolio_profile_alias=policy.portfolio_profile_alias,
        product_scope=policy.product_id,
        max_submitted_notional_usdc=str(
            policy.max_submitted_notional_usdc
        ),
        max_possible_execution_notional_usdc=str(
            policy.max_possible_execution_notional_usdc
        ),
        max_turnover_notional_usdc=(
            str(policy.max_turnover_notional_usdc)
            if policy.max_turnover_notional_usdc is not None
            else None
        ),
        exact_size=(
            str(policy.exact_size)
            if policy.exact_size is not None
            else None
        ),
        placement_execution_available=(
            service.placement_execution_available
        ),
        cancel_execution_available=service.cancel_execution_available,
        rate_limit=OperatorHotpointRateLimitReadback(
            create_claims_consumed=(
                1 if record.goal_create_claim_consumed else 0
            ),
            create_claims_remaining=(
                0 if record.goal_create_claim_consumed else 1
            ),
            consumed_by_domain=record.goal_create_claim_domain,
        ),
        recent_placement=recent_placement,
        kill_switch_state=record.kill_switch_state,
        window_state=record.window_state,
        create_state=record.create_state,
        cancel_state=record.cancel_state,
        parent_client_order_id=record.parent_client_order_id,
        child_client_order_id=record.child_client_order_id,
        side=record.side,
        window_started_at=record.window_started_at,
        window_expires_at=record.window_expires_at,
        diagnostic_code=record.diagnostic_code,
        allowed_actions=_allowed_actions(record, service),
        create_claim_consumed=(
            record.create_state is not HotpointCreateState.NOT_CLAIMED
        ),
        cancel_claim_consumed=(
            record.cancel_state is not HotpointCancelState.NOT_CLAIMED
        ),
        create_exchange_invoked=record.create_exchange_invoked,
        cancel_exchange_invoked=record.cancel_exchange_invoked,
        correlation_id=(
            record.correlation_id
            if record.correlation_id != "not_recorded"
            else None
        ),
        audit_id=(
            record.audit_id
            if record.audit_id
            != "00000000-0000-0000-0000-000000000000"
            else None
        ),
        updated_at=(
            record.updated_at
            if not record.updated_at.startswith("1970-01-01")
            else None
        ),
    )


def _service(
    services: Mapping[str, OperatorHotpointControlService],
    domain: str,
) -> OperatorHotpointControlService:
    service = services.get(str(domain).upper())
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_domain_unavailable",
        )
    return service


def _context(
    *,
    actor: AdminApiActor,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> OperatorHotpointRequestContext:
    return OperatorHotpointRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid4()),
        operator_intent=operator_intent,
    )


def _raise(exc: OperatorHotpointControlError) -> None:
    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from None


def _require_live_runtime(*, route: str) -> None:
    try:
        readiness = build_admin_api_command_runtime_readiness()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_live_runtime_unavailable",
        ) from None
    if not readiness.runtime_ready:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_live_runtime_unavailable",
        )
    try:
        service_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_live_runtime_unavailable",
        ) from None
    if not operator_mvp_live_service_state_allows_route_admission(
        service_state,
        method="POST",
        route=route,
    ):
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_live_runtime_unavailable",
        )


@router.get(
    "/hotpoint",
    response_model=OperatorHotpointReadback,
    responses=_RESPONSES,
    summary="Read backend-owned Hotpoint controls and call accounting",
)
def get_operator_hotpoint(
    actor: _Actor,
    services: _Services,
    domain: Annotated[Literal["SPOT", "FUTURES"], Query()] = "SPOT",
):
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    service = _service(services, domain)
    try:
        return _readback(service.read(), service)
    except OperatorHotpointControlError as exc:
        _raise(exc)


@router.get(
    "/hotpoint/eligible-parents",
    response_model=OperatorHotpointParentListResponse,
    responses=_RESPONSES,
    summary="List exact system-owned parents eligible for one Hotpoint window",
)
def list_operator_hotpoint_parents(
    actor: _Actor,
    services: _Services,
    domain: Annotated[Literal["SPOT", "FUTURES"], Query()] = "SPOT",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    require_permission(actor, AdminApiPermission.AUTOMATION_READ)
    service = _service(services, domain)
    try:
        rows, total = service.list_eligible_parents(
            limit=limit,
            offset=offset,
        )
    except OperatorHotpointControlError as exc:
        _raise(exc)
    items = [
        OperatorHotpointParentItem.model_validate(
            {"domain": service.policy.domain, **row}
        )
        for row in rows
    ]
    return OperatorHotpointParentListResponse(
        domain=service.policy.domain,
        items=items,
        returned_count=len(items),
        total_count=total,
        limit=limit,
        offset=offset,
        portfolio_profile_alias=service.policy.portfolio_profile_alias,
        product_scope=service.policy.product_id,
    )


def _mutation(
    *,
    method: Literal["control", "run_once", "safe_closeout"],
    operator_intent: str,
    context: OperatorHotpointRequestContext,
    record: OperatorHotpointControlRecord,
    service: OperatorHotpointControlService,
) -> OperatorHotpointMutationResponse:
    invoked = bool(
        record.create_exchange_invoked is True
        if method == "run_once"
        else record.cancel_exchange_invoked is True
        if method == "safe_closeout"
        else False
    )
    return OperatorHotpointMutationResponse(
        status="accepted",
        service_method=method,
        operator_intent=operator_intent,
        control=_readback(record, service),
        correlation_id=context.correlation_id,
        idempotency_key=context.idempotency_key,
        audit_id=context.audit_id,
        live_exchange_submitted=invoked,
        live_coinbase_orders_ran=invoked,
    )


@router.post(
    "/hotpoint/control",
    response_model=OperatorHotpointMutationResponse,
    responses=_RESPONSES,
    summary="Enable, disable, arm, or disarm one bounded Hotpoint window",
)
def control_operator_hotpoint(
    body: OperatorHotpointControlRequest,
    actor: _Actor,
    services: _Services,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["control_operator_hotpoint"],
        Header(alias="X-Operator-Intent"),
    ],
):
    require_permission(actor, AdminApiPermission.AUTOMATION_CONTROL)
    service = _service(services, body.domain)
    context = _context(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        record = service.control(
            action=body.action,
            expected_revision=body.expected_revision,
            confirm_control_action=body.confirm_control_action,
            parent_client_order_id=body.parent_client_order_id,
            authorize_one_bounded_trigger_window=(
                body.authorize_one_bounded_trigger_window
            ),
            acknowledge_unknown_outcome_consumes_create_allowance=(
                body.acknowledge_unknown_outcome_consumes_create_allowance
            ),
            acknowledge_backend_derives_child_terms=(
                body.acknowledge_backend_derives_child_terms
            ),
            context=context,
        )
    except OperatorHotpointControlError as exc:
        _raise(exc)
    return _mutation(
        method="control",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
    )


@router.post(
    "/hotpoint/run-once",
    response_model=OperatorHotpointMutationResponse,
    responses=_RESPONSES,
    summary="Evaluate one armed window and dispatch at most one claimed child",
)
def run_operator_hotpoint_once(
    body: OperatorHotpointRunRequest,
    actor: _Actor,
    services: _Services,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["run_operator_hotpoint_once"],
        Header(alias="X-Operator-Intent"),
    ],
):
    require_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    service = _service(services, body.domain)
    if not service.placement_execution_available:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_domain_execution_unavailable",
        )
    if (
        body.confirm_bounded_trigger_evaluation is not True
        or body.acknowledge_unknown_outcome_consumes_create_allowance
        is not True
    ):
        raise HTTPException(
            status_code=422,
            detail="operator_hotpoint_run_authority_invalid",
        )
    _require_live_runtime(
        route=OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
    )
    context = _context(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        record = service.run_once(context=context)
    except OperatorHotpointControlError as exc:
        _raise(exc)
    return _mutation(
        method="run_once",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
    )


@router.post(
    "/hotpoint/safe-closeout",
    response_model=OperatorHotpointMutationResponse,
    responses=_RESPONSES,
    summary="Claim and safely cancel only the exact accepted Hotpoint child",
)
def safe_closeout_operator_hotpoint(
    body: OperatorHotpointSafeCloseoutRequest,
    actor: _Actor,
    services: _Services,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["safe_closeout_operator_hotpoint_child"],
        Header(alias="X-Operator-Intent"),
    ],
):
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    service = _service(services, body.domain)
    if not service.cancel_execution_available:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_domain_cancel_unavailable",
        )
    _require_live_runtime(
        route=OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
    )
    context = _context(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        record = service.safe_closeout(
            confirm_exact_child_safe_closeout=(
                body.confirm_exact_child_safe_closeout
            ),
            acknowledge_unknown_outcome_consumes_cancel_allowance=(
                body.acknowledge_unknown_outcome_consumes_cancel_allowance
            ),
            context=context,
        )
    except OperatorHotpointControlError as exc:
        _raise(exc)
    return _mutation(
        method="safe_closeout",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
    )
