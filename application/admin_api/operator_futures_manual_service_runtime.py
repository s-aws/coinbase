"""Installed runtime construction for the Goal 10 Futures lifecycle."""

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
from .operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ACTIVE_GOAL_ID,
    FuturesManualEligibilityReader,
    OperatorFuturesManualLifecycleService,
)
from .operator_mvp_policy import (
    OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
)
from .operator_futures_manual_runtime import (
    AdminApiFuturesManualExchangeExecutor,
)


_DEFAULT_SERVICE: OperatorFuturesManualLifecycleService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class FuturesManualExecutionPosture:
    """Value-blind local readiness for the exact Goal 10 execution route."""

    ready: bool
    diagnostic_code: str


def evaluate_operator_futures_manual_execution_posture(
    *,
    execution_authority_enabled: bool,
    live_runtime_enabled: bool,
    credentials_configured: bool,
    rest_client_available: bool,
    live_service_state: AdminApiLiveExecutionServiceState,
) -> FuturesManualExecutionPosture:
    """Evaluate Futures readiness without any Spot portfolio infrastructure."""

    if not execution_authority_enabled:
        diagnostic = (
            "operator_futures_manual_execution_authority_missing"
        )
    elif not live_runtime_enabled:
        diagnostic = "operator_futures_manual_live_runtime_disabled"
    elif not credentials_configured:
        diagnostic = "operator_futures_manual_credentials_missing"
    elif not rest_client_available:
        diagnostic = "operator_futures_manual_rest_client_unavailable"
    elif not operator_futures_manual_live_service_state_allows_route_admission(
        live_service_state,
        method="POST",
        route=OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
    ):
        diagnostic = (
            "operator_futures_manual_service_decision_unavailable"
        )
    else:
        return FuturesManualExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_manual_execution_posture_ready"
            ),
        )
    return FuturesManualExecutionPosture(
        ready=False,
        diagnostic_code=diagnostic,
    )


def get_operator_futures_manual_execution_posture(
) -> FuturesManualExecutionPosture:
    """Resolve Coinbase-call-free installed readiness for Goal 10."""

    credentials_configured = futures_default_rest_client_configured()
    rest_client_available = False
    try:
        if credentials_configured:
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
        from .live_execution import (
            get_disabled_live_execution_service,
        )

        live_service_state = (
            get_disabled_live_execution_service().admission_state()
        )
    return evaluate_operator_futures_manual_execution_posture(
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
        live_service_state=live_service_state,
    )


def get_default_operator_futures_manual_lifecycle_service(
) -> OperatorFuturesManualLifecycleService:
    """Build one process-local service over PostgreSQL and the REST wrapper."""

    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_futures_manual_lifecycle import (
                    get_default_operator_futures_manual_lifecycle_repository,
                )

                rest_client = get_futures_default_rest_client()
                _DEFAULT_SERVICE = OperatorFuturesManualLifecycleService(
                    repository=(
                        get_default_operator_futures_manual_lifecycle_repository()
                    ),
                    eligibility_reader=FuturesManualEligibilityReader(
                        rest_client=rest_client,
                        goal_id=FUTURES_MANUAL_ACTIVE_GOAL_ID,
                    ),
                    exchange_executor=(
                        AdminApiFuturesManualExchangeExecutor(
                            rest_client=rest_client
                        )
                    ),
                )
    return _DEFAULT_SERVICE


__all__ = [
    "FuturesManualExecutionPosture",
    "evaluate_operator_futures_manual_execution_posture",
    "get_default_operator_futures_manual_lifecycle_service",
    "get_operator_futures_manual_execution_posture",
]
