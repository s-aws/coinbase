"""Truthful Admin API authority readback for operator follow-up intents."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from application.admin_api import read_service as read_service_module
from application.admin_api.live_execution import (
    AdminApiLiveExecutionServiceState,
    build_live_execution_adapter_contract,
)
from application.admin_api.read_service import AdminApiReadService
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiFunctionalityExposureStatus,
    AdminApiLiveExecutionStatus,
    AdminApiModuleSupportStatus,
    AdminApiPermission,
    AdminApiRouteAvailability,
)
from core.operator_follow_up_intent import OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV


_FOLLOW_UP_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent"
)
_MATERIALIZATION_ROUTE = f"{_FOLLOW_UP_ROUTE}/materialization"
_SAFE_CLOSEOUT_ROUTE = f"{_MATERIALIZATION_ROUTE}/safe-closeout"


def _follow_up_capabilities():
    return {
        item.method: item
        for item in AdminApiReadService().build_admin_capabilities().capabilities
        if item.route == _FOLLOW_UP_ROUTE
    }


def _materialization_capabilities():
    return {
        (item.method, item.route): item
        for item in AdminApiReadService().build_admin_capabilities().capabilities
        if item.route in {_MATERIALIZATION_ROUTE, _SAFE_CLOSEOUT_ROUTE}
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


def test_materialization_capabilities_stay_blocked_when_live_service_is_admitted_but_feature_is_off(
    monkeypatch,
):
    monkeypatch.delenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, raising=False)
    monkeypatch.setattr(
        read_service_module,
        "_decision_backed_live_service_state",
        lambda: AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
            source="synthetic_test",
            missing_reason=None,
        ),
    )

    capabilities = _materialization_capabilities()

    assert set(capabilities) == {
        ("GET", _MATERIALIZATION_ROUTE),
        ("POST", _MATERIALIZATION_ROUTE),
        ("POST", _SAFE_CLOSEOUT_ROUTE),
    }
    for item in capabilities.values():
        assert item.availability == AdminApiRouteAvailability.BACKEND_BLOCKED
        assert item.frontend_safe is False
        assert item.live_enabled is False
        assert item.notes == (
            "Operator follow-up intent is disabled: "
            "operator_follow_up_intent_disabled"
        )


@pytest.mark.parametrize(
    ("route", "service_method", "action_class", "adapter_method"),
    [
        (
            _MATERIALIZATION_ROUTE,
            "materialize_order_follow_up_intent",
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            "materialize",
        ),
        (
            _SAFE_CLOSEOUT_ROUTE,
            "safe_closeout_materialized_follow_up_intent",
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "safe_closeout",
        ),
    ],
)
def test_materialization_live_adapter_truth_names_specialized_backend_runtime(
    route,
    service_method,
    action_class,
    adapter_method,
):
    adapter = build_live_execution_adapter_contract(
        method="POST",
        route=route,
        module_id="spot_operations",
        service_method=service_method,
        action_class=action_class,
        include_construction_contract=False,
    )

    assert adapter["configured"] is True
    assert adapter["executable"] is True
    assert adapter["source"] == (
        "canonical_operator_follow_up_materialization_runtime"
    )
    assert adapter["adapter_reference"] == (
        "OperatorFollowUpMaterializationFacade." + adapter_method
    )
    assert "AdminApiCommandService" not in adapter["adapter_reference"]
    assert adapter["route_mapping_satisfies_construction"] is True
    assert adapter["adapter_configuration_satisfies_construction"] is True
    assert adapter["browser_authority"] == "display_only"
    assert adapter["bff_authority"] == "forward_only_no_execution"


def test_materialization_live_enablement_stays_false_when_feature_is_off(
    monkeypatch,
):
    monkeypatch.delenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, raising=False)
    monkeypatch.setattr(
        read_service_module,
        "_decision_backed_live_service_state",
        lambda: AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
            source="synthetic_test",
            missing_reason=None,
        ),
    )

    paths = {
        item.route: item
        for item in AdminApiReadService().build_live_enablement().paths
        if item.route in {_MATERIALIZATION_ROUTE, _SAFE_CLOSEOUT_ROUTE}
    }

    assert set(paths) == {_MATERIALIZATION_ROUTE, _SAFE_CLOSEOUT_ROUTE}
    for item in paths.values():
        assert item.live_enabled is False
        assert item.live_eligible is False
        assert item.live_command_runtime_ready is False
        assert item.live_command_runtime_missing_reason == (
            "operator_follow_up_intent_disabled"
        )


def test_materialization_capabilities_are_route_truthful_when_feature_and_service_are_enabled(
    monkeypatch,
):
    monkeypatch.setenv(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV, "1")
    monkeypatch.setattr(
        read_service_module,
        "_decision_backed_live_service_state",
        lambda: AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
            source="synthetic_test",
            missing_reason=None,
        ),
    )

    capabilities = _materialization_capabilities()
    readback = capabilities[("GET", _MATERIALIZATION_ROUTE)]
    materialize = capabilities[("POST", _MATERIALIZATION_ROUTE)]
    safe_closeout = capabilities[("POST", _SAFE_CLOSEOUT_ROUTE)]

    assert readback.availability == AdminApiRouteAvailability.AVAILABLE
    assert readback.frontend_safe is True
    assert readback.live_enabled is False
    assert readback.action_class == AdminApiActionClass.READ_ONLY
    assert readback.shared_method == "read_order_follow_up_materialization"
    for item, action_class, service_method in (
        (
            materialize,
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            "materialize_order_follow_up_intent",
        ),
        (
            safe_closeout,
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "safe_closeout_materialized_follow_up_intent",
        ),
    ):
        assert item.availability == AdminApiRouteAvailability.AVAILABLE
        assert item.frontend_safe is True
        assert item.live_enabled is True
        assert item.action_class == action_class
        assert item.shared_method == service_method

    live_paths = {
        item.route: item
        for item in AdminApiReadService().build_live_enablement().paths
        if item.route in {_MATERIALIZATION_ROUTE, _SAFE_CLOSEOUT_ROUTE}
    }
    for route, adapter_method in (
        (_MATERIALIZATION_ROUTE, "materialize"),
        (_SAFE_CLOSEOUT_ROUTE, "safe_closeout"),
    ):
        adapter_precondition = next(
            item
            for item in live_paths[route].readiness_preconditions
            if item.precondition.value == "live_execution_adapter"
        )
        assert adapter_precondition.source == (
            "canonical_operator_follow_up_materialization_runtime"
        )
        assert adapter_precondition.expected_source == (
            "OperatorFollowUpMaterializationFacade." + adapter_method
        )


def test_materialization_route_inventory_binds_three_distinct_authority_surfaces():
    entries = {
        item.surface: item
        for item in ADMIN_API_ROUTE_INVENTORY
        if "follow-up-intent/materialization" in item.surface
    }

    assert set(entries) == {
        f"GET {_MATERIALIZATION_ROUTE}",
        f"POST {_MATERIALIZATION_ROUTE}",
        f"POST {_SAFE_CLOSEOUT_ROUTE}",
    }
    assert entries[f"GET {_MATERIALIZATION_ROUTE}"].action_class == (
        AdminApiActionClass.READ_ONLY
    )
    assert entries[f"GET {_MATERIALIZATION_ROUTE}"].permission == (
        AdminApiPermission.AUDIT_READ
    )
    assert entries[f"POST {_MATERIALIZATION_ROUTE}"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_PLACE
    )
    assert entries[f"POST {_MATERIALIZATION_ROUTE}"].permission == (
        AdminApiPermission.ORDER_CREATE
    )
    assert entries[f"POST {_MATERIALIZATION_ROUTE}"].shared_method == (
        "materialize_order_follow_up_intent"
    )
    assert entries[f"POST {_SAFE_CLOSEOUT_ROUTE}"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    assert entries[f"POST {_SAFE_CLOSEOUT_ROUTE}"].permission == (
        AdminApiPermission.ORDER_CANCEL
    )
    assert entries[f"POST {_SAFE_CLOSEOUT_ROUTE}"].shared_method == (
        "safe_closeout_materialized_follow_up_intent"
    )
    for surface, item in entries.items():
        assert item.module_id == "spot_operations"
        if surface.startswith("POST "):
            assert "required" in item.idempotency
    assert "no Coinbase read or exchange mutation" in entries[
        f"GET {_MATERIALIZATION_ROUTE}"
    ].parity_test
    assert "one Create with zero retry or fallback" in entries[
        f"POST {_MATERIALIZATION_ROUTE}"
    ].parity_test
    assert "unknown consumes without retry, fallback" in entries[
        f"POST {_SAFE_CLOSEOUT_ROUTE}"
    ].parity_test


def test_materialization_openapi_requires_fresh_intent_and_withholds_raw_exchange_evidence():
    schema = yaml.safe_load(
        Path("openapi/coinbase-admin-api.yaml").read_text(encoding="utf-8")
    )
    paths = schema["paths"]
    materialize = paths[_MATERIALIZATION_ROUTE]["post"]
    safe_closeout = paths[_SAFE_CLOSEOUT_ROUTE]["post"]

    for operation, expected_intent in (
        (materialize, "authorize_and_materialize_follow_up_intent"),
        (safe_closeout, "safe_closeout_materialized_follow_up_intent"),
    ):
        headers = {
            item["name"]: item
            for item in operation["parameters"]
            if item.get("in") == "header"
        }
        assert headers["Idempotency-Key"]["required"] is True
        assert headers["X-Correlation-Id"]["required"] is True
        assert headers["X-Operator-Intent"]["required"] is True
        assert headers["X-Operator-Intent"]["schema"]["const"] == (
            expected_intent
        )

    components = schema["components"]["schemas"]
    request_properties = set(
        components["AdminOrderFollowUpMaterializationRequest"]["properties"]
    )
    cancel_properties = set(
        components["AdminOrderFollowUpMaterializationCancelRequest"]["properties"]
    )
    assert request_properties == {
        "authorize_materialization_of_attached_intent",
        "acknowledge_unknown_outcome_consumes_create_allowance",
        "acknowledge_child_terms_are_backend_derived",
    }
    assert cancel_properties == {
        "authorize_single_cancel_for_safe_closeout",
        "acknowledge_unknown_outcome_consumes_cancel_allowance",
    }
    forbidden_public_fields = {
        "exchange_order_id",
        "raw_response",
        "raw_coinbase_response",
        "withheld_exception_text",
        "api_key",
        "api_secret",
        "private_identifier",
    }
    materialization_schemas = {
        name: value
        for name, value in components.items()
        if name.startswith("AdminOrderFollowUpMaterialization")
    }
    assert materialization_schemas
    for value in materialization_schemas.values():
        assert forbidden_public_fields.isdisjoint(value.get("properties", {}))
        assert value.get("additionalProperties") is False


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
