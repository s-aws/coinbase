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


def test_dashboard_spot_cost_basis_payload_reads_durable_snapshot():
    import dashboard_server

    from business.spot_cost_basis import (
        append_cost_basis_snapshot_record,
        build_cost_basis_snapshot_record,
    )

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_cost_basis_dashboard_{uuid4().hex}.jsonl"
    try:
        append_cost_basis_snapshot_record(
            state_file,
            build_cost_basis_snapshot_record(
                cost_basis={
                    "status": "available",
                    "portfolio_uuid": "portfolio-1",
                    "record_count": 2,
                    "baseline_count": 2,
                    "read_only_coinbase_requests": [
                        "get_portfolios",
                        "get_portfolio_breakdown",
                    ],
                },
                inventory_coverage={
                    "eligible_product_count": 3,
                    "wallet_balance_product_count": 2,
                    "coinbase_average_cost_product_count": 1,
                    "wallet_only_product_count": 1,
                    "status_counts": {"wallet_only": 1},
                },
                drift_audit={
                    "product_count": 3,
                    "status_counts": {"stale": 1},
                },
                gap_triage={
                    "product_count": 2,
                    "status_counts": {
                        "wallet_only": 1,
                        "stale_average_cost": 1,
                    },
                },
                generated_at=datetime(2026, 1, 1),
            ),
        )

        payload = dashboard_server._build_spot_cost_basis_payload(str(state_file))

        assert payload["type"] == "spot_cost_basis_status"
        assert payload["status"] == "success"
        latest = payload["operator_status"]["latest_snapshot"]
        assert latest["baseline"]["record_count"] == 2
        assert latest["inventory_coverage"]["wallet_only_product_count"] == 1
        assert latest["drift_audit"]["status_counts"]["stale"] == 1
        assert latest["gap_triage"]["product_count"] == 2
    finally:
        state_file.unlink(missing_ok=True)


def test_dashboard_spot_campaign_payload_reads_durable_snapshot():
    import dashboard_server

    from business.spot_campaign import (
        append_spot_campaign_snapshot_record,
        build_spot_campaign_snapshot_record,
    )

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_campaign_dashboard_{uuid4().hex}.jsonl"
    config = {
        "version": 1,
        "side": "SELL",
        "quote_notional": "1",
        "max_products": 1,
        "automation": {
            "enabled": True,
            "repeat_every_hours": "6",
            "max_runs": 1,
        },
        "safety_policy": {
            "max_total_notional_per_run": "1",
            "max_notional_per_order": "1",
            "require_known_profitable_inventory": True,
        },
    }
    try:
        append_spot_campaign_snapshot_record(
            state_file,
            build_spot_campaign_snapshot_record(
                config=config,
                mode="release_gate",
                status="ready",
                dry_run_matrix={
                    "plan": {"planned_count": 1, "skipped_count": 0},
                    "safety_evaluation": {"decision": "allowed"},
                    "pnl_snapshot": {"portfolio": {"total_pnl": "0"}},
                },
                release_gate={
                    "gate_status": "passed",
                    "failures": [],
                    "warnings": [],
                },
                generated_at=datetime(2026, 1, 1),
            ),
        )
        append_spot_campaign_snapshot_record(
            state_file,
            build_spot_campaign_snapshot_record(
                config=config,
                mode="sell_authority_allowlist",
                status="ready",
                sell_authority_allowlist={
                    "sell_authority_profile": "fill_ledger_strict",
                    "allowlist_count": 2,
                    "blocked_count": 1,
                    "estimated_allowlisted_quote_notional": "2.01",
                    "authority_source_counts": {"fill_ledger": 2},
                    "authority_status_counts": {"known_profitable": 2},
                    "allow_products": ["AAA-USDC", "BBB-USDC"],
                },
                generated_at=datetime(2026, 1, 2),
            ),
        )

        payload = dashboard_server._build_spot_campaign_payload(str(state_file))

        assert payload["type"] == "spot_campaign_status"
        assert payload["status"] == "success"
        latest = payload["operator_status"]["latest_snapshot"]
        summary = payload["operator_status"]["operator_summary"]
        assert payload["operator_status"]["latest_readiness_snapshot"]["mode"] == (
            "sell_authority_allowlist"
        )
        assert latest["sell_authority_allowlist"]["allowlist_count"] == 2
        assert summary["sell_authority_allowlist_count"] == 2
        assert summary["sell_authority_blocked_count"] == 1
        assert summary["sell_authority_source_counts"] == {"fill_ledger": 2}
        assert payload["operator_status"]["campaign_count"] == 1
    finally:
        state_file.unlink(missing_ok=True)


