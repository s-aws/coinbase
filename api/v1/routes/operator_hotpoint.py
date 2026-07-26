"""Authenticated Hotpoint Operations control and one-child proof routes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated, Literal, Mapping
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from application.admin_api.auth import (
    actor_has_permission,
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
    FUTURES_HOTPOINT_GOAL_ID,
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
    OperatorFuturesHotpointCallReadback,
    OperatorFuturesHotpointCandidateReadback,
    OperatorFuturesHotpointExternalCommandReadback,
    OperatorFuturesHotpointReadback,
    OperatorHotpointControlRequest,
    OperatorHotpointMutationResponse,
    OperatorHotpointParentItem,
    OperatorHotpointParentListResponse,
    OperatorHotpointRateLimitReadback,
    OperatorHotpointRecentPlacementReadback,
    OperatorHotpointReadback,
    OperatorHotpointReadbackResponse,
    OperatorHotpointRunRequestBody,
    OperatorHotpointSafeCloseoutRequestBody,
)
from application.admin_api.operator_hotpoint_runtime import (
    FuturesHotpointExecutionPosture,
    get_default_operator_hotpoint_control_services,
    get_operator_futures_hotpoint_execution_posture,
)
from application.admin_api.operator_futures_hotpoint_v2 import (
    OperatorFuturesHotpointReadback as OperatorFuturesHotpointServiceReadback,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FUTURES_MANUAL_MARGIN_SUBREADS,
    FuturesManualLifecycleError,
    classify_futures_manual_candidate_freshness,
)
from core.enums import AdminApiPermission, AdminFuturesManualCallOutcome


OPERATOR_HOTPOINT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED"
)
OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
)
_VISIBLE_ASCII = r"^[\x21-\x7e]+$"
_FUTURES_HOTPOINT_AUDIT_NAMESPACE = UUID(
    "9286871d-1bc7-4e0b-94da-f54a2fae240a"
)
_FUTURES_HOTPOINT_CANDIDATE_PUBLIC_FIELDS = tuple(
    OperatorFuturesHotpointCandidateReadback.model_fields
)


def require_operator_hotpoint_enabled() -> None:
    if os.environ.get(OPERATOR_HOTPOINT_ENABLED_ENV) != "1":
        raise HTTPException(status_code=503, detail="operator_hotpoint_disabled")


def _require_futures_v2_mutation_enabled(*, domain: str) -> None:
    if (
        str(domain).upper() == "FUTURES"
        and os.environ.get(OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV) != "1"
    ):
        raise HTTPException(
            status_code=503,
            detail="operator_futures_hotpoint_v2_disabled",
        )


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


def _legacy_readback(
    record: OperatorHotpointControlRecord,
    service: OperatorHotpointControlService,
    *,
    actor: AdminApiActor,
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
    actions = _allowed_actions(record, service)
    if not actor_has_permission(
        actor,
        AdminApiPermission.AUTOMATION_CONTROL,
    ):
        actions = [
            action
            for action in actions
            if action not in {"ENABLE", "DISABLE", "ARM", "DISARM"}
        ]
    elif not actor_has_permission(
        actor,
        AdminApiPermission.AUTOMATION_RESUME,
    ):
        actions = [
            action for action in actions if action not in {"ENABLE", "ARM"}
        ]
    if not (
        actor_has_permission(
            actor,
            AdminApiPermission.AUTOMATION_TRIGGER,
        )
        and actor_has_permission(
            actor,
            AdminApiPermission.ORDER_CREATE,
        )
    ):
        actions = [action for action in actions if action != "RUN_ONCE"]
    if not actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CANCEL,
    ):
        actions = [
            action for action in actions if action != "SAFE_CLOSEOUT"
        ]
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
        allowed_actions=actions,
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


def _futures_call_readback(
    outcome: AdminFuturesManualCallOutcome,
    call_boundary_entered: bool | None,
) -> OperatorFuturesHotpointCallReadback:
    consumed = outcome is not AdminFuturesManualCallOutcome.NOT_RUN
    return OperatorFuturesHotpointCallReadback(
        outcome=outcome,
        call_boundary_entered=call_boundary_entered,
        allowance_consumed=consumed,
        allowance_remaining=0 if consumed else 1,
    )


def _create_state(
    outcome: AdminFuturesManualCallOutcome,
) -> HotpointCreateState:
    if outcome is AdminFuturesManualCallOutcome.NOT_RUN:
        return HotpointCreateState.NOT_CLAIMED
    return HotpointCreateState(outcome.value)


def _cancel_state(
    outcome: AdminFuturesManualCallOutcome,
    *,
    cancel_disposition: str | None,
) -> HotpointCancelState:
    if cancel_disposition == "NOT_REQUIRED":
        return HotpointCancelState.NOT_REQUIRED
    if outcome is AdminFuturesManualCallOutcome.NOT_RUN:
        return HotpointCancelState.NOT_CLAIMED
    return HotpointCancelState(outcome.value)


def _futures_readback(
    record: OperatorFuturesHotpointServiceReadback,
    service: OperatorHotpointControlService,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesHotpointReadback:
    lifecycle = record.lifecycle
    control = record.control
    try:
        posture = get_operator_futures_hotpoint_execution_posture()
    except Exception:
        posture = FuturesHotpointExecutionPosture(
            ready=False,
            diagnostic_code=(
                "operator_futures_hotpoint_execution_posture_unavailable"
            ),
        )
    freshness = classify_futures_manual_candidate_freshness(
        lifecycle.candidate,
        now=datetime.now(timezone.utc),
    )
    candidate_fresh = (
        freshness == "operator_futures_manual_candidate_fresh"
    )
    candidate = (
        OperatorFuturesHotpointCandidateReadback.model_validate(
            {
                field_name: (
                    lifecycle.candidate[field_name]
                    if field_name not in {"post_only", "product_policy_revision"}
                    else lifecycle.candidate[field_name] in {True, "true"}
                    if field_name == "post_only"
                    else int(lifecycle.candidate[field_name])
                )
                for field_name in _FUTURES_HOTPOINT_CANDIDATE_PUBLIC_FIELDS
            }
        )
        if lifecycle.candidate is not None
        else None
    )
    preview = _futures_call_readback(
        lifecycle.preview_outcome,
        lifecycle.preview_exchange_invoked,
    )
    create = _futures_call_readback(
        lifecycle.create_outcome,
        lifecycle.create_exchange_invoked,
    )
    reconciliation = _futures_call_readback(
        lifecycle.reconciliation_outcome,
        lifecycle.reconciliation_exchange_invoked,
    )
    cancel = _futures_call_readback(
        lifecycle.cancel_outcome,
        lifecycle.cancel_exchange_invoked,
    )
    order_mutation_boundary_entered = bool(
        lifecycle.create_exchange_invoked is True
        or lifecycle.cancel_exchange_invoked is True
    )
    actions = list(record.allowed_actions)
    if not actor_has_permission(
        actor,
        AdminApiPermission.AUTOMATION_CONTROL,
    ):
        actions = [
            action
            for action in actions
            if action not in {"ENABLE", "DISABLE", "ARM", "DISARM"}
        ]
    elif not actor_has_permission(
        actor,
        AdminApiPermission.AUTOMATION_RESUME,
    ):
        actions = [
            action for action in actions if action not in {"ENABLE", "ARM"}
        ]
    actor_can_run = (
        actor_has_permission(actor, AdminApiPermission.AUTOMATION_TRIGGER)
        and actor_has_permission(actor, AdminApiPermission.ORDER_CREATE)
    )
    actor_can_safe_closeout = actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CANCEL,
    )
    if (
        not actor_can_run
        or not posture.ready
        or lifecycle.active_cycle_number is not None
        or lifecycle.cycles_used >= 10
        or preview.allowance_consumed
        or create.allowance_consumed
    ):
        actions = [action for action in actions if action != "RUN_ONCE"]
    safe_closeout_authorized = (
        lifecycle.create_outcome
        is AdminFuturesManualCallOutcome.ACCEPTED
        or (
            lifecycle.create_outcome
            is AdminFuturesManualCallOutcome.UNKNOWN
            and lifecycle.create_exchange_invoked is True
        )
    )
    if (
        not actor_can_safe_closeout
        or not posture.ready
        or not safe_closeout_authorized
        or reconciliation.allowance_consumed
        or cancel.allowance_consumed
    ):
        actions = [
            action for action in actions if action != "SAFE_CLOSEOUT"
        ]
    correlation_id = lifecycle.correlation_id
    if correlation_id is None and control.correlation_id != "not_recorded":
        correlation_id = control.correlation_id
    audit_id = lifecycle.audit_id
    if (
        audit_id is None
        and control.audit_id
        != "00000000-0000-0000-0000-000000000000"
    ):
        audit_id = control.audit_id
    updated_at = lifecycle.updated_at
    if (
        updated_at is None
        and not control.updated_at.startswith("1970-01-01")
    ):
        updated_at = control.updated_at
    return OperatorFuturesHotpointReadback(
        domain="FUTURES",
        goal_id=record.goal_id,
        revision=record.revision,
        environment=os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "local"),
        placement_execution_available=(
            service.placement_execution_available
        ),
        cancel_execution_available=service.cancel_execution_available,
        kill_switch_state=control.kill_switch_state,
        window_state=control.window_state,
        create_state=_create_state(lifecycle.create_outcome),
        cancel_state=_cancel_state(
            lifecycle.cancel_outcome,
            cancel_disposition=record.cancel_disposition,
        ),
        parent_client_order_id=control.parent_client_order_id,
        child_client_order_id=lifecycle.client_order_id,
        side=control.side,
        window_started_at=control.window_started_at,
        window_expires_at=control.window_expires_at,
        trigger_fill_count=record.trigger_fill_count,
        trigger_evidence_sha256=record.trigger_evidence_sha256,
        window_id_sha256=record.window_id_sha256,
        cycles_used=lifecycle.cycles_used,
        cycles_remaining=max(0, 10 - lifecycle.cycles_used),
        active_cycle_number=lifecycle.active_cycle_number,
        eligibility_outcome=lifecycle.eligibility_outcome,
        eligibility_diagnostic_code=(
            lifecycle.eligibility_diagnostic_code.replace(
                "operator_futures_manual",
                "operator_futures_hotpoint",
            )
        ),
        category_attempts={
            category: lifecycle.category_attempts[category]
            for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        margin_subread_attempts={
            subread: lifecycle.margin_subread_attempts[subread]
            for subread in FUTURES_MANUAL_MARGIN_SUBREADS
        },
        latest_external_command=(
            OperatorFuturesHotpointExternalCommandReadback.model_validate(
                record.latest_external_command
            )
            if record.latest_external_command is not None
            else None
        ),
        candidate=candidate,
        candidate_fresh_for_execution=candidate_fresh,
        candidate_freshness_diagnostic_code=freshness.replace(
            "operator_futures_manual",
            "operator_futures_hotpoint",
        ),
        candidate_sha256=lifecycle.candidate_sha256,
        portfolio_id_sha256=lifecycle.portfolio_id_sha256,
        eligibility_evidence_sha256=(
            lifecycle.eligibility_evidence_sha256
        ),
        execution_posture_ready=posture.ready,
        execution_posture_diagnostic_code=posture.diagnostic_code,
        preview=preview,
        preview_id_sha256=lifecycle.preview_id_sha256,
        create=create,
        exchange_order_id_sha256=lifecycle.exchange_order_id_sha256,
        reconciliation=reconciliation,
        order_status=lifecycle.order_status,
        authoritatively_nonterminal=(
            lifecycle.authoritatively_nonterminal
        ),
        cancel_disposition=record.cancel_disposition,
        cancel=cancel,
        diagnostic_code=record.diagnostic_code,
        allowed_actions=actions,
        correlation_id=correlation_id,
        audit_id=audit_id,
        updated_at=updated_at,
        live_exchange_submitted=order_mutation_boundary_entered,
        live_coinbase_orders_ran=order_mutation_boundary_entered,
    )


def _readback(
    record: (
        OperatorHotpointControlRecord
        | OperatorFuturesHotpointServiceReadback
    ),
    service: OperatorHotpointControlService,
    *,
    actor: AdminApiActor,
) -> OperatorHotpointReadback | OperatorFuturesHotpointReadback:
    if isinstance(record, OperatorFuturesHotpointServiceReadback):
        return _futures_readback(record, service, actor=actor)
    return _legacy_readback(record, service, actor=actor)


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
    domain: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> OperatorHotpointRequestContext:
    audit_id = (
        str(
            uuid5(
                _FUTURES_HOTPOINT_AUDIT_NAMESPACE,
                f"{FUTURES_HOTPOINT_GOAL_ID}:{idempotency_key}",
            )
        )
        if str(domain).upper() == "FUTURES"
        else str(uuid4())
    )
    return OperatorHotpointRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=audit_id,
        operator_intent=operator_intent,
    )


def _raise(
    exc: OperatorHotpointControlError | FuturesManualLifecycleError,
) -> None:
    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from None


def _require_live_runtime(*, route: str, domain: str) -> None:
    exact_domain = str(domain).upper()
    if exact_domain == "FUTURES":
        try:
            posture = get_operator_futures_hotpoint_execution_posture()
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="operator_hotpoint_live_runtime_unavailable",
            ) from None
        if not posture.ready:
            raise HTTPException(
                status_code=503,
                detail="operator_hotpoint_live_runtime_unavailable",
            )
        return
    if exact_domain == "SPOT":
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
    response_model=OperatorHotpointReadbackResponse,
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
        return _readback(service.read(), service, actor=actor)
    except (OperatorHotpointControlError, FuturesManualLifecycleError) as exc:
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
    except (OperatorHotpointControlError, FuturesManualLifecycleError) as exc:
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
    record: (
        OperatorHotpointControlRecord
        | OperatorFuturesHotpointServiceReadback
    ),
    service: OperatorHotpointControlService,
    actor: AdminApiActor,
) -> OperatorHotpointMutationResponse:
    if isinstance(record, OperatorFuturesHotpointServiceReadback):
        lifecycle = record.lifecycle
        invoked = bool(
            lifecycle.create_exchange_invoked is True
            if method == "run_once"
            else lifecycle.cancel_exchange_invoked is True
            if method == "safe_closeout"
            else False
        )
    else:
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
        control=_readback(record, service, actor=actor),
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
    if body.action in {"ENABLE", "ARM"}:
        require_permission(actor, AdminApiPermission.AUTOMATION_RESUME)
    _require_futures_v2_mutation_enabled(domain=body.domain)
    service = _service(services, body.domain)
    context = _context(
        actor=actor,
        domain=body.domain,
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
    except (OperatorHotpointControlError, FuturesManualLifecycleError) as exc:
        _raise(exc)
    return _mutation(
        method="control",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
        actor=actor,
    )


@router.post(
    "/hotpoint/run-once",
    response_model=OperatorHotpointMutationResponse,
    responses=_RESPONSES,
    summary="Evaluate one armed window and dispatch at most one claimed child",
)
def run_operator_hotpoint_once(
    body: OperatorHotpointRunRequestBody,
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
    _require_futures_v2_mutation_enabled(domain=body.domain)
    service = _service(services, body.domain)
    if not service.placement_execution_available:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_domain_execution_unavailable",
        )
    if body.domain == "SPOT" and (
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
        domain=body.domain,
    )
    context = _context(
        actor=actor,
        domain=body.domain,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        if body.domain == "FUTURES":
            record = service.run_once(
                expected_revision=body.expected_revision,
                expected_parent_client_order_id=(
                    body.expected_parent_client_order_id
                ),
                confirm_bounded_trigger_evaluation=(
                    body.confirm_bounded_trigger_evaluation
                ),
                authorize_one_no_retry_six_category_cycle=(
                    body.authorize_one_no_retry_six_category_cycle
                ),
                acknowledge_cycle_is_goal_global_and_limited_to_ten=(
                    body.acknowledge_cycle_is_goal_global_and_limited_to_ten
                ),
                acknowledge_unsuccessful_or_unknown_cycle_fails_closed=(
                    body
                    .acknowledge_unsuccessful_or_unknown_cycle_fails_closed
                ),
                authorize_one_preview_and_conditional_identical_create=(
                    body
                    .authorize_one_preview_and_conditional_identical_create
                ),
                acknowledge_unknown_preview_or_create_consumes_allowance=(
                    body
                    .acknowledge_unknown_preview_or_create_consumes_allowance
                ),
                acknowledge_create_requires_accepted_identical_preview=(
                    body
                    .acknowledge_create_requires_accepted_identical_preview
                ),
                context=context,
            )
        else:
            record = service.run_once(context=context)
    except (OperatorHotpointControlError, FuturesManualLifecycleError) as exc:
        _raise(exc)
    return _mutation(
        method="run_once",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
        actor=actor,
    )


@router.post(
    "/hotpoint/safe-closeout",
    response_model=OperatorHotpointMutationResponse,
    responses=_RESPONSES,
    summary="Claim and safely cancel only the exact accepted Hotpoint child",
)
def safe_closeout_operator_hotpoint(
    body: OperatorHotpointSafeCloseoutRequestBody,
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
    _require_futures_v2_mutation_enabled(domain=body.domain)
    service = _service(services, body.domain)
    if not service.cancel_execution_available:
        raise HTTPException(
            status_code=503,
            detail="operator_hotpoint_domain_cancel_unavailable",
        )
    _require_live_runtime(
        route=OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
        domain=body.domain,
    )
    context = _context(
        actor=actor,
        domain=body.domain,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        if body.domain == "FUTURES":
            record = service.safe_closeout(
                expected_revision=body.expected_revision,
                expected_child_client_order_id=(
                    body.expected_child_client_order_id
                ),
                confirm_exact_child_safe_closeout=(
                    body.confirm_exact_child_safe_closeout
                ),
                authorize_one_exact_no_retry_reconciliation=(
                    body.authorize_one_exact_no_retry_reconciliation
                ),
                acknowledge_unknown_reconciliation_consumes_allowance=(
                    body
                    .acknowledge_unknown_reconciliation_consumes_allowance
                ),
                acknowledge_cancel_only_exact_authoritatively_nonterminal_child=(
                    body
                    .acknowledge_cancel_only_exact_authoritatively_nonterminal_child
                ),
                acknowledge_unknown_outcome_consumes_cancel_allowance=(
                    body
                    .acknowledge_unknown_outcome_consumes_cancel_allowance
                ),
                context=context,
            )
        else:
            record = service.safe_closeout(
                confirm_exact_child_safe_closeout=(
                    body.confirm_exact_child_safe_closeout
                ),
                acknowledge_unknown_outcome_consumes_cancel_allowance=(
                    body
                    .acknowledge_unknown_outcome_consumes_cancel_allowance
                ),
                context=context,
            )
    except (OperatorHotpointControlError, FuturesManualLifecycleError) as exc:
        _raise(exc)
    return _mutation(
        method="safe_closeout",
        operator_intent=operator_intent,
        context=context,
        record=record,
        service=service,
        actor=actor,
    )
