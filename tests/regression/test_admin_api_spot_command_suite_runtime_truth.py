"""Runtime and request-authority truth for the Spot command-suite readback."""

import pytest

from core.enums import (
    AdminApiFunctionalityExposureStatus,
    AdminApiFunctionalityWorkflowType,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiLiveReadinessPrecondition,
    AdminApiModuleSupportStatus,
    AdminApiMutationFamilyType,
)


pytestmark = [
    pytest.mark.regression,
    pytest.mark.usefixtures("coinbase_execution_lease"),
]

_CONTROLLED_LIVE_ROUTES = {
    "/api/v1/orders",
    "/api/v1/orders/{client_order_id}/cancel",
}


def _service_with_runtime_state(monkeypatch, *, runtime_ready: bool):
    from application.admin_api.read_service import AdminApiReadService

    service = AdminApiReadService()
    baseline = service.build_live_enablement()
    paths = []
    for path in baseline.paths:
        if path.route not in _CONTROLLED_LIVE_ROUTES:
            paths.append(path)
            continue
        request_preconditions = [
            item
            for item in path.readiness_preconditions
            if item.precondition
            != AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_SERVICE
        ]
        paths.append(
            path.model_copy(
                update={
                    "live_enabled": True,
                    "live_eligible": runtime_ready,
                    "status": AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                    "live_command_runtime_ready": runtime_ready,
                    "live_command_runtime_missing_reason": (
                        None if runtime_ready else "root_order_registrar_unavailable"
                    ),
                    "readiness_preconditions": request_preconditions,
                }
            )
        )
    controlled_live = baseline.model_copy(update={"paths": paths})
    monkeypatch.setattr(service, "build_live_enablement", lambda: controlled_live)
    return service


def _suite_with_runtime_state(monkeypatch, *, runtime_ready: bool):
    service = _service_with_runtime_state(
        monkeypatch,
        runtime_ready=runtime_ready,
    )
    return service.build_spot_command_suite().model_dump(mode="json")


def test_spot_command_suite_separates_enabled_route_from_unready_runtime(monkeypatch):
    payload = _suite_with_runtime_state(monkeypatch, runtime_ready=False)
    commands = {item["mutation_family"]: item for item in payload["commands"]}

    for family in (
        AdminApiMutationFamilyType.SPOT_MANUAL_ORDER.value,
        AdminApiMutationFamilyType.SPOT_ORDER_CANCEL.value,
    ):
        command = commands[family]
        assert command["live_enabled"] is True
        assert command["live_eligible"] is False
        assert command["executable"] is False
        assert command["status"] == AdminApiGateStatus.BLOCKED.value
        assert "live_command_runtime" in command["missing_gate_chain"]
        assert command["browser_authority"] == "display_only"
        assert command["bff_authority"] == "forward_only_no_execution"


