"""Read-only futures/perpetual routes for the Admin API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from typing import Annotated, Any, Literal, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_service import (
    FUTURES_COMMAND_SERVICE_SOURCE_DISABLED,
    FUTURES_COMMAND_SOURCE_DISABLED_MESSAGE,
    AdminApiCommandService,
)
from application.admin_api.futures_risk_proof import FileFuturesRiskProofStore
from application.admin_api.futures_order_preview import (
    FuturesOrderPreviewArtifactError,
)
from application.admin_api.futures_order_preview_r12 import (
    FUTURES_PREVIEW_R12_ARTIFACT_PATH,
    FuturesPreviewR12ArtifactStore,
)
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import (
    AdminApiLiveExecutionService,
    FileAdminApiLiveAdapterDecisionStore,
    FileAdminApiLiveServiceDecisionStore,
)
from application.admin_api.futures_route_contracts import (
    FUTURES_CANCEL_ROUTE_CONTRACT,
    FUTURES_CLOSE_REDUCE_ROUTE_CONTRACT,
    FUTURES_PLACE_ROUTE_CONTRACT,
    FUTURES_RECONCILE_ROUTE_CONTRACT,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminFuturesAccountReadResponse,
    AdminFuturesCommandSuiteResponse,
    AdminFuturesOrderPreviewR12Response,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
    FuturesCancelOrderCommand,
    FuturesCancelOrderRequest,
    FuturesFillReadbackResponse,
    FuturesCloseReduceCommand,
    FuturesCloseReduceRequest,
    FuturesPlaceOrderCommand,
    FuturesPlaceOrderRequest,
    FuturesReconciliationCommand,
    FuturesReconciliationRequest,
    FuturesRiskProofDetailResponse,
    FuturesRiskProofListResponse,
    FuturesRiskProofRecordCommand,
    FuturesRiskProofRecordItem,
    FuturesRiskProofRecordRequest,
)
from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    AdminMvpService,
    get_admin_mvp_service,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    FuturesManualRequestContext,
    OperatorFuturesManualLifecycleService,
    classify_futures_manual_candidate_freshness,
    is_futures_manual_goal_terminal,
)
from application.admin_api.operator_futures_manual_models import (
    OperatorFuturesManualCallReadback,
    OperatorFuturesManualCandidateReadback,
    OperatorFuturesManualExecuteRequest,
    OperatorFuturesManualMutationResponse,
    OperatorFuturesManualReadback,
    OperatorFuturesManualRefreshRequest,
)
from application.admin_api.operator_futures_manual_service_runtime import (
    get_default_operator_futures_manual_lifecycle_service,
    get_operator_futures_manual_execution_posture,
)
from application.admin_api.operator_futures_product_policy import (
    OperatorFuturesProductPolicyError,
)
from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS,
    FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES,
)
from application.admin_api.operator_futures_product_ticket_models import (
    OperatorFuturesProductPolicyItemReadback,
    OperatorFuturesProductPolicyRequest,
    OperatorFuturesProductTicketCandidateReadback,
    OperatorFuturesProductTicketExecuteRequest,
    OperatorFuturesProductTicketMutationResponse,
    OperatorFuturesProductTicketReadback,
    OperatorFuturesProductTicketRefreshRequest,
)
from application.admin_api.operator_futures_product_ticket_service import (
    FuturesProductTicketState,
    OperatorFuturesProductTicketService,
)
from application.admin_api.operator_futures_product_ticket_service_runtime import (
    OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED_ENV,
    get_default_operator_futures_product_ticket_service,
    get_operator_futures_product_ticket_execution_posture,
)
from application.admin_api.operator_futures_order_operations_models import (
    OperatorFuturesOrderCancelRequest,
    OperatorFuturesOrderDetailResponse,
    OperatorFuturesOrderListResponse,
    OperatorFuturesOrderMutationResolutionResponse,
    OperatorFuturesOrderMutationResponse,
    OperatorFuturesOrderOperationsReadback,
    OperatorFuturesOrderRefreshRequest,
)
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsGoalRecord,
    FuturesOrderOperationsRequestContext,
    OperatorFuturesOrderOperationsService,
)
from application.admin_api.operator_futures_order_operations_service_runtime import (
    OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED_ENV,
    get_default_operator_futures_order_operations_service,
    get_operator_futures_order_operations_execution_posture,
)
from application.admin_api.operator_futures_follow_up_intent import (
    FuturesFollowUpIntentReadback,
    FuturesFollowUpIntentRequestContext,
    OperatorFuturesFollowUpIntentService,
)
from application.admin_api.operator_futures_follow_up_intent_models import (
    OperatorFuturesFollowUpIntentAttachRequest,
    OperatorFuturesFollowUpIntentAttachResponse,
    OperatorFuturesFollowUpIntentReadResponse,
)
from application.admin_api.operator_futures_follow_up_intent_service_runtime import (
    OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED_ENV,
    get_default_operator_futures_follow_up_intent_service,
)
from application.admin_api.operator_futures_position_lifecycle import (
    FuturesPositionGoalRecord,
    FuturesPositionLifecycleError,
    FuturesPositionRequestContext,
    OperatorFuturesPositionLifecycleService,
    classify_futures_position_selection_freshness,
)
from application.admin_api.operator_futures_position_models import (
    OperatorFuturesPositionCallReadback,
    OperatorFuturesPositionExecuteRequest,
    OperatorFuturesPositionLifecycleReadback,
    OperatorFuturesPositionMutationResponse,
    OperatorFuturesPositionRefreshRequest,
    OperatorFuturesPositionSelectionReadback,
)
from application.admin_api.operator_futures_position_service_runtime import (
    get_default_operator_futures_position_lifecycle_service,
    get_operator_futures_position_execution_posture,
)
from application.admin_api.read_service import (
    AdminApiReadService,
    futures_command_suite_api_payload,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
)

from .orders import (
    COMMAND_ROUTE_RESPONSES,
    get_audit_store,
    get_approval_store,
    get_cap_guard_store,
    get_command_service,
    get_idempotency_store,
    get_live_execution_service,
    get_reconciliation_store,
    _build_envelope,
    _command_response,
    _execute_idempotent_command,
    _idempotency_payload_hash,
)


router = APIRouter()

OPERATOR_FUTURES_MANUAL_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED"
)
OPERATOR_FUTURES_POSITION_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_POSITION_ENABLED"
)

futures_place_route_contract = FUTURES_PLACE_ROUTE_CONTRACT
futures_close_reduce_route_contract = FUTURES_CLOSE_REDUCE_ROUTE_CONTRACT
futures_cancel_route_contract = FUTURES_CANCEL_ROUTE_CONTRACT
futures_reconcile_route_contract = FUTURES_RECONCILE_ROUTE_CONTRACT

READ_ONLY_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}

SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    501: {
        "model": AdminApiCommandResponse,
        "description": (
            "Fixed source-disabled response; no replay, admission, audit, "
            "service, adapter, or Coinbase execution occurs."
        ),
    },
}

FUTURES_MANUAL_ROUTE_RESPONSES = {
    **READ_ONLY_ROUTE_RESPONSES,
    409: {"model": AdminApiErrorResponse},
    422: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}


def require_operator_futures_product_ticket_enabled() -> None:
    if (
        os.environ.get(
            OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED_ENV
        )
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_product_ticket_disabled",
        )


def require_operator_futures_manual_enabled() -> None:
    if os.environ.get(OPERATOR_FUTURES_MANUAL_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_manual_disabled",
        )


def require_operator_futures_position_enabled() -> None:
    if os.environ.get(OPERATOR_FUTURES_POSITION_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_position_disabled",
        )


def require_operator_futures_order_operations_enabled() -> None:
    if (
        os.environ.get(
            OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED_ENV
        )
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_order_operations_disabled",
        )


def require_operator_futures_follow_up_intent_enabled() -> None:
    if (
        os.environ.get(
            OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED_ENV
        )
        != "1"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_follow_up_intent_disabled",
        )


def get_operator_futures_position_lifecycle_service(
) -> OperatorFuturesPositionLifecycleService:
    try:
        return get_default_operator_futures_position_lifecycle_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_position_backend_unavailable",
        ) from None


def get_operator_futures_manual_lifecycle_service(
) -> OperatorFuturesManualLifecycleService:
    try:
        return get_default_operator_futures_manual_lifecycle_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_manual_backend_unavailable",
        ) from None


def get_operator_futures_product_ticket_service(
) -> OperatorFuturesProductTicketService:
    try:
        return get_default_operator_futures_product_ticket_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_product_ticket_backend_unavailable",
        ) from None


def get_operator_futures_order_operations_service(
) -> OperatorFuturesOrderOperationsService:
    try:
        return get_default_operator_futures_order_operations_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_order_operations_backend_unavailable",
        ) from None


def get_operator_futures_follow_up_intent_service(
) -> OperatorFuturesFollowUpIntentService:
    try:
        return get_default_operator_futures_follow_up_intent_service()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_follow_up_intent_backend_unavailable",
        ) from None


def _futures_manual_readback(
    record: FuturesManualGoalRecord,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesManualReadback:
    execution_posture = (
        get_operator_futures_manual_execution_posture()
    )
    actor_can_refresh = actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CREATE,
    )
    actor_can_execute = (
        actor_can_refresh
        and actor_has_permission(
            actor,
            AdminApiPermission.ORDER_CANCEL,
        )
    )
    candidate_freshness = classify_futures_manual_candidate_freshness(
        record.candidate,
        now=datetime.now(timezone.utc),
    )
    candidate_fresh = (
        candidate_freshness
        == "operator_futures_manual_candidate_fresh"
    )
    allowed_actions: list[
        Literal["REFRESH_ELIGIBILITY", "EXECUTE_PREVIEW_GATED_PROOF"]
    ] = []
    if (
        record.active_cycle_number is None
        and record.preview_outcome.value == "NOT_RUN"
        and not is_futures_manual_goal_terminal(
            record.eligibility_diagnostic_code
        )
    ):
        if record.cycles_used < 10 and actor_can_refresh:
            allowed_actions.append("REFRESH_ELIGIBILITY")
        if (
            record.eligibility_outcome is not None
            and record.eligibility_outcome.value == "ELIGIBLE"
            and candidate_fresh
            and execution_posture.ready
            and actor_can_execute
        ):
            allowed_actions.append("EXECUTE_PREVIEW_GATED_PROOF")
    candidate = (
        OperatorFuturesManualCandidateReadback.model_validate(
            {
                field_name: record.candidate[field_name]
                for field_name in (
                    OperatorFuturesManualCandidateReadback.model_fields
                )
            }
        )
        if record.candidate is not None
        else None
    )
    return OperatorFuturesManualReadback(
        goal_id=record.goal_id,
        revision=record.revision,
        environment=os.environ.get(
            "COINBASE_ADMIN_API_ENVIRONMENT",
            "local",
        ),
        cycles_used=record.cycles_used,
        cycles_remaining=max(0, 10 - record.cycles_used),
        active_cycle_number=record.active_cycle_number,
        eligibility_outcome=record.eligibility_outcome,
        eligibility_diagnostic_code=(
            record.eligibility_diagnostic_code
        ),
        category_attempts=record.category_attempts,
        candidate=candidate,
        candidate_fresh_for_execution=candidate_fresh,
        candidate_freshness_diagnostic_code=candidate_freshness,
        candidate_sha256=record.candidate_sha256,
        portfolio_id_sha256=record.portfolio_id_sha256,
        eligibility_evidence_sha256=(
            record.eligibility_evidence_sha256
        ),
        execution_posture_ready=execution_posture.ready,
        execution_posture_diagnostic_code=(
            execution_posture.diagnostic_code
        ),
        client_order_id=record.client_order_id,
        preview=OperatorFuturesManualCallReadback(
            outcome=record.preview_outcome,
            call_boundary_entered=record.preview_exchange_invoked,
        ),
        preview_id_sha256=record.preview_id_sha256,
        create=OperatorFuturesManualCallReadback(
            outcome=record.create_outcome,
            call_boundary_entered=record.create_exchange_invoked,
        ),
        exchange_order_id_sha256=record.exchange_order_id_sha256,
        reconciliation=OperatorFuturesManualCallReadback(
            outcome=record.reconciliation_outcome,
            call_boundary_entered=(
                record.reconciliation_exchange_invoked
            ),
        ),
        order_status=record.order_status,
        authoritatively_nonterminal=(
            record.authoritatively_nonterminal
        ),
        cancel=OperatorFuturesManualCallReadback(
            outcome=record.cancel_outcome,
            call_boundary_entered=record.cancel_exchange_invoked,
        ),
        diagnostic_code=record.diagnostic_code,
        allowed_actions=allowed_actions,
        correlation_id=record.correlation_id,
        audit_id=record.audit_id,
        updated_at=record.updated_at,
    )


def _futures_manual_context(
    *,
    actor: AdminApiActor,
    body: (
        OperatorFuturesManualRefreshRequest
        | OperatorFuturesManualExecuteRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> FuturesManualRequestContext:
    refresh = (
        body
        if isinstance(body, OperatorFuturesManualRefreshRequest)
        else None
    )
    execute = (
        body
        if isinstance(body, OperatorFuturesManualExecuteRequest)
        else None
    )
    return FuturesManualRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid4()),
        operator_intent=operator_intent,
        authorize_one_no_retry_six_category_cycle=(
            refresh is not None
            and refresh.authorize_one_no_retry_six_category_cycle
        ),
        acknowledge_cycle_is_goal_global_and_limited_to_ten=(
            refresh is not None
            and refresh.acknowledge_cycle_is_goal_global_and_limited_to_ten
        ),
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=(
            refresh is not None
            and refresh.acknowledge_unsuccessful_or_unknown_cycle_fails_closed
        ),
        authorize_preview_create_and_safe_closeout=(
            execute is not None
            and execute.authorize_preview_create_and_safe_closeout
        ),
        acknowledge_unknown_outcome_consumes_allowance=(
            execute is not None
            and execute.acknowledge_unknown_outcome_consumes_allowance
        ),
        acknowledge_create_requires_accepted_identical_preview=(
            execute is not None
            and execute.acknowledge_create_requires_accepted_identical_preview
        ),
        acknowledge_cancel_is_only_for_exact_nonterminal_child=(
            execute is not None
            and execute.acknowledge_cancel_is_only_for_exact_nonterminal_child
        ),
    )


def _raise_futures_manual(exc: FuturesManualLifecycleError) -> None:
    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from None


def _require_futures_manual_live_runtime() -> None:
    if not get_operator_futures_manual_execution_posture().ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_manual_live_runtime_unavailable",
        )


_PRODUCT_POLICY_ACTION_READBACK = {
    "APPROVE": "APPROVE_PRODUCT",
    "ENABLE": "ENABLE_PRODUCT",
    "DISABLE": "DISABLE_PRODUCT",
    "RETIRE": "RETIRE_PRODUCT",
    "SELECT": "SELECT_PRODUCT",
}


def _futures_product_ticket_readback(
    state: FuturesProductTicketState,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesProductTicketReadback:
    policy = state.policy
    record = state.lifecycle
    posture = get_operator_futures_product_ticket_execution_posture()
    can_configure = actor_has_permission(
        actor,
        AdminApiPermission.CONFIG_UPDATE,
    )
    can_refresh = actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CREATE,
    )
    can_execute = (
        can_refresh
        and actor_has_permission(actor, AdminApiPermission.ORDER_CANCEL)
    )
    policy_goal_terminal = record.preview_outcome.value != "NOT_RUN"
    freshness = classify_futures_manual_candidate_freshness(
        record.candidate,
        now=datetime.now(timezone.utc),
    )
    candidate_fresh = (
        freshness == "operator_futures_manual_candidate_fresh"
    )
    allowed_actions: list[
        Literal[
            "APPROVE_PRODUCT",
            "ENABLE_PRODUCT",
            "DISABLE_PRODUCT",
            "RETIRE_PRODUCT",
            "SELECT_PRODUCT",
            "REFRESH_ELIGIBILITY",
            "EXECUTE_PREVIEW_GATED_PROOF",
        ]
    ] = []
    policy_actions_available: set[str] = set()
    products = []
    for item in policy.products:
        item_actions = (
            list(item.allowed_actions)
            if can_configure and not policy_goal_terminal
            else []
        )
        products.append(
            OperatorFuturesProductPolicyItemReadback(
                product_id=item.product_id,
                lifecycle=item.lifecycle,
                selected=(
                    item.product_id == policy.selected_product_id
                ),
                allowed_actions=item_actions,
            )
        )
        if can_configure:
            for action in item_actions:
                policy_actions_available.add(
                    _PRODUCT_POLICY_ACTION_READBACK[action]
                )
    for policy_action in (
        "APPROVE_PRODUCT",
        "ENABLE_PRODUCT",
        "DISABLE_PRODUCT",
        "RETIRE_PRODUCT",
        "SELECT_PRODUCT",
    ):
        if policy_action in policy_actions_available:
            allowed_actions.append(policy_action)
    if (
        record.active_cycle_number is None
        and record.preview_outcome.value == "NOT_RUN"
    ):
        if (
            record.cycles_used < 10
            and can_refresh
            and policy.selection is not None
        ):
            allowed_actions.append("REFRESH_ELIGIBILITY")
        if (
            record.eligibility_outcome is not None
            and record.eligibility_outcome.value == "ELIGIBLE"
            and candidate_fresh
            and posture.ready
            and can_execute
        ):
            allowed_actions.append("EXECUTE_PREVIEW_GATED_PROOF")
    candidate = (
        OperatorFuturesProductTicketCandidateReadback.model_validate(
            {
                field_name: record.candidate[field_name]
                for field_name in (
                    OperatorFuturesProductTicketCandidateReadback.model_fields
                )
            }
        )
        if record.candidate is not None
        else None
    )
    return OperatorFuturesProductTicketReadback(
        goal_id=record.goal_id,
        environment=os.environ.get(
            "COINBASE_ADMIN_API_ENVIRONMENT",
            "local",
        ),
        configured_product_scope=list(
            FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
        ),
        policy_revision=policy.revision,
        policy_snapshot_sha256=policy.snapshot_sha256,
        products=products,
        selected_product_id=policy.selected_product_id,
        selected_policy_revision=(
            policy.selection.policy_revision
            if policy.selection is not None
            else None
        ),
        selected_policy_sha256=(
            policy.selection.policy_sha256
            if policy.selection is not None
            else None
        ),
        ticket_revision=record.revision,
        cycles_used=record.cycles_used,
        cycles_remaining=max(0, 10 - record.cycles_used),
        active_cycle_number=record.active_cycle_number,
        eligibility_outcome=record.eligibility_outcome,
        eligibility_diagnostic_code=(
            record.eligibility_diagnostic_code.replace(
                "operator_futures_manual",
                "operator_futures_product_ticket",
            )
        ),
        category_attempts={
            category: int(record.category_attempts.get(category, 0))
            for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES
        },
        candidate=candidate,
        candidate_fresh_for_execution=candidate_fresh,
        candidate_freshness_diagnostic_code=(
            freshness.replace(
                "operator_futures_manual",
                "operator_futures_product_ticket",
            )
        ),
        candidate_sha256=record.candidate_sha256,
        portfolio_id_sha256=record.portfolio_id_sha256,
        eligibility_evidence_sha256=(
            record.eligibility_evidence_sha256
        ),
        execution_posture_ready=posture.ready,
        execution_posture_diagnostic_code=posture.diagnostic_code,
        client_order_id=record.client_order_id,
        preview=OperatorFuturesManualCallReadback(
            outcome=record.preview_outcome,
            call_boundary_entered=record.preview_exchange_invoked,
        ),
        preview_id_sha256=record.preview_id_sha256,
        create=OperatorFuturesManualCallReadback(
            outcome=record.create_outcome,
            call_boundary_entered=record.create_exchange_invoked,
        ),
        exchange_order_id_sha256=record.exchange_order_id_sha256,
        reconciliation=OperatorFuturesManualCallReadback(
            outcome=record.reconciliation_outcome,
            call_boundary_entered=(
                record.reconciliation_exchange_invoked
            ),
        ),
        order_status=record.order_status,
        authoritatively_nonterminal=record.authoritatively_nonterminal,
        cancel=OperatorFuturesManualCallReadback(
            outcome=record.cancel_outcome,
            call_boundary_entered=record.cancel_exchange_invoked,
        ),
        diagnostic_code=record.diagnostic_code.replace(
            "operator_futures_manual",
            "operator_futures_product_ticket",
        ),
        allowed_actions=allowed_actions,
        correlation_id=record.correlation_id,
        audit_id=record.audit_id,
        updated_at=record.updated_at or policy.updated_at,
    )


def _futures_product_ticket_context(
    *,
    actor: AdminApiActor,
    body: (
        OperatorFuturesProductTicketRefreshRequest
        | OperatorFuturesProductTicketExecuteRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> FuturesManualRequestContext:
    refresh = (
        body
        if isinstance(body, OperatorFuturesProductTicketRefreshRequest)
        else None
    )
    execute = (
        body
        if isinstance(body, OperatorFuturesProductTicketExecuteRequest)
        else None
    )
    return FuturesManualRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        expected_revision=body.expected_ticket_revision,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid4()),
        operator_intent=operator_intent,
        authorize_one_no_retry_six_category_cycle=(
            refresh is not None
            and refresh.authorize_one_no_retry_six_category_cycle
        ),
        acknowledge_cycle_is_goal_global_and_limited_to_ten=(
            refresh is not None
            and refresh.acknowledge_cycle_is_goal_global_and_limited_to_ten
        ),
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=(
            refresh is not None
            and refresh.acknowledge_unsuccessful_or_unknown_cycle_fails_closed
        ),
        authorize_preview_create_and_safe_closeout=(
            execute is not None
            and execute.authorize_preview_create_and_safe_closeout
        ),
        acknowledge_unknown_outcome_consumes_allowance=(
            execute is not None
            and execute.acknowledge_unknown_outcome_consumes_allowance
        ),
        acknowledge_create_requires_accepted_identical_preview=(
            execute is not None
            and execute.acknowledge_create_requires_accepted_identical_preview
        ),
        acknowledge_cancel_is_only_for_exact_nonterminal_child=(
            execute is not None
            and execute.acknowledge_cancel_is_only_for_exact_nonterminal_child
        ),
    )


def _raise_futures_product_ticket(
    exc: FuturesManualLifecycleError | OperatorFuturesProductPolicyError,
) -> None:
    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from None


def _require_futures_product_ticket_live_runtime() -> None:
    if not get_operator_futures_product_ticket_execution_posture().ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "operator_futures_product_ticket_"
                "live_runtime_unavailable"
            ),
        )


def _futures_position_readback(
    record: FuturesPositionGoalRecord,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesPositionLifecycleReadback:
    posture = get_operator_futures_position_execution_posture()
    actor_can_refresh = actor_has_permission(
        actor,
        AdminApiPermission.ORDER_CREATE,
    )
    actor_can_execute = (
        actor_can_refresh
        and actor_has_permission(actor, AdminApiPermission.ORDER_CANCEL)
    )
    freshness = classify_futures_position_selection_freshness(
        record.selection,
        now=datetime.now(timezone.utc),
    )
    fresh = freshness == "operator_futures_position_selection_fresh"
    allowed_actions: list[
        Literal[
            "REFRESH_SELECTED_POSITION",
            "CLOSE_FULL",
            "REDUCE_ONE_CONTRACT",
        ]
    ] = []
    if (
        record.active_cycle_number is None
        and record.action_outcome.value == "NOT_RUN"
    ):
        if record.cycles_used < 10 and actor_can_refresh:
            allowed_actions.append("REFRESH_SELECTED_POSITION")
        if (
            actor_can_execute
            and posture.ready
            and fresh
            and record.eligibility_outcome is not None
            and record.eligibility_outcome.value == "ELIGIBLE"
            and record.selection is not None
        ):
            allowed_actions.append("CLOSE_FULL")
            if record.selection.get("bounded_reduce_size") == "1":
                allowed_actions.append("REDUCE_ONE_CONTRACT")
    selection = (
        OperatorFuturesPositionSelectionReadback.model_validate(
            {
                field_name: record.selection[field_name]
                for field_name in (
                    OperatorFuturesPositionSelectionReadback.model_fields
                )
            }
        )
        if record.selection is not None
        else None
    )
    return OperatorFuturesPositionLifecycleReadback(
        goal_id=record.goal_id,
        revision=record.revision,
        environment=os.environ.get(
            "COINBASE_ADMIN_API_ENVIRONMENT",
            "local",
        ),
        cycles_used=record.cycles_used,
        cycles_remaining=max(0, 10 - record.cycles_used),
        active_cycle_number=record.active_cycle_number,
        eligibility_outcome=record.eligibility_outcome,
        eligibility_diagnostic_code=record.eligibility_diagnostic_code,
        category_attempts=record.category_attempts,
        selection=selection,
        selection_fresh_for_execution=fresh,
        selection_freshness_diagnostic_code=freshness,
        selection_sha256=record.selection_sha256,
        portfolio_id_sha256=record.portfolio_id_sha256,
        eligibility_evidence_sha256=record.eligibility_evidence_sha256,
        execution_posture_ready=posture.ready,
        execution_posture_diagnostic_code=posture.diagnostic_code,
        selected_mode=record.selected_mode,
        client_order_id=record.client_order_id,
        action_call=OperatorFuturesPositionCallReadback(
            outcome=record.action_outcome,
            call_boundary_entered=record.action_exchange_invoked,
        ),
        exchange_order_id_sha256=record.exchange_order_id_sha256,
        order_reconciliation=OperatorFuturesPositionCallReadback(
            outcome=record.order_reconciliation_outcome,
            call_boundary_entered=(
                record.order_reconciliation_exchange_invoked
            ),
        ),
        order_status=record.order_status,
        authoritatively_nonterminal=record.authoritatively_nonterminal,
        position_reconciliation=OperatorFuturesPositionCallReadback(
            outcome=record.position_reconciliation_outcome,
            call_boundary_entered=(
                record.position_reconciliation_exchange_invoked
            ),
        ),
        remaining_contracts=record.remaining_contracts,
        cancel=OperatorFuturesPositionCallReadback(
            outcome=record.cancel_outcome,
            call_boundary_entered=record.cancel_exchange_invoked,
        ),
        diagnostic_code=record.diagnostic_code,
        allowed_actions=allowed_actions,
        correlation_id=record.correlation_id,
        audit_id=record.audit_id,
        updated_at=record.updated_at,
    )


def _futures_position_context(
    *,
    actor: AdminApiActor,
    body: (
        OperatorFuturesPositionRefreshRequest
        | OperatorFuturesPositionExecuteRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> FuturesPositionRequestContext:
    refresh = (
        body
        if isinstance(body, OperatorFuturesPositionRefreshRequest)
        else None
    )
    execute = (
        body
        if isinstance(body, OperatorFuturesPositionExecuteRequest)
        else None
    )
    return FuturesPositionRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid4()),
        operator_intent=operator_intent,
        authorize_one_no_retry_six_category_cycle=(
            refresh is not None
            and refresh.authorize_one_no_retry_six_category_cycle
        ),
        acknowledge_cycle_is_goal_global_and_limited_to_ten=(
            refresh is not None
            and refresh.acknowledge_cycle_is_goal_global_and_limited_to_ten
        ),
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=(
            refresh is not None
            and refresh.acknowledge_unsuccessful_or_unknown_cycle_fails_closed
        ),
        authorize_exact_selected_position_action=(
            execute is not None
            and execute.authorize_exact_selected_position_action
        ),
        acknowledge_action_is_mutually_exclusive_and_single_use=(
            execute is not None
            and execute.acknowledge_action_is_mutually_exclusive_and_single_use
        ),
        acknowledge_unknown_outcome_consumes_allowance=(
            execute is not None
            and execute.acknowledge_unknown_outcome_consumes_allowance
        ),
        acknowledge_exact_order_cancel_only=(
            execute is not None
            and execute.acknowledge_exact_order_cancel_only
        ),
    )


def _raise_futures_position(
    exc: FuturesPositionLifecycleError,
) -> None:
    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from None


def _require_futures_position_live_runtime() -> None:
    if not get_operator_futures_position_execution_posture().ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_position_live_runtime_unavailable",
        )


def _futures_order_operations_readback(
    record: FuturesOrderOperationsGoalRecord,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesOrderOperationsReadback:
    posture = (
        get_operator_futures_order_operations_execution_posture()
    )
    can_refresh = actor_has_permission(
        actor, AdminApiPermission.ORDER_CREATE
    )
    can_cancel = actor_has_permission(
        actor, AdminApiPermission.ORDER_CANCEL
    )
    allowed_actions: list[
        Literal["REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"]
    ] = []
    if (
        record.active_cycle_number is None
        and record.cycles_used < 10
        and record.cancel_outcome != "CLAIMED"
    ):
        if can_refresh:
            allowed_actions.extend(
                ["REFRESH_CATALOG", "RECONCILE_EXACT"]
            )
        if (
            can_cancel
            and posture.ready
            and record.cancel_outcome == "NOT_RUN"
        ):
            allowed_actions.append("CANCEL_EXACT")
    return OperatorFuturesOrderOperationsReadback(
        goal_id=record.goal_id,
        revision=record.revision,
        environment=os.environ.get(
            "COINBASE_ADMIN_API_ENVIRONMENT", "local"
        ),
        cycles_used=record.cycles_used,
        cycles_remaining=max(0, 10 - record.cycles_used),
        active_cycle_number=record.active_cycle_number,
        last_action=record.last_action,
        last_target_client_order_id=(
            record.last_target_client_order_id
        ),
        last_outcome=record.last_outcome,
        diagnostic_code=record.diagnostic_code,
        category_attempts=record.category_attempts,
        page_count=record.page_count,
        order_count=record.order_count,
        portfolio_id_sha256=record.portfolio_id_sha256,
        evidence_sha256=record.evidence_sha256,
        cancel_outcome=record.cancel_outcome,
        cancel_exchange_invoked=record.cancel_exchange_invoked,
        cancel_target_client_order_id=(
            record.cancel_target_client_order_id
        ),
        cancel_exchange_order_id_sha256=(
            record.cancel_exchange_order_id_sha256
        ),
        execution_posture_ready=posture.ready,
        execution_posture_diagnostic_code=posture.diagnostic_code,
        allowed_actions=allowed_actions,
        correlation_id=record.correlation_id,
        audit_id=record.audit_id,
        refreshed_at=record.refreshed_at,
        updated_at=record.updated_at,
    )


def _futures_order_operations_historical_result(
    record: FuturesOrderOperationsGoalRecord,
    *,
    actor: AdminApiActor,
) -> OperatorFuturesOrderOperationsReadback:
    """Project immutable cycle evidence without current action authority."""

    return _futures_order_operations_readback(
        record,
        actor=actor,
    ).model_copy(
        update={
            "execution_posture_ready": False,
            "execution_posture_diagnostic_code": (
                "operator_futures_orders_historical_result_non_actionable"
            ),
            "allowed_actions": [],
        }
    )


def _futures_order_operations_context(
    *,
    actor: AdminApiActor,
    body: (
        OperatorFuturesOrderRefreshRequest
        | OperatorFuturesOrderCancelRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> FuturesOrderOperationsRequestContext:
    return FuturesOrderOperationsRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid4()),
        operator_intent=operator_intent,
        authorize_one_no_retry_cycle=(
            body.authorize_one_no_retry_cycle
        ),
        acknowledge_cycle_is_goal_global_and_limited_to_ten=(
            body.acknowledge_cycle_is_goal_global_and_limited_to_ten
        ),
        acknowledge_unknown_read_fails_closed=(
            body.acknowledge_unknown_read_fails_closed
        ),
        acknowledge_unknown_cancel_consumes_allowance=(
            isinstance(body, OperatorFuturesOrderCancelRequest)
            and body.acknowledge_unknown_cancel_consumes_allowance
        ),
    )


def _raise_futures_order_operations(exc: ValueError) -> None:
    code = (
        str(exc.args[0])
        if len(exc.args) == 1
        and isinstance(exc.args[0], str)
        and exc.args[0].startswith("operator_futures_")
        else "operator_futures_order_operations_failed"
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=code,
    ) from None


def _futures_follow_up_intent_response(
    readback: FuturesFollowUpIntentReadback,
    *,
    actor: AdminApiActor,
    replayed: bool | None = None,
) -> (
    OperatorFuturesFollowUpIntentReadResponse
    | OperatorFuturesFollowUpIntentAttachResponse
):
    allowed_actions: list[Literal["ATTACH_FOLLOW_UP_INTENT"]] = []
    if (
        readback.eligibility.eligible
        and readback.follow_up_intent is None
        and actor_has_permission(actor, AdminApiPermission.ORDER_CREATE)
    ):
        allowed_actions.append("ATTACH_FOLLOW_UP_INTENT")
    payload = {
        "goal_id": readback.goal_id,
        "source_client_order_id": readback.source_client_order_id,
        "environment": os.environ.get(
            "COINBASE_ADMIN_API_ENVIRONMENT", "local"
        ),
        "eligibility": asdict(readback.eligibility),
        "follow_up_intent": (
            asdict(readback.follow_up_intent)
            if readback.follow_up_intent is not None
            else None
        ),
        "allowed_actions": allowed_actions,
        "coinbase_calls": readback.coinbase_calls,
        "child_created": readback.child_created,
        "raw_responses_included": readback.raw_responses_included,
        "private_identifiers_included": (
            readback.private_identifiers_included
        ),
        "exception_text_included": readback.exception_text_included,
    }
    if replayed is None:
        return OperatorFuturesFollowUpIntentReadResponse(**payload)
    return OperatorFuturesFollowUpIntentAttachResponse(
        **payload,
        replayed=replayed,
    )


def _raise_futures_follow_up_intent(exc: ValueError) -> None:
    code = (
        str(exc.args[0])
        if len(exc.args) == 1
        and isinstance(exc.args[0], str)
        and exc.args[0].startswith("operator_futures_follow_up_intent_")
        else "operator_futures_follow_up_intent_failed"
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=code,
    ) from None


def _require_futures_order_operations_cancel_runtime() -> None:
    if not get_operator_futures_order_operations_execution_posture().ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_futures_order_operations_live_runtime_unavailable",
        )


def get_futures_risk_proof_store() -> FileFuturesRiskProofStore:
    """Return the append-only futures risk proof store."""

    return FileFuturesRiskProofStore()


def get_live_service_decision_store() -> FileAdminApiLiveServiceDecisionStore:
    """Return the append-only live-service decision store."""

    return FileAdminApiLiveServiceDecisionStore()


def get_live_adapter_decision_store() -> FileAdminApiLiveAdapterDecisionStore:
    """Return the append-only live-adapter decision store."""

    return FileAdminApiLiveAdapterDecisionStore()


def get_read_service(
    futures_risk_proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
    live_service_decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_live_service_decision_store),
    ],
    live_adapter_decision_store: Annotated[
        FileAdminApiLiveAdapterDecisionStore,
        Depends(get_live_adapter_decision_store),
    ],
) -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService(
        futures_risk_proof_store=futures_risk_proof_store,
        live_service_decision_store=live_service_decision_store,
        live_adapter_decision_store=live_adapter_decision_store,
    )


def get_authoritative_futures_read_service() -> AdminMvpService:
    """Return the local source-disabled Futures evidence service."""

    return get_admin_mvp_service()


def get_futures_order_preview_store() -> FuturesPreviewR12ArtifactStore:
    """Return the fixed R12 reader without historical selector fallback."""

    return FuturesPreviewR12ArtifactStore(
        FUTURES_PREVIEW_R12_ARTIFACT_PATH,
        enforce_latest_selection=False,
    )


TReadModel = TypeVar("TReadModel", bound=BaseModel)


def _read_model_response(model: type[TReadModel], payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(model.model_validate(payload)))


def _authoritative_read_model_response(
    model: type[TReadModel],
    result: object,
) -> JSONResponse:
    status_code = int(getattr(result, "status_code"))
    body = getattr(result, "body")
    headers = dict(getattr(result, "headers", {}))
    content = (
        jsonable_encoder(model.model_validate(body))
        if status_code == status.HTTP_200_OK
        else jsonable_encoder(body)
    )
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _admin_mvp_context(
    actor: AdminApiActor,
    *,
    idempotency_key: str | None,
    correlation_id: str | None,
    operator_intent: str | None,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=(idempotency_key or "admin-api-read").strip()
        or "admin-api-read",
        correlation_id=(correlation_id or "admin-api-correlation").strip()
        or "admin-api-correlation",
        operator_intent=(operator_intent or "read_futures_fill_readback").strip()
        or "read_futures_fill_readback",
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
    )


def _risk_proof_record_item(record: object) -> FuturesRiskProofRecordItem:
    return FuturesRiskProofRecordItem.model_validate(
        record.model_dump(mode="json")
    )


@router.get(
    "/futures/command-suite",
    response_model=AdminFuturesCommandSuiteResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual command contract readiness",
)
def get_futures_command_suite(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read blocked M57 futures/perpetual command contract evidence."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return JSONResponse(
        content=futures_command_suite_api_payload(
            service.build_futures_command_suite()
        )
    )


@router.get(
    "/futures/risk-proofs",
    response_model=FuturesRiskProofListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual risk proof records",
)
def list_futures_risk_proofs(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
    command: AdminFuturesCommandAction | None = None,
    proof_kind: AdminFuturesCommandRiskProofKind | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read persisted futures/perpetual risk proof evidence."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    if command is None:
        records = proof_store.read_recent(limit=limit)
    else:
        records = proof_store.read_for_command(
            command=command,
            proof_kind=proof_kind,
            limit=limit,
        )
    if command is None and proof_kind is not None:
        records = [
            record
            for record in records
            if record.proof_kind == proof_kind
        ][:limit]
    response = FuturesRiskProofListResponse(
        filters={
            "command": command.value if command else None,
            "proof_kind": proof_kind.value if proof_kind else None,
            "limit": limit,
        },
        count=len(records),
        items=[_risk_proof_record_item(record) for record in records],
        proof_records_created=bool(records),
    )
    return _read_model_response(FuturesRiskProofListResponse, response)


@router.get(
    "/futures/risk-proofs/{futures_risk_proof_id}",
    response_model=FuturesRiskProofDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one futures or perpetual risk proof record",
)
def get_futures_risk_proof(
    futures_risk_proof_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
) -> JSONResponse:
    """Read one persisted futures/perpetual risk proof by proof id."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    record = proof_store.find_by_proof_id(futures_risk_proof_id)
    response = FuturesRiskProofDetailResponse(
        futures_risk_proof_id=futures_risk_proof_id,
        found=record is not None,
        record=_risk_proof_record_item(record) if record is not None else None,
        proof_record_created=record is not None,
    )
    return _read_model_response(FuturesRiskProofDetailResponse, response)