def test_dashboard_spot_direct_order_audit_payload_reads_local_audit(monkeypatch):
    import business.spot_direct_order_audit as audit_module
    import dashboard_server

    monkeypatch.setattr(dashboard_server, "PostgresDB", lambda: object())
    monkeypatch.setattr(
        audit_module,
        "fetch_direct_order_event_rows",
        lambda _db, client_order_id, limit: [
            {
                "client_order_id": client_order_id,
                "event_type": "order_submitted",
                "payload": {"order_id": "exchange-1"},
                "created_at": datetime(2026, 1, 1),
            }
        ],
    )
    monkeypatch.setattr(
        audit_module,
        "fetch_direct_order_fill_rows",
        lambda _db, client_order_id, limit: [
            {
                "client_order_id": client_order_id,
                "product_id": "AAA-USDC",
                "side": "BUY",
                "quantity": "1",
                "price": "1.01",
                "fees": "0",
            }
        ],
    )

    payload = dashboard_server._build_spot_direct_order_audit_payload(
        client_order_id="client-order-audit-1"
    )

    assert payload["type"] == "spot_direct_order_audit"
    assert payload["status"] == "success"
    assert payload["client_order_id"] == "client-order-audit-1"
    assert payload["audit"]["record_type"] == "spot_direct_order_audit"
    assert payload["audit"]["client_order_id"] == "client-order-audit-1"
    assert payload["audit"]["live_coinbase_orders_ran"] is False


def test_dashboard_spot_sweep_pnl_payload_uses_public_marks_and_fill_repo(monkeypatch):
    import business.spot_cost_basis as cost_basis_module
    import business.fill_ledger as fill_ledger_module
    import coinbase.rest as coinbase_rest_module
    import configuration
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
    monkeypatch.setattr(configuration, "get_rest_client", lambda: object())
    monkeypatch.setattr(
        cost_basis_module,
        "fetch_coinbase_average_cost_records",
        lambda **_kwargs: {
            "records": [
                {
                    "source": "coinbase_average_cost",
                    "status": "available",
                    "product_id": "AAA-USDC",
                    "quantity": "2",
                    "average_entry_price": "9",
                },
            ],
            "read_only_coinbase_requests": [
                "get_portfolios",
                "get_portfolio_breakdown",
            ],
        },
    )

    payload = dashboard_server._build_spot_sweep_pnl_payload(["AAA-USDC"])
    average_payload = dashboard_server._build_spot_sweep_pnl_payload(
        ["AAA-USDC"],
        include_coinbase_average_cost=True,
    )

    assert payload["type"] == "spot_sweep_pnl"
    assert payload["status"] == "success"
    assert payload["pnl_report"]["snapshot"]["portfolio"]["total_pnl"] == "4"
    assert payload["read_only_coinbase_requests"] == ["get_public_products"]
    assert average_payload["read_only_coinbase_requests"] == [
        "get_public_products",
        "get_portfolios",
        "get_portfolio_breakdown",
    ]
    assert average_payload["pnl_report"]["average_cost_pnl"]["portfolio"][
        "unrealized_pnl"
    ] == "6"
