from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
)
from application.admin_api.models import (
    AdminAccountManagementReadResponse,
    AdminFeesReadResponse,
    AdminFuturesAccountReadResponse,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
    AdminProductsReadResponse,
    AdminWalletReadResponse,
)


PRIVATE_PORTFOLIO_UUID = "11111111-2222-4333-8444-555555555555"
PRIVATE_EXCEPTION_TEXT = "withheld-account-reader-detail"


def _context() -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key="account-read-privacy",
        correlation_id="account-read-privacy-correlation",
        operator_intent="read_operator_account_evidence",
        actor_id="operator-account-read-privacy",
        roles=("operator",),
    )


@dataclass
class _ControlledReadClient:
    calls: list[str] = field(default_factory=list)

    def get_account_wallets(self) -> dict[str, dict[str, str]]:
        self.calls.append("get_account_wallets")
        return {
            "USDC": {
                "currency": "USDC",
                "available_balance": "12.34",
                "total_balance": "15.00",
                "hold_balance": "2.66",
            }
        }

    def get_api_key_permissions(self) -> dict[str, object]:
        self.calls.append("get_api_key_permissions")
        return {
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, object]]:
        self.calls.append("list_portfolios")
        return [
            {
                "uuid": PRIVATE_PORTFOLIO_UUID,
                "name": "Default",
                "type": "DEFAULT",
            }
        ]

    def get_futures_positions(self) -> dict[str, dict[str, object]]:
        self.calls.append("get_futures_positions")
        return {
            "AVP-20DEC30-CDE": {
                "product_id": "AVP-20DEC30-CDE",
                "side": "LONG",
                "number_of_contracts": "1",
                "current_price": "6.92",
                "entry_price": "6.50",
                "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
                "private_extension": {
                    "retail_portfolio_id": PRIVATE_PORTFOLIO_UUID,
                },
            }
        }

    def get_futures_margin_collateral_snapshot(self) -> dict[str, object]:
        self.calls.append("get_futures_margin_collateral_snapshot")
        return {
            "status": "ready",
            "account_family": "coinbase_futures_us_cfm",
            "balance_summary": {
                "available_margin": {"value": "250.00", "currency": "USD"},
                "total_usd_balance": {"value": "500.00", "currency": "USD"},
                "cfm_usd_balance": {"value": "500.00", "currency": "USD"},
                "futures_buying_power": {"value": "1000.00", "currency": "USD"},
                "initial_margin": {"value": "40.00", "currency": "USD"},
                "liquidation_threshold": {"value": "80.00", "currency": "USD"},
                "intraday_margin_window_measure": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
                    "maintenance_margin": "20.00",
                    "liquidation_buffer": "420.00",
                },
            },
            "intraday_margin_setting": {
                "setting": "INTRADAY_MARGIN_SETTING_ENABLED",
            },
            "current_margin_windows": [],
            "futures_sweeps": [],
            "intx_applicability": "not_applicable_us_account",
        }

    def get_product_dict(self, product_id: str) -> dict[str, object]:
        self.calls.append(f"get_product_dict:{product_id}")
        return {
            "product_id": product_id,
            "product_type": "FUTURE",
            "price_increment": "0.01",
            "base_increment": "1",
            "retail_portfolio_id": PRIVATE_PORTFOLIO_UUID,
            "private_extension": {"portfolio_uuid": PRIVATE_PORTFOLIO_UUID},
        }

    def get_transaction_summary(self) -> dict[str, object]:
        self.calls.append("get_transaction_summary")
        return {
            "fee_tier": {
                "name": "Advanced",
                "maker_fee_rate": "0.0040",
                "taker_fee_rate": "0.0060",
            },
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
        }


class _UnavailablePoisonClient:
    def __getattribute__(self, name: str) -> Any:
        if name.startswith("get_") or name == "list_portfolios":
            raise AssertionError(f"REST access is forbidden while unavailable: {name}")
        return super().__getattribute__(name)


class _UnnamedPortfolioReadClient(_ControlledReadClient):
    def list_portfolios(self) -> list[dict[str, object]]:
        self.calls.append("list_portfolios")
        return [
            {
                "uuid": PRIVATE_PORTFOLIO_UUID,
                "type": "DEFAULT",
            }
        ]


class _FailingReadClient:
    def _fail(self) -> None:
        raise RuntimeError(f"{PRIVATE_EXCEPTION_TEXT}:{PRIVATE_PORTFOLIO_UUID}")

    get_account_wallets = _fail
    get_api_key_permissions = _fail
    list_portfolios = _fail
    get_futures_positions = _fail
    get_futures_margin_collateral_snapshot = _fail

    def get_product_dict(self, _product_id: str) -> None:
        self._fail()

    get_transaction_summary = _fail


def _read(
    service: AdminMvpService,
    path: str,
    query: dict[str, object] | None = None,
) -> dict[str, Any]:
    result = service.get_read_response(path, query or {}, _context())
    assert result.status_code == 200
    return result.body


