from __future__ import annotations

from dataclasses import replace

from application.admin_api.live_execution import (
    AdminApiLiveExecutionServiceState,
    CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
)
from application.admin_api.operator_futures_product_ticket_service_runtime import (
    evaluate_operator_futures_product_ticket_execution_posture,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_FUTURES_PRODUCT_TICKET_EXECUTE_ROUTE,
)
from core.enums import AdminApiLiveExecutionStatus


def _state() -> AdminApiLiveExecutionServiceState:
    return AdminApiLiveExecutionServiceState(
        required=True,
        present=True,
        status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        source=CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
        missing_reason=None,
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        supported_routes=frozenset(
            {
                (
                    "POST",
                    OPERATOR_MVP_FUTURES_PRODUCT_TICKET_EXECUTE_ROUTE,
                )
            }
        ),
    )


def test_product_ticket_posture_requires_exact_controlled_live_route() -> None:
    ready = evaluate_operator_futures_product_ticket_execution_posture(
        execution_authority_enabled=True,
        live_runtime_enabled=True,
        credentials_configured=True,
        rest_client_available=True,
        live_service_state=_state(),
    )
    blocked = evaluate_operator_futures_product_ticket_execution_posture(
        execution_authority_enabled=True,
        live_runtime_enabled=True,
        credentials_configured=True,
        rest_client_available=True,
        live_service_state=replace(
            _state(),
            supported_routes=frozenset(),
        ),
    )

    assert ready.ready is True
    assert ready.diagnostic_code == (
        "operator_futures_product_ticket_execution_posture_ready"
    )
    assert blocked.ready is False
    assert blocked.diagnostic_code == (
        "operator_futures_product_ticket_service_decision_unavailable"
    )


def test_product_ticket_posture_fails_closed_at_each_local_boundary() -> None:
    defaults = {
        "execution_authority_enabled": True,
        "live_runtime_enabled": True,
        "credentials_configured": True,
        "rest_client_available": True,
        "live_service_state": _state(),
    }
    scenarios = [
        (
            {"execution_authority_enabled": False},
            "operator_futures_product_ticket_execution_authority_missing",
        ),
        (
            {"live_runtime_enabled": False},
            "operator_futures_product_ticket_live_runtime_disabled",
        ),
        (
            {"credentials_configured": False},
            "operator_futures_product_ticket_credentials_missing",
        ),
        (
            {"rest_client_available": False},
            "operator_futures_product_ticket_rest_client_unavailable",
        ),
    ]
    for updates, expected in scenarios:
        posture = evaluate_operator_futures_product_ticket_execution_posture(
            **{**defaults, **updates}
        )
        assert posture.ready is False
        assert posture.diagnostic_code == expected
