"""Installed construction and posture for the Futures Orders workspace."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock

from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)

from .futures_default_rest_client import (
    futures_default_rest_client_configured,
    get_futures_default_rest_client,
)
from .live_execution import (
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    AdminApiLiveExecutionServiceState,
    get_decision_backed_live_execution_service,
    operator_futures_manual_live_service_state_allows_route_admission,
)
from .operator_futures_order_operations import FuturesOrderCatalogReader
from .operator_futures_order_operations_runtime import (
    AdminApiFuturesOrderOperationsExchangeExecutor,
)
from .operator_futures_order_operations_service import (
    OperatorFuturesOrderOperationsService,
)
from .operator_mvp_policy import OPERATOR_MVP_FUTURES_ORDER_CANCEL_ROUTE


OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED"
)


@dataclass(frozen=True, slots=True)
class FuturesOrderOperationsExecutionPosture:
    ready: bool
    diagnostic_code: str


def evaluate_operator_futures_order_operations_execution_posture(
    *,
    feature_enabled: bool,
    execution_authority_enabled: bool,
    live_runtime_enabled: bool,
    credentials_configured: bool,
    rest_client_available: bool,
    live_service_state: AdminApiLiveExecutionServiceState,
) -> FuturesOrderOperationsExecutionPosture:
    if not feature_enabled:
        diagnostic = "operator_futures_orders_feature_disabled"
    elif not execution_authority_enabled:
        diagnostic = "operator_futures_orders_execution_authority_missing"
    elif not live_runtime_enabled:
        diagnostic = "operator_futures_orders_live_runtime_disabled"
    elif not credentials_configured:
        diagnostic = "operator_futures_orders_credentials_missing"
    elif not rest_client_available:
        diagnostic = "operator_futures_orders_rest_client_unavailable"
    elif not operator_futures_manual_live_service_state_allows_route_admission(
        live_service_state,
        method="POST",
        route=OPERATOR_MVP_FUTURES_ORDER_CANCEL_ROUTE,
    ):
        diagnostic = "operator_futures_orders_service_decision_unavailable"
    else:
        return FuturesOrderOperationsExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_orders_execution_posture_ready"
            ),
        )
    return FuturesOrderOperationsExecutionPosture(
        ready=False,
        diagnostic_code=diagnostic,
    )


def get_operator_futures_order_operations_execution_posture(
) -> FuturesOrderOperationsExecutionPosture:
    configured = futures_default_rest_client_configured()
    rest_available = False
    try:
        if configured:
            rest_available = get_futures_default_rest_client() is not None
    except Exception:
        rest_available = False
    try:
        live_service_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
    except Exception:
        from .live_execution import get_disabled_live_execution_service

        live_service_state = (
            get_disabled_live_execution_service().admission_state()
        )
    return evaluate_operator_futures_order_operations_execution_posture(
        feature_enabled=(
            os.environ.get(
                OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED_ENV, ""
            ).strip()
            == "1"
        ),
        execution_authority_enabled=coinbase_execution_authority_enabled(),
        live_runtime_enabled=(
            os.environ.get(LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        ),
        credentials_configured=configured,
        rest_client_available=rest_available,
        live_service_state=live_service_state,
    )


_DEFAULT_SERVICE: OperatorFuturesOrderOperationsService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


def get_default_operator_futures_order_operations_service(
) -> OperatorFuturesOrderOperationsService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_futures_order_operations import (
                    get_default_operator_futures_order_operations_repository,
                )
                from .operator_futures_fill_triggered_follow_up_runtime import (
                    OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED_ENV,
                    get_default_operator_futures_fill_triggered_follow_up_service,
                )

                rest_client = get_futures_default_rest_client()
                fill_dispatcher = None
                if (
                    os.environ.get(
                        OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED_ENV
                    )
                    == "1"
                ):
                    fill_dispatcher = (
                        get_default_operator_futures_fill_triggered_follow_up_service()
                        .on_source_reconciled
                    )
                _DEFAULT_SERVICE = OperatorFuturesOrderOperationsService(
                    repository=(
                        get_default_operator_futures_order_operations_repository()
                    ),
                    catalog_reader=FuturesOrderCatalogReader(
                        rest_client=rest_client
                    ),
                    exchange_executor=(
                        AdminApiFuturesOrderOperationsExchangeExecutor(
                            rest_client=rest_client
                        )
                    ),
                    authoritative_fill_dispatcher=fill_dispatcher,
                )
    return _DEFAULT_SERVICE


def reset_operator_futures_order_operations_service_for_tests() -> None:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        _DEFAULT_SERVICE = None


__all__ = [
    "FuturesOrderOperationsExecutionPosture",
    "OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED_ENV",
    "evaluate_operator_futures_order_operations_execution_posture",
    "get_default_operator_futures_order_operations_service",
    "get_operator_futures_order_operations_execution_posture",
    "reset_operator_futures_order_operations_service_for_tests",
]
