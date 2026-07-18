"""Truthful Admin API authority readback for operator follow-up intents."""

from __future__ import annotations

import pytest

from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiFunctionalityExposureStatus,
    AdminApiModuleSupportStatus,
    AdminApiRouteAvailability,
)
from core.operator_follow_up_intent import OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV


_FOLLOW_UP_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent"
)


def _follow_up_capabilities():
    return {
        item.method: item
        for item in AdminApiReadService().build_admin_capabilities().capabilities
        if item.route == _FOLLOW_UP_ROUTE
    }


def _follow_up_taxonomy():
    return next(
        item
        for item in AdminApiReadService().build_enterprise_readiness().mutation_taxonomy
        if item.mutation_id == "spot.follow_up_intent"
    )


@pytest.mark.parametrize("feature_value", [None, "0", "true", " 1"])
def test_follow_up_capabilities_fail_closed_when_feature_is_not_exact_one(
    monkeypatch,
    feature_value,
):
    if feature_value is None:
        monkeypatch.delenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, raising=False)
    else:
        monkeypatch.setenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, feature_value)

    capabilities = _follow_up_capabilities()

    assert set(capabilities) == {"GET", "POST"}
    for item in capabilities.values():
        assert item.availability == AdminApiRouteAvailability.BACKEND_BLOCKED
        assert item.frontend_safe is False
        assert item.live_enabled is False
        assert item.notes == (
            "Operator follow-up intent is disabled: "
            "operator_follow_up_intent_disabled"
        )


def test_follow_up_capabilities_expose_only_local_operator_intent_when_enabled(
    monkeypatch,
):
    monkeypatch.setenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, "1")

    capabilities = _follow_up_capabilities()

    assert set(capabilities) == {"GET", "POST"}
    for item in capabilities.values():
        assert item.availability == AdminApiRouteAvailability.AVAILABLE
        assert item.frontend_safe is True
        assert item.live_enabled is False

    assert capabilities["GET"].action_class == AdminApiActionClass.READ_ONLY
    assert capabilities["GET"].command_contract is False
    assert capabilities["GET"].notes == (
        "Backend-owned local operator follow-up intent readback; no Coinbase call"
    )
    assert capabilities["POST"].action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert capabilities["POST"].command_contract is True
    assert capabilities["POST"].notes == (
        "Backend-owned local operator follow-up intent attachment; no Coinbase call"
    )


def test_follow_up_readiness_remains_draft_and_blocked_when_feature_is_disabled(
    monkeypatch,
):
    monkeypatch.delenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, raising=False)

    taxonomy = _follow_up_taxonomy()

    assert taxonomy.exposure_status == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED
    )
    assert taxonomy.support_status == (
        AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED
    )
    assert taxonomy.blockers == ["operator_follow_up_intent_disabled"]
    assert "disabled" in taxonomy.summary
    assert taxonomy.live_adapter_required is False
    assert taxonomy.live_coinbase_execution.value == "not_run"


def test_follow_up_readiness_is_complete_local_only_when_feature_is_enabled(
    monkeypatch,
):
    monkeypatch.setenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, "1")

    taxonomy = _follow_up_taxonomy()

    assert taxonomy.exposure_status == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED
    )
    assert taxonomy.support_status == AdminApiModuleSupportStatus.PLATFORM_READY
    assert taxonomy.blockers == []
    assert "complete" in taxonomy.summary
    assert "local-only" in taxonomy.summary
    assert "Coinbase" in taxonomy.summary
    assert taxonomy.live_adapter_required is False
    assert taxonomy.live_coinbase_execution.value == "not_run"
    assert (
        "src/features/operator-read-models/orders/OrderFollowUpIntentPanel.tsx"
        in taxonomy.frontend_contract_refs
    )
    assert "src/shared/api/contracts/backendApiClient.ts" in (
        taxonomy.frontend_contract_refs
    )
