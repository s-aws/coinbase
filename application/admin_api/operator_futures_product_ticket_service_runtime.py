"""Installed runtime construction for Goal 3 Futures product tickets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from threading import Lock
from typing import Any

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
from .operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_GOAL_ID,
    FuturesProductTicketEligibilityReader,
    validate_futures_product_ticket_eligibility_evidence,
)
from .operator_futures_product_ticket_runtime import (
    AdminApiFuturesProductTicketExchangeExecutor,
)
from .operator_futures_product_ticket_service import (
    OperatorFuturesProductTicketService,
)
from .operator_mvp_policy import (
    OPERATOR_MVP_FUTURES_PRODUCT_TICKET_EXECUTE_ROUTE,
)


OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED"
)

_DEFAULT_SERVICE: OperatorFuturesProductTicketService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


class _DeferredFuturesDefaultRestClient:
    """Resolve Default-profile credentials only at an exchange boundary."""

    def __init__(
        self,
        *,
        resolver: Callable[[], Any] | None = None,
    ) -> None:
        self._resolver = resolver or get_futures_default_rest_client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver(), name)


@dataclass(frozen=True, slots=True)
class FuturesProductTicketExecutionPosture:
    ready: bool
    diagnostic_code: str


def evaluate_operator_futures_product_ticket_execution_posture(
    *,
    execution_authority_enabled: bool,
    live_runtime_enabled: bool,
    credentials_configured: bool,
    rest_client_available: bool,
    live_service_state: AdminApiLiveExecutionServiceState,
) -> FuturesProductTicketExecutionPosture:
    if not execution_authority_enabled:
        diagnostic = (
            "operator_futures_product_ticket_execution_authority_missing"
        )
    elif not live_runtime_enabled:
        diagnostic = (
            "operator_futures_product_ticket_live_runtime_disabled"
        )
    elif not credentials_configured:
        diagnostic = (
            "operator_futures_product_ticket_credentials_missing"
        )
    elif not rest_client_available:
        diagnostic = (
            "operator_futures_product_ticket_rest_client_unavailable"
        )
    elif not operator_futures_manual_live_service_state_allows_route_admission(
        live_service_state,
        method="POST",
        route=OPERATOR_MVP_FUTURES_PRODUCT_TICKET_EXECUTE_ROUTE,
    ):
        diagnostic = (
            "operator_futures_product_ticket_service_decision_unavailable"
        )
    else:
        return FuturesProductTicketExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_product_ticket_execution_posture_ready"
            ),
        )
    return FuturesProductTicketExecutionPosture(
        ready=False,
        diagnostic_code=diagnostic,
    )


def get_operator_futures_product_ticket_execution_posture(
) -> FuturesProductTicketExecutionPosture:
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
        live_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
    except Exception:
        from .live_execution import (
            get_disabled_live_execution_service,
        )

        live_state = get_disabled_live_execution_service().admission_state()
    return evaluate_operator_futures_product_ticket_execution_posture(
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
        live_service_state=live_state,
    )


def get_default_operator_futures_product_ticket_service(
) -> OperatorFuturesProductTicketService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database import order as order_db
                from database.operator_futures_manual_lifecycle import (
                    OperatorFuturesManualLifecycleRepository,
                )
                from database.operator_futures_product_policy import (
                    OperatorFuturesProductPolicyRepository,
                )

                rest_client = _DeferredFuturesDefaultRestClient()
                policy_repository = (
                    OperatorFuturesProductPolicyRepository(
                        order_db.DB_CLIENT
                    )
                )
                policy_repository.ensure_schema()
                portfolio_id = str(
                    os.environ.get(
                        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
                    )
                    or ""
                ).strip()
                lifecycle_repository = (
                    OperatorFuturesManualLifecycleRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=portfolio_id or None,
                        goal_id=FUTURES_PRODUCT_TICKET_GOAL_ID,
                        eligibility_evidence_validator=(
                            validate_futures_product_ticket_eligibility_evidence
                        ),
                        claim_validator=(
                            policy_repository.validate_selection_binding
                        ),
                        client_order_id_prefix=(
                            "operator-futures-product-ticket-"
                        ),
                    )
                )
                lifecycle_repository.ensure_schema()
                _DEFAULT_SERVICE = OperatorFuturesProductTicketService(
                    policy_repository=policy_repository,
                    lifecycle_repository=lifecycle_repository,
                    eligibility_reader=(
                        FuturesProductTicketEligibilityReader(
                            rest_client=rest_client,
                            selection_reader=policy_repository.selection,
                        )
                    ),
                    exchange_executor=(
                        AdminApiFuturesProductTicketExchangeExecutor(
                            rest_client=rest_client
                        )
                    ),
                )
    return _DEFAULT_SERVICE


def reset_operator_futures_product_ticket_service_for_tests() -> None:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        _DEFAULT_SERVICE = None


__all__ = [
    "FuturesProductTicketExecutionPosture",
    "OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED_ENV",
    "evaluate_operator_futures_product_ticket_execution_posture",
    "get_default_operator_futures_product_ticket_service",
    "get_operator_futures_product_ticket_execution_posture",
    "reset_operator_futures_product_ticket_service_for_tests",
]
