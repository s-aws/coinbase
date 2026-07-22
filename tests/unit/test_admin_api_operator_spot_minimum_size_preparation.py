from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from application.admin_api.automation_models import (
    AutomationMinimumSizeCandidatePreparationResponse,
)
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


class _LookupFailureClient:
    def __init__(
        self,
        fail_lookup: str,
        exception_type: type[Exception],
    ) -> None:
        self._delegate = _Client()
        self._fail_lookup = fail_lookup
        self._exception_type = exception_type

    def __getattr__(self, name: str) -> Any:
        if name == self._fail_lookup:
            raise self._exception_type("withheld-private-error")
        return getattr(self._delegate, name)


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


def test_preparation_wallet_call_accounting_unknown_is_stage_specific():
    client = _Client()
    client.get_account_wallets_strict = lambda: _WalletRead(
        wallets={"USDC": _Wallet("USDC", "2", "2")},
        request_count=0,
        page_count=0,
    )

    result = _run(client)

    assert result.outcome is MinimumSizePreparationOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "automation_minimum_size_wallet_balances_unknown"
    )
    assert result.completed_categories == (
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
    )


@pytest.mark.parametrize(
    ("fail_method", "diagnostic_code", "next_method"),
    (
        (
            "get_api_key_permissions",
            "automation_minimum_size_api_key_permissions_unknown",
            "list_portfolios",
        ),
        (
            "list_portfolios",
            "automation_minimum_size_portfolio_catalog_unknown",
            "get_account_wallets_strict",
        ),
        (
            "get_account_wallets_strict",
            "automation_minimum_size_wallet_balances_unknown",
            "get_products_batch",
        ),
        (
            "get_products_batch",
            "automation_minimum_size_product_metadata_unknown",
            "get_market_trades",
        ),
        (
            "get_market_trades",
            "automation_minimum_size_best_bid_ask_unknown",
            "get_spot_transaction_summary",
        ),
        (
            "get_spot_transaction_summary",
            "automation_minimum_size_fee_summary_unknown",
            "",
        ),
    ),
)
def test_preparation_unknown_is_stage_specific_terminal_and_never_retries(
    fail_method: str,
    diagnostic_code: str,
    next_method: str,
):
    client = _Client(fail_method=fail_method)

    result = _run(client)

    assert result.outcome is MinimumSizePreparationOutcome.UNKNOWN
    assert result.diagnostic_code == diagnostic_code
    assert result.coinbase_api_call_count is None
    assert result.call_count_exact is False
    assert client.calls.count(fail_method) == 1
    if next_method:
        assert next_method not in client.calls
    assert "withheld-private-error" not in repr(result)


@pytest.mark.parametrize(
    ("fail_lookup", "diagnostic_code", "completed_categories"),
    (
        (
            "get_api_key_permissions",
            "automation_minimum_size_api_key_permissions_unknown",
            (),
        ),
        (
            "list_portfolios",
            "automation_minimum_size_portfolio_catalog_unknown",
            ("API_KEY_PERMISSIONS",),
        ),
        (
            "get_account_wallets_strict",
            "automation_minimum_size_wallet_balances_unknown",
            ("API_KEY_PERMISSIONS", "PORTFOLIO_CATALOG"),
        ),
        (
            "get_products_batch",
            "automation_minimum_size_product_metadata_unknown",
            (
                "API_KEY_PERMISSIONS",
                "PORTFOLIO_CATALOG",
                "ACCOUNT_WALLET_BALANCES",
            ),
        ),
        (
            "get_market_trades",
            "automation_minimum_size_best_bid_ask_unknown",
            (
                "API_KEY_PERMISSIONS",
                "PORTFOLIO_CATALOG",
                "ACCOUNT_WALLET_BALANCES",
                "PRODUCT_METADATA",
            ),
        ),
        (
            "get_spot_transaction_summary",
            "automation_minimum_size_fee_summary_unknown",
            (
                "API_KEY_PERMISSIONS",
                "PORTFOLIO_CATALOG",
                "ACCOUNT_WALLET_BALANCES",
                "PRODUCT_METADATA",
                "BEST_BID_ASK",
            ),
        ),
    ),
)
@pytest.mark.parametrize("exception_type", (RuntimeError, AttributeError))
def test_preparation_method_lookup_failure_is_stage_specific(
    fail_lookup: str,
    diagnostic_code: str,
    completed_categories: tuple[str, ...],
    exception_type: type[Exception],
):
    client = _LookupFailureClient(fail_lookup, exception_type)

    result = _run(client)  # type: ignore[arg-type]

    assert result.outcome is MinimumSizePreparationOutcome.UNKNOWN
    assert result.diagnostic_code == diagnostic_code
    assert result.completed_categories == completed_categories
    assert result.coinbase_api_call_count is None
    assert result.call_count_exact is False
    assert fail_lookup not in client.calls
    assert "withheld-private-error" not in repr(result)


def test_preparation_truly_missing_method_is_rejected_not_unknown():
    result = _run(object())  # type: ignore[arg-type]

    assert result.outcome is MinimumSizePreparationOutcome.BLOCKED
    assert result.diagnostic_code == (
        "automation_minimum_size_api_key_permissions_rejected"
    )
    assert result.completed_categories == ()
    assert result.coinbase_api_call_count == 0
    assert result.call_count_exact is True


def test_preparation_response_rejects_unknown_code_with_mismatched_evidence():
    base = {
        "outcome": "UNKNOWN",
        "candidate_version": 7,
        "spot_execution_mode": "MINIMUM_SIZE_POST_ONLY_V7",
        "cycle_number": 3,
        "boundary_classification": None,
        "diagnostic_code": (
            "automation_minimum_size_portfolio_catalog_unknown"
        ),
        "completed_categories": ["api_key_permissions"],
        "coinbase_api_call_count": None,
        "call_count_exact": False,
        "definition": None,
        "max_possible_execution_notional_usdc": None,
        "audit_id": "30000000-0000-4000-8000-000000000001",
        "correlation_id": "minimum-size-stage-unknown",
    }

    valid = AutomationMinimumSizeCandidatePreparationResponse(**base)
    assert valid.diagnostic_code == (
        "automation_minimum_size_portfolio_catalog_unknown"
    )

    with pytest.raises(ValidationError):
        AutomationMinimumSizeCandidatePreparationResponse(
            **{**base, "completed_categories": []}
        )
    with pytest.raises(ValidationError):
        AutomationMinimumSizeCandidatePreparationResponse(
            **{
                **base,
                "outcome": "BLOCKED",
                "coinbase_api_call_count": 1,
                "call_count_exact": True,
            }
        )
    for invalid_evidence in (
        {"boundary_classification": "minimum_size_v4_fee_reserve_conflict"},
        {"definition": {}},
        {"max_possible_execution_notional_usdc": "1.01"},
        {"coinbase_api_call_count": 1, "call_count_exact": True},
    ):
        with pytest.raises(ValidationError):
            AutomationMinimumSizeCandidatePreparationResponse(
                **{**base, **invalid_evidence}
            )
