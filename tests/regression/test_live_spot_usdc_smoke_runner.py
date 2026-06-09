"""Regression checks for the live spot smoke runner helpers."""

from decimal import Decimal
from pathlib import Path

import pytest

from tools.run_live_spot_usdc_smoke import (
    LiveOrderReport,
    _build_summary,
    _build_reconciliation_gate,
    _client_order_id,
    _fills_notional_and_size,
    _submit_limit_sell_cancel_smoke,
)
from core.enums import SpotFillBackfillStatus, SpotLiveReconciliationGateStatus
from tools.run_spot_fill_backfill_recovery import (
    build_recovery_summary,
    collect_backfill_order_reports,
)


pytestmark = pytest.mark.regression


class FakeClient:
    def __init__(self, fills):
        self.fills = fills

    def get_fills(self, **kwargs):
        assert kwargs["order_ids"] == ["order-1"]
        assert "product_ids" not in kwargs
        return {"fills": self.fills}


def test_live_spot_smoke_fill_parser_handles_quote_sized_buy_fill():
    client = FakeClient([
        {
            "price": "0.00000012",
            "size": "0.9993504",
            "size_in_quote": True,
        },
    ])

    base_size, notional = _fills_notional_and_size(
        client,
        "MOG-USDC",
        "order-1",
    )

    assert base_size == Decimal("8327920")
    assert notional == Decimal("0.9993504")


def test_live_spot_smoke_fill_parser_handles_base_sized_sell_fill():
    client = FakeClient([
        {
            "price": "0.0000001100027",
            "size": "8327920",
            "size_in_quote": False,
        },
    ])

    base_size, notional = _fills_notional_and_size(
        client,
        "MOG-USDC",
        "order-1",
    )

    assert base_size == Decimal("8327920")
    assert notional == Decimal("0.916093685384")


def test_live_spot_smoke_summary_reports_retained_inventory():
    summary = _build_summary(
        product={
            "product_id": "MOG-USDC",
            "quote_min_size": "1",
            "price": "0.00000012",
            "base_increment": "1",
            "quote_increment": "0.00000001",
        },
        quote_size=Decimal("1"),
        preview={"best_bid": "0.00000011", "best_ask": "0.00000012"},
        reports=[
            LiveOrderReport(
                label="market_sell",
                product_id="MOG-USDC",
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped_retained_inventory",
                base_size="8327920",
            ),
        ],
    )

    assert summary["retained_base_by_product"] == {"MOG-USDC": "8327920"}


def test_live_spot_reconciliation_gate_requires_market_fill_backfill():
    summary = {
        "orders": [
            {
                "label": "matrix_market_buy",
                "exchange_order_id": "order-buy",
                "executed_notional_usdc": "1",
            },
        ],
        "fill_backfill": {
            "total_fetched_fill_count": 1,
            "total_appended_fill_count": 1,
            "orders": [
                {
                    "exchange_order_id": "order-buy",
                    "fetched_fill_count": 1,
                    "status": SpotFillBackfillStatus.APPENDED.value,
                },
            ],
        },
    }

    gate = _build_reconciliation_gate(summary)

    assert gate["status"] == SpotLiveReconciliationGateStatus.PASSED.value
    assert gate["checked_order_count"] == 1


def test_live_spot_smoke_generated_client_order_ids_fit_fill_ledger_limit():
    assert len(_client_order_id("lmb")) <= 40
    assert len(_client_order_id("lsls")) <= 40


def test_live_spot_smoke_limit_sell_helper_submits_post_only_and_cancels():
    class FakeLimitSellClient:
        def __init__(self):
            self.limit_calls = []
            self.cancel_calls = []

        def limit_order_gtc(self, **kwargs):
            self.limit_calls.append(kwargs)
            return {"success": True, "success_response": {"order_id": "order-1"}}

        def cancel_orders(self, order_ids):
            self.cancel_calls.append(order_ids)

        def get_order(self, order_id):
            assert order_id == "order-1"
            return {"order": {"status": "CANCELLED"}}

        def get_fills(self, **kwargs):
            assert kwargs["order_ids"] == ["order-1"]
            return {"fills": []}

    client = FakeLimitSellClient()

    report = _submit_limit_sell_cancel_smoke(
        client,
        {
            "product_id": "MOG-USDC",
            "price_increment": "0.00000001",
            "base_increment": "1",
        },
        Decimal("8327920"),
        {"best_ask": "0.00000012"},
    )

    assert report.label == "post_only_limit_sell_cancel"
    assert report.side == "SELL"
    assert report.order_type == "limit_gtc_post_only"
    assert report.submitted_notional_usdc == "1.0826296"
    assert client.limit_calls[0]["post_only"] is True
    assert client.cancel_calls == [["order-1"]]


def test_spot_fill_backfill_recovery_collects_durable_smoke_and_sweep_orders():
    smoke_records = [
        {
            "record_type": "live_spot_usdc_smoke",
            "orders": [
                {
                    "product_id": "MOG-USDC",
                    "side": "BUY",
                    "client_order_id": "coid-smoke",
                    "exchange_order_id": "exchange-smoke",
                    "status": "FILLED",
                },
            ],
        },
    ]
    sweep_records = [
        {
            "record_type": "sweep_run",
            "config_id": "cfg-1",
            "run_id": "run-1",
            "execution": {
                "orders": [
                    {
                        "product_id": "AAA-USDC",
                        "side": "SELL",
                        "client_order_id": "coid-sweep",
                        "exchange_order_id": "exchange-sweep",
                        "status": "submitted",
                    },
                    {
                        "product_id": "AAA-USDC",
                        "side": "SELL",
                        "client_order_id": "coid-sweep",
                        "exchange_order_id": "exchange-sweep",
                        "status": "submitted",
                    },
                ],
            },
        },
    ]

    orders = collect_backfill_order_reports(
        smoke_records=smoke_records,
        sweep_records=sweep_records,
        smoke_audit_file=Path("runtime_state/live_spot_usdc_smoke.jsonl"),
        sweep_state_file=Path("runtime_state/spot_portfolio_sweeps.jsonl"),
        source="all",
    )

    assert len(orders) == 2
    assert {order["source"] for order in orders} == {"smoke", "sweep"}
    assert orders[1]["run_id"] == "run-1"


def test_spot_fill_backfill_recovery_summary_reports_zero_live_notional():
    summary = build_recovery_summary(
        orders=[
            {
                "source": "sweep",
                "source_status": "submitted",
                "client_order_id": "coid-1",
                "exchange_order_id": "exchange-1",
            },
            {
                "source": "sweep",
                "source_status": "skipped",
                "client_order_id": None,
                "exchange_order_id": None,
            },
        ],
        dry_run=True,
        source="sweep",
        smoke_audit_file=Path("runtime_state/live_spot_usdc_smoke.jsonl"),
        sweep_state_file=Path("runtime_state/spot_portfolio_sweeps.jsonl"),
    )

    assert summary["candidate_order_count"] == 2
    assert summary["eligible_order_count"] == 1
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["read_only_coinbase_requests"] == []
