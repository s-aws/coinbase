from __future__ import annotations

import json
import re
from copy import deepcopy
from types import SimpleNamespace

from application.admin_api.models import (
    AdminFuturesAccountReadResponse,
    AdminFuturesAccountReadinessEvidence,
    AdminFuturesAccountRealityEvidence,
    AdminFuturesEvidenceItem,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionReadFilters,
    AdminFuturesPositionListResponse,
    AdminFuturesPositionReadItem,
)
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
    _source_disabled_futures_account_snapshot,
)
from application.admin_api.read_service import _futures_position_item_from_raw
from core.enums import AdminFuturesEvidenceSource


PRIVATE_PORTFOLIO_UUID = "11111111-2222-4333-8444-555555555555"
WITHHELD_EXCEPTION_TEXT = "withheld-futures-reader-exception-text"
POSITION_KEY_PATTERN = re.compile(r"^fpos_[0-9a-f]{64}$")


def _context() -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key="futures-public-projection",
        correlation_id="futures-public-projection-correlation",
        operator_intent="read_futures_public_projection",
        actor_id="futures-public-projection-operator",
        roles=("viewer",),
    )


def _hostile_local_snapshot() -> dict[str, object]:
    snapshot = _source_disabled_futures_account_snapshot(
        "2026-07-20T12:00:00+00:00"
    )
    snapshot["account_reality"].update(
        {
            "status": "ready",
            "source": "backend_rest_client",
            "proof_id": "account-reality-sanitized",
            "read_error": "none",
            "private_extension": WITHHELD_EXCEPTION_TEXT,
        }
    )
    snapshot["readiness"]["private_extension"] = WITHHELD_EXCEPTION_TEXT
    snapshot["portfolio_scope"] = {
        "portfolio_id": PRIVATE_PORTFOLIO_UUID,
        "portfolio_name": WITHHELD_EXCEPTION_TEXT,
        "source": "backend_rest_client",
        "freshness_status": "backend_rest_fresh",
    }
    snapshot["futures_portfolio_binding"].update(
        {
            "status": "matched",
            "ready": True,
            "blocker": None,
            "observed_portfolio_id": PRIVATE_PORTFOLIO_UUID,
            "observed_portfolio_label": "Default",
            "observed_portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
            "read_authorized": True,
            "source": "coinbase_api_key_permissions_and_portfolio_catalog",
            "freshness_status": "backend_rest_fresh",
            "permissions_read_ran": True,
            "portfolio_catalog_read_ran": True,
            "portfolio_id": PRIVATE_PORTFOLIO_UUID,
            "credential_trade_permission_present": True,
        }
    )
    snapshot["readiness"].update(
        {
            "futures_account_scope_ready": True,
            "futures_default_profile_bound": True,
            "futures_observed_position_scope_ready": True,
            "futures_margin_collateral_ready": True,
            "usable_for_futures_risk": True,
        }
    )
    snapshot["futures_positions"] = [
        {
            "product_id": "AVP-20DEC30-CDE",
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
            "position_side": "LONG",
            "number_of_contracts": "1.0000",
            "net_size": "1.0000",
            "entry_price": "6.5000",
            "entry_vwap": "6.5000",
            "current_price": "6.9200",
            "margin_type": "cross",
            "margin_amt": {
                "value": "25.00",
                "currency": "USD",
                "private": PRIVATE_PORTFOLIO_UUID,
            },
            "leverage": "2.000",
            "liquidation_buffer_percentage": "40.000",
            "unrealized_pnl": {
                "value": "0.42",
                "currency": "USD",
                "exception": WITHHELD_EXCEPTION_TEXT,
            },
            "product_metadata": {
                "private_extension": PRIVATE_PORTFOLIO_UUID,
            },
            "raw_position": {
                "exception": WITHHELD_EXCEPTION_TEXT,
            },
            "updated_at": "2026-07-20T12:34:56.000000Z",
            "private_extension": {
                "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
                "exception": WITHHELD_EXCEPTION_TEXT,
            },
            "source": "backend_rest_client",
        }
    ]
    snapshot["futures_margin_collateral"] = {
        "status": "ready",
        "source": "backend_rest_client",
        "blocker": "none",
        "collateral": {
            "name": "collateral",
            "status": "ready",
            "source": "backend_rest_client",
            "detail": WITHHELD_EXCEPTION_TEXT,
            "value": {
                "available_margin": {
                    "value": "250.00",
                    "currency": "USD",
                    "private": PRIVATE_PORTFOLIO_UUID,
                },
                "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
            },
        },
        "margin": {
            "name": "margin",
            "status": "ready",
            "source": "backend_rest_client",
            "detail": WITHHELD_EXCEPTION_TEXT,
            "value": {
                "initial_margin": {
                    "value": "40.00",
                    "currency": "USD",
                    "private": PRIVATE_PORTFOLIO_UUID,
                },
                "private_extension": WITHHELD_EXCEPTION_TEXT,
            },
        },
    }
    snapshot["coinbase_read_ran"] = False
    return snapshot


