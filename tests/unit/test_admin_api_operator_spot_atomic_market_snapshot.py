from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from application.admin_api.operator_spot_atomic_market_snapshot import (
    AtomicMarketSnapshotOutcome,
    run_atomic_market_snapshot_candidate,
)
from application.admin_api.operator_automation import (
    _atomic_market_snapshot_read_activity,
)


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
DEFINITION_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
RUN_ID = "22222222-3333-4444-8555-666666666666"
GOAL_KEY = "operator_spot_automation_atomic_market_snapshot_successor_v10"


def test_non_materialized_atomic_activity_reports_exact_reads() -> None:
    activity = _atomic_market_snapshot_read_activity(
        coinbase_api_call_count=8,
        call_count_exact=True,
    )

    assert activity.operation == "PREVIEW_GATED_CREATE"
    assert activity.coinbase_api_call_count == 8
    assert activity.read_call_count == 8
    assert activity.preview_call_count == 0
    assert activity.exchange_mutation_count == 0
    assert activity.create_call_count == 0
    assert activity.cancel_call_count == 0
    assert activity.call_count_exact is True


def test_non_materialized_atomic_activity_preserves_unknown_read_boundary() -> None:
    activity = _atomic_market_snapshot_read_activity(
        coinbase_api_call_count=None,
        call_count_exact=False,
    )

    assert activity.operation == "PREVIEW_GATED_CREATE"
    assert activity.coinbase_api_call_count is None
    assert activity.read_call_count is None
    assert activity.preview_call_count == 0
    assert activity.exchange_mutation_count == 0
    assert activity.create_call_count == 0
    assert activity.cancel_call_count == 0
    assert activity.call_count_exact is False


@dataclass
class _Wallet:
    currency: str
    available_balance: str
    total_balance: str


@dataclass
class _WalletRead:
    wallets: dict[str, _Wallet]
    complete: bool = True
    page_count: int = 1
    request_count: int = 1
    blocker: str | None = None
    portfolio_ids: frozenset[str] = frozenset({PORTFOLIO_ID})


@dataclass
class _Client:
    calls: list[str] = field(default_factory=list)
    market_time: datetime = NOW

    def _called(self, name: str) -> None:
        self.calls.append(name)

    def get_api_key_permissions(self) -> dict[str, Any]:
        self._called("get_api_key_permissions")
        return {
            "portfolio_uuid": PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, Any]]:
        self._called("list_portfolios")
        return [{"uuid": PORTFOLIO_ID, "name": "Test", "type": "CONSUMER"}]

    def get_account_wallets_strict(self) -> _WalletRead:
        self._called("get_account_wallets_strict")
        return _WalletRead(wallets={"USDC": _Wallet("USDC", "2", "2")})

    def get_products_batch(self, product_ids: list[str]) -> dict[str, Any]:
        assert product_ids == ["BTC-USDC"]
        self._called("get_products_batch")
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
        self._called("get_market_trades")
        return {
            "trades": [
                {"product_id": "BTC-USDC", "time": self.market_time.isoformat()}
            ],
            "best_bid": "100000.00",
            "best_ask": "100000.01",
        }

    def get_spot_transaction_summary(self) -> dict[str, Any]:
        self._called("get_spot_transaction_summary")
        return {
            "fee_tier": {"maker_fee_rate": "0.006", "taker_fee_rate": "0.008"}
        }


def _exact_reader(_client: Any, **kwargs: Any) -> dict[str, Any]:
    assert kwargs["product_id"] == "BTC-USDC"
    return {
        "authoritative": True,
        "pagination_complete": True,
        "confirmed_absent": True,
        "exact_identity_match": False,
        "matched_order": None,
        "page_count": 1,
    }


def _active_reader(_client: Any, **kwargs: Any):
    assert kwargs["product_type"] == "SPOT"
    return [], {
        "authoritative": True,
        "pagination_complete": True,
        "page_count": 1,
        "order_count": 0,
    }


def _run(client: _Client, *, final_now: datetime = NOW):
    times = iter((NOW, final_now, final_now))
    return run_atomic_market_snapshot_candidate(
        rest_client=client,
        approved_portfolio_id=PORTFOLIO_ID,
        approved_portfolio_label="Test",
        definition_id=DEFINITION_ID,
        run_id=RUN_ID,
        goal_key=GOAL_KEY,
        candidate_version=10,
        cycle_number=1,
        correlation_id="correlation-v10",
        now_factory=lambda: next(times),
        exact_order_reader=_exact_reader,
        active_order_reader=_active_reader,
    )


def test_atomic_snapshot_derives_identity_then_completes_exact_eight_reads_once():
    client = _Client()

    result = _run(client)

    assert result.outcome is AtomicMarketSnapshotOutcome.MATERIALIZED
    assert result.plan is not None
    assert result.plan.limit_price == "100000"
    assert result.plan.submitted_notional_usdc == "1"
    assert result.plan.max_possible_execution_notional_usdc == "1.01"
    assert result.plan_sha256 is not None and len(result.plan_sha256) == 64
    assert result.client_order_id is not None
    assert result.market_snapshot_sha256 is not None
    assert result.evidence_sha256 is not None
    assert result.completed_categories == (
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
        "ACCOUNT_WALLET_BALANCES",
        "PRODUCT_METADATA",
        "BEST_BID_ASK",
        "FEE_SUMMARY",
        "EXACT_ORDER_RECONCILIATION",
        "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG",
    )
    assert result.coinbase_api_call_count == 8
    assert len(result.attempts) == 8
    assert result.attempts[0].observed_at == NOW
    assert result.attempts[6].observed_at == NOW
    assert result.attempts[7].observed_at == NOW
    assert client.calls == [
        "get_api_key_permissions",
        "list_portfolios",
        "get_account_wallets_strict",
        "get_products_batch",
        "get_market_trades",
        "get_spot_transaction_summary",
    ]
    assert "available_balance" not in repr(result)


def test_atomic_snapshot_fails_closed_when_snapshot_expires_after_final_catalog():
    client = _Client(market_time=NOW - timedelta(seconds=29))

    result = _run(client, final_now=NOW + timedelta(seconds=2))

    assert result.outcome is AtomicMarketSnapshotOutcome.BLOCKED
    assert result.diagnostic_code == "atomic_market_snapshot_stale"
    assert result.plan is None
    assert result.plan_sha256 is None
    assert result.client_order_id is None
    assert result.call_count_exact is True
    assert result.coinbase_api_call_count == 8
