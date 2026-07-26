"""Canonical Admin API adapter for one claimed Hotpoint child Create."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from threading import Lock
from typing import Any

from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    AdminApiRole,
    OrderSide,
    OrderType,
    TimeInForce,
)

from .models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
)
from .live_execution import (
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    AdminApiLiveExecutionServiceState,
    get_decision_backed_live_execution_service,
    operator_futures_manual_live_service_state_allows_route_admission,
)
from .operator_mvp_policy import (
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
)
from .operator_hotpoint_control import (
    FUTURES_HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HOTPOINT_RUN_OPERATOR_INTENT,
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
    HotpointCancelExecution,
    HotpointCancelPlan,
    HotpointCancelState,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointPlacementExecution,
    HotpointPlacementOutcome,
    HotpointPlacementPlan,
    HotpointWindowState,
    OperatorHotpointControlError,
    OperatorHotpointControlRecord,
    OperatorHotpointControlService,
    SPOT_HOTPOINT_SCOPE_POLICY,
)


def _actor(plan: HotpointPlacementPlan) -> AdminApiActor:
    try:
        roles = [AdminApiRole(role) for role in plan.roles]
    except ValueError:
        raise ValueError("operator_hotpoint_actor_invalid") from None
    if not roles:
        raise ValueError("operator_hotpoint_actor_invalid")
    return AdminApiActor(actor_id=plan.actor_id, roles=roles)


def _compose_command(plan: HotpointPlacementPlan) -> ManualOrderCommand:
    request = ManualOrderRequest(
        client_order_id=plan.child_client_order_id,
        product_id=plan.product_id,
        side=OrderSide(plan.side),
        order_type=OrderType.LIMIT,
        base_size=str(plan.base_size),
        limit_price=str(plan.limit_price),
        post_only=plan.post_only,
        time_in_force=TimeInForce.GOOD_UNTIL_CANCELLED,
        manual_live_acknowledgement=True,
    )
    envelope = AdminApiCommandEnvelope(
        idempotency_key=plan.placement_claim_id,
        correlation_id=plan.correlation_id,
        operator_intent=HOTPOINT_RUN_OPERATOR_INTENT,
        actor=_actor(plan),
    )
    return ManualOrderCommand(
        envelope=envelope,
        request=request,
        admin_max_submitted_notional_usdc=str(
            plan.max_submitted_notional_usdc
        ),
        admin_max_executed_notional_usdc=str(
            plan.max_possible_execution_notional_usdc
        ),
        admission_audit_id=plan.audit_id,
        allow_live_execution=True,
        hotpoint_goal_id=plan.goal_id,
        hotpoint_parent_client_order_id=plan.parent_client_order_id,
        hotpoint_plan_sha256=plan.evidence_sha256,
        hotpoint_portfolio_id=plan.portfolio_id,
    )


def _fixed_error(response: AdminApiCommandResponse) -> str | None:
    data = response.data
    if not isinstance(data, Mapping):
        return None
    value = data.get("error")
    if value in {
        "operator_hotpoint_create_rejected",
        "operator_hotpoint_create_outcome_unknown",
    }:
        return str(value)
    return None


class AdminApiHotpointPlacementExecutor:
    """Map one immutable plan into the shared guarded placement service."""

    def __init__(
        self,
        *,
        command_service_getter: Callable[[], Any] | None = None,
    ) -> None:
        self._command_service_getter = (
            command_service_getter or self._default_command_service
        )

    @staticmethod
    def _default_command_service() -> Any:
        from .command_runtime import build_admin_api_command_service

        return build_admin_api_command_service()

    def __call__(
        self,
        plan: HotpointPlacementPlan,
    ) -> HotpointPlacementExecution:
        try:
            command = _compose_command(plan)
            from core.coinbase_execution_authority import (
                COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
                canonical_coinbase_execution_scope,
            )

            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_SPOT_PLACE
            ):
                response = (
                    self._command_service_getter().place_hotpoint_test_order(
                        command
                    )
                )
        except Exception:
            return HotpointPlacementExecution(
                outcome=HotpointPlacementOutcome.UNKNOWN,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_create_outcome_unknown",
                exchange_invoked=False,
            )
        if not isinstance(response, AdminApiCommandResponse):
            return HotpointPlacementExecution(
                outcome=HotpointPlacementOutcome.UNKNOWN,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_create_outcome_unknown",
                exchange_invoked=False,
            )

        invoked = bool(
            response.live_exchange_submitted
            and response.live_coinbase_orders_ran
        )
        exact_boundary = bool(
            response.action_class is AdminApiActionClass.LIVE_EXCHANGE_PLACE
            and response.required_permission is AdminApiPermission.ORDER_CREATE
            and response.service_method == "place_hotpoint_test_order"
        )
        if (
            exact_boundary
            and response.status is AdminApiCommandStatus.ACCEPTED
            and response.client_order_id == plan.child_client_order_id
            and invoked
        ):
            return HotpointPlacementExecution(
                outcome=HotpointPlacementOutcome.ACCEPTED,
                child_client_order_id=plan.child_client_order_id,
                diagnostic_code="operator_hotpoint_create_accepted",
                exchange_invoked=True,
            )

        fixed_error = _fixed_error(response)
        if (
            exact_boundary
            and response.status
            in {
                AdminApiCommandStatus.REJECTED,
                AdminApiCommandStatus.NOT_IMPLEMENTED,
                AdminApiCommandStatus.CONFLICT,
            }
            and (
                not invoked
                or fixed_error == "operator_hotpoint_create_rejected"
            )
        ):
            return HotpointPlacementExecution(
                outcome=HotpointPlacementOutcome.REJECTED,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_create_rejected",
                exchange_invoked=invoked,
            )

        return HotpointPlacementExecution(
            outcome=HotpointPlacementOutcome.UNKNOWN,
            child_client_order_id=None,
            diagnostic_code="operator_hotpoint_create_outcome_unknown",
            exchange_invoked=invoked,
        )


class AdminApiHotpointCancelExecutor:
    """Map one exact-child cancel claim into the canonical Cancel service."""

    def __init__(
        self,
        *,
        command_service_getter: Callable[[], Any] | None = None,
    ) -> None:
        self._command_service_getter = (
            command_service_getter
            or AdminApiHotpointPlacementExecutor._default_command_service
        )

    def __call__(self, plan: HotpointCancelPlan) -> HotpointCancelExecution:
        try:
            envelope = AdminApiCommandEnvelope(
                idempotency_key=plan.cancel_claim_id,
                correlation_id=plan.correlation_id,
                operator_intent=HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
                actor=AdminApiActor(
                    actor_id=plan.actor_id,
                    roles=[AdminApiRole(role) for role in plan.roles],
                ),
            )
            command = CancelOrderCommand(
                envelope=envelope,
                client_order_id=plan.child_client_order_id,
                request=CancelOrderRequest(
                    reason="exact Hotpoint child safe closeout",
                    manual_live_acknowledgement=True,
                ),
                allow_live_execution=True,
                hotpoint_goal_id=plan.goal_id,
                hotpoint_parent_client_order_id=(
                    plan.parent_client_order_id
                ),
                hotpoint_plan_sha256=plan.plan_sha256,
                hotpoint_portfolio_id=plan.portfolio_id,
            )
            from core.coinbase_execution_authority import (
                COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
                canonical_coinbase_execution_scope,
            )

            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
            ):
                response = (
                    self._command_service_getter().cancel_order_by_client_order_id(
                        command
                    )
                )
        except Exception:
            return HotpointCancelExecution(
                outcome=HotpointPlacementOutcome.UNKNOWN,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_cancel_outcome_unknown",
                exchange_invoked=False,
            )
        if not isinstance(response, AdminApiCommandResponse):
            return HotpointCancelExecution(
                outcome=HotpointPlacementOutcome.UNKNOWN,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_cancel_outcome_unknown",
                exchange_invoked=False,
            )
        invoked = bool(
            response.live_exchange_submitted
            and response.live_coinbase_orders_ran
        )
        exact_boundary = bool(
            response.action_class is AdminApiActionClass.LIVE_EXCHANGE_CANCEL
            and response.required_permission is AdminApiPermission.ORDER_CANCEL
            and response.service_method == "cancel_order_by_client_order_id"
            and response.client_order_id == plan.child_client_order_id
        )
        if (
            exact_boundary
            and response.status is AdminApiCommandStatus.ACCEPTED
            and invoked
        ):
            return HotpointCancelExecution(
                outcome=HotpointPlacementOutcome.ACCEPTED,
                child_client_order_id=plan.child_client_order_id,
                diagnostic_code="operator_hotpoint_cancel_accepted",
                exchange_invoked=True,
            )
        if (
            exact_boundary
            and response.status
            in {
                AdminApiCommandStatus.REJECTED,
                AdminApiCommandStatus.NOT_IMPLEMENTED,
                AdminApiCommandStatus.CONFLICT,
            }
            and (
                not invoked
                or response.failure_stage == "cancellation_rejected"
            )
        ):
            return HotpointCancelExecution(
                outcome=HotpointPlacementOutcome.REJECTED,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_cancel_rejected",
                exchange_invoked=invoked,
            )
        return HotpointCancelExecution(
            outcome=HotpointPlacementOutcome.UNKNOWN,
            child_client_order_id=None,
            diagnostic_code="operator_hotpoint_cancel_outcome_unknown",
            exchange_invoked=invoked,
        )


__all__ = [
    "AdminApiHotpointCancelExecutor",
    "AdminApiHotpointPlacementExecutor",
    "FuturesHotpointExecutionPosture",
    "UnavailableFuturesHotpointControlService",
    "evaluate_operator_futures_hotpoint_execution_posture",
    "get_default_operator_hotpoint_control_service",
    "get_default_operator_hotpoint_control_services",
    "get_operator_futures_hotpoint_execution_posture",
    "initialize_operator_futures_hotpoint_v2_runtime",
]


_DEFAULT_SERVICE: OperatorHotpointControlService | None = None
_DEFAULT_FUTURES_SERVICE: OperatorHotpointControlService | None = None
_DEFAULT_FUTURES_V2_SERVICE: Any | None = None
_DEFAULT_SERVICE_LOCK = Lock()
_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
)


@dataclass(frozen=True, slots=True)
class FuturesHotpointExecutionPosture:
    """Call-free readiness for both Goal 13 exchange-bearing routes."""

    ready: bool
    diagnostic_code: str


def evaluate_operator_futures_hotpoint_execution_posture(
    *,
    feature_enabled: bool,
    execution_authority_enabled: bool,
    live_runtime_enabled: bool,
    credentials_configured: bool,
    rest_client_available: bool,
    portfolio_configured: bool,
    live_service_state: AdminApiLiveExecutionServiceState,
) -> FuturesHotpointExecutionPosture:
    """Evaluate Goal 13 without treating Spot cap fields as Futures policy."""

    if not feature_enabled:
        diagnostic = "operator_futures_hotpoint_v2_disabled"
    elif not execution_authority_enabled:
        diagnostic = (
            "operator_futures_hotpoint_execution_authority_missing"
        )
    elif not live_runtime_enabled:
        diagnostic = "operator_futures_hotpoint_live_runtime_disabled"
    elif not credentials_configured:
        diagnostic = "operator_futures_hotpoint_credentials_missing"
    elif not rest_client_available:
        diagnostic = "operator_futures_hotpoint_rest_client_unavailable"
    elif not portfolio_configured:
        diagnostic = "operator_futures_hotpoint_default_portfolio_required"
    elif not all(
        operator_futures_manual_live_service_state_allows_route_admission(
            live_service_state,
            method="POST",
            route=route,
        )
        for route in (
            OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
            OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
        )
    ):
        diagnostic = (
            "operator_futures_hotpoint_service_decision_unavailable"
        )
    else:
        return FuturesHotpointExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_hotpoint_execution_posture_ready"
            ),
        )
    return FuturesHotpointExecutionPosture(
        ready=False,
        diagnostic_code=diagnostic,
    )


def get_operator_futures_hotpoint_execution_posture(
) -> FuturesHotpointExecutionPosture:
    """Resolve installed Goal 13 readiness without making a Coinbase call."""

    from .futures_default_rest_client import (
        futures_default_rest_client_configured,
        get_futures_default_rest_client,
    )

    credentials_configured = futures_default_rest_client_configured()
    rest_client_available = False
    if credentials_configured:
        try:
            rest_client_available = (
                get_futures_default_rest_client() is not None
            )
        except Exception:
            rest_client_available = False
    try:
        live_service_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
    except Exception:
        from .live_execution import get_disabled_live_execution_service

        live_service_state = (
            get_disabled_live_execution_service().admission_state()
        )
    return evaluate_operator_futures_hotpoint_execution_posture(
        feature_enabled=(
            os.environ.get(
                _OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV
            )
            == "1"
        ),
        execution_authority_enabled=(
            coinbase_execution_authority_enabled()
        ),
        live_runtime_enabled=(
            os.environ.get(
                LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
                "",
            ).strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        credentials_configured=credentials_configured,
        rest_client_available=rest_client_available,
        portfolio_configured=bool(
            str(
                os.environ.get(
                    "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
                )
                or ""
            ).strip()
        ),
        live_service_state=live_service_state,
    )


class UnavailableFuturesHotpointControlService(
    OperatorHotpointControlService
):
    """Expose fixed Futures policy without inventing a private binding."""

    policy = FUTURES_HOTPOINT_SCOPE_POLICY
    placement_execution_available = False
    cancel_execution_available = False
    control_available = False

    def __init__(
        self,
        *,
        shared_goal_service: OperatorHotpointControlService,
    ) -> None:
        self.shared_goal_service = shared_goal_service

    def read(self) -> OperatorHotpointControlRecord:
        shared = self.shared_goal_service.read()
        return OperatorHotpointControlRecord(
            goal_id=shared.goal_id,
            revision=0,
            kill_switch_state=HotpointKillSwitchState.DISABLED,
            window_state=HotpointWindowState.NONE,
            parent_client_order_id=None,
            product_id=None,
            side=None,
            window_id=None,
            window_started_at=None,
            window_expires_at=None,
            create_state=HotpointCreateState.NOT_CLAIMED,
            cancel_state=HotpointCancelState.NOT_CLAIMED,
            create_exchange_invoked=None,
            cancel_exchange_invoked=None,
            placement_claim_id=None,
            cancel_claim_id=None,
            child_client_order_id=None,
            diagnostic_code=(
                "operator_futures_hotpoint_portfolio_not_configured"
            ),
            actor_id="system",
            roles=(),
            correlation_id="not_recorded",
            audit_id="00000000-0000-0000-0000-000000000000",
            recorded_at="1970-01-01T00:00:00+00:00",
            updated_at="1970-01-01T00:00:00+00:00",
            goal_create_claim_consumed=shared.goal_create_claim_consumed,
            goal_create_claim_domain=shared.goal_create_claim_domain,
            goal_cancel_claim_consumed=shared.goal_cancel_claim_consumed,
            goal_cancel_claim_domain=shared.goal_cancel_claim_domain,
        )

    def list_eligible_parents(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], int]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or offset < 0
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_pagination_invalid",
                422,
            )
        return [], 0

    @staticmethod
    def _unavailable() -> None:
        raise OperatorHotpointControlError(
            "operator_futures_hotpoint_portfolio_not_configured",
            503,
        )

    def control(self, **_kwargs: Any) -> OperatorHotpointControlRecord:
        self._unavailable()
        raise AssertionError("unreachable")

    def run_once(
        self,
        **_kwargs: Any,
    ) -> OperatorHotpointControlRecord:
        self._unavailable()
        raise AssertionError("unreachable")

    def safe_closeout(
        self,
        **_kwargs: Any,
    ) -> OperatorHotpointControlRecord:
        self._unavailable()
        raise AssertionError("unreachable")


def get_default_operator_hotpoint_control_service(
) -> OperatorHotpointControlService:
    """Build the process-local service over PostgreSQL durable authority."""

    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_hotpoint_control import (
                    get_default_operator_hotpoint_control_repository,
                )

                _DEFAULT_SERVICE = OperatorHotpointControlService(
                    repository=(
                        get_default_operator_hotpoint_control_repository()
                    ),
                    placement_executor=AdminApiHotpointPlacementExecutor(),
                    cancel_executor=AdminApiHotpointCancelExecutor(),
                    policy=SPOT_HOTPOINT_SCOPE_POLICY,
                )
    return _DEFAULT_SERVICE


def _unavailable_futures_placement(
    _plan: HotpointPlacementPlan,
) -> HotpointPlacementExecution:
    raise RuntimeError("operator_futures_hotpoint_execution_source_disabled")


def _unavailable_futures_cancel(
    _plan: HotpointCancelPlan,
) -> HotpointCancelExecution:
    raise RuntimeError("operator_futures_hotpoint_cancel_source_disabled")


def _build_default_operator_futures_hotpoint_v2_service() -> Any:
    """Compose Goal 13 only from its dedicated ledgers and Futures adapters."""

    configured_portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID") or ""
    ).strip()
    if not configured_portfolio_id:
        raise RuntimeError(
            "operator_futures_hotpoint_default_portfolio_required"
        )

    from database.operator_futures_manual_lifecycle import (
        get_default_operator_futures_hotpoint_lifecycle_repository,
    )
    from database.operator_hotpoint_control import (
        get_default_operator_futures_hotpoint_control_repository,
    )

    from .futures_default_rest_client import (
        get_futures_default_rest_client,
    )
    from .operator_futures_hotpoint_v2 import (
        FuturesHotpointEligibilityReader,
        FuturesHotpointExactCloseoutExecutor,
        OperatorFuturesHotpointV2Service,
    )
    from .operator_futures_product_ticket_runtime import (
        AdminApiFuturesProductTicketExchangeExecutor,
    )

    control_repository = (
        get_default_operator_futures_hotpoint_control_repository()
    )
    control_repository.ensure_schema()
    control_repository.recover_stranded_claim()
    lifecycle_repository = (
        get_default_operator_futures_hotpoint_lifecycle_repository(
            control_repository=control_repository,
        )
    )
    rest_client = get_futures_default_rest_client()
    control_service = OperatorHotpointControlService(
        repository=control_repository,
        placement_executor=_unavailable_futures_placement,
        cancel_executor=_unavailable_futures_cancel,
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        placement_execution_available=False,
        cancel_execution_available=False,
    )
    exchange_executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest_client
    )
    return OperatorFuturesHotpointV2Service(
        control_service=control_service,
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda trigger: (
            FuturesHotpointEligibilityReader(
                rest_client=rest_client,
                trigger=trigger,
            )
        ),
        exchange_executor=exchange_executor,
        closeout_executor=FuturesHotpointExactCloseoutExecutor(
            rest_client=rest_client,
            configured_portfolio_id=configured_portfolio_id,
        ),
    )


def initialize_operator_futures_hotpoint_v2_runtime() -> Any:
    """Eagerly initialize and recover Goal 13 before accepting traffic."""

    global _DEFAULT_FUTURES_V2_SERVICE
    if (
        os.environ.get(_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV)
        != "1"
    ):
        return None
    if _DEFAULT_FUTURES_V2_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_FUTURES_V2_SERVICE is None:
                _DEFAULT_FUTURES_V2_SERVICE = (
                    _build_default_operator_futures_hotpoint_v2_service()
                )
    return _DEFAULT_FUTURES_V2_SERVICE


def get_default_operator_hotpoint_control_services(
) -> dict[str, Any]:
    """Select historical Goal 9 or Goal 13 without cross-ledger fallback."""

    global _DEFAULT_FUTURES_SERVICE, _DEFAULT_FUTURES_V2_SERVICE
    spot_service = get_default_operator_hotpoint_control_service()
    services = {"SPOT": spot_service}
    if (
        os.environ.get(_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED_ENV)
        != "1"
    ):
        if _DEFAULT_FUTURES_SERVICE is None:
            with _DEFAULT_SERVICE_LOCK:
                if _DEFAULT_FUTURES_SERVICE is None:
                    _DEFAULT_FUTURES_SERVICE = (
                        UnavailableFuturesHotpointControlService(
                            shared_goal_service=spot_service,
                        )
                    )
        services["FUTURES"] = _DEFAULT_FUTURES_SERVICE
        return services

    if _DEFAULT_FUTURES_V2_SERVICE is None:
        try:
            with _DEFAULT_SERVICE_LOCK:
                if _DEFAULT_FUTURES_V2_SERVICE is None:
                    _DEFAULT_FUTURES_V2_SERVICE = (
                        _build_default_operator_futures_hotpoint_v2_service()
                    )
        except Exception:
            return services
    services["FUTURES"] = _DEFAULT_FUTURES_V2_SERVICE
    return services
