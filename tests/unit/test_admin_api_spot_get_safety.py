from __future__ import annotations

import json


PRIVATE_BALANCE = "987654.321-private-balance"
PRIVATE_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


def _fail_if_legacy_builder_runs(*_args, **_kwargs):
    raise AssertionError("ordinary Admin Spot GET delegated to a legacy live-read builder")


def _assert_value_blind(payload: object) -> None:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    assert PRIVATE_BALANCE not in serialized
    assert PRIVATE_PORTFOLIO_ID not in serialized
    for forbidden_key in (
        "available_balance",
        "portfolio_id",
        "retail_portfolio_id",
        "total_pnl",
        "unrealized_pnl_usdc",
        "entry_price",
        "quantity",
    ):
        assert f'"{forbidden_key}"' not in serialized


def test_ordinary_spot_readiness_get_builder_is_local_call_free_and_value_blind(
    monkeypatch,
) -> None:
    import dashboard_server

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        dashboard_server,
        "_build_spot_readiness_payload",
        _fail_if_legacy_builder_runs,
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_ID)
    monkeypatch.setenv("COINBASE_API_KEY", PRIVATE_BALANCE)

    payload = AdminApiReadService().build_spot_readiness(
        product_ids=["BTC-USDC"],
    )

    assert payload == {
        "type": "spot_readiness",
        "status": "blocked",
        "products": [{"product_id": "BTC-USDC"}],
        "planned_budget": {},
        "wallet_snapshot": {
            "status": "withheld",
            "available": False,
            "values_withheld": True,
            "reason": "wallet_evidence_resolves_only_during_authorized_backend_action",
        },
        "action_guard_summary": [
            {
                "label": "Per-action wallet admission",
                "mode": "backend_only",
                "reason": "wallet_evidence_resolves_only_during_authorized_backend_action",
            }
        ],
        "message": "spot_readiness_requires_explicit_authorized_backend_action",
        "blockers": ["explicit_authorized_refresh_not_implemented"],
        "local_only": True,
        "values_withheld": True,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "live_coinbase_read_ran": False,
        "live_coinbase_orders_ran": False,
        "external_state_refresh_available": False,
        "external_state_refresh_route": None,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
    }
    _assert_value_blind(payload)


def test_ordinary_spot_sweep_pnl_get_builder_is_local_call_free_and_value_blind(
    monkeypatch,
) -> None:
    import dashboard_server

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        dashboard_server,
        "_build_spot_sweep_pnl_payload",
        _fail_if_legacy_builder_runs,
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_ID)
    monkeypatch.setenv("COINBASE_API_KEY", PRIVATE_BALANCE)

    payload = AdminApiReadService().build_spot_sweep_pnl(
        product_ids=["BTC-USDC"],
        include_coinbase_average_cost=True,
    )

    assert payload == {
        "type": "spot_sweep_pnl",
        "status": "blocked",
        "pnl_report": None,
        "read_only_coinbase_requests": [],
        "message": "spot_pnl_values_withheld_from_ordinary_get",
        "requested_product_ids": ["BTC-USDC"],
        "blockers": ["explicit_authorized_refresh_not_implemented"],
        "local_only": True,
        "values_withheld": True,
        "coinbase_average_cost_requested": True,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "live_coinbase_read_ran": False,
        "live_coinbase_orders_ran": False,
        "external_state_refresh_available": False,
        "external_state_refresh_route": None,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
    }
    _assert_value_blind(payload)


def test_spot_get_safety_evidence_is_declared_in_the_typed_contract() -> None:
    from application.admin_api.models import (
        SpotReadinessResponse,
        SpotSweepPnlResponse,
    )

    safety_fields = {
        "blockers",
        "local_only",
        "values_withheld",
        "coinbase_read_attempted",
        "coinbase_read_succeeded",
        "live_coinbase_read_ran",
        "external_state_refresh_available",
        "external_state_refresh_route",
        "browser_authority",
        "bff_authority",
    }

    readiness_fields = set(
        SpotReadinessResponse.model_json_schema()["properties"]
    )
    pnl_fields = set(SpotSweepPnlResponse.model_json_schema()["properties"])

    assert safety_fields <= readiness_fields
    assert safety_fields | {
        "requested_product_ids",
        "coinbase_average_cost_requested",
    } <= pnl_fields