def test_enterprise_readiness_classifies_only_manual_and_cancel_as_controlled_live(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    service = AdminApiReadService()

    def fail_if_dynamic_live_readback_is_built():
        raise AssertionError("enterprise readiness must remain a static catalog")

    monkeypatch.setattr(
        service,
        "build_live_enablement",
        fail_if_dynamic_live_readback_is_built,
    )

    payload = service.build_enterprise_readiness().model_dump(mode="json")
    workflows = {
        item["workflow_id"]: item for item in payload["functionality_inventory"]
    }
    order_workflow = workflows["spot.order_command_drafts"]
    parked_workflow = workflows["spot.sweep_automation_and_live_executor"]

    assert order_workflow["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.LIVE_EXECUTION.value
    )
    assert order_workflow["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
    )
    assert order_workflow["support_status"] == (
        AdminApiModuleSupportStatus.PLATFORM_READY.value
    )
    assert order_workflow["command_routes"] == [
        "POST /api/v1/orders",
        "POST /api/v1/orders/{client_order_id}/cancel",
    ]
    assert order_workflow["live_enabled"] is False
    assert "approval_snapshot_missing" in order_workflow["blockers"]
    assert "cap_guard_missing" in order_workflow["blockers"]
    assert "reconciliation_plan_missing" in order_workflow["blockers"]
    assert "live_execution_disabled" not in order_workflow["blockers"]
    assert "current_live_runtime_readback_required" in (
        order_workflow["blockers"]
    )

    assert parked_workflow["live_enabled"] is False
    assert parked_workflow["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert parked_workflow["support_status"] == (
        AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
    )

    taxonomy = {
        item["mutation_id"]: item for item in payload["mutation_taxonomy"]
    }
    for mutation_id in ("spot.manual_order", "spot.order_cancel"):
        item = taxonomy[mutation_id]
        assert item["exposure_status"] == (
            AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
        )
        assert item["support_status"] == (
            AdminApiModuleSupportStatus.PLATFORM_READY.value
        )
        assert "live_execution_disabled" not in item["blockers"]
        assert "approval_snapshot_missing" in item["blockers"]
        assert "reconciliation_plan_missing" in item["blockers"]
        assert "current_live_runtime_readback_required" in item["blockers"]
        assert "per-request" in item["summary"]

    for mutation_id in (
        "spot.campaign_execution",
        "spot.sweep_automation",
        "stealth.create",
        "stealth.cancel",
        "stealth.reveal",
        "stealth.move",
    ):
        item = taxonomy[mutation_id]
        assert item["support_status"] == (
            AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
        )
        assert item["exposure_status"] == (
            AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
        )


def test_spot_command_suite_runtime_capability_is_not_request_authorization(monkeypatch):
    payload = _suite_with_runtime_state(monkeypatch, runtime_ready=True)
    commands = {item["mutation_family"]: item for item in payload["commands"]}

    assert payload["live_enabled_command_count"] == 2
    assert payload["executable_command_count"] == 2
    assert "does not authorize a request" in payload["message"]
    for family in (
        AdminApiMutationFamilyType.SPOT_MANUAL_ORDER.value,
        AdminApiMutationFamilyType.SPOT_ORDER_CANCEL.value,
    ):
        command = commands[family]
        assert command["live_enabled"] is True
        assert command["live_eligible"] is True
        assert command["executable"] is True
        assert command["status"] == AdminApiGateStatus.BLOCKED.value
        assert "live_command_runtime" not in command["missing_gate_chain"]
        assert "approval_snapshot" in command["missing_gate_chain"]
        assert "admission_audit_trail" in command["missing_gate_chain"]
        assert "cap_guard_contract" in command["missing_gate_chain"]
        assert "reconciliation_plan" in command["missing_gate_chain"]
        assert any(
            "does not authorize this request" in evidence
            for evidence in command["evidence"]
        )
        assert command["browser_authority"] == "display_only"
        assert command["bff_authority"] == "forward_only_no_execution"


@pytest.mark.parametrize(
    ("route", "service_method", "action_class"),
    [
        (
            "/api/v1/orders",
            "place_manual_order",
            "live_exchange_place",
        ),
        (
            "/api/v1/orders/{client_order_id}/cancel",
            "cancel_order_by_client_order_id",
            "live_exchange_cancel",
        ),
    ],
)
def test_manual_spot_adapter_reports_installed_canonical_runtime_capability(
    route,
    service_method,
    action_class,
):
    from application.admin_api.live_execution import (
        build_live_execution_adapter_contract,
    )

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
    assert adapter["source"] == "canonical_admin_operator_runtime"
    assert adapter["missing_reason"] == "per_request_admission_required"
    assert adapter["route_mapping_satisfies_construction"] is True
    assert adapter["adapter_configuration_satisfies_construction"] is True
    assert adapter["construction_precondition_resolved"] is True
    assert adapter["missing_construction_artifacts"] == []
    assert adapter["construction_blockers"] == []
    assert adapter["latest_adapter_decision_resolver_eligible"] is False
    assert adapter["latest_adapter_decision_resolves_construction"] is False
    assert adapter["browser_authority"] == "display_only"
    assert adapter["bff_authority"] == "forward_only_no_execution"
    assert "does not authorize a request" in adapter["detail"]


def test_only_manual_spot_routes_use_current_runtime_adapter_evidence():
    from application.admin_api.live_execution import (
        build_live_execution_adapter_contract,
    )

    campaign = build_live_execution_adapter_contract(
        method="POST",
        route="/api/v1/spot/campaign/executions",
        module_id="spot_operations",
        service_method="execute_spot_campaign",
        action_class="live_exchange_place",
        include_construction_contract=False,
    )
    stealth_reveal = build_live_execution_adapter_contract(
        method="POST",
        route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        module_id="stealth_orders",
        service_method="reveal_stealth_order_by_stealth_order_id",
        action_class="live_exchange_place",
        include_construction_contract=False,
    )

    assert campaign["configured"] is False
    assert campaign["executable"] is False
    assert campaign["source"] == "disabled_backend_service"
    assert stealth_reveal["configured"] is True
    assert stealth_reveal["executable"] is False
    assert stealth_reveal["source"] == "m55_stealth_reveal_backend_dry_run"


def test_generic_live_enablement_text_distinguishes_capability_from_authority():
    from application.admin_api.read_service import AdminApiReadService

    payload = AdminApiReadService().build_live_enablement().model_dump(mode="json")
    checks = {item["name"]: item for item in payload["checks"]}

    command_detail = checks["m6_command_contracts"]["detail"]
    reconciliation_detail = checks["reconciliation_gate"]["detail"]
    assert "remain live-disabled until explicit M8 approval" not in command_detail
    assert "Manual Spot place/cancel" in command_detail
    assert "No path is live-enabled" not in reconciliation_detail
    assert "does not authorize a request" in reconciliation_detail


def test_live_enablement_requires_command_runtime_readiness_for_eligibility(
    monkeypatch,
):
    from application.admin_api import read_service
    from application.admin_api.command_runtime import (
        AdminApiCommandRuntimeReadiness,
    )
    from application.admin_api.live_execution import (
        AdminApiLiveExecutionServiceState,
    )
    from application.admin_api.read_service import AdminApiReadService

    portfolio_scope = (
        read_service.build_admin_api_command_runtime_readiness().spot_portfolio_scope
    )
    monkeypatch.setattr(
        read_service,
        "_decision_backed_live_service_state",
        lambda: AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
            source="synthetic_controlled_live_decision",
            missing_reason=None,
        ),
    )
    monkeypatch.setattr(
        read_service,
        "build_admin_api_command_runtime_readiness",
        lambda: AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=True,
            runtime_ready=False,
            missing_reason="order_event_publisher_unavailable",
            order_root_registrar_available=True,
            order_event_publisher_available=False,
            spot_portfolio_scope=portfolio_scope,
        ),
    )

    payload = AdminApiReadService().build_live_enablement().model_dump(mode="json")
    controlled = {
        item["route"]: item
        for item in payload["paths"]
        if item["route"] in _CONTROLLED_LIVE_ROUTES
    }

    assert payload["live_enabled_path_count"] == 2
    assert payload["live_eligible_path_count"] == 0
    for path in controlled.values():
        assert path["live_enabled"] is True
        assert path["live_eligible"] is False
        assert path["live_command_runtime_ready"] is False
        assert path["live_command_runtime_missing_reason"] == (
            "order_event_publisher_unavailable"
        )


def test_bootstrap_and_health_report_armed_routes_without_granting_requests(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED", "true")
    service = AdminApiReadService()

    bootstrap = service.build_admin_bootstrap().model_dump(mode="json")
    health = service.build_admin_health().model_dump(mode="json")
    diagnostics = {
        (item["method"], item["path"]): item
        for item in health["diagnostics"]
    }

    assert bootstrap["mutating_routes_live_disabled"] is False
    assert bootstrap["live_execution_enabled"] is True
    assert health["live_execution_enabled"] is True
    for route in _CONTROLLED_LIVE_ROUTES:
        diagnostic = diagnostics[("POST", route)]
        assert diagnostic["status"] == "available"
        assert "route is supported" in diagnostic["message"]
        assert "runtime is armed" in diagnostic["message"]
        assert "per-request authorization is still required" in diagnostic[
            "message"
        ]

    campaign = diagnostics[("POST", "/api/v1/spot/campaign/executions")]
    assert campaign["status"] == "live_disabled"
    assert "not a controlled-live operator route" in campaign["message"]
