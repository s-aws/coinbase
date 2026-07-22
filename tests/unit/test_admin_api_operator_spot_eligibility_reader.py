"""Strict production reader for the eight approved Spot eligibility categories."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
from typing import Any

import pytest

from application.admin_api.operator_spot_eligibility import (
    SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
    SpotEligibilityReadContext,
    SpotEligibilityReadOutcome,
    SpotEligibilityRunContext,
    derive_spot_eligibility_client_order_id,
)
from application.admin_api.operator_spot_eligibility_reader import (
    CoinbaseApprovedSpotEligibilityReader,
    SpotEligibilityPlanTerms,
    SpotEligibilityReadSnapshot,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
PORTFOLIO_SHA256 = (
    "cf4c4732fd3b8f8a55b60871950a2f22c893ea7afd75d2146826534e3f67cc49"
)
PLAN_SHA256 = "a" * 64


@dataclass
class _Wallet:
    currency: str
    available_balance: str
    total_balance: str


@dataclass
class _StrictWalletRead:
    wallets: dict[str, _Wallet]
    complete: bool = True
    page_count: int = 2
    request_count: int = 2
    blocker: str | None = None
    portfolio_ids: frozenset[str] = frozenset({PORTFOLIO_ID})


@dataclass
class _StrictClient:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    wallet_available: str = "10"
    product_overrides: dict[str, Any] = field(default_factory=dict)
    best_bid: str = "100"
    best_ask: str = "101"
    market_time: datetime = NOW
    market_trade_product_id: str = "BTC-USDC"
    market_trades_override: Any = None
    order_rows: list[dict[str, Any]] = field(default_factory=list)
    active_order_pages: list[list[dict[str, Any]]] = field(
        default_factory=lambda: [[]]
    )

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    def get_api_key_permissions(self) -> dict[str, Any]:
        self._record("get_api_key_permissions")
        return {
            "portfolio_uuid": PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
            "private_extension": "withheld-private-permission-value",
        }

    def list_portfolios(self) -> list[dict[str, Any]]:
        self._record("list_portfolios")
        return [
            {
                "uuid": PORTFOLIO_ID,
                "name": "Test",
                "type": "CONSUMER",
                "private_extension": "withheld-private-catalog-value",
            }
        ]

    def get_account_wallets_strict(self) -> _StrictWalletRead:
        self._record("get_account_wallets_strict")
        return _StrictWalletRead(
            wallets={
                "USDC": _Wallet(
                    currency="USDC",
                    available_balance=self.wallet_available,
                    total_balance=self.wallet_available,
                ),
                "BTC": _Wallet(
                    currency="BTC",
                    available_balance="1",
                    total_balance="1",
                ),
            }
        )

    def get_products_batch(self, product_ids: list[str]) -> dict[str, Any]:
        self._record("get_products_batch", product_ids=product_ids)
        row = {
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "base_currency_id": "BTC",
            "quote_currency_id": "USDC",
            "status": "ONLINE",
            "base_increment": "0.00001",
            "quote_increment": "0.01",
            "price_increment": "0.01",
            "base_min_size": "0.00001",
            "quote_min_size": "1",
            "trading_disabled": False,
            "is_disabled": False,
            "cancel_only": False,
            "view_only": False,
            "auction_mode": False,
        }
        row.update(self.product_overrides)
        return {"BTC-USDC": row}

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, Any]:
        self._record("get_best_bid_ask", product_ids=product_ids)
        return {
            "pricebooks": [
                {
                    "product_id": "BTC-USDC",
                    "bids": [{"price": self.best_bid, "size": "1"}],
                    "asks": [{"price": self.best_ask, "size": "1"}],
                    "time": self.market_time.isoformat(),
                    "private_extension": "withheld-private-market-value",
                }
            ]
        }

    def get_market_trades(self, *, product_id: str, limit: int) -> dict[str, Any]:
        self._record("get_market_trades", product_id=product_id, limit=limit)
        if self.market_trades_override is not None:
            return self.market_trades_override
        return {
            "trades": [
                {
                    "product_id": self.market_trade_product_id,
                    "price": "100.50",
                    "size": "0.01",
                    "time": self.market_time.isoformat(),
                    "private_extension": "withheld-private-trade-value",
                }
            ],
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "time": NOW.isoformat(),
            "private_extension": "withheld-private-market-value",
        }

    def get_spot_transaction_summary(self) -> dict[str, Any]:
        self._record("get_spot_transaction_summary")
        return {
            "fee_tier": {
                "name": "Advanced",
                "maker_fee_rate": "0.004",
                "taker_fee_rate": "0.006",
            },
            "private_extension": "withheld-private-fee-value",
        }

    def list_orders(self, **kwargs: Any) -> dict[str, Any]:
        self._record("list_orders", **kwargs)
        if kwargs.get("order_status") == ["OPEN"]:
            cursor = kwargs.get("cursor")
            index = 0 if cursor is None else int(str(cursor).removeprefix("active-page-"))
            rows = list(self.active_order_pages[index])
            has_next = index + 1 < len(self.active_order_pages)
            return {
                "orders": rows,
                "has_next": has_next,
                "cursor": f"active-page-{index + 1}" if has_next else "",
            }
        return {
            "orders": list(self.order_rows),
            "has_next": False,
            "cursor": "",
        }

    def create_order(self, **_kwargs: Any) -> None:
        raise AssertionError("Create is outside eligibility-reader authority")

    def cancel_orders(self, **_kwargs: Any) -> None:
        raise AssertionError("Cancel is outside eligibility-reader authority")


def _run_context(
    *,
    goal_key: str | None = None,
) -> SpotEligibilityRunContext:
    return SpotEligibilityRunContext(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        correlation_id="eligibility-reader-test",
        **({"goal_key": goal_key} if goal_key is not None else {}),
    )


def _read_context(
    *,
    goal_key: str | None = None,
) -> SpotEligibilityReadContext:
    context = _run_context(goal_key=goal_key)
    return SpotEligibilityReadContext(
        run_id=context.run_id,
        definition_id=context.definition_id,
        definition_revision=context.definition_revision,
        plan_sha256=context.plan_sha256,
        portfolio_id_sha256=context.portfolio_id_sha256,
        correlation_id=context.correlation_id,
        cycle_number=1,
        product_id="BTC-USDC",
        client_order_id=derive_spot_eligibility_client_order_id(
            run_id=RUN_ID,
            plan_sha256=PLAN_SHA256,
            goal_key=context.goal_key,
        ),
        goal_key=context.goal_key,
    )


def _plan(
    *,
    side: str = "BUY",
    post_only: bool = False,
    base_size: str = "0.02",
    limit_price: str = "50",
) -> SpotEligibilityPlanTerms:
    return SpotEligibilityPlanTerms(
        plan_sha256=PLAN_SHA256,
        product_id="BTC-USDC",
        side=side,
        base_size=base_size,
        limit_price=limit_price,
        submitted_notional_usdc="1.00",
        possible_execution_notional_usdc="1.00",
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.00",
        post_only=post_only,
    )


def _reader(
    client: _StrictClient,
    *,
    plan: SpotEligibilityPlanTerms | None = None,
    goal_key: str | None = None,
) -> CoinbaseApprovedSpotEligibilityReader:
    return CoinbaseApprovedSpotEligibilityReader(
        rest_client=client,
        expected_context=_run_context(goal_key=goal_key),
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        plan=plan or _plan(),
        now_factory=lambda: NOW,
    )


def test_reader_executes_only_exact_category_methods_with_sanitized_evidence():
    client = _StrictClient()
    reader = _reader(client)
    context = _read_context()

    results = [
        reader.read_api_key_permissions(context),
        reader.read_portfolio_catalog(context),
        reader.read_account_wallet_balances(context),
        reader.read_product_metadata(context),
        reader.read_best_bid_ask(context),
        reader.read_fee_summary(context),
        reader.read_exact_order_reconciliation(context),
        reader.read_account_active_spot_order_catalog(context),
    ]

    assert all(result.outcome is SpotEligibilityReadOutcome.SUCCEEDED for result in results)
    assert all(result.eligible is True for result in results)
    assert [result.http_request_count for result in results] == [1, 1, 2, 1, 1, 1, 1, 1]
    assert all(result.evidence_sha256 is not None for result in results)
    assert [name for name, _kwargs in client.calls] == [
        "get_api_key_permissions",
        "list_portfolios",
        "get_account_wallets_strict",
        "get_products_batch",
        "get_best_bid_ask",
        "get_spot_transaction_summary",
        "list_orders",
        "list_orders",
    ]
    assert client.calls[3][1] == {"product_ids": ["BTC-USDC"]}
    assert client.calls[4][1] == {"product_ids": ["BTC-USDC"]}
    assert client.calls[6][1] == {
        "limit": 100,
        "product_ids": ["BTC-USDC"],
        "product_type": "SPOT",
        "retail_portfolio_id": PORTFOLIO_ID,
    }
    assert client.calls[7][1] == {
        "limit": 100,
        "order_status": ["OPEN"],
        "product_type": "SPOT",
        "retail_portfolio_id": PORTFOLIO_ID,
    }
    serialized = repr(results)
    for forbidden in (
        PORTFOLIO_ID,
        "withheld-private-permission-value",
        "withheld-private-catalog-value",
        "withheld-private-market-value",
        "withheld-private-fee-value",
    ):
        assert forbidden not in serialized


def test_near_market_reader_uses_documented_trade_snapshot_and_post_only_bid() -> None:
    client = _StrictClient(best_bid="100", best_ask="101")
    reader = _reader(
        client,
        plan=_plan(post_only=True, base_size="0.01", limit_price="100"),
        goal_key=SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
    )
    context = _read_context(goal_key=SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY)

    results = [
        reader.read_api_key_permissions(context),
        reader.read_portfolio_catalog(context),
        reader.read_account_wallet_balances(context),
        reader.read_product_metadata(context),
        reader.read_best_bid_ask(context),
    ]

    assert all(result.outcome is SpotEligibilityReadOutcome.SUCCEEDED for result in results)
    assert [name for name, _kwargs in client.calls][-1] == "get_market_trades"


def test_near_market_reader_rejects_plan_above_current_same_snapshot_bid() -> None:
    client = _StrictClient(best_bid="99", best_ask="101")
    reader = _reader(
        client,
        plan=_plan(post_only=True, base_size="0.01", limit_price="100"),
        goal_key=SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
    )
    context = _read_context(goal_key=SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY)
    reader.read_api_key_permissions(context)
    reader.read_portfolio_catalog(context)
    reader.read_account_wallet_balances(context)
    reader.read_product_metadata(context)

    result = reader.read_best_bid_ask(context)

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False


def test_reader_rejects_insufficient_wallet_with_exact_page_accounting():
    client = _StrictClient(wallet_available="0.99")
    reader = _reader(client)
    context = _read_context()
    assert reader.read_api_key_permissions(context).eligible is True
    assert reader.read_portfolio_catalog(context).eligible is True

    result = reader.read_account_wallet_balances(context)

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.http_request_count == 2
    assert result.call_count_exact is True


@pytest.mark.parametrize(
    "override",
    [
        {"product_id": "ETH-USDC"},
        {"product_type": "FUTURE"},
        {"trading_disabled": True},
        {"price_increment": "0.03"},
        {"base_min_size": "1"},
        {
            "base_currency_id": None,
            "quote_currency_id": None,
            "base_currency": "BTC",
            "quote_currency": "USDC",
        },
    ],
)
def test_reader_rejects_product_scope_or_plan_increment_mismatch(override):
    client = _StrictClient(product_overrides=override)
    reader = _reader(client)

    result = reader.read_product_metadata(_read_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.http_request_count == 1


def test_reader_rejects_standing_price_outside_existing_backend_policy():
    client = _StrictClient(best_bid="99", best_ask="100")
    reader = _reader(client)
    assert reader.read_product_metadata(_read_context()).eligible is True

    result = reader.read_best_bid_ask(_read_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.observed_at == NOW
    assert result.http_request_count == 1


def test_reader_rejects_book_whose_source_timestamp_is_stale():
    client = _StrictClient(market_time=NOW - timedelta(minutes=5))
    reader = _reader(client)

    result = reader.read_best_bid_ask(_read_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.observed_at == NOW - timedelta(minutes=5)
    assert result.http_request_count == 1


def test_reader_rejects_future_book_timestamp_even_when_quotes_match():
    client = _StrictClient(market_time=NOW + timedelta(seconds=1))
    reader = _reader(client)

    result = reader.read_best_bid_ask(_read_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.http_request_count == 1


def test_v3_reader_uses_exact_product_market_trade_time_and_same_snapshot_quotes():
    client = _StrictClient()
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )
    context = _read_context(
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(context)

    assert result.outcome is SpotEligibilityReadOutcome.SUCCEEDED
    assert result.eligible is True
    assert result.observed_at == NOW
    assert result.http_request_count == 1
    assert client.calls == [
        ("get_market_trades", {"product_id": "BTC-USDC", "limit": 1})
    ]


def test_v3_reader_rejects_stale_or_wrong_product_trade_without_receipt_time_substitution():
    client = _StrictClient(
        market_time=NOW - timedelta(minutes=5),
        market_trade_product_id="ETH-USDC",
    )
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )
    context = _read_context(
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(context)

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.observed_at == NOW - timedelta(minutes=5)
    assert result.http_request_count == 1
    assert client.calls == [
        ("get_market_trades", {"product_id": "BTC-USDC", "limit": 1})
    ]


@pytest.mark.parametrize(
    "snapshot",
    [
        {"trades": [], "best_bid": "100", "best_ask": "101", "time": NOW.isoformat()},
        {
            "trades": [
                {"product_id": "BTC-USDC", "time": NOW.isoformat()},
                {"product_id": "BTC-USDC", "time": NOW.isoformat()},
            ],
            "best_bid": "100",
            "best_ask": "101",
            "time": NOW.isoformat(),
        },
        {
            "trades": [{"product_id": "BTC-USDC"}],
            "best_bid": "100",
            "best_ask": "101",
            "time": NOW.isoformat(),
        },
        {
            "trades": [{"product_id": "BTC-USDC", "time": "not-a-time"}],
            "best_bid": "100",
            "best_ask": "101",
            "time": NOW.isoformat(),
        },
    ],
)
def test_v3_reader_rejects_missing_or_ambiguous_trade_time_without_proxy_timestamp(
    snapshot,
):
    client = _StrictClient(market_trades_override=snapshot)
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(
        _read_context(
            goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        )
    )

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.observed_at is None
    assert result.http_request_count == 1
    assert client.calls == [
        ("get_market_trades", {"product_id": "BTC-USDC", "limit": 1})
    ]


def test_v3_reader_rejects_excessive_future_trade_time_without_replacing_source_timestamp():
    client = _StrictClient(market_time=NOW + timedelta(milliseconds=1001))
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(
        _read_context(
            goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        )
    )

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.observed_at == NOW + timedelta(milliseconds=1001)
    assert result.http_request_count == 1


def test_v3_reader_accepts_bounded_trade_clock_skew_without_replacing_source_timestamp():
    client = _StrictClient(market_time=NOW + timedelta(milliseconds=250))
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(
        _read_context(
            goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        )
    )

    assert result.outcome is SpotEligibilityReadOutcome.SUCCEEDED
    assert result.eligible is True
    assert result.observed_at == NOW + timedelta(milliseconds=250)
    assert result.http_request_count == 1


def test_v3_reader_missing_market_trade_method_has_no_proxy_timestamp():
    client = _StrictClient()
    client.get_market_trades = None
    reader = _reader(
        client,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )

    result = reader.read_best_bid_ask(
        _read_context(
            goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        )
    )

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.observed_at is None
    assert result.http_request_count == 0
    assert client.calls == []


def test_reader_rejects_existing_exact_child_without_active_catalog_query():
    context = _read_context()
    client = _StrictClient(
        order_rows=[
            {
                "client_order_id": context.client_order_id,
                "order_id": "withheld-exchange-id",
                "product_id": "BTC-USDC",
                "status": "OPEN",
                "retail_portfolio_id": PORTFOLIO_ID,
            }
        ]
    )
    reader = _reader(client)

    result = reader.read_exact_order_reconciliation(context)

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.http_request_count == 1
    assert "order_status" not in client.calls[-1][1]
    assert "withheld-exchange-id" not in repr(result)


def _complete_reader_cycle(
    reader: CoinbaseApprovedSpotEligibilityReader,
    context: SpotEligibilityReadContext,
) -> list[Any]:
    return [
        reader.read_api_key_permissions(context),
        reader.read_portfolio_catalog(context),
        reader.read_account_wallet_balances(context),
        reader.read_product_metadata(context),
        reader.read_best_bid_ask(context),
        reader.read_fee_summary(context),
        reader.read_exact_order_reconciliation(context),
        reader.read_account_active_spot_order_catalog(context),
    ]


def test_active_catalog_is_account_wide_portfolio_scoped_and_counts_each_page_once():
    client = _StrictClient(active_order_pages=[[], []])
    reader = _reader(client)
    context = _read_context()

    results = _complete_reader_cycle(reader, context)

    terminal = results[-1]
    assert terminal.outcome is SpotEligibilityReadOutcome.SUCCEEDED
    assert terminal.eligible is True
    assert terminal.logical_call_count == 1
    assert terminal.http_request_count == 2
    catalog_calls = [kwargs for name, kwargs in client.calls if name == "list_orders"][-2:]
    assert catalog_calls == [
        {
            "limit": 100,
            "order_status": ["OPEN"],
            "product_type": "SPOT",
            "retail_portfolio_id": PORTFOLIO_ID,
        },
        {
            "limit": 100,
            "order_status": ["OPEN"],
            "product_type": "SPOT",
            "retail_portfolio_id": PORTFOLIO_ID,
            "cursor": "active-page-1",
        },
    ]
    assert all("product_ids" not in call for call in catalog_calls)


def test_active_catalog_rejects_any_row_without_retaining_private_identity():
    secret_order_id = "withheld-active-exchange-id"
    client = _StrictClient(
        active_order_pages=[
            [
                {
                    "client_order_id": "withheld-active-client-id",
                    "order_id": secret_order_id,
                    "status": "PENDING",
                }
            ]
        ]
    )
    reader = _reader(client)
    context = _read_context()
    assert reader.read_api_key_permissions(context).eligible is True
    assert reader.read_portfolio_catalog(context).eligible is True

    result = reader.read_account_active_spot_order_catalog(context)

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.logical_call_count == 1
    assert result.http_request_count == 1
    assert result.evidence_sha256 is None
    assert secret_order_id not in repr(result)
    with pytest.raises(ValueError, match="spot_eligibility_reader_snapshot_incomplete"):
        reader.execution_snapshot()


def test_active_catalog_exception_is_fixed_unknown_and_never_retried():
    secret = "withheld-active-catalog-failure"

    class _FailingActiveCatalogClient(_StrictClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            self._record("list_orders", **kwargs)
            if kwargs.get("order_status") == ["OPEN"]:
                raise RuntimeError(secret)
            return {
                "orders": list(self.order_rows),
                "has_next": False,
                "cursor": "",
            }

    client = _FailingActiveCatalogClient()
    reader = _reader(client)
    context = _read_context()
    assert reader.read_api_key_permissions(context).eligible is True
    assert reader.read_portfolio_catalog(context).eligible is True

    result = reader.read_account_active_spot_order_catalog(context)

    assert result.outcome is SpotEligibilityReadOutcome.UNKNOWN
    assert result.eligible is False
    assert result.logical_call_count == 1
    assert result.http_request_count is None
    assert result.call_count_exact is False
    active_calls = [
        kwargs
        for name, kwargs in client.calls
        if name == "list_orders" and kwargs.get("order_status") == ["OPEN"]
    ]
    assert len(active_calls) == 1
    assert secret not in repr(result)


def test_transient_execution_snapshot_is_typed_read_only_and_value_blind_in_repr():
    client = _StrictClient(active_order_pages=[[], []])
    reader = _reader(client)
    context = _read_context()

    with pytest.raises(ValueError, match="spot_eligibility_reader_snapshot_incomplete"):
        reader.execution_snapshot()
    assert all(result.eligible for result in _complete_reader_cycle(reader, context))

    snapshot = reader.execution_snapshot()

    assert isinstance(snapshot, SpotEligibilityReadSnapshot)
    assert snapshot.cycle_number == 1
    assert snapshot.plan_sha256 == PLAN_SHA256
    assert snapshot.portfolio.portfolio_id_sha256 == PORTFOLIO_SHA256
    assert snapshot.portfolio.retail_portfolio_id == PORTFOLIO_ID
    assert snapshot.wallets["USDC"].available_balance == Decimal("10")
    assert snapshot.market_reference.best_bid == Decimal("100")
    assert snapshot.market_reference.best_ask == Decimal("101")
    assert snapshot.exact_order_absence.page_count == 1
    assert snapshot.active_order_catalog_absence.page_count == 2
    with pytest.raises(TypeError):
        snapshot.wallets["USDC"] = snapshot.wallets["USDC"]  # type: ignore[index]
    serialized = repr(snapshot)
    for forbidden in (
        PORTFOLIO_ID,
        PLAN_SHA256,
        "10",
        "100",
        "101",
        context.client_order_id,
    ):
        assert forbidden not in serialized


def test_reader_fails_closed_on_context_or_plan_binding_drift_before_call():
    client = _StrictClient()
    reader = _reader(client)
    drifted = replace(
        _read_context(),
        cycle_number=2,
        plan_sha256="c" * 64,
    )

    with pytest.raises(ValueError, match="spot_eligibility_reader_context_mismatch"):
        reader.read_api_key_permissions(drifted)

    assert client.calls == []


def test_reader_module_has_no_exchange_mutation_or_generic_execution_gateway():
    import application.admin_api.operator_spot_eligibility_reader as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    forbidden_identifiers = {
        "canonical_coinbase_execution_scope",
        "AdminApiCommandService",
        "create_order",
        "cancel_order",
        "cancel_orders",
        "execute",
        "execution_gateway",
    }
    observed_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    observed_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    observed_arguments = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in (*node.args.args, *node.args.kwonlyargs)
    }
    observed_strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert forbidden_identifiers.isdisjoint(observed_names)
    assert forbidden_identifiers.isdisjoint(observed_attributes)
    assert forbidden_identifiers.isdisjoint(observed_arguments)
    assert not any(
        forbidden in value
        for forbidden in forbidden_identifiers
        for value in observed_strings
    )
    assert "read_authoritative_coinbase_orders" in observed_names
