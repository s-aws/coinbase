"""Domain-specific installed-posture admission for Goal 10 Futures."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from application.admin_api.live_execution import (
    AdminApiLiveExecutionServiceState,
    CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    operator_futures_manual_live_service_state_allows_route_admission,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
)
from application.admin_api.operator_futures_manual_service_runtime import (
    evaluate_operator_futures_manual_execution_posture,
    get_operator_futures_manual_execution_posture,
)
from application.admin_api import (
    operator_futures_manual_service_runtime as futures_manual_service_runtime,
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
                    OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
                )
            }
        ),
    )


def test_futures_admission_uses_installed_posture_not_spot_caps() -> None:
    state = replace(
        _state(),
        max_submitted_notional_usdc=None,
        max_executed_notional_usdc=None,
    )

    assert operator_futures_manual_live_service_state_allows_route_admission(
        state,
        method="POST",
        route=OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
    )


def test_futures_admission_requires_exact_configured_route() -> None:
    state = _state()

    assert not operator_futures_manual_live_service_state_allows_route_admission(
        replace(state, supported_routes=frozenset()),
        method="POST",
        route=OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
    )
    assert not operator_futures_manual_live_service_state_allows_route_admission(
        replace(state, source="synthetic"),
        method="POST",
        route=OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
    )
    assert not operator_futures_manual_live_service_state_allows_route_admission(
        replace(
            state,
            status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
        ),
        method="POST",
        route=OPERATOR_MVP_FUTURES_MANUAL_LIFECYCLE_EXECUTE_ROUTE,
    )


def test_futures_execution_posture_has_no_spot_runtime_dependency() -> None:
    ready = evaluate_operator_futures_manual_execution_posture(
        execution_authority_enabled=True,
        live_runtime_enabled=True,
        credentials_configured=True,
        rest_client_available=True,
        live_service_state=_state(),
    )

    assert ready.ready is True
    assert ready.diagnostic_code == (
        "operator_futures_manual_execution_posture_ready"
    )


def test_installed_true_runtime_literal_admits_futures_posture(
    monkeypatch,
) -> None:
    import configuration

    monkeypatch.setenv(LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "true")
    monkeypatch.setattr(
        futures_manual_service_runtime,
        "coinbase_execution_authority_enabled",
        lambda: True,
    )
    monkeypatch.setattr(configuration, "API_KEY", "configured-key")
    monkeypatch.setattr(configuration, "API_SECRET", "configured-secret")
    monkeypatch.setattr(
        configuration,
        "get_rest_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        futures_manual_service_runtime,
        "get_decision_backed_live_execution_service",
        lambda: SimpleNamespace(admission_state=lambda: _state()),
    )

    posture = get_operator_futures_manual_execution_posture()

    assert posture.ready is True
    assert posture.diagnostic_code == (
        "operator_futures_manual_execution_posture_ready"
    )


def test_futures_execution_posture_fails_closed_at_each_local_boundary() -> None:
    scenarios = [
        (
            {"execution_authority_enabled": False},
            "operator_futures_manual_execution_authority_missing",
        ),
        (
            {"live_runtime_enabled": False},
            "operator_futures_manual_live_runtime_disabled",
        ),
        (
            {"credentials_configured": False},
            "operator_futures_manual_credentials_missing",
        ),
        (
            {"rest_client_available": False},
            "operator_futures_manual_rest_client_unavailable",
        ),
        (
            {
                "live_service_state": replace(
                    _state(),
                    supported_routes=frozenset(),
                )
            },
            "operator_futures_manual_service_decision_unavailable",
        ),
    ]
    defaults = {
        "execution_authority_enabled": True,
        "live_runtime_enabled": True,
        "credentials_configured": True,
        "rest_client_available": True,
        "live_service_state": _state(),
    }
    for updates, expected in scenarios:
        posture = evaluate_operator_futures_manual_execution_posture(
            **{**defaults, **updates}
        )
        assert posture.ready is False
        assert posture.diagnostic_code == expected
