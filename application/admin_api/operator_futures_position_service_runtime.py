"""Installed runtime construction for the Goal 11 position lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock

from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)

from .live_execution import (
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    AdminApiLiveExecutionServiceState,
    get_decision_backed_live_execution_service,
    operator_futures_position_live_service_state_allows_route_admission,
)
from .operator_futures_position_lifecycle import (
    FuturesPositionEligibilityReader,
    OperatorFuturesPositionLifecycleService,
)
from .operator_futures_position_runtime import (
    AdminApiFuturesPositionExchangeExecutor,
)
from .operator_mvp_policy import (
    OPERATOR_MVP_FUTURES_POSITION_LIFECYCLE_EXECUTE_ROUTE,
)


_DEFAULT_SERVICE: OperatorFuturesPositionLifecycleService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class FuturesPositionExecutionPosture:
    ready: bool
    diagnostic_code: str


def evaluate_operator_futures_position_execution_posture(
    *,
    execution_authority_enabled: bool,
    live_runtime_enabled: bool,
    credentials_configured: bool,
    rest_client_available: bool,
    live_service_state: AdminApiLiveExecutionServiceState,
) -> FuturesPositionExecutionPosture:
    if not execution_authority_enabled:
        diagnostic = (
            "operator_futures_position_execution_authority_missing"
        )
    elif not live_runtime_enabled:
        diagnostic = "operator_futures_position_live_runtime_disabled"
    elif not credentials_configured:
        diagnostic = "operator_futures_position_credentials_missing"
    elif not rest_client_available:
        diagnostic = "operator_futures_position_rest_client_unavailable"
    elif not operator_futures_position_live_service_state_allows_route_admission(
        live_service_state,
        method="POST",
        route=OPERATOR_MVP_FUTURES_POSITION_LIFECYCLE_EXECUTE_ROUTE,
    ):
        diagnostic = (
            "operator_futures_position_service_decision_unavailable"
        )
    else:
        return FuturesPositionExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_position_execution_posture_ready"
            ),
        )
    return FuturesPositionExecutionPosture(
        ready=False,
        diagnostic_code=diagnostic,
    )


def get_operator_futures_position_execution_posture(
) -> FuturesPositionExecutionPosture:
    credentials_configured = False
    rest_client_available = False
    try:
        from configuration import API_KEY, API_SECRET, get_rest_client

        credentials_configured = bool(API_KEY and API_SECRET)
        if credentials_configured:
            rest_client_available = get_rest_client() is not None
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
    return evaluate_operator_futures_position_execution_posture(
        execution_authority_enabled=coinbase_execution_authority_enabled(),
        live_runtime_enabled=(
            os.environ.get(
                LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
                "",
            ).strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        credentials_configured=credentials_configured,
        rest_client_available=rest_client_available,
        live_service_state=live_service_state,
    )


def get_default_operator_futures_position_lifecycle_service(
) -> OperatorFuturesPositionLifecycleService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from configuration import REST_CLIENT
                from database.operator_futures_position_lifecycle import (
                    get_default_operator_futures_position_lifecycle_repository,
                )

                _DEFAULT_SERVICE = OperatorFuturesPositionLifecycleService(
                    repository=(
                        get_default_operator_futures_position_lifecycle_repository()
                    ),
                    eligibility_reader_factory=lambda position_key: (
                        FuturesPositionEligibilityReader(
                            rest_client=REST_CLIENT,
                            position_key=position_key,
                        )
                    ),
                    exchange_executor=(
                        AdminApiFuturesPositionExchangeExecutor(
                            rest_client=REST_CLIENT
                        )
                    ),
                )
    return _DEFAULT_SERVICE


__all__ = [
    "FuturesPositionExecutionPosture",
    "evaluate_operator_futures_position_execution_posture",
    "get_default_operator_futures_position_lifecycle_service",
    "get_operator_futures_position_execution_posture",
]
