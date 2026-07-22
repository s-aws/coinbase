from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.admin_api.operator_spot_near_market_preparation import (
    NearMarketPreparationOutcome,
    run_near_market_candidate_preparation,
)


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


@dataclass
class _Wallet:
    currency: str
    available_balance: str
    total_balance: str


@dataclass
class _WalletRead:
    wallets: dict[str, _Wallet]
    complete: bool = True
    page_count: int = 2
    request_count: int = 2
    blocker: str | None = None
    portfolio_ids: frozenset[str] = frozenset({PORTFOLIO_ID})


@dataclass
class _Client:
    calls: list[str] = field(default_factory=list)
    available_usdc: str = "2"
    fail_method: str | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_method == name:
            raise RuntimeError("withheld-private-error")

    def get_api_key_permissions(self) -> dict[str, Any]:
        self._call("get_api_key_permissions")
        return {
            "portfolio_uuid": PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, Any]]:
        self._call("list_portfolios")
        return [{"uuid": PORTFOLIO_ID, "name": "Test", "type": "CONSUMER"}]

    def get_account_wallets_strict(self) -> _WalletRead:
        self._call("get_account_wallets_strict")
        return _WalletRead(
            wallets={
                "USDC": _Wallet("USDC", self.available_usdc, self.available_usdc),
            }
        )

    def get_products_batch(self, product_ids: list[str]) -> dict[str, Any]:
        assert product_ids == ["BTC-USDC"]
        self._call("get_products_batch")
        return {
            "BTC-USDC": {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "base_currency_id": "BTC",
                "quote_currency_id": "USDC",
                "status": "ONLINE",
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "price_increment": "0.01",
                "base_min_size": "0.00000001",
                "quote_min_size": "0.01",
                "trading_disabled": False,
                "is_disabled": False,
                "cancel_only": False,
                "view_only": False,
                "auction_mode": False,
            }
        }

    def get_market_trades(self, *, product_id: str, limit: int) -> dict[str, Any]:
        assert (product_id, limit) == ("BTC-USDC", 1)
        self._call("get_market_trades")
        return {
            "trades": [
                {"product_id": "BTC-USDC", "time": NOW.isoformat()}
            ],
            "best_bid": "65000.12",
            "best_ask": "65000.13",
        }

    def get_spot_transaction_summary(self) -> dict[str, Any]:
        self._call("get_spot_transaction_summary")
        return {"fee_tier": {"maker_fee_rate": "0.004", "taker_fee_rate": "0.006"}}

    def preview_order(self, **_kwargs: Any) -> None:
        raise AssertionError("Preview is outside preparation authority")

    def create_order(self, **_kwargs: Any) -> None:
        raise AssertionError("Create is outside preparation authority")

    def cancel_orders(self, **_kwargs: Any) -> None:
        raise AssertionError("Cancel is outside preparation authority")


def test_preparation_derives_terms_from_six_no_retry_categories() -> None:
    client = _Client()

    result = run_near_market_candidate_preparation(
        rest_client=client,
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        now_factory=lambda: NOW,
    )

    assert result.outcome is NearMarketPreparationOutcome.MATERIALIZED
    assert result.diagnostic_code == "automation_near_market_terms_derived"
    assert result.plan is not None
    assert result.plan.post_only is True
    assert result.plan.limit_price == "65000.12"
    assert result.completed_categories == (
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
        "ACCOUNT_WALLET_BALANCES",
        "PRODUCT_METADATA",
        "BEST_BID_ASK",
        "FEE_SUMMARY",
    )
    assert result.coinbase_api_call_count == 7
    assert result.call_count_exact is True
    assert client.calls == [
        "get_api_key_permissions",
        "list_portfolios",
        "get_account_wallets_strict",
        "get_products_batch",
        "get_market_trades",
        "get_spot_transaction_summary",
    ]


def test_preparation_stops_without_plan_when_no_valid_size_exists() -> None:
    result = run_near_market_candidate_preparation(
        rest_client=_Client(available_usdc="0.001"),
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        now_factory=lambda: NOW,
    )

    assert result.outcome is NearMarketPreparationOutcome.BLOCKED
    assert result.diagnostic_code == "near_market_no_valid_size"
    assert result.plan is None
    assert result.coinbase_api_call_count == 7
    assert result.call_count_exact is True


def test_preparation_exception_is_unknown_and_never_retries() -> None:
    client = _Client(fail_method="get_market_trades")

    result = run_near_market_candidate_preparation(
        rest_client=client,
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        now_factory=lambda: NOW,
    )

    assert result.outcome is NearMarketPreparationOutcome.UNKNOWN
    assert result.diagnostic_code == "automation_near_market_preparation_unknown"
    assert result.plan is None
    assert result.coinbase_api_call_count is None
    assert result.call_count_exact is False
    assert client.calls.count("get_market_trades") == 1
    assert "get_spot_transaction_summary" not in client.calls
    assert "withheld-private-error" not in repr(result)
