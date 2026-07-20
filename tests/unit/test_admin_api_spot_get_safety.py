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

    assert payload["type"] == "spot_readiness"
    assert payload["status"] == "blocked"
    assert payload["account_reality"]["status"] == "blocked"
    assert payload["account_reality"]["source"] == (
        "backend_admin_api_local_evidence"
    )
    assert payload["account_reality"]["fresh_until"] is None
    assert payload["account_scope"]["configured_product_scope"] == [
        "BTC-USDC"
    ]
    assert payload["portfolio_scope"]["portfolio_id"] == "withheld"
    assert payload["portfolio_scope"]["portfolio_name"] == "Test"
    assert payload["spot_admission_input"]["status"] == "blocked"
    assert payload["products"][0]["product_id"] == "BTC-USDC"
    assert payload["products"][0]["product_type"] == "SPOT"
    assert payload["products"][0]["product_family"] == "spot"
    assert payload["products"][0]["product_read_status"] == "blocked"
    assert payload["products"][0]["backend_owned"] is True
    assert payload["products"][0]["capabilities"][
        "product_capability_contract"
    ]["mode"] == "blocked"
    assert payload["wallet_snapshot"]["available"] is False
    assert payload["wallet_snapshot"]["backend_owned"] is True
    assert len(payload["action_guard_summary"]) == 4
    assert payload["message"] == (
        "spot_readiness_uses_durable_account_reality_evidence"
    )
    assert payload["blockers"] == ["coinbase_page_load_read_not_authorized"]
    assert payload["local_only"] is True
    assert payload["values_withheld"] is True
    assert payload["coinbase_read_attempted"] is False
    assert payload["coinbase_read_succeeded"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["external_state_refresh_available"] is True
    assert payload["external_state_refresh_route"] == (
        "/api/v1/admin/account-reality/refresh"
    )
    assert payload["browser_authority"] == "display_only"
    assert payload["bff_authority"] == "read_only_forward"
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
    assert {
        "account_reality",
        "account_scope",
        "portfolio_scope",
        "account_readiness",
        "spot_admission_input",
        "configured_product_scope",
        "captured_at",
        "fresh_until",
        "coinbase_read_enabled",
    } <= readiness_fields
    assert safety_fields | {
        "requested_product_ids",
        "coinbase_average_cost_requested",
    } <= pnl_fields