@router.get(
    "/futures/orders/{client_order_id}/fill-readback",
    response_model=FuturesFillReadbackResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read Futures/Perpetual order fill evidence by client_order_id",
)
def get_futures_order_fill_readback(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    product_id: str | None = None,
    backend_contract_ref: str | None = None,
    fill_limit: Annotated[int, Query(ge=1, le=500)] = 100,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    query: dict[str, Any] = {"fill_limit": str(fill_limit)}
    if product_id is not None:
        query["product_id"] = product_id
    if backend_contract_ref is not None:
        query["backend_contract_ref"] = backend_contract_ref
    result = get_admin_mvp_service().get_read_response(
        f"/api/v1/futures/orders/{client_order_id}/fill-readback",
        query,
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_futures_fill_readback",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/futures/order-operations",
    response_model=OperatorFuturesOrderListResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="List durable Default-profile Futures order projections",
)
def list_operator_futures_orders(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
    product_id: str | None = None,
    order_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read PostgreSQL projections without invoking Coinbase."""

    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    payload = service.list_orders(
        product_id=product_id,
        order_status=order_status,
        limit=limit,
        offset=offset,
    )
    response = OperatorFuturesOrderListResponse(
        authority=_futures_order_operations_readback(
            service.read_goal(), actor=actor
        ),
        filters=payload["filters"],
        pagination=payload["pagination"],
        items=payload["items"],
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.get(
    "/futures/order-operations/mutation-results/{request_correlation_id}",
    response_model=OperatorFuturesOrderMutationResolutionResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Resolve one immutable Futures order mutation result",
)
def get_operator_futures_order_mutation_result(
    request_correlation_id: Annotated[
        str,
        Path(min_length=1, max_length=255),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
) -> JSONResponse:
    """Read one actor-bound cycle result without invoking Coinbase."""

    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        found, terminal, record = service.read_cycle_result(
            correlation_id=request_correlation_id,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        _raise_futures_order_operations(exc)
    response = OperatorFuturesOrderMutationResolutionResponse(
        request_correlation_id=request_correlation_id,
        found=found,
        terminal=terminal,
        result=(
            _futures_order_operations_historical_result(
                record,
                actor=actor,
            )
            if record is not None
            else None
        ),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.get(
    "/futures/order-operations/{client_order_id}",
    response_model=OperatorFuturesOrderDetailResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Read one durable Default-profile Futures order",
)
def get_operator_futures_order(
    client_order_id: Annotated[str, Path(min_length=1, max_length=128)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
) -> JSONResponse:
    """Read exact detail by operator-facing client_order_id."""

    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    item = service.get_order(client_order_id)
    response = OperatorFuturesOrderDetailResponse(
        authority=_futures_order_operations_readback(
            service.read_goal(), actor=actor
        ),
        client_order_id=client_order_id,
        found=item is not None,
        order=item,
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.get(
    "/futures/order-operations/{client_order_id}/follow-up-intent",
    response_model=OperatorFuturesFollowUpIntentReadResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Read one local Futures follow-up intent attachment",
)
def get_operator_futures_follow_up_intent(
    client_order_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesFollowUpIntentService,
        Depends(get_operator_futures_follow_up_intent_service),
    ],
) -> JSONResponse:
    """Read call-free attachment eligibility from PostgreSQL."""

    require_operator_futures_follow_up_intent_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        readback = service.read(client_order_id)
    except ValueError as exc:
        _raise_futures_follow_up_intent(exc)
    return JSONResponse(
        content=jsonable_encoder(
            _futures_follow_up_intent_response(
                readback,
                actor=actor,
            )
        )
    )


@router.post(
    "/futures/order-operations/{client_order_id}/follow-up-intent",
    response_model=OperatorFuturesFollowUpIntentAttachResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Attach one local backend-owned Futures follow-up intent",
)
def attach_operator_futures_follow_up_intent(
    body: OperatorFuturesFollowUpIntentAttachRequest,
    client_order_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["attach_futures_follow_up_intent"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesFollowUpIntentService,
        Depends(get_operator_futures_follow_up_intent_service),
    ],
) -> JSONResponse:
    """Persist an intent only; never invoke Coinbase or create a child."""

    require_operator_futures_follow_up_intent_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        readback, replayed = service.attach(
            context=FuturesFollowUpIntentRequestContext(
                actor_id=actor.actor_id,
                roles=tuple(role.value for role in actor.roles),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=str(uuid4()),
                operator_intent=operator_intent,
                reason_code=body.reason_code,
                acknowledge_future_materialization_requires_fresh_authorization=(
                    body
                    .acknowledge_future_materialization_requires_fresh_authorization
                ),
                acknowledge_no_coinbase_call_or_child_creation=(
                    body.acknowledge_no_coinbase_call_or_child_creation
                ),
            ),
            source_client_order_id=client_order_id,
            expected_source_observed_at=(
                body.expected_source_observed_at
            ),
            expected_source_evidence_sha256=(
                body.expected_source_evidence_sha256
            ),
        )
    except ValueError as exc:
        _raise_futures_follow_up_intent(exc)
    return JSONResponse(
        content=jsonable_encoder(
            _futures_follow_up_intent_response(
                readback,
                actor=actor,
                replayed=replayed,
            )
        )
    )


@router.post(
    "/futures/order-operations/refresh",
    response_model=OperatorFuturesOrderMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Run one no-retry Default-profile Futures order catalog cycle",
)
def refresh_operator_futures_orders(
    body: OperatorFuturesOrderRefreshRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["refresh_futures_order_catalog"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
) -> JSONResponse:
    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        record = service.refresh_catalog(
            context=_futures_order_operations_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            )
        )
    except ValueError as exc:
        _raise_futures_order_operations(exc)
    response = OperatorFuturesOrderMutationResponse(
        action="REFRESH_CATALOG",
        result=_futures_order_operations_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/order-operations/{client_order_id}/reconciliation",
    response_model=OperatorFuturesOrderMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Reconcile one Futures order by client_order_id",
)
def reconcile_operator_futures_order(
    body: OperatorFuturesOrderRefreshRequest,
    client_order_id: Annotated[str, Path(min_length=1, max_length=128)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["reconcile_exact_futures_order"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
) -> JSONResponse:
    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        record = service.reconcile_exact(
            context=_futures_order_operations_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
            client_order_id=client_order_id,
        )
    except ValueError as exc:
        _raise_futures_order_operations(exc)
    response = OperatorFuturesOrderMutationResponse(
        action="RECONCILE_EXACT",
        result=_futures_order_operations_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


def _source_disabled_futures_command_response(
    *,
    actor: AdminApiActor,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission,
    service_method: str,
    command: AdminFuturesCommandAction,
    identity_key: str,
    identity_value: str,
) -> JSONResponse:
    """Return fixed 501 evidence before admission, replay, or mutation code."""

    require_permission(actor, required_permission)
    response = AdminApiCommandResponse(
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        action_class=action_class,
        required_permission=required_permission,
        service_method=service_method,
        message=FUTURES_COMMAND_SOURCE_DISABLED_MESSAGE,
        client_order_id=(
            identity_value if identity_key == "client_order_id" else None
        ),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        live_exchange_submitted=False,
        live_coinbase_orders_ran=False,
        data={
            "command": command.value,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "operator_intent_present": bool(operator_intent.strip()),
            "source_disabled": True,
            "source_disabled_reason": FUTURES_COMMAND_SERVICE_SOURCE_DISABLED,
            "coinbase_order_submitted": False,
            "coinbase_cancel_submitted": False,
            "reconciliation_executed": False,
            "futures_state_mutated": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "live_adapter_invoked": False,
            "browser_authority": "display_only",
            "bff_authority": "source_disabled_not_forwarded",
            "spot_rule_authority": False,
        },
        failure_stage=FUTURES_COMMAND_SERVICE_SOURCE_DISABLED,
    )
    return _command_response(response)


@router.get(
    "/futures/product-ticket",
    response_model=OperatorFuturesProductTicketReadback,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Read the durable Futures product policy and selected ticket",
)
def get_operator_futures_product_ticket(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> OperatorFuturesProductTicketReadback:
    """Read PostgreSQL authority without invoking Coinbase."""

    require_operator_futures_product_ticket_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _futures_product_ticket_readback(
        service.read(),
        actor=actor,
    )


def _apply_futures_product_policy(
    *,
    action: Literal["APPROVE", "ENABLE", "DISABLE", "RETIRE", "SELECT"],
    response_action: Literal[
        "APPROVE_PRODUCT",
        "ENABLE_PRODUCT",
        "DISABLE_PRODUCT",
        "RETIRE_PRODUCT",
        "SELECT_PRODUCT",
    ],
    product_id: str,
    body: OperatorFuturesProductPolicyRequest,
    actor: AdminApiActor,
    service: OperatorFuturesProductTicketService,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
) -> JSONResponse:
    require_operator_futures_product_ticket_enabled()
    require_permission(actor, AdminApiPermission.CONFIG_UPDATE)
    try:
        state = service.apply_policy(
            action=action,
            product_id=product_id,
            expected_revision=body.expected_policy_revision,
            actor_id=actor.actor_id,
            roles=tuple(role.value for role in actor.roles),
            operator_reason=body.operator_reason,
            operator_intent=operator_intent,
            confirm_exact_product_policy_action=(
                body.confirm_exact_product_policy_action
            ),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    except OperatorFuturesProductPolicyError as exc:
        _raise_futures_product_ticket(exc)
    response = OperatorFuturesProductTicketMutationResponse(
        action=response_action,
        result=_futures_product_ticket_readback(state, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/product-ticket/products/{product_id}/approve",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Approve one exact configured Futures product",
)
def approve_operator_futures_product(
    product_id: Annotated[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        Path(),
    ],
    body: OperatorFuturesProductPolicyRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["approve_exact_futures_product_for_operator_ticket"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    return _apply_futures_product_policy(
        action="APPROVE",
        response_action="APPROVE_PRODUCT",
        product_id=product_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/futures/product-ticket/products/{product_id}/enable",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Enable one approved Futures product",
)
def enable_operator_futures_product(
    product_id: Annotated[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        Path(),
    ],
    body: OperatorFuturesProductPolicyRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["enable_exact_futures_product_for_operator_ticket"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    return _apply_futures_product_policy(
        action="ENABLE",
        response_action="ENABLE_PRODUCT",
        product_id=product_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/futures/product-ticket/products/{product_id}/disable",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Disable one configured Futures product",
)
def disable_operator_futures_product(
    product_id: Annotated[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        Path(),
    ],
    body: OperatorFuturesProductPolicyRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["disable_exact_futures_product_for_operator_ticket"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    return _apply_futures_product_policy(
        action="DISABLE",
        response_action="DISABLE_PRODUCT",
        product_id=product_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/futures/product-ticket/products/{product_id}/retire",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Retire one configured Futures product",
)
def retire_operator_futures_product(
    product_id: Annotated[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        Path(),
    ],
    body: OperatorFuturesProductPolicyRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["retire_exact_futures_product_for_operator_ticket"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    return _apply_futures_product_policy(
        action="RETIRE",
        response_action="RETIRE_PRODUCT",
        product_id=product_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/futures/product-ticket/products/{product_id}/select",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Select one enabled Futures product for the operator ticket",
)
def select_operator_futures_product(
    product_id: Annotated[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        Path(),
    ],
    body: OperatorFuturesProductPolicyRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["select_exact_futures_product_for_operator_ticket"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    return _apply_futures_product_policy(
        action="SELECT",
        response_action="SELECT_PRODUCT",
        product_id=product_id,
        body=body,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )


@router.post(
    "/futures/product-ticket/eligibility",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Refresh exact selected-product Futures eligibility",
)
def refresh_operator_futures_product_ticket_eligibility(
    body: OperatorFuturesProductTicketRefreshRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal[
            "refresh_one_futures_product_ticket_eligibility_cycle"
        ],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    require_operator_futures_product_ticket_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        state = service.refresh(
            context=_futures_product_ticket_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            )
        )
    except FuturesManualLifecycleError as exc:
        _raise_futures_product_ticket(exc)
    response = OperatorFuturesProductTicketMutationResponse(
        action="REFRESH_ELIGIBILITY",
        result=_futures_product_ticket_readback(state, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/product-ticket/execute",
    response_model=OperatorFuturesProductTicketMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Execute one selected-product Preview-gated Futures proof",
)
def execute_operator_futures_product_ticket(
    body: OperatorFuturesProductTicketExecuteRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal[
            "preview_submit_and_safe_closeout_one_futures_product_ticket"
        ],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesProductTicketService,
        Depends(get_operator_futures_product_ticket_service),
    ],
) -> JSONResponse:
    require_operator_futures_product_ticket_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    _require_futures_product_ticket_live_runtime()
    try:
        state = service.execute(
            context=_futures_product_ticket_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            )
        )
    except FuturesManualLifecycleError as exc:
        _raise_futures_product_ticket(exc)
    response = OperatorFuturesProductTicketMutationResponse(
        action="EXECUTE_PREVIEW_GATED_PROOF",
        result=_futures_product_ticket_readback(state, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.get(
    "/futures/manual-lifecycle",
    response_model=OperatorFuturesManualReadback,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Read the durable manual Futures lifecycle",
)
def get_operator_futures_manual_lifecycle(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesManualLifecycleService,
        Depends(get_operator_futures_manual_lifecycle_service),
    ],
) -> JSONResponse:
    """Read backend-owned V3 eligibility and single-use call accounting."""

    require_operator_futures_manual_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return JSONResponse(
        content=jsonable_encoder(
            _futures_manual_readback(service.read(), actor=actor)
        )
    )


@router.post(
    "/futures/manual-lifecycle/eligibility",
    response_model=OperatorFuturesManualMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Run one no-retry six-category Futures eligibility cycle",
)
def refresh_operator_futures_manual_eligibility(
    body: OperatorFuturesManualRefreshRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["refresh_one_futures_manual_eligibility_cycle"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesManualLifecycleService,
        Depends(get_operator_futures_manual_lifecycle_service),
    ],
) -> JSONResponse:
    """Run only the approved six read-only Coinbase categories once."""

    require_operator_futures_manual_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        record = service.refresh(
            context=_futures_manual_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            )
        )
    except FuturesManualLifecycleError as exc:
        _raise_futures_manual(exc)
    response = OperatorFuturesManualMutationResponse(
        action="REFRESH_ELIGIBILITY",
        result=_futures_manual_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/manual-lifecycle/execute",
    response_model=OperatorFuturesManualMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Execute one preview-gated Futures proof and safe closeout",
)
def execute_operator_futures_manual_lifecycle(
    body: OperatorFuturesManualExecuteRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["preview_submit_and_safe_closeout_one_futures_order"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesManualLifecycleService,
        Depends(get_operator_futures_manual_lifecycle_service),
    ],
) -> JSONResponse:
    """Preview, identically Create, reconcile once, and conditionally Cancel."""

    require_operator_futures_manual_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    _require_futures_manual_live_runtime()
    try:
        record = service.execute(
            context=_futures_manual_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            )
        )
    except FuturesManualLifecycleError as exc:
        _raise_futures_manual(exc)
    response = OperatorFuturesManualMutationResponse(
        action="EXECUTE_PREVIEW_GATED_PROOF",
        result=_futures_manual_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.get(
    "/futures/position-lifecycle",
    response_model=OperatorFuturesPositionLifecycleReadback,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Read the durable selected-position lifecycle",
)
def get_operator_futures_position_lifecycle(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesPositionLifecycleService,
        Depends(get_operator_futures_position_lifecycle_service),
    ],
) -> JSONResponse:
    """Read Goal 11 eligibility and single-use action accounting."""

    require_operator_futures_position_enabled()
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return JSONResponse(
        content=jsonable_encoder(
            _futures_position_readback(service.read(), actor=actor)
        )
    )


@router.post(
    "/futures/position-lifecycle/eligibility",
    response_model=OperatorFuturesPositionMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Refresh one selected Futures position without retry",
)
def refresh_operator_futures_position_eligibility(
    body: OperatorFuturesPositionRefreshRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["refresh_one_futures_position_eligibility_cycle"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesPositionLifecycleService,
        Depends(get_operator_futures_position_lifecycle_service),
    ],
) -> JSONResponse:
    """Bind six no-retry reads to one backend opaque position key."""

    require_operator_futures_position_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    try:
        record = service.refresh(
            context=_futures_position_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
            position_key=body.position_key,
        )
    except FuturesPositionLifecycleError as exc:
        _raise_futures_position(exc)
    response = OperatorFuturesPositionMutationResponse(
        action="REFRESH_SELECTED_POSITION",
        result=_futures_position_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/position-lifecycle/execute",
    response_model=OperatorFuturesPositionMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Close or reduce one selected Futures position",
)
def execute_operator_futures_position_lifecycle(
    body: OperatorFuturesPositionExecuteRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["authorize_one_futures_position_close_or_reduce"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesPositionLifecycleService,
        Depends(get_operator_futures_position_lifecycle_service),
    ],
) -> JSONResponse:
    """Submit one mode, reconcile order/position, and conditionally Cancel."""

    require_operator_futures_position_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    _require_futures_position_live_runtime()
    try:
        record = service.execute(
            context=_futures_position_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
            mode=body.mode,
        )
    except FuturesPositionLifecycleError as exc:
        _raise_futures_position(exc)
    response = OperatorFuturesPositionMutationResponse(
        action=body.mode,
        result=_futures_position_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/orders",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses=SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES,
    summary="Return fixed source-disabled Futures placement evidence",
)
def place_futures_order(
    body: FuturesPlaceOrderRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    """Reject Futures placement at the installed source-disabled boundary."""

    return _source_disabled_futures_command_response(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_futures_order",
        command=AdminFuturesCommandAction.PLACE,
        identity_key="product_id",
        identity_value=body.product_id,
    )


@router.post(
    "/futures/positions/{position_key}/close-reduce",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses=SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES,
    summary="Return fixed source-disabled Futures close/reduce evidence",
)
def close_or_reduce_futures_position(
    body: FuturesCloseReduceRequest,
    position_key: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    """Reject Futures close/reduce at the source-disabled boundary."""

    return _source_disabled_futures_command_response(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="close_or_reduce_futures_position",
        command=AdminFuturesCommandAction.CLOSE_REDUCE,
        identity_key="position_key",
        identity_value=position_key,
    )


@router.post(
    "/futures/order-operations/{client_order_id}/cancel",
    response_model=OperatorFuturesOrderMutationResponse,
    responses=FUTURES_MANUAL_ROUTE_RESPONSES,
    summary="Cancel one freshly reconciled Default-profile Futures order",
)
def cancel_operator_futures_order(
    body: OperatorFuturesOrderCancelRequest,
    client_order_id: Annotated[
        str, Path(min_length=1, max_length=128)
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", min_length=1, max_length=255),
    ],
    operator_intent: Annotated[
        Literal["cancel_exact_futures_order"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFuturesOrderOperationsService,
        Depends(get_operator_futures_order_operations_service),
    ],
) -> JSONResponse:
    """Reconcile once, then consume the independent exact Cancel allowance."""

    require_operator_futures_order_operations_enabled()
    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    _require_futures_order_operations_cancel_runtime()
    try:
        record = service.cancel_exact(
            context=_futures_order_operations_context(
                actor=actor,
                body=body,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
            ),
            client_order_id=client_order_id,
        )
    except ValueError as exc:
        _raise_futures_order_operations(exc)
    response = OperatorFuturesOrderMutationResponse(
        action="CANCEL_EXACT",
        result=_futures_order_operations_readback(record, actor=actor),
    )
    return JSONResponse(content=jsonable_encoder(response))


@router.post(
    "/futures/orders/{client_order_id}/cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses=SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES,
    summary="Return fixed source-disabled legacy Futures cancel evidence",
)
def cancel_futures_order(
    body: FuturesCancelOrderRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1)
    ],
    correlation_id: Annotated[
        str, Header(alias="X-Correlation-Id", min_length=1)
    ],
    operator_intent: Annotated[
        str, Header(alias="X-Operator-Intent", min_length=1)
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    """Reject the legacy generic Futures cancel draft."""

    return _source_disabled_futures_command_response(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_futures_order",
        command=AdminFuturesCommandAction.CANCEL,
        identity_key="client_order_id",
        identity_value=client_order_id,
    )


@router.post(
    "/futures/positions/{position_key}/reconciliation",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses=SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES,
    summary="Return fixed source-disabled Futures reconciliation evidence",
)
def reconcile_futures_position(
    body: FuturesReconciliationRequest,
    position_key: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    """Reject Futures reconciliation at the source-disabled boundary."""

    return _source_disabled_futures_command_response(
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.RECONCILIATION_RECORD,
        service_method="reconcile_futures_position",
        command=AdminFuturesCommandAction.RECONCILE,
        identity_key="position_key",
        identity_value=position_key,
    )


@router.post(
    "/futures/risk-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record futures and perpetual risk proof evidence",
)
def record_futures_risk_proof(
    request: Request,
    body: FuturesRiskProofRecordRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for backend-owned no-live futures risk proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    identity_value = f"{body.command.value}:{body.proof_kind.value}"
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_futures_risk_proof",
        route_template="/api/v1/futures/risk-proofs",
        module_id="futures_perpetuals",
        identity_key="futures_risk_proof",
        identity_value=identity_value,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner_with_admission=lambda admission_decision: (
            service.record_futures_risk_proof(
                FuturesRiskProofRecordCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.get(
    "/futures/order-preview",
    response_model=AdminFuturesOrderPreviewR12Response,
    responses={
        **READ_ONLY_ROUTE_RESPONSES,
        503: {
            "model": AdminApiErrorResponse,
            "description": "Preview evidence is missing, incomplete, or invalid.",
        },
    },
    summary="Read immutable Futures Preview evidence",
)
def get_futures_order_preview(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    store: Annotated[
        FuturesPreviewR12ArtifactStore,
        Depends(get_futures_order_preview_store),
    ],
) -> JSONResponse:
    """Read the terminal artifact without constructing a Coinbase client."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        payload = store.read_completed()
        validated = AdminFuturesOrderPreviewR12Response.model_validate(
            payload
        )
    except (FuturesOrderPreviewArtifactError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Futures Preview evidence is unavailable or invalid",
        ) from exc
    return JSONResponse(
        content=jsonable_encoder(validated.model_dump(mode="json"))
    )


@router.get(
    "/futures/account",
    response_model=AdminFuturesAccountReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual account risk evidence",
)
def get_futures_account(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminMvpService,
        Depends(get_authoritative_futures_read_service),
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    """Read futures/perpetual account evidence without mutating exchange state."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    result = service.get_read_response(
        "/api/v1/futures/account",
        {},
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_futures_account_reality",
        ),
    )
    return _authoritative_read_model_response(
        AdminFuturesAccountReadResponse,
        result,
    )


@router.get(
    "/futures/positions",
    response_model=AdminFuturesPositionListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual positions",
)
def list_futures_positions(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminMvpService,
        Depends(get_authoritative_futures_read_service),
    ],
    product_id: str | None = None,
    position_side: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    """Read futures/perpetual positions by position identity."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    query: dict[str, Any] = {
        "limit": str(limit),
        "offset": str(offset),
    }
    if product_id is not None:
        query["product_id"] = product_id
    if position_side is not None:
        query["position_side"] = position_side
    result = service.get_read_response(
        "/api/v1/futures/positions",
        query,
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_futures_positions",
        ),
    )
    return _authoritative_read_model_response(
        AdminFuturesPositionListResponse,
        result,
    )


@router.get(
    "/futures/positions/{position_key}",
    response_model=AdminFuturesPositionDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one futures or perpetual position by position_key",
)
def get_futures_position_by_position_key(
    position_key: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminMvpService,
        Depends(get_authoritative_futures_read_service),
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    """Read one futures/perpetual position by backend-defined position key."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    result = service.get_read_response(
        f"/api/v1/futures/positions/{position_key}",
        {},
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_futures_position_detail",
        ),
    )
    return _authoritative_read_model_response(
        AdminFuturesPositionDetailResponse,
        result,
    )
