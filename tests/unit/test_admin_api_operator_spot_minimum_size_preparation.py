from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.admin_api.operator_spot_minimum_size_preparation import (
    MinimumSizePreparationOutcome,
    run_minimum_size_candidate_preparation,
)


NOW = datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc)
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
                "quote_min_size": "1.00",
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
            "trades": [{"product_id": "BTC-USDC", "time": NOW.isoformat()}],
            "best_bid": "100000.00",
            "best_ask": "100000.01",
        }

    def get_spot_transaction_summary(self) -> dict[str, Any]:
        self._call("get_spot_transaction_summary")
        return {"fee_tier": {"maker_fee_rate": "0.006", "taker_fee_rate": "0.008"}}

    def preview_order(self, **_kwargs: Any) -> None:
        raise AssertionError("Preview is outside preparation authority")

    def create_order(self, **_kwargs: Any) -> None:
        raise AssertionError("Create is outside preparation authority")

    def cancel_orders(self, **_kwargs: Any) -> None:
        raise AssertionError("Cancel is outside preparation authority")


def _run(client: _Client):
    return run_minimum_size_candidate_preparation(
        rest_client=client,
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        now_factory=lambda: NOW,
    )


def test_preparation_localizes_v4_and_derives_v7_terms_from_six_no_retry_categories():
    client = _Client()

    result = _run(client)

    assert result.outcome is MinimumSizePreparationOutcome.MATERIALIZED
    assert result.diagnostic_code == "minimum_size_v4_fee_reserve_conflict"
    assert result.plan is not None
    assert result.plan.max_possible_execution_notional_usdc == "1.01"
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
    assert len(client.calls) == 6
    assert "available_usdc" not in repr(result)


def test_preparation_blocks_wallet_shortfall_with_no_terms_or_private_value():
    result = _run(_Client(available_usdc="0.50"))

    assert result.outcome is MinimumSizePreparationOutcome.BLOCKED
    assert result.diagnostic_code == "minimum_size_wallet_insufficient"
    assert result.plan is None
    assert result.coinbase_api_call_count == 7
    assert "0.50" not in repr(result)


def test_preparation_unknown_is_terminal_and_never_retries():
    client = _Client(fail_method="get_market_trades")

    result = _run(client)

    assert result.outcome is MinimumSizePreparationOutcome.UNKNOWN
    assert result.diagnostic_code == "automation_minimum_size_preparation_unknown"
    assert result.coinbase_api_call_count is None
    assert result.call_count_exact is False
    assert client.calls.count("get_market_trades") == 1
    assert "get_spot_transaction_summary" not in client.calls
    assert "withheld-private-error" not in repr(result)

