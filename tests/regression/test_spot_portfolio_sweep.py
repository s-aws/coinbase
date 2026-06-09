"""Regression tests for USDC spot portfolio sweep planning."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from business.spot_portfolio_sweep import (
    append_sweep_run_record,
    build_sweep_operator_status,
    build_sweep_plan_explain,
    build_sweep_disabled_record,
    build_sweep_product_metadata,
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
from core.enums import (
    InventoryAuthorityStatus,
    OrderSide,
    SpotFillBackfillStatus,
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
        assert args.max_total_notional_per_run == Decimal("20")
        assert args.allow_product == ["AAA-USDC"]
    finally:
        config_file.unlink(missing_ok=True)
