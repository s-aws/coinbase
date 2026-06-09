"""Regression tests for USDC spot portfolio sweep planning."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from business.spot_portfolio_sweep import (
    append_sweep_run_record,
    build_sweep_config_id,
    build_sweep_operator_status,
    build_sweep_plan_explain,
    build_sweep_disabled_record,
    build_sweep_product_metadata,
    build_sweep_recovery_record,
    build_sweep_run_record,
    build_spot_portfolio_pnl_report,
    build_spot_portfolio_pnl_snapshot,
    build_spot_inventory_coverage_report,
    build_sweep_config_registry,
    build_usdc_portfolio_sweep_plan,
    evaluate_sweep_automation_due,
    evaluate_sweep_safety_policy,
    execute_usdc_portfolio_sweep_plan,
    filter_usdc_spot_products,
    load_sweep_run_records,
    reconcile_sweep_run_record,
    summarize_sweep_execution,
)
from business.spot_cost_basis import (
    append_cost_basis_snapshot_record,
    build_coinbase_average_cost_records,
    build_cost_basis_drift_audit,
    build_cost_basis_gap_triage,
    build_cost_basis_operator_status,
    build_cost_basis_snapshot_record,
    coinbase_average_cost_records_to_baselines,
    load_cost_basis_snapshot_records,
)
from core.enums import (
    EventSourceChannel,
    EventStreamType,
    InventoryLotSource,
    InventoryAuthorityStatus,
    OrderStatus,
    OrderSide,
    SpotCostBasisSource,
    SpotCostBasisStatus,
    SpotFillBackfillStatus,
    SpotAuditRecordType,
    SpotFillLedgerFindingType,
    SpotFillLedgerHealthStatus,
    SpotFillLedgerRepairStatus,
    SpotInventoryCoverageStatus,
    SpotPortfolioPnlScope,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepOrderType,
    SpotPortfolioSweepReconciliationStatus,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
    SpotPortfolioSweepSkipReason,
    SpotPortfolioSweepItemStatus,
    SpotSweepFillLedgerMatchStatus,
    SpotSweepRecoveryGateStatus,
)


pytestmark = pytest.mark.regression


def _product(
    product_id,
    *,
    base_currency=None,
    quote_currency="USDC",
    product_type="SPOT",
    price="10",
    quote_min_size="1",
    base_min_size="0.000001",
    quote_increment="0.01",
    base_increment="0.000001",
    price_increment="0.000001",
    status="online",
    **overrides,
):
    if base_currency is None:
        base_currency = product_id.rsplit("-", 1)[0]
    product = {
        "product_id": product_id,
        "base_currency_id": base_currency,
        "quote_currency_id": quote_currency,
        "product_type": product_type,
        "price": price,
        "quote_min_size": quote_min_size,
        "base_min_size": base_min_size,
        "quote_increment": quote_increment,
        "base_increment": base_increment,
        "price_increment": price_increment,
        "status": status,
    }
    product.update(overrides)
    return product


def _wallet(currency, available):
    return {currency: {"available_balance": {"value": str(available)}}}


def test_filter_usdc_spot_products_excludes_usd_duplicates_and_disabled_flags():
    products = [
        _product("BTC-USDC"),
        _product("BTC-USD", quote_currency="USD"),
        _product("ETH-USDC", trading_disabled=True),
        _product("SOL-USDC", product_type="FUTURE"),
        _product("USDC-USDC", base_currency="USDC"),
        _product("DOGE-USDC", status="offline"),
    ]

    eligible = filter_usdc_spot_products(products)

    assert [product["product_id"] for product in eligible] == ["BTC-USDC"]


def test_sweep_plan_applies_allow_products_before_max_products():
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY.value,
        quote_notional="1",
        products=[
            _product("00-USDC", base_currency="00", price="0.01"),
            _product("ACX-USDC", base_currency="ACX", price="0.05"),
        ],
        wallets=_wallet("USDC", "10"),
        max_products=1,
        allow_products=["ACX-USDC"],
    )

    assert [item.product_id for item in plan.planned_items] == ["ACX-USDC"]
    assert plan.eligible_product_count == 2
    assert plan.selected_product_count == 1


def test_sweep_config_id_includes_non_empty_product_scope():
    base_config_id = build_sweep_config_id(
        side=OrderSide.BUY.value,
        quote_notional="1",
        max_products=1,
    )
    scoped_config_id = build_sweep_config_id(
        side=OrderSide.BUY.value,
        quote_notional="1",
        max_products=1,
        allow_products=["ACX-USDC"],
    )

    assert scoped_config_id != base_config_id


def test_buy_plan_uses_usdc_wallet_and_does_not_bump_below_min_notional():
    products = [
        _product("AAA-USDC", price="2", quote_min_size="1"),
        _product("BBB-USDC", price="5", quote_min_size="1"),
        _product("CCC-USDC", price="10", quote_min_size="20"),
    ]
    wallets = _wallet("USDC", "15")

    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="10",
        products=products,
        wallets=wallets,
    ).to_dict()

    by_product = {item["product_id"]: item for item in plan["items"]}
    assert plan["planned_count"] == 1
    assert plan["skipped_count"] == 2
    assert by_product["AAA-USDC"]["status"] == SpotPortfolioSweepItemStatus.PLANNED.value
    assert by_product["AAA-USDC"]["planned_quote_size"] == "10"
    assert by_product["BBB-USDC"]["skip_reason"] == (
        SpotPortfolioSweepSkipReason.INSUFFICIENT_QUOTE_BALANCE.value
    )
    assert by_product["CCC-USDC"]["skip_reason"] == (
        SpotPortfolioSweepSkipReason.BELOW_QUOTE_MIN.value
    )
    assert by_product["CCC-USDC"]["planned_quote_size"] == "10"


def test_sell_plan_uses_base_wallet_and_skips_insufficient_inventory():
    products = [
        _product("AAA-USDC", price="2", quote_min_size="1"),
        _product("BBB-USDC", price="5", quote_min_size="1"),
    ]
    wallets = {
        "AAA": {"available_balance": {"value": "10"}},
        "BBB": {"available_balance": {"value": "0.5"}},
        "USDC": {"available_balance": {"value": "100"}},
    }

    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL.value,
        quote_notional="10",
        products=products,
        wallets=wallets,
    ).to_dict()

    by_product = {item["product_id"]: item for item in plan["items"]}
    assert by_product["AAA-USDC"]["status"] == SpotPortfolioSweepItemStatus.PLANNED.value
    assert by_product["AAA-USDC"]["planned_base_size"] == "5"
    assert by_product["AAA-USDC"]["estimated_quote_notional"] == "10"
    assert by_product["BBB-USDC"]["skip_reason"] == (
        SpotPortfolioSweepSkipReason.INSUFFICIENT_BASE_BALANCE.value
    )
    assert by_product["BBB-USDC"]["planned_base_size"] == "2"


def test_sell_plan_skips_when_rounded_size_falls_below_base_minimum():
    products = [
        _product(
            "AAA-USDC",
            price="100",
            quote_min_size="1",
            base_min_size="1",
            base_increment="0.1",
        ),
    ]
    wallets = {"AAA": {"available_balance": {"value": "10"}}}

    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL,
        quote_notional="10",
        products=products,
        wallets=wallets,
    ).to_dict()

    item = plan["items"][0]
    assert item["status"] == SpotPortfolioSweepItemStatus.SKIPPED.value
    assert item["skip_reason"] == SpotPortfolioSweepSkipReason.BELOW_BASE_MIN.value
    assert item["planned_base_size"] == "0.1"


def _fill(
    key,
    product_id,
    side,
    quantity,
    price,
    fees,
    timestamp,
    client_order_id=None,
):
    return {
        "derived_trade_key": key,
        "instrument": product_id,
        "product_id": product_id,
        "side": side,
        "quantity": quantity,
        "price": price,
        "timestamp": timestamp,
        "fees": fees,
        "client_order_id": client_order_id,
    }


class _FakeFillLedgerRepo:
    def __init__(self, fills):
        from business.fill_ledger import FillLedger

        self.fills = [
            fill
            if isinstance(fill, FillLedger)
            else FillLedger.from_dict(fill)
            for fill in fills
        ]

    def get_fills_by_product(self, product_id, side=None):
        fills = [
            fill
            for fill in self.fills
            if fill.instrument == product_id or fill.product_id == product_id
        ]
        if side:
            fills = [fill for fill in fills if fill.side == side.upper()]
        return fills

    def get_fills_by_instrument(self, instrument):
        return [fill for fill in self.fills if fill.instrument == instrument]

    def get_fills_by_order(self, client_order_id):
        return [
            fill
            for fill in self.fills
            if fill.client_order_id == client_order_id
        ]


def test_pnl_snapshot_reports_product_portfolio_and_since_last_purchase_scopes():
    fills = [
        _fill("buy-1", "BTC-USDC", "BUY", "2", "10", "1", datetime(2026, 1, 1)),
        _fill("sell-1", "BTC-USDC", "SELL", "0.5", "12", "0.5", datetime(2026, 1, 2)),
        _fill("buy-2", "BTC-USDC", "BUY", "1", "8", "0.2", datetime(2026, 1, 3)),
        _fill("usd-skip", "ETH-USD", "BUY", "1", "100", "0", datetime(2026, 1, 4)),
    ]

    snapshot = build_spot_portfolio_pnl_snapshot(
        fills=fills,
        mark_prices={"BTC-USDC": Decimal("9")},
        generated_at=datetime(2026, 1, 4),
    ).to_dict()

    assert snapshot["portfolio"]["total_pnl"] == "-1.2"
    assert SpotPortfolioPnlScope.REALIZED_LOT.value in snapshot["scopes"]
    assert snapshot["portfolio"]["realized_lot"]["realized_pnl"] == "0.25"
    assert len(snapshot["products"]) == 1
    btc = snapshot["products"][0]
    assert btc["product_id"] == "BTC-USDC"
    assert btc["buy_notional"] == "28"
    assert btc["sell_notional"] == "6"
    assert btc["fees"] == "1.7"
    assert btc["net_base_size"] == "2.5"
    assert btc["mark_value"] == "22.5"
    assert btc["cashflow"] == "-23.7"
    assert btc["total_pnl"] == "-1.2"
    assert btc["since_last_purchase"]["buy_notional"] == "8"
    assert btc["since_last_purchase"]["net_base_size"] == "1"
    assert btc["since_last_purchase"]["total_pnl"] == "0.8"
    assert btc["realized_lot"]["method"] == "fifo_known_cost_basis"
    assert btc["realized_lot"]["matched_sell_base_size"] == "0.5"
    assert btc["realized_lot"]["open_base_size"] == "2.5"


def test_pnl_snapshot_groups_fill_rows_when_product_id_is_null():
    fills = [
        {
            "derived_trade_key": "buy-1",
            "instrument": "ACX-USDC",
            "product_id": None,
            "side": "BUY",
            "quantity": "10",
            "price": "0.04",
            "timestamp": datetime(2026, 1, 1),
            "fees": "0.01",
        },
        {
            "derived_trade_key": "usd-skip",
            "instrument": "ACX-USD",
            "product_id": None,
            "side": "BUY",
            "quantity": "10",
            "price": "0.04",
            "timestamp": datetime(2026, 1, 1),
            "fees": "0",
        },
    ]

    snapshot = build_spot_portfolio_pnl_snapshot(
        fills=fills,
        mark_prices={"ACX-USDC": Decimal("0.05")},
        generated_at=datetime(2026, 1, 2),
    ).to_dict()

    assert len(snapshot["products"]) == 1
    assert snapshot["products"][0]["product_id"] == "ACX-USDC"
    assert snapshot["products"][0]["buy_notional"] == "0.4"
    assert snapshot["products"][0]["mark_value"] == "0.5"


def test_pnl_report_uses_repo_fills_and_usdc_public_marks():
    fills = [
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
        _fill("usd-skip", "AAA-USD", "BUY", "1", "10", "0", datetime(2026, 1, 1)),
    ]

    report = build_spot_portfolio_pnl_report(
        fill_ledger_repo=_FakeFillLedgerRepo(fills),
        products=[
            _product("AAA-USDC", price="12"),
            _product("BBB-USDC", price="3"),
            _product("AAA-USD", quote_currency="USD", price="12"),
        ],
        product_ids=["AAA-USDC"],
        generated_at=datetime(2026, 1, 2),
    )

    assert report["selected_product_ids"] == ["AAA-USDC"]
    assert report["eligible_mark_product_count"] == 2
    assert report["snapshot"]["portfolio"]["total_pnl"] == "4"
    assert report["snapshot"]["products"][0]["mark_price"] == "12"


def test_coinbase_average_cost_records_map_asset_positions_to_usdc_products():
    records = build_coinbase_average_cost_records(
        portfolio_breakdown={
            "breakdown": {
                "portfolio": {"uuid": "portfolio-1", "name": "default"},
                "spot_positions": [
                    {
                        "asset": "AAA",
                        "account_uuid": "account-aaa",
                        "available_to_trade_crypto": "2",
                        "total_balance_crypto": "2.5",
                        "average_entry_price": {
                            "value": "10",
                            "currency": "USDC",
                        },
                        "cost_basis": {"value": "20", "currency": "USDC"},
                    },
                    {
                        "asset": "USD",
                        "available_to_trade_crypto": "5",
                        "average_entry_price": {
                            "value": "1",
                            "currency": "USD",
                        },
                    },
                ],
            },
        },
        products=[
            _product("AAA-USDC"),
            _product("AAA-USD", quote_currency="USD"),
            _product("BBB-USDC"),
        ],
        generated_at=datetime(2026, 1, 2),
    )
    baselines = coinbase_average_cost_records_to_baselines(records)

    assert [record["product_id"] for record in records] == ["AAA-USDC"]
    assert records[0]["status"] == SpotCostBasisStatus.AVAILABLE.value
    assert records[0]["source"] == SpotCostBasisSource.COINBASE_AVERAGE_COST.value
    assert records[0]["quantity"] == "2"
    assert baselines == [
        {
            "product_id": "AAA-USDC",
            "quantity": "2",
            "remaining_quantity": "2",
            "entry_price": "10",
            "entry_timestamp": datetime(2026, 1, 2).isoformat(),
            "fees": "0",
            "cost_basis_status": "known",
            "source_id": "account-aaa",
            "lot_source": InventoryLotSource.COINBASE_AVERAGE_COST.value,
        }
    ]


def test_pnl_report_can_include_coinbase_average_cost_scope():
    report = build_spot_portfolio_pnl_report(
        fill_ledger_repo=_FakeFillLedgerRepo([]),
        products=[
            _product("AAA-USDC", price="12"),
            _product("BBB-USDC", price="3"),
        ],
        product_ids=["AAA-USDC"],
        coinbase_average_costs=[
            {
                "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
                "status": SpotCostBasisStatus.AVAILABLE.value,
                "product_id": "AAA-USDC",
                "quantity": "2",
                "average_entry_price": "10",
            },
            {
                "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
                "status": SpotCostBasisStatus.AVAILABLE.value,
                "product_id": "BBB-USDC",
                "quantity": "5",
                "average_entry_price": "2",
            },
        ],
        generated_at=datetime(2026, 1, 2),
    )

    average = report["average_cost_pnl"]
    assert average["scope"] == SpotPortfolioPnlScope.AVERAGE_COST.value
    assert average["product_count"] == 1
    assert average["portfolio"]["cost_basis"] == "20"
    assert average["portfolio"]["mark_value"] == "24"
    assert average["portfolio"]["unrealized_pnl"] == "4"
    assert average["products"][0]["source"] == (
        SpotCostBasisSource.COINBASE_AVERAGE_COST.value
    )


def test_inventory_coverage_report_distinguishes_known_unknown_and_wallet_only():
    repo = _FakeFillLedgerRepo([
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
    ])

    report = build_spot_inventory_coverage_report(
        fill_ledger_repo=repo,
        products=[
            _product("AAA-USDC"),
            _product("BBB-USDC"),
            _product("CCC-USDC"),
        ],
        wallets={
            "AAA": {"available_balance": {"value": "2"}},
            "BBB": {"available_balance": {"value": "1"}},
            "CCC": {"available_balance": {"value": "1"}},
        },
        inventory_baselines=[
            {
                "product_id": "BBB-USDC",
                "quantity": "1",
                "remaining_quantity": "1",
                "cost_basis_status": "unknown",
            },
        ],
        generated_at=datetime(2026, 1, 2),
    )

    by_product = {row["product_id"]: row for row in report["products"]}
    assert by_product["AAA-USDC"]["coverage_status"] == (
        SpotInventoryCoverageStatus.COVERED.value
    )
    assert by_product["BBB-USDC"]["coverage_status"] == (
        SpotInventoryCoverageStatus.UNKNOWN_COST_BASIS.value
    )
    assert by_product["CCC-USDC"]["coverage_status"] == (
        SpotInventoryCoverageStatus.WALLET_ONLY.value
    )
    assert report["wallet_balance_product_count"] == 3
    assert report["wallet_only_product_count"] == 1


def test_inventory_coverage_report_marks_coinbase_average_cost_authority():
    report = build_spot_inventory_coverage_report(
        fill_ledger_repo=_FakeFillLedgerRepo([]),
        products=[_product("CCC-USDC")],
        wallets={"CCC": {"available_balance": {"value": "1"}}},
        coinbase_average_costs=[
            {
                "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
                "status": SpotCostBasisStatus.AVAILABLE.value,
                "product_id": "CCC-USDC",
                "quantity": "1",
                "average_entry_price": "3",
            },
        ],
        generated_at=datetime(2026, 1, 2),
    )

    row = report["products"][0]
    assert row["coverage_status"] == SpotInventoryCoverageStatus.COINBASE_AVERAGE_COST.value
    assert row["cost_basis_authority"] == SpotCostBasisSource.COINBASE_AVERAGE_COST.value
    assert row["coinbase_average_cost_quantity"] == "1"
    assert report["coinbase_average_cost_product_count"] == 1
    assert report["wallet_only_product_count"] == 0


class _FakeSweepRestClient:
    def __init__(self):
        self.create_order_calls = []

    def create_order(self, **kwargs):
        self.create_order_calls.append(kwargs)
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-order-1",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    def get_order(self, order_id):
        assert order_id == "exchange-order-1"
        return {"order": {"status": "FILLED"}}

    def list_fills(self, **kwargs):
        assert kwargs["order_id"] == "exchange-order-1"
        assert "product_id" not in kwargs
        return {
            "fills": [
                {
                    "size": "2",
                    "price": "0.5",
                    "size_in_quote": False,
                },
            ],
        }


class _FakeOrderEventPublisher:
    enabled = True

    def __init__(self):
        self.publish_event_calls = []

    def publish_event(self, **kwargs):
        self.publish_event_calls.append(kwargs)
        return True


def test_live_executor_rechecks_guard_before_rest_submission():
    products = [_product("AAA-USDC", price="1", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = _FakeSweepRestClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "0.5"),
        product_metadata=build_sweep_product_metadata(products),
        client_order_id_factory=lambda: "coid-blocked",
    )

    assert reports[0].status == SpotPortfolioSweepExecutionStatus.BLOCKED.value
    assert reports[0].guard_failure["block_category"] == "wallet_available"
    assert rest_client.create_order_calls == []


def test_live_executor_submits_market_buy_and_reports_notional():
    products = [_product("AAA-USDC", price="0.5", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = _FakeSweepRestClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "10"),
        product_metadata=build_sweep_product_metadata(products),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        client_order_id_factory=lambda: "coid-live-buy",
    )
    summary = summarize_sweep_execution(reports=reports)

    assert reports[0].status == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
    assert reports[0].exchange_order_id == "exchange-order-1"
    assert reports[0].submitted_notional_usdc == "1"
    assert reports[0].executed_notional_usdc == "1"
    assert summary["run_status"] == SpotPortfolioSweepRunStatus.COMPLETED.value
    assert summary["live_coinbase_orders_ran"] is True
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "coid-live-buy",
            "product_id": "AAA-USDC",
            "side": "BUY",
            "order_configuration": {
                "market_market_ioc": {
                    "quote_size": "1",
                },
            },
        }
    ]


def test_live_executor_default_client_order_id_is_uuid_text():
    products = [_product("AAA-USDC", price="0.5", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = _FakeSweepRestClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "10"),
        product_metadata=build_sweep_product_metadata(products),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
    )

    client_order_id = rest_client.create_order_calls[0]["client_order_id"]
    assert reports[0].client_order_id == client_order_id
    assert str(UUID(client_order_id)) == client_order_id


def test_live_executor_publishes_submission_event_for_sweep_order():
    products = [_product("AAA-USDC", price="0.5", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = _FakeSweepRestClient()
    event_publisher = _FakeOrderEventPublisher()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "10"),
        product_metadata=build_sweep_product_metadata(products),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        client_order_id_factory=lambda: str(uuid4()),
        order_event_publisher=event_publisher,
    )

    assert reports[0].submission_event_recorded is True
    assert len(event_publisher.publish_event_calls) == 1
    event = event_publisher.publish_event_calls[0]
    assert event["event_type"] == EventStreamType.ORDER_SUBMITTED.value
    assert event["source_channel"] == EventSourceChannel.REST_SUBMIT.value
    assert event["status_to"] == OrderStatus.PENDING.value
    assert event["payload"]["client_order_id"] == reports[0].client_order_id
    assert event["payload"]["order_id"] == "exchange-order-1"
    assert event["payload"]["product_id"] == "AAA-USDC"
    assert event["payload"]["quote_size"] == "1"


def test_live_executor_does_not_count_plan_skips_as_execution_errors():
    products = [
        _product("AAA-USDC", price="0.5", quote_min_size="1"),
        _product("BBB-USDC", price="1", quote_min_size="2"),
    ]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = _FakeSweepRestClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "10"),
        product_metadata=build_sweep_product_metadata(products),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        client_order_id_factory=lambda: "coid-live-buy",
    )
    summary = summarize_sweep_execution(reports=reports)

    assert [report.status for report in reports] == [
        SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
        SpotPortfolioSweepExecutionStatus.SKIPPED.value,
    ]
    assert reports[1].error == "requested notional rounds below the product quote_min_size"
    assert summary["run_status"] == SpotPortfolioSweepRunStatus.COMPLETED.value
    assert summary["blocked_or_error_count"] == 0
    assert summary["skipped_order_count"] == 1
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "coid-live-buy",
            "product_id": "AAA-USDC",
            "side": "BUY",
            "order_configuration": {
                "market_market_ioc": {
                    "quote_size": "1",
                },
            },
        }
    ]


def test_live_executor_preserves_exchange_id_when_post_submit_fill_fetch_fails():
    class FillFetchFailClient(_FakeSweepRestClient):
        def list_fills(self, **_kwargs):
            raise RuntimeError("fill fetch failed")

    products = [_product("AAA-USDC", price="0.5", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="1",
        products=products,
        wallets=_wallet("USDC", "10"),
    )
    rest_client = FillFetchFailClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "10"),
        product_metadata=build_sweep_product_metadata(products),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        client_order_id_factory=lambda: "coid-live-buy",
    )
    summary = summarize_sweep_execution(reports=reports)

    assert reports[0].status == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
    assert reports[0].exchange_order_id == "exchange-order-1"
    assert reports[0].submitted_notional_usdc == "1"
    assert reports[0].executed_notional_usdc == "0"
    assert reports[0].error == "RuntimeError: fill fetch failed"
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["run_status"] == SpotPortfolioSweepRunStatus.PARTIAL.value
    assert summary["total_submitted_notional_usdc"] == "1"


def test_live_executor_submits_limit_buy_with_offset_and_reports_notional():
    products = [
        _product(
            "AAA-USDC",
            price="10",
            quote_min_size="1",
            price_increment="0.01",
        )
    ]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="10",
        products=products,
        wallets=_wallet("USDC", "20"),
    )
    rest_client = _FakeSweepRestClient()

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan,
        rest_client=rest_client,
        wallet_fetcher=lambda: _wallet("USDC", "20"),
        product_metadata=build_sweep_product_metadata(products),
        order_type=SpotPortfolioSweepOrderType.LIMIT_GTC,
        limit_price_offset_bps="100",
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        client_order_id_factory=lambda: "coid-limit-buy",
    )

    assert reports[0].status == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
    assert reports[0].order_type == SpotPortfolioSweepOrderType.LIMIT_GTC.value
    assert reports[0].limit_price == "10.1"
    assert reports[0].submitted_notional_usdc == "10.1"
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "coid-limit-buy",
            "product_id": "AAA-USDC",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "10.1",
                    "post_only": False,
                },
            },
        }
    ]


def test_sweep_safety_policy_blocks_artificial_run_limit():
    products = [
        _product("AAA-USDC", price="1", quote_min_size="1"),
        _product("BBB-USDC", price="1", quote_min_size="1"),
    ]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.BUY,
        quote_notional="5",
        products=products,
        wallets=_wallet("USDC", "20"),
    )

    evaluation = evaluate_sweep_safety_policy(
        plan=plan,
        policy={"max_total_notional_per_run": "9"},
    ).to_dict()

    assert evaluation["decision"] == SpotPortfolioSweepSafetyDecision.BLOCKED.value
    assert evaluation["total_planned_notional_usdc"] == "10"
    assert evaluation["violations"][0]["code"] == "max_total_notional_per_run"


def test_sweep_safety_policy_allows_sell_when_known_profitable_lot_covers_size():
    products = [_product("AAA-USDC", price="12", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL,
        quote_notional="12",
        products=products,
        wallets={"AAA": {"available_balance": {"value": "2"}}},
    )
    repo = _FakeFillLedgerRepo([
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
    ])

    evaluation = evaluate_sweep_safety_policy(
        plan=plan,
        policy={"require_known_profitable_inventory": True},
        fill_ledger_repo=repo,
    ).to_dict()

    assert evaluation["decision"] == SpotPortfolioSweepSafetyDecision.ALLOWED.value


def test_sweep_plan_explain_includes_sell_lot_authority_details():
    products = [_product("AAA-USDC", price="12", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL,
        quote_notional="12",
        products=products,
        wallets={"AAA": {"available_balance": {"value": "2"}}},
    )
    repo = _FakeFillLedgerRepo([
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
    ])
    evaluation = evaluate_sweep_safety_policy(
        plan=plan,
        policy={"require_known_profitable_inventory": True},
        fill_ledger_repo=repo,
    )

    explain = build_sweep_plan_explain(
        plan=plan,
        safety_evaluation=evaluation,
        fill_ledger_repo=repo,
    )

    assert explain["safety_decision"] == SpotPortfolioSweepSafetyDecision.ALLOWED.value
    assert explain["items"][0]["sell_authority"]["status"] == (
        InventoryAuthorityStatus.KNOWN_PROFITABLE.value
    )
    assert explain["items"][0]["sell_authority"]["known_profitable_quantity"] == "2"


def test_sweep_safety_policy_blocks_sell_without_known_profitable_lot():
    products = [_product("AAA-USDC", price="9", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL,
        quote_notional="9",
        products=products,
        wallets={"AAA": {"available_balance": {"value": "2"}}},
    )
    repo = _FakeFillLedgerRepo([
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
    ])

    evaluation = evaluate_sweep_safety_policy(
        plan=plan,
        policy={"require_known_profitable_inventory": True},
        fill_ledger_repo=repo,
    ).to_dict()

    assert evaluation["decision"] == SpotPortfolioSweepSafetyDecision.BLOCKED.value
    assert evaluation["violations"][0]["code"] == "known_profitable_inventory"
    assert evaluation["violations"][0]["inventory_authority"]["status"] == (
        InventoryAuthorityStatus.INSUFFICIENT_KNOWN_PROFITABLE.value
    )


def test_sweep_safety_policy_requires_opt_in_for_coinbase_average_cost_sell_authority():
    products = [_product("AAA-USDC", price="10", quote_min_size="1")]
    plan = build_usdc_portfolio_sweep_plan(
        side=OrderSide.SELL,
        quote_notional="10",
        products=products,
        wallets={"AAA": {"available_balance": {"value": "2"}}},
    )
    repo = _FakeFillLedgerRepo([])
    baselines = [
        {
            "product_id": "AAA-USDC",
            "quantity": "2",
            "remaining_quantity": "2",
            "entry_price": "8",
            "cost_basis_status": "known",
            "lot_source": InventoryLotSource.COINBASE_AVERAGE_COST.value,
        },
    ]

    blocked = evaluate_sweep_safety_policy(
        plan=plan,
        policy={"require_known_profitable_inventory": True},
        fill_ledger_repo=repo,
        coinbase_average_cost_baselines=baselines,
        profit_target_pct="0.5",
    ).to_dict()
    allowed = evaluate_sweep_safety_policy(
        plan=plan,
        policy={
            "require_known_profitable_inventory": True,
            "allow_coinbase_average_cost_basis": True,
            "coinbase_average_cost_profit_buffer_pct": "0.5",
        },
        fill_ledger_repo=repo,
        coinbase_average_cost_baselines=baselines,
        profit_target_pct="0.5",
    ).to_dict()

    assert blocked["decision"] == SpotPortfolioSweepSafetyDecision.BLOCKED.value
    assert blocked["violations"][0]["inventory_authority"]["status"] == (
        InventoryAuthorityStatus.NO_LOTS.value
    )
    assert allowed["decision"] == SpotPortfolioSweepSafetyDecision.ALLOWED.value
    assert allowed["violations"] == []

    explain = build_sweep_plan_explain(
        plan=plan,
        safety_evaluation=allowed,
        fill_ledger_repo=repo,
        coinbase_average_cost_baselines=baselines,
        profit_target_pct="0.5",
    )
    authority = explain["items"][0]["sell_authority"]
    assert authority["status"] == (
        InventoryAuthorityStatus.COINBASE_AVERAGE_PROFITABLE.value
    )
    assert authority["cost_basis_authority"] == (
        SpotCostBasisSource.COINBASE_AVERAGE_COST.value
    )
    assert authority["coinbase_average_profitable_quantity"] == "2"


def test_cost_basis_drift_audit_compares_fill_ledger_to_coinbase_average_cost():
    repo = _FakeFillLedgerRepo([
        _fill("buy-1", "AAA-USDC", "BUY", "2", "10", "0", datetime(2026, 1, 1)),
    ])

    audit = build_cost_basis_drift_audit(
        fill_ledger_repo=repo,
        products=[_product("AAA-USDC"), _product("BBB-USDC")],
        average_cost_records=[
            {
                "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
                "status": SpotCostBasisStatus.AVAILABLE.value,
                "product_id": "AAA-USDC",
                "quantity": "2",
                "average_entry_price": "11",
            },
        ],
        generated_at=datetime(2026, 1, 2),
        warning_threshold_pct="5",
    )

    by_product = {row["product_id"]: row for row in audit["products"]}
    assert by_product["AAA-USDC"]["status"] == SpotCostBasisStatus.STALE.value
    assert by_product["AAA-USDC"]["local_average_entry_price"] == "10"
    assert by_product["AAA-USDC"]["coinbase_average_entry_price"] == "11"
    assert by_product["AAA-USDC"]["drift_pct"] == "10"
    assert by_product["BBB-USDC"]["status"] == (
        SpotCostBasisStatus.MISSING_POSITION.value
    )
    assert audit["status_counts"][SpotCostBasisStatus.STALE.value] == 1


def test_cost_basis_gap_triage_and_snapshot_status_are_durable():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_cost_basis_{uuid4().hex}.jsonl"
    coverage = {
        "eligible_product_count": 2,
        "wallet_balance_product_count": 1,
        "coinbase_average_cost_product_count": 0,
        "wallet_only_product_count": 1,
        "status_counts": {
            SpotInventoryCoverageStatus.WALLET_ONLY.value: 1,
        },
        "products": [
            {
                "product_id": "AAA-USDC",
                "coverage_status": SpotInventoryCoverageStatus.WALLET_ONLY.value,
                "wallet_available": "1",
                "local_evidence_quantity": "0",
                "coinbase_average_cost_quantity": "0",
                "reason": "wallet balance exceeds local evidence",
            },
        ],
    }
    drift = {
        "product_count": 2,
        "status_counts": {SpotCostBasisStatus.STALE.value: 1},
        "products": [
            {
                "product_id": "BBB-USDC",
                "status": SpotCostBasisStatus.STALE.value,
                "local_quantity": "1",
                "local_average_entry_price": "10",
                "coinbase_quantity": "1",
                "coinbase_average_entry_price": "11",
                "drift_pct": "10",
            },
        ],
    }

    try:
        triage = build_cost_basis_gap_triage(
            inventory_coverage=coverage,
            drift_audit=drift,
            generated_at=datetime(2026, 1, 2),
        )
        record = build_cost_basis_snapshot_record(
            cost_basis={
                "status": SpotCostBasisStatus.AVAILABLE.value,
                "portfolio_uuid": "portfolio-1",
                "record_count": 1,
                "baseline_count": 1,
                "read_only_coinbase_requests": [
                    "get_portfolios",
                    "get_portfolio_breakdown",
                ],
            },
            inventory_coverage=coverage,
            drift_audit=drift,
            gap_triage=triage,
            generated_at=datetime(2026, 1, 2),
        )
        append_cost_basis_snapshot_record(state_file, record)
        status = build_cost_basis_operator_status(
            records=load_cost_basis_snapshot_records(state_file),
            generated_at=datetime(2026, 1, 3),
        )

        assert triage["product_count"] == 2
        assert triage["status_counts"]["missing_average_cost_position"] == 1
        assert triage["status_counts"]["stale_average_cost"] == 1
        assert record["record_type"] == "spot_cost_basis_snapshot"
        assert record["live_coinbase_orders_ran"] is False
        assert record["total_submitted_notional_usdc"] == "0"
        assert status["snapshot_count"] == 1
        assert status["latest_snapshot"]["gap_triage"]["product_count"] == 2
    finally:
        state_file.unlink(missing_ok=True)


def test_reconcile_sweep_run_record_checks_exchange_order_client_id_and_fills():
    rest_client = _FakeSweepRestClient()
    fill_repo = _FakeFillLedgerRepo([
        _fill(
            "fill-1",
            "AAA-USDC",
            "BUY",
            "2",
            "0.5",
            "0",
            datetime(2026, 1, 1),
            client_order_id="coid-live-buy",
        ),
    ])
    record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY"},
        execution={
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "side": "BUY",
                    "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    "client_order_id": "coid-live-buy",
                    "exchange_order_id": "exchange-order-1",
                    "executed_notional_usdc": "1",
                }
            ],
        },
    )

    reconciliation = reconcile_sweep_run_record(
        record=record,
        rest_client=rest_client,
        fill_ledger_repo=fill_repo,
        reconciled_at=datetime(2026, 1, 2),
    )

    assert reconciliation["record_type"] == "sweep_reconciliation"
    assert reconciliation["summary"]["status_counts"][
        SpotPortfolioSweepReconciliationStatus.MATCHED.value
    ] == 1
    assert reconciliation["summary"]["fill_ledger_status_counts"][
        SpotSweepFillLedgerMatchStatus.MATCHED.value
    ] == 1
    assert reconciliation["orders"][0]["client_order_id_match"] is None
    assert reconciliation["orders"][0]["reconciled_executed_notional_usdc"] == "1"
    assert reconciliation["orders"][0]["fill_ledger_match"]["status"] == (
        SpotSweepFillLedgerMatchStatus.MATCHED.value
    )


def test_spot_fill_backfill_reports_append_failure_as_error():
    from business.spot_fill_backfill import backfill_fill_ledger_from_order_reports

    class FailingFillRepo:
        def append_fill(self, _fill):
            return False

    class RestClient:
        def list_fills(self, **_kwargs):
            return {
                "fills": [
                    {
                        "entry_id": "fill-1",
                        "product_id": "AAA-USDC",
                        "side": "BUY",
                        "price": "1",
                        "size": "1",
                    },
                ],
            }

    report = backfill_fill_ledger_from_order_reports(
        fill_ledger_repo=FailingFillRepo(),
        rest_client=RestClient(),
        order_reports=[
            {
                "product_id": "AAA-USDC",
                "side": "BUY",
                "client_order_id": "coid-1",
                "exchange_order_id": "exchange-1",
            },
        ],
    )

    assert report["orders"][0]["status"] == SpotFillBackfillStatus.ERROR.value
    assert report["orders"][0]["skipped_fill_count"] == 1


def test_spot_fill_backfill_fetches_order_fills_without_product_filter():
    from business.spot_fill_backfill import fetch_rest_fills_for_order

    class RestClient:
        def __init__(self):
            self.calls = []

        def list_fills(self, **kwargs):
            self.calls.append(kwargs)
            return {"fills": []}

    rest_client = RestClient()

    fills = fetch_rest_fills_for_order(
        rest_client,
        exchange_order_id="exchange-1",
        product_id="AAA-USDC",
    )

    assert fills == []
    assert rest_client.calls == [{"order_id": "exchange-1", "limit": 100}]


def test_sweep_operator_status_summarizes_durable_run_records():
    run_record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY", "quote_notional": "1"},
        execution={
            "submitted_order_count": 2,
            "blocked_or_error_count": 0,
            "total_submitted_notional_usdc": "2",
            "total_executed_notional_usdc": "1.5",
            "fill_backfill": {"total_fetched_fill_count": 2},
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "side": "BUY",
                    "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    "executed_notional_usdc": "1.5",
                },
            ],
        },
    )
    reconciliation = {
        "record_type": "sweep_reconciliation",
        "config_id": "cfg-1",
        "run_id": "run-1",
        "status": SpotPortfolioSweepRunStatus.COMPLETED.value,
        "created_at": datetime(2026, 1, 2).isoformat(),
        "summary": {"order_count": 2},
    }

    status = build_sweep_operator_status(
        records=[run_record, reconciliation],
        generated_at=datetime(2026, 1, 3),
    )

    assert status["config_count"] == 1
    assert status["run_count"] == 1
    assert status["total_submitted_notional_usdc"] == "2"
    assert status["total_executed_notional_usdc"] == "1.5"
    assert status["configs"][0]["latest_reconciliation"]["summary"] == {
        "order_count": 2
    }
    assert status["configs"][0]["latest_run"]["orders"][0]["product_id"] == "AAA-USDC"
    assert status["configs"][0]["recent_runs"][0]["fill_backfill"] == {
        "total_fetched_fill_count": 2
    }


def test_sweep_operator_status_reclassifies_skip_only_partial_run_as_completed():
    run_record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.PARTIAL.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY", "quote_notional": "1"},
        execution={
            "submitted_order_count": 1,
            "blocked_or_error_count": 1,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.99",
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "side": "BUY",
                    "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    "submitted_notional_usdc": "1",
                    "executed_notional_usdc": "0.99",
                },
                {
                    "product_id": "BBB-USDC",
                    "side": "BUY",
                    "status": SpotPortfolioSweepExecutionStatus.SKIPPED.value,
                    "submitted_notional_usdc": "0",
                    "executed_notional_usdc": "0",
                    "error": "requested quote notional is below product quote minimum",
                },
            ],
        },
    )

    status = build_sweep_operator_status(
        records=[run_record],
        generated_at=datetime(2026, 1, 3),
    )
    latest_run = status["configs"][0]["latest_run"]

    assert status["blocked_or_error_count"] == 0
    assert latest_run["status"] == SpotPortfolioSweepRunStatus.COMPLETED.value
    assert latest_run["recorded_status"] == SpotPortfolioSweepRunStatus.PARTIAL.value
    assert latest_run["execution"]["blocked_or_error_count"] == 0
    assert latest_run["execution"]["skipped_order_count"] == 1


def test_sweep_config_registry_flattens_latest_run_and_reconciliation():
    run_record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY", "quote_notional": "1"},
        execution={
            "submitted_order_count": 1,
            "blocked_or_error_count": 0,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.9",
            "fill_backfill": {"total_fetched_fill_count": 1},
        },
    )
    disabled = build_sweep_disabled_record(
        config_id="cfg-2",
        config={"side": "SELL", "quote_notional": "1"},
        disabled_at=datetime(2026, 1, 2),
    )
    reconciliation = {
        "record_type": "sweep_reconciliation",
        "config_id": "cfg-1",
        "run_id": "run-1",
        "status": SpotPortfolioSweepRunStatus.COMPLETED.value,
        "created_at": datetime(2026, 1, 3).isoformat(),
        "summary": {},
    }

    registry = build_sweep_config_registry(
        records=[run_record, disabled, reconciliation],
        generated_at=datetime(2026, 1, 4),
    )

    by_config = {config["config_id"]: config for config in registry["configs"]}
    assert registry["config_count"] == 2
    assert registry["disabled_config_count"] == 1
    assert by_config["cfg-1"]["latest_run_id"] == "run-1"
    assert by_config["cfg-1"]["latest_fill_backfill"] == {
        "total_fetched_fill_count": 1
    }
    assert by_config["cfg-1"]["latest_reconciliation_status"] == (
        SpotPortfolioSweepRunStatus.COMPLETED.value
    )
    assert by_config["cfg-2"]["disabled"] is True


def test_sweep_recovery_gate_plan_finds_unreconciled_skipped_backfill_runs():
    from tools.run_spot_sweep_recovery_gate import build_sweep_recovery_gate_plan

    run_record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY"},
        execution={
            "fill_backfill": {"skipped": True},
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "side": "BUY",
                    "client_order_id": "coid-1",
                    "exchange_order_id": "exchange-1",
                    "status": "submitted",
                },
            ],
        },
    )

    plan = build_sweep_recovery_gate_plan(
        records=[run_record],
        state_file=Path("runtime_state/spot_portfolio_sweeps.jsonl"),
    )

    assert plan["planned_reconciliation_run_count"] == 1
    assert plan["planned_backfill_order_count"] == 1
    assert plan["backfill_orders"][0]["client_order_id"] == "coid-1"


def test_sweep_recovery_record_is_visible_in_operator_registry():
    recovered_at = datetime(2026, 1, 1, 12, 0, 0)
    run_record = build_sweep_run_record(
        config_id="cfg-1",
        run_id="run-1",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
        config={"side": "BUY"},
    )
    recovery_record = build_sweep_recovery_record(
        plan={
            "state_file": "runtime_state/spot_portfolio_sweeps.jsonl",
            "config_id": "cfg-1",
            "run_id": "run-1",
            "planned_reconciliation_run_count": 1,
            "planned_backfill_order_count": 1,
        },
        status=SpotSweepRecoveryGateStatus.PASSED,
        config_id="cfg-1",
        run_id="run-1",
        created_at=recovered_at,
    )

    registry = build_sweep_config_registry(records=[run_record, recovery_record])

    assert recovery_record["record_type"] == SpotAuditRecordType.SWEEP_RECOVERY.value
    assert registry["configs"][0]["latest_recovery_status"] == (
        SpotSweepRecoveryGateStatus.PASSED.value
    )
    assert registry["configs"][0]["latest_recovery_at"] == recovered_at.isoformat()


def test_spot_fill_ledger_health_flags_repairable_zero_price_rows():
    from business.spot_fill_ledger_health import analyze_spot_fill_ledger_rows

    report = analyze_spot_fill_ledger_rows(
        rows=[
            {
                "id": 1,
                "derived_trade_key": "11111111-1111-1111-1111-111111111111",
                "instrument": "00-USDC",
                "side": "BUY",
                "quantity": Decimal("277.58"),
                "price": Decimal("0"),
                "fees": Decimal("0"),
                "client_order_id": "coid-1",
                "exchange_entry_id": "entry-1",
                "reconciliation_status": "RECONCILED",
            },
        ],
        order_reports=[
            {
                "client_order_id": "coid-1",
                "exchange_order_id": "exchange-1",
            },
        ],
        generated_at=datetime(2026, 1, 1),
    )

    assert report["status"] == SpotFillLedgerHealthStatus.FAILED.value
    assert (
        report["finding_type_counts"][
            SpotFillLedgerFindingType.NON_POSITIVE_PRICE.value
        ]
        == 1
    )
    assert report["finding_type_counts"][SpotFillLedgerFindingType.ZERO_NOTIONAL.value] == 1
    assert report["repairable_finding_count"] == 1
    assert report["findings"][0]["repairable"] is True


def test_spot_fill_ledger_repair_plans_exact_rest_fill_correction():
    from business.spot_fill_ledger_health import (
        apply_spot_fill_ledger_repair_actions,
        build_spot_fill_ledger_repair_actions,
    )

    rows = [
        {
            "id": 1,
            "derived_trade_key": "11111111-1111-1111-1111-111111111111",
            "instrument": "00-USDC",
            "side": "BUY",
            "quantity": Decimal("277.58"),
            "price": Decimal("0"),
            "fees": Decimal("0"),
            "client_order_id": "coid-1",
            "exchange_entry_id": "entry-1",
            "reconciliation_status": "RECONCILED",
        },
    ]
    actions = build_spot_fill_ledger_repair_actions(
        rows=rows,
        order_reports=[
            {
                "product_id": "00-USDC",
                "side": "BUY",
                "client_order_id": "coid-1",
                "exchange_order_id": "exchange-1",
            },
        ],
        rest_fills_by_order_id={
            "exchange-1": [
                {
                    "product_id": "00-USDC",
                    "side": "BUY",
                    "entry_id": "entry-1",
                    "trade_id": "22222222-2222-2222-2222-222222222222",
                    "price": "0.0036",
                    "size": "277.58",
                    "commission": "0.0006495372",
                    "trade_time": "2026-01-01T00:00:00Z",
                },
            ],
        },
    )
    repair = apply_spot_fill_ledger_repair_actions(
        db_client=None,
        actions=actions,
        apply=False,
    )

    assert actions[0]["status"] == SpotFillLedgerRepairStatus.PLANNED.value
    assert actions[0]["new_price"] == "0.0036"
    assert actions[0]["new_notional_usdc"] == "0.999288"
    assert repair["status"] == SpotFillLedgerRepairStatus.DRY_RUN.value
    assert repair["status_counts"][SpotFillLedgerRepairStatus.DRY_RUN.value] == 1


def test_sweep_automation_due_interval_max_runs_and_disable():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_sweeps_test_{uuid4().hex}.jsonl"
    config = {
        "side": "BUY",
        "quote_notional": "1",
        "max_products": 1,
    }
    config_id = "cfg-1"
    now = datetime(2026, 1, 1, 12, 0, 0)
    old = datetime(2026, 1, 1, 5, 0, 0)
    recent = datetime(2026, 1, 1, 11, 0, 0)

    assert evaluate_sweep_automation_due(
        config_id=config_id,
        repeat_every_hours="6",
        max_runs=2,
        records=[],
        now=now,
    )["decision"] == SpotPortfolioSweepAutomationDecision.DUE.value

    try:
        append_sweep_run_record(
            state_file,
            build_sweep_run_record(
                config_id=config_id,
                run_id="run-old",
                status=SpotPortfolioSweepRunStatus.COMPLETED.value,
                started_at=old,
                completed_at=old,
                config=config,
            ),
        )
        append_sweep_run_record(
            state_file,
            build_sweep_run_record(
                config_id=config_id,
                run_id="run-recent",
                status=SpotPortfolioSweepRunStatus.COMPLETED.value,
                started_at=recent,
                completed_at=recent,
                config=config,
            ),
        )
        records = load_sweep_run_records(state_file)
        assert evaluate_sweep_automation_due(
            config_id=config_id,
            repeat_every_hours="6",
            max_runs=3,
            records=records,
            now=now,
        )["decision"] == SpotPortfolioSweepAutomationDecision.NOT_DUE.value
        assert evaluate_sweep_automation_due(
            config_id=config_id,
            repeat_every_hours="6",
            max_runs=2,
            records=records,
            now=now,
        )["decision"] == (
            SpotPortfolioSweepAutomationDecision.MAX_RUNS_REACHED.value
        )

        append_sweep_run_record(
            state_file,
            build_sweep_disabled_record(
                config_id=config_id,
                config=config,
                disabled_at=now,
            ),
        )
        assert evaluate_sweep_automation_due(
            config_id=config_id,
            repeat_every_hours="6",
            max_runs=3,
            records=load_sweep_run_records(state_file),
            now=now,
        )["decision"] == SpotPortfolioSweepAutomationDecision.DISABLED.value
    finally:
        state_file.unlink(missing_ok=True)


def test_live_sweep_config_file_populates_runner_args():
    from tools.run_spot_portfolio_sweep_live import (
        _apply_config_file,
        _load_sweep_config_file,
        build_parser,
    )

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    config_file = scratch_dir / f"spot_sweep_config_{uuid4().hex}.json"
    try:
        config_file.write_text(
            """
            {
              "version": 1,
              "side": "SELL",
              "quote_notional": "2.5",
              "max_products": 3,
              "order_type": "limit_gtc",
              "limit_price_offset_bps": "25",
              "repeat_every_hours": "6",
              "max_runs": 4,
              "safety_policy": {
                "require_known_profitable_inventory": true,
                "allow_coinbase_average_cost_basis": true,
                "coinbase_average_cost_profit_buffer_pct": "0.75",
                "max_total_notional_per_run": "20",
                "allow_products": ["AAA-USDC"]
              }
            }
            """,
            encoding="utf-8",
        )
        parser = build_parser()
        args = parser.parse_args(["--config-file", str(config_file), "--validate-config"])

        _apply_config_file(args, _load_sweep_config_file(config_file))

        assert args.side == OrderSide.SELL.value
        assert args.quote_notional == Decimal("2.5")
        assert args.max_products == 3
        assert args.order_type == SpotPortfolioSweepOrderType.LIMIT_GTC.value
        assert args.limit_price_offset_bps == Decimal("25")
        assert args.repeat_every_hours == Decimal("6")
        assert args.max_runs == 4
        assert args.require_known_profitable_inventory is True
        assert args.allow_coinbase_average_cost_basis is True
        assert args.coinbase_average_cost_profit_buffer_pct == Decimal("0.75")
        assert args.max_total_notional_per_run == Decimal("20")
        assert args.allow_product == ["AAA-USDC"]
    finally:
        config_file.unlink(missing_ok=True)


def test_average_cost_sell_authority_requires_known_inventory_policy():
    from tools.run_spot_portfolio_sweep_live import main

    with pytest.raises(SystemExit) as exc:
        main([
            "--side",
            "SELL",
            "--quote-notional",
            "1",
            "--allow-coinbase-average-cost-basis",
            "--validate-config",
        ])

    assert exc.value.code == 2


def test_operation_lock_blocks_overlapping_scheduled_jobs():
    from tools.run_spot_portfolio_sweep_live import _OperationLock

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    lock_file = scratch_dir / f"spot_operation_{uuid4().hex}.lock"
    first = _OperationLock(lock_file, stale_after_seconds=3600).acquire()
    try:
        assert lock_file.exists()
        with pytest.raises(RuntimeError):
            _OperationLock(lock_file, stale_after_seconds=3600).acquire()
    finally:
        first.release()
        lock_file.unlink(missing_ok=True)