def _serialized(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_futures_get_projection_withholds_private_values_and_uses_opaque_detail_keys(
    monkeypatch,
) -> None:
    service = AdminMvpService(AdminMvpDependencies())
    snapshot = _hostile_local_snapshot()
    monkeypatch.setattr(
        service,
        "_futures_local_account_snapshot",
        lambda: deepcopy(snapshot),
    )

    account = service.get_read_response(
        "/api/v1/futures/account",
        {},
        _context(),
    ).body
    positions = service.get_read_response(
        "/api/v1/futures/positions",
        {"limit": "10", "offset": "0"},
        _context(),
    ).body
    position_key = positions["items"][0]["position_key"]
    detail = service.get_read_response(
        f"/api/v1/futures/positions/{position_key}",
        {},
        _context(),
    ).body
    invalid_detail = service.get_read_response(
        f"/api/v1/futures/positions/futures_position:{PRIVATE_PORTFOLIO_UUID}:AVP-20DEC30-CDE",
        {},
        _context(),
    ).body
    invalid_positions = service.get_read_response(
        "/api/v1/futures/positions",
        {"product_id": WITHHELD_EXCEPTION_TEXT, "limit": "9999", "offset": "-1"},
        _context(),
    ).body

    AdminFuturesAccountReadResponse.model_validate(account)
    AdminFuturesPositionListResponse.model_validate(positions)
    AdminFuturesPositionDetailResponse.model_validate(detail)
    AdminFuturesPositionDetailResponse.model_validate(invalid_detail)
    AdminFuturesPositionListResponse.model_validate(invalid_positions)

    assert POSITION_KEY_PATTERN.fullmatch(position_key)
    assert detail["found"] is True
    assert detail["position_key"] == position_key
    assert invalid_detail["found"] is False
    assert invalid_detail["position_key"] is None
    assert invalid_detail["position"] is None

    for payload in (account, positions, detail, invalid_detail, invalid_positions):
        serialized = _serialized(payload)
        assert PRIVATE_PORTFOLIO_UUID not in serialized
        assert WITHHELD_EXCEPTION_TEXT not in serialized
        assert payload["private_identifier_values_included"] is False

    assert account["account_reality"] == {
        "status": "ready",
        "source": "backend_rest_client",
    }
    assert "private_extension" not in account["account_readiness"]
    assert invalid_positions["filters"] == {
        "product_id": None,
        "position_side": None,
        "limit": 500,
        "offset": 0,
        "filter_status": "invalid",
    }

    assert positions["position_key_policy"] == "opaque_backend_token"
    assert detail["position_key_policy"] == "opaque_backend_token"
    item = positions["items"][0]
    assert item["number_of_contracts"] == "1"
    assert item["net_size"] == "1"
    assert item["entry_price"] == "6.5"
    assert item["current_price"] == "6.92"
    assert item["margin_type"] == "CROSS"
    assert item["margin_amount_label"] == "amount:25:USD"
    assert item["position_pnl_label"] == "pnl:0.42:USD"
    assert item["product_metadata_label"] == "product_metadata_unavailable"
    assert item["leverage"] == "2"
    assert item["liquidation_buffer_percentage"] == "40"
    assert item["updated_at"] == "2026-07-20T12:34:56Z"
    for forbidden in (
        "portfolio_uuid",
        "raw_position",
        "product_metadata",
        "position_pnl",
        "margin_amount",
    ):
        assert forbidden not in item
    assert account["portfolio_binding"]["observed_portfolio_id"] is None
    assert account["portfolio_binding"]["portfolio_id"] is None
    assert "value" not in account["collateral"]
    assert "detail" not in account["collateral"]
    assert account["collateral"]["value_label"] == (
        "collateral_observed:amount:250:USD"
    )


def test_legacy_read_service_position_projection_is_opaque_and_scalar_only() -> None:
    item = _futures_position_item_from_raw(
        product_id="AVP-20DEC30-CDE",
        position={
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
            "side": "SHORT",
            "number_of_contracts": "2.000",
            "entry_price": "8.2500",
            "current_price": "7.0000",
            "margin_type": WITHHELD_EXCEPTION_TEXT,
            "margin_amt": {"private": PRIVATE_PORTFOLIO_UUID},
            "unrealized_pnl": WITHHELD_EXCEPTION_TEXT,
            "updated_at": "2026-07-20T12:34:56+00:00",
            "private_extension": WITHHELD_EXCEPTION_TEXT,
        },
        product_metadata={
            "product_id": "AVP-20DEC30-CDE",
            "private_extension": WITHHELD_EXCEPTION_TEXT,
        },
        mandatory_fee_per_contract="0.3400",
        source=AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK,
    )

    payload = item.model_dump(mode="json")
    AdminFuturesPositionReadItem.model_validate(payload)
    assert POSITION_KEY_PATTERN.fullmatch(payload["position_key"])
    assert payload["number_of_contracts"] == "2"
    assert payload["entry_price"] == "8.25"
    assert payload["current_price"] == "7"
    assert payload["mandatory_fee_per_contract"] == "0.34"
    assert payload["margin_type"] == "UNKNOWN"
    assert PRIVATE_PORTFOLIO_UUID not in _serialized(payload)
    assert WITHHELD_EXCEPTION_TEXT not in _serialized(payload)
    for forbidden in (
        "portfolio_uuid",
        "raw_position",
        "product_metadata",
        "position_pnl",
        "margin_amount",
    ):
        assert forbidden not in payload


def test_futures_public_openapi_models_have_no_flexible_private_value_escape_hatches() -> None:
    position_schema = AdminFuturesPositionReadItem.model_json_schema()
    position_properties = position_schema["properties"]
    assert position_properties["position_key"]["pattern"] == (
        "^fpos_[0-9a-f]{64}$"
    )
    for forbidden in (
        "portfolio_uuid",
        "raw_position",
        "product_metadata",
        "position_pnl",
        "margin_amount",
    ):
        assert forbidden not in position_properties

    evidence_schema = AdminFuturesEvidenceItem.model_json_schema()
    assert "value" not in evidence_schema["properties"]
    assert "detail" not in evidence_schema["properties"]
    assert "value_label" in evidence_schema["properties"]

    for strict_model in (
        AdminFuturesAccountRealityEvidence,
        AdminFuturesAccountReadinessEvidence,
        AdminFuturesPositionReadFilters,
    ):
        assert strict_model.model_json_schema()["additionalProperties"] is False
    account_reality_properties = (
        AdminFuturesAccountRealityEvidence.model_json_schema()["properties"]
    )
    assert set(account_reality_properties) == {"status", "source"}
    filters_properties = AdminFuturesPositionReadFilters.model_json_schema()[
        "properties"
    ]
    assert set(filters_properties) == {
        "product_id",
        "position_side",
        "limit",
        "offset",
        "filter_status",
    }

    list_schema = AdminFuturesPositionListResponse.model_json_schema()
    detail_schema = AdminFuturesPositionDetailResponse.model_json_schema()
    account_schema = AdminFuturesAccountReadResponse.model_json_schema()
    assert list_schema["properties"]["private_identifier_values_included"][
        "const"
    ] is False
    assert detail_schema["properties"]["private_identifier_values_included"][
        "const"
    ] is False
    assert account_schema["properties"]["private_identifier_values_included"][
        "const"
    ] is False
    for response_schema in (list_schema, detail_schema, account_schema):
        assert response_schema["properties"]["read_only"]["const"] is True
        assert response_schema["properties"]["live_coinbase_orders_ran"][
            "const"
        ] is False
        assert response_schema["properties"]["live_coinbase_execution"][
            "const"
        ] == "not_run"
    assert list_schema["properties"]["position_key_policy"]["const"] == (
        "opaque_backend_token"
    )
    assert detail_schema["properties"]["position_key_policy"]["const"] == (
        "opaque_backend_token"
    )
