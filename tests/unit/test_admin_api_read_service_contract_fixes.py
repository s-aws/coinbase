from application.admin_api.read_service import AdminApiReadService
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import AdminApiActionClass, ProductCapability


def test_enterprise_taxonomy_covers_selected_root_reconciliation_once():
    payload = AdminApiReadService().build_enterprise_readiness().model_dump(
        mode="json"
    )

    command_surfaces = sorted(
        item.surface
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.action_class != AdminApiActionClass.READ_ONLY
    )
    taxonomy_surfaces = sorted(
        surface
        for item in payload["mutation_taxonomy"]
        for surface in item["command_surfaces"]
    )

    assert taxonomy_surfaces == command_surfaces
    assert len(taxonomy_surfaces) == len(set(taxonomy_surfaces))

    taxonomy = {
        item["mutation_id"]: item for item in payload["mutation_taxonomy"]
    }["spot.selected_root_reconciliation"]
    assert taxonomy["command_surfaces"] == [
        "POST /api/v1/orders/{client_order_id}/reconciliation"
    ]
    assert taxonomy["action_classes"] == ["local_state_mutation"]
    assert taxonomy["required_permissions"] == ["order:cancel"]
    assert taxonomy["identity_keys"] == ["client_order_id"]
    assert taxonomy["approval_required"] is False
    assert taxonomy["cap_guard_required"] is False
    assert taxonomy["reconciliation_required"] is False
    assert taxonomy["live_adapter_required"] is True
    assert taxonomy["route_local_execution_allowed"] is False

    workflow = {
        item["workflow_id"]: item for item in payload["functionality_inventory"]
    }["spot.selected_root_reconciliation"]
    assert workflow["command_routes"] == taxonomy["command_surfaces"]
    assert workflow["identity_keys"] == ["client_order_id"]
    assert workflow["live_coinbase_execution"] == "not_run"


def test_guard_risk_capability_errors_are_value_blind_and_counted(monkeypatch):
    import core.product_capability as capability_module

    private_detail = "private capability evaluator detail"

    def fail_evaluate_product_capability(*args, **kwargs):
        raise RuntimeError(private_detail)

    monkeypatch.setattr(
        capability_module,
        "evaluate_product_capability",
        fail_evaluate_product_capability,
    )

    response = AdminApiReadService().build_guard_risk_policy(
        product_id="BTC-USDC"
    )
    policy = response.product_capability_policy
    errors = policy.value["decision_errors"]

    assert response.product_capability_decisions == []
    assert policy.status.value == "unavailable"
    assert policy.value["decision_count"] == 0
    assert policy.value["decision_error_count"] == len(ProductCapability)
    assert len(errors) == len(ProductCapability)
    assert all(error.endswith("exception_class:RuntimeError") for error in errors)
    assert private_detail not in str(errors)
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
