"""Lazy installed construction for approved-Test Spot order operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock

from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)

from .command_runtime import build_admin_api_command_service
from .live_execution import (
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    get_decision_backed_live_execution_service,
    operator_mvp_live_service_state_allows_route_admission,
)
from .operator_mvp_policy import OPERATOR_MVP_CANCEL_ORDER_ROUTE
from .operator_spot_order_truth import SpotOrderCatalogReader
from .operator_spot_order_truth_service import (
    OperatorSpotOrderTruthService,
)
from .spot_portfolio_binding import SPOT_PORTFOLIO_ID_ENV


OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED"
)


@dataclass(frozen=True, slots=True)
class SpotOrderTruthExecutionPosture:
    ready: bool
    diagnostic_code: str


def get_operator_spot_order_truth_execution_posture(
) -> SpotOrderTruthExecutionPosture:
    try:
        live_state = (
            get_decision_backed_live_execution_service().admission_state()
        )
        service_decision_ready = (
            operator_mvp_live_service_state_allows_route_admission(
                live_state,
                method="POST",
                route=OPERATOR_MVP_CANCEL_ORDER_ROUTE,
            )
        )
    except Exception:
        service_decision_ready = False
    if os.environ.get(OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV, "") != "1":
        code = "operator_spot_order_truth_feature_disabled"
    elif not coinbase_execution_authority_enabled():
        code = "operator_spot_order_truth_execution_authority_missing"
    elif (
        os.environ.get(LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "")
        .strip()
        .lower()
        not in {"1", "true", "yes", "on"}
    ):
        code = "operator_spot_order_truth_live_runtime_disabled"
    elif not os.environ.get(SPOT_PORTFOLIO_ID_ENV, "").strip():
        code = "operator_spot_order_truth_test_portfolio_missing"
    elif not service_decision_ready:
        code = "operator_spot_order_truth_service_decision_unavailable"
    else:
        return SpotOrderTruthExecutionPosture(
            ready=True,
            diagnostic_code="operator_spot_order_truth_execution_posture_ready",
        )
    return SpotOrderTruthExecutionPosture(ready=False, diagnostic_code=code)


_DEFAULT_SERVICE: OperatorSpotOrderTruthService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


def get_default_operator_spot_order_truth_service(
) -> OperatorSpotOrderTruthService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_spot_order_truth import (
                    get_default_operator_spot_order_truth_repository,
                )
                from database.order import get_parent_order

                command_service = build_admin_api_command_service()
                rest_client = command_service.dependencies.rest_client
                if rest_client is None:
                    raise RuntimeError(
                        "operator_spot_order_truth_rest_client_unavailable"
                    )
                expected_portfolio_id = os.environ.get(
                    SPOT_PORTFOLIO_ID_ENV, ""
                ).strip()
                if not expected_portfolio_id:
                    raise RuntimeError(
                        "operator_spot_order_truth_test_portfolio_missing"
                    )
                _DEFAULT_SERVICE = OperatorSpotOrderTruthService(
                    repository=(
                        get_default_operator_spot_order_truth_repository()
                    ),
                    catalog_reader=SpotOrderCatalogReader(
                        rest_client=rest_client,
                        expected_portfolio_id=expected_portfolio_id,
                        local_order_loader=get_parent_order,
                    ),
                    local_order_loader=get_parent_order,
                )
    return _DEFAULT_SERVICE


def reset_operator_spot_order_truth_service_for_tests() -> None:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        _DEFAULT_SERVICE = None


__all__ = [
    "OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV",
    "SpotOrderTruthExecutionPosture",
    "get_default_operator_spot_order_truth_service",
    "get_operator_spot_order_truth_execution_posture",
    "reset_operator_spot_order_truth_service_for_tests",
]
