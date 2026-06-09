"""Regression tests for dashboard spot sweep status payloads."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from business.spot_portfolio_sweep import append_sweep_run_record, build_sweep_run_record
from core.enums import SpotPortfolioSweepRunStatus


pytestmark = pytest.mark.regression


def test_dashboard_spot_sweep_status_payload_reads_durable_ledger():
    import dashboard_server

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_sweeps_dashboard_{uuid4().hex}.jsonl"
    try:
        append_sweep_run_record(
            state_file,
            build_sweep_run_record(
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
                    "total_executed_notional_usdc": "0.75",
                },
            ),
        )

        payload = dashboard_server._build_spot_sweep_status_payload(str(state_file))

        assert payload["type"] == "spot_sweep_status"
        assert payload["status"] == "success"
        assert payload["operator_status"]["run_count"] == 1
        assert payload["operator_status"]["total_executed_notional_usdc"] == "0.75"
    finally:
        state_file.unlink(missing_ok=True)


def test_dashboard_spot_sweep_pnl_payload_uses_public_marks_and_fill_repo(monkeypatch):
    import business.fill_ledger as fill_ledger_module
    import coinbase.rest as coinbase_rest_module
    import dashboard_server
    import database.database as database_module

    from business.fill_ledger import FillLedger

    class FakeRestClient:
        def __init__(self, **_kwargs):
            pass

        def get_public_products(self, **_kwargs):
            return {
                "products": [
                    {
                        "product_id": "AAA-USDC",
                        "base_currency_id": "AAA",
                        "quote_currency_id": "USDC",
                        "product_type": "SPOT",
                        "status": "online",
                        "price": "12",
                        "quote_min_size": "1",
                        "base_min_size": "0.000001",
                        "quote_increment": "0.01",
                        "base_increment": "0.000001",
                        "price_increment": "0.01",
                    },
                ],
            }

    class FakeFillRepo:
        def __init__(self, _db):
            pass

        def get_fills_by_product(self, product_id, side=None):
            if product_id != "AAA-USDC":
                return []
            fills = [
                FillLedger.from_dict({
                    "derived_trade_key": "buy-1",
                    "instrument": "AAA-USDC",
                    "product_id": "AAA-USDC",
                    "side": "BUY",
                    "quantity": "2",
                    "price": "10",
                    "timestamp": datetime(2026, 1, 1),
                    "fees": "0",
                })
            ]
            if side:
                return [fill for fill in fills if fill.side == side.upper()]
            return fills

    monkeypatch.setattr(coinbase_rest_module, "RESTClient", FakeRestClient)
    monkeypatch.setattr(fill_ledger_module, "FillLedgerRepository", FakeFillRepo)
    monkeypatch.setattr(database_module, "PostgresDB", lambda: object())

    payload = dashboard_server._build_spot_sweep_pnl_payload(["AAA-USDC"])

    assert payload["type"] == "spot_sweep_pnl"
    assert payload["status"] == "success"
    assert payload["pnl_report"]["snapshot"]["portfolio"]["total_pnl"] == "4"
