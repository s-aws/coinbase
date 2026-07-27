from __future__ import annotations

from application.admin_api.read_service import AdminApiReadService
from application.admin_api.route_inventory import (
    ADMIN_API_ROUTE_INVENTORY,
)
from core.enums import AdminApiActionClass, AdminApiPermission


def test_goal16_and_m58_enterprise_contracts_do_not_borrow_authority() -> None:
    readiness = AdminApiReadService().build_enterprise_readiness()
    workflows = {
        item.workflow_id: item
        for item in readiness.functionality_inventory
    }
    goal16 = workflows["operator_spot_sweep_safe_closeout_v1"]
    m58 = workflows["spot.sweep_automation_and_live_executor"]

    goal16_reads = {
        "GET /api/v1/spot/safe-closeout-sweeps/candidates",
        "GET /api/v1/spot/safe-closeout-sweeps/current",
        "GET /api/v1/spot/safe-closeout-sweeps/{sweep_id}",
    }
    goal16_commands = {
        "POST /api/v1/spot/safe-closeout-sweeps",
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/pause"
        ),
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/resume"
        ),
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/abort"
        ),
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/advance"
        ),
    }
    assert set(goal16.read_routes) == goal16_reads
    assert set(goal16.command_routes) == goal16_commands
    assert goal16.automation_routes == []
    assert goal16.identity_keys == ["sweep_id", "client_order_id"]
    assert all(
        "usdc_pair_snapshot" not in reference
        and "run_spot_portfolio_sweep" not in reference
        for reference in goal16.backend_contract_refs
    )
    assert all(
        "safe-closeout-sweeps" not in surface
        for surface in (
            m58.read_routes
            + m58.command_routes
            + m58.automation_routes
            + m58.backend_contract_refs
        )
    )
    assert "m58_operator_workflow_unavailable" in m58.blockers
    assert (
        "operator_spot_sweep_live_read_authority_incomplete"
        in goal16.blockers
    )

    taxonomy = {
        item.mutation_id: item
        for item in readiness.mutation_taxonomy
    }
    local = taxonomy[
        "spot.operator_safe_closeout_sweep_local_control"
    ]
    advance = taxonomy["spot.operator_safe_closeout_sweep_advance"]
    assert set(local.command_surfaces) == goal16_commands - {
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/advance"
        )
    }
    assert local.live_adapter_required is False
    assert advance.command_surfaces == [
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/advance"
        )
    ]
    assert advance.live_adapter_required is True

    inventory = {
        item.surface: item for item in ADMIN_API_ROUTE_INVENTORY
    }
    for surface in goal16_reads:
        row = inventory[surface]
        assert row.action_class is AdminApiActionClass.READ_ONLY
        assert row.permission is AdminApiPermission.ANALYTICS_READ
    for surface in goal16_commands:
        row = inventory[surface]
        assert row.required_permissions == [
            AdminApiPermission.SPOT_SWEEP_EXECUTE,
            AdminApiPermission.ORDER_CANCEL,
        ]
    assert inventory[
        (
            "POST /api/v1/spot/safe-closeout-sweeps/"
            "{sweep_id}/advance"
        )
    ].action_class is AdminApiActionClass.LIVE_EXCHANGE_CANCEL