def _serialized(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_controlled_live_account_reads_retain_internal_binding_but_withhold_uuid_from_public_models() -> None:
    client = _ControlledReadClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=client, rest_client_available=True)
    )

    internal = service._account_snapshot()
    assert (
        internal["futures_portfolio_binding"]["observed_portfolio_id"]
        == PRIVATE_PORTFOLIO_UUID
    )
    assert internal["futures_portfolio_binding"]["ready"] is True
    assert client.calls
    client.calls.clear()

    account = _read(service, "/api/v1/admin/account-management")
    wallet = _read(service, "/api/v1/admin/wallet")
    product = _read(
        service,
        "/api/v1/admin/products",
        {"product_id": ["AVP-20DEC30-CDE"]},
    )
    fees = _read(service, "/api/v1/admin/fees")
    spot_readiness = _read(
        service,
        "/api/v1/spot/readiness",
        {"product_id": ["AVP-20DEC30-CDE"]},
    )
    futures_account = _read(service, "/api/v1/futures/account")
    futures_positions = _read(service, "/api/v1/futures/positions")
    futures_detail = _read(
        service,
        "/api/v1/futures/positions/futures_position:default:AVP-20DEC30-CDE",
    )
    futures_command_suite = _read(service, "/api/v1/futures/command-suite")
    futures_risk_proofs = _read(service, "/api/v1/futures/risk-proofs")

    public_payloads = (
        account,
        wallet,
        product,
        fees,
        spot_readiness,
        futures_account,
        futures_positions,
        futures_detail,
        futures_command_suite,
        futures_risk_proofs,
    )
    typed_payloads = (
        (AdminAccountManagementReadResponse, account),
        (AdminWalletReadResponse, wallet),
        (AdminProductsReadResponse, product),
        (AdminFeesReadResponse, fees),
        (AdminFuturesAccountReadResponse, futures_account),
        (AdminFuturesPositionListResponse, futures_positions),
        (AdminFuturesPositionDetailResponse, futures_detail),
    )
    for model, payload in typed_payloads:
        model.model_validate(payload)
    for payload in public_payloads:
        assert PRIVATE_PORTFOLIO_UUID not in _serialized(payload)

    assert client.calls == []
    assert account["account_reality"]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert account["live_coinbase_read_ran"] is False
    assert wallet["wallets"] == []
    assert wallet["live_coinbase_read_ran"] is False
    assert product["products"][0]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert product["live_coinbase_read_ran"] is False
    assert fees["fee_tier"]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert fees["live_coinbase_read_ran"] is False
    assert futures_account["position_count"] == 0
    assert futures_positions["items"] == []
    assert futures_detail["found"] is False


def test_unavailable_rest_adapter_keeps_operator_reads_call_free_and_fixed() -> None:
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=_UnavailablePoisonClient(),
            rest_client_available=False,
        )
    )

    account = _read(service, "/api/v1/admin/account-management")
    wallet = _read(service, "/api/v1/admin/wallet")
    product = _read(
        service,
        "/api/v1/admin/products",
        {"product_id": ["AVP-20DEC30-CDE"]},
    )
    fees = _read(service, "/api/v1/admin/fees")
    futures_account = _read(service, "/api/v1/futures/account")
    futures_positions = _read(service, "/api/v1/futures/positions")

    assert account["account_reality"]["status"] == "unavailable"
    assert account["account_reality"]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert account["live_coinbase_read_ran"] is False
    assert wallet["wallets"] == []
    assert wallet["live_coinbase_read_ran"] is False
    assert product["products"][0]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert product["live_coinbase_read_ran"] is False
    assert fees["fee_tier"]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert fees["live_coinbase_read_ran"] is False
    assert futures_account["position_count"] == 0
    assert futures_account["live_coinbase_read_ran"] is False
    assert futures_positions["items"] == []
    assert futures_positions["live_coinbase_read_ran"] is False


def test_portfolio_name_fallback_cannot_reexpose_withheld_uuid() -> None:
    client = _UnnamedPortfolioReadClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=client,
            rest_client_available=True,
        )
    )

    account = _read(service, "/api/v1/admin/account-management")

    assert client.calls == []
    assert account["portfolio_scope"]["portfolio_id"] == "local-admin-portfolio"
    assert account["portfolio_scope"]["portfolio_name"] == "Local Admin Portfolio"
    assert account["account_reality"]["read_error"] == (
        "coinbase_page_load_read_not_authorized"
    )
    assert PRIVATE_PORTFOLIO_UUID not in _serialized(account)


def test_failed_controlled_reads_expose_fixed_classification_not_exception_text() -> None:
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=_FailingReadClient(),
            rest_client_available=True,
        )
    )

    payloads = (
        _read(service, "/api/v1/admin/account-management"),
        _read(
            service,
            "/api/v1/admin/products",
            {"product_id": ["AVP-20DEC30-CDE"]},
        ),
        _read(service, "/api/v1/admin/fees"),
        _read(service, "/api/v1/futures/account"),
    )
    serialized = _serialized(payloads)

    assert PRIVATE_EXCEPTION_TEXT not in serialized
    assert PRIVATE_PORTFOLIO_UUID not in serialized
    assert "RuntimeError" not in serialized
    assert "coinbase_page_load_read_not_authorized" in serialized
    assert all(payload["live_coinbase_read_ran"] is False for payload in payloads)
