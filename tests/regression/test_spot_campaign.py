"""Regression tests for read-only USDC spot campaign orchestration."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from business.spot_campaign import (
    append_spot_campaign_snapshot_record,
    build_spot_campaign_dry_run_matrix,
    build_spot_campaign_intake_request,
    build_spot_campaign_operator_status,
    build_spot_campaign_release_gate,
    build_spot_campaign_retry_plan,
    build_spot_campaign_snapshot_record,
    load_spot_campaign_snapshot_records,
    normalize_spot_campaign_config,
    spot_campaign_config_to_sweep_config,
)
from business.spot_portfolio_sweep import append_sweep_run_record, build_sweep_run_record
from core.enums import (
    SpotCampaignGateStatus,
    SpotCampaignRetryOrderClass,
    SpotCampaignRunMode,
    SpotCampaignStatus,
    SpotOperationLockStatus,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
    SpotSweepRecoveryGateStatus,
)
from tools.run_spot_campaign import main as run_spot_campaign_main
from tools.run_spot_feature_intake_gate import build_spot_feature_intake_summary


pytestmark = pytest.mark.regression


PRODUCTS = [
    {
        "product_id": "AAA-USDC",
        "base_currency_id": "AAA",
        "quote_currency_id": "USDC",
        "product_type": "SPOT",
        "status": "online",
        "price": "10",
        "quote_min_size": "1",
        "base_min_size": "0.000001",
        "quote_increment": "0.01",
        "base_increment": "0.000001",
        "price_increment": "0.01",
    },
    {
        "product_id": "BBB-USDC",
        "base_currency_id": "BBB",
        "quote_currency_id": "USDC",
        "product_type": "SPOT",
        "status": "online",
        "price": "20",
        "quote_min_size": "1",
        "base_min_size": "0.000001",
        "quote_increment": "0.01",
        "base_increment": "0.000001",
        "price_increment": "0.01",
    },
]

WALLETS = {
    "USDC": {"available_balance": {"value": "10", "currency": "USDC"}},
    "AAA": {"available_balance": {"value": "1", "currency": "AAA"}},
    "BBB": {"available_balance": {"value": "1", "currency": "BBB"}},
}


def _campaign_config(**overrides):
    config = {
        "version": 1,
        "campaign_name": "regression_campaign",
        "side": "BUY",
        "quote_notional": "1",
        "max_products": 2,
        "order_type": "market_ioc",
        "automation": {
            "enabled": True,
            "repeat_every_hours": "6",
            "max_runs": 3,
        },
        "product_scope": {
            "quote_currency": "USDC",
            "us_customer_available": True,
            "selection_rule": "all_coinbase_usdc_spot_us_customer_available",
        },
        "safety_policy": {
            "max_total_notional_per_run": "2",
            "max_notional_per_order": "1",
            "max_planned_orders": 2,
        },
        "inventory_policy": {"retention": "retain"},
        "cost_basis_authority": {
            "allowed_sources": ["fill_ledger", "imported_baseline"],
        },
    }
    config.update(overrides)
    return config


def test_spot_campaign_config_normalizes_to_sweep_config_and_intake():
    normalized = normalize_spot_campaign_config(_campaign_config())
    sweep_config = spot_campaign_config_to_sweep_config(normalized)
    intake = build_spot_campaign_intake_request(normalized)
    intake_summary = build_spot_feature_intake_summary(request=intake)

    assert normalized["campaign_id"].startswith("spot-campaign-")
    assert normalized["quote_currency"] == "USDC"
    assert sweep_config["version"] == 1
    assert sweep_config["config_id"] == normalized["sweep_config_id"]
    assert sweep_config["side"] == "BUY"
    assert intake_summary["phase_50_ready"] is True
    assert intake_summary["live_coinbase_orders_ran"] is False


def test_spot_campaign_dry_run_matrix_uses_sweep_plan_and_safety_policy():
    matrix = build_spot_campaign_dry_run_matrix(
        config=_campaign_config(),
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=False,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert matrix["live_coinbase_orders_ran"] is False
    assert matrix["plan"]["planned_count"] == 2
    assert "items" not in matrix["plan"]
    assert matrix["safety_evaluation"]["decision"] == (
        SpotPortfolioSweepSafetyDecision.ALLOWED.value
    )
    assert matrix["safety_evaluation"]["total_planned_notional_usdc"] == "2"


def test_spot_campaign_release_gate_blocks_safety_failures():
    config = _campaign_config(
        safety_policy={
            "max_total_notional_per_run": "1",
            "max_notional_per_order": "1",
        }
    )
    matrix = build_spot_campaign_dry_run_matrix(
        config=config,
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=False,
    )
    gate = build_spot_campaign_release_gate(
        config=config,
        dry_run_matrix=matrix,
        intake_summary=build_spot_feature_intake_summary(
            request=build_spot_campaign_intake_request(config)
        ),
    )

    assert gate["gate_status"] == SpotCampaignGateStatus.FAILED.value
    assert gate["status"] == SpotCampaignStatus.BLOCKED.value
    assert gate["failures"][0]["code"] == "safety_policy_blocked"


def test_spot_campaign_snapshot_ledger_builds_operator_status():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    state_file = scratch_dir / f"spot_campaign_{uuid4().hex}.jsonl"
    try:
        matrix = build_spot_campaign_dry_run_matrix(
            config=_campaign_config(),
            products=PRODUCTS,
            wallets=WALLETS,
            include_items=False,
        )
        record = build_spot_campaign_snapshot_record(
            config=_campaign_config(),
            mode="dry_run",
            status="ready",
            dry_run_matrix=matrix,
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        append_spot_campaign_snapshot_record(state_file, record)

        records = load_spot_campaign_snapshot_records(state_file)
        status = build_spot_campaign_operator_status(records=records)

        assert len(records) == 1
        assert status["campaign_count"] == 1
        assert status["snapshot_count"] == 1
        assert status["latest_snapshot"]["dry_run"]["plan"]["planned_count"] == 2
        assert status["total_submitted_notional_usdc"] == "0"
        assert status["operator_summary"]["readiness_status"] == (
            SpotCampaignStatus.READY.value
        )
        assert status["operator_summary"]["planned_order_count"] == 2
    finally:
        state_file.unlink(missing_ok=True)


def test_spot_campaign_operator_status_preserves_readiness_after_live_canary():
    config = _campaign_config()
    readiness_record = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.RELEASE_GATE,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "automation_due": {
                "decision": SpotPortfolioSweepAutomationDecision.DUE.value,
                "next_run_at": "2026-01-01T06:00:00+00:00",
                "run_count": 1,
                "max_runs": 3,
            },
            "plan": {
                "planned_count": 2,
                "skipped_count": 1,
                "skip_counts": {"below_quote_min": 1},
                "estimated_planned_quote_notional": "2",
            },
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
            "pnl_snapshot": {
                "portfolio": {
                    "total_pnl": "0.25",
                    "mark_value": "10",
                    "fees": "0.01",
                },
            },
        },
        release_gate={
            "gate_status": SpotCampaignGateStatus.PASSED.value,
            "status": SpotCampaignStatus.READY.value,
            "failures": [],
            "warnings": [],
            "operation_lock_status": {
                "status": SpotOperationLockStatus.RELEASED.value,
                "exists": False,
                "stale": False,
            },
            "recovery_plan": {
                "planned_reconciliation_run_count": 0,
                "planned_backfill_order_count": 0,
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    live_record = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.LIVE_CANARY,
        status=SpotCampaignStatus.READY,
        sweep_summary={
            "run_id": "spot-sweep-live-1",
            "status": SpotPortfolioSweepRunStatus.COMPLETED.value,
            "recorded_status": SpotPortfolioSweepRunStatus.COMPLETED.value,
            "live_coinbase_orders_ran": True,
            "skipped_order_count": 1,
            "total_submitted_notional_usdc": "2",
            "total_executed_notional_usdc": "1.98",
        },
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    status = build_spot_campaign_operator_status(
        records=[readiness_record, live_record],
        generated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    summary = status["operator_summary"]
    assert status["latest_snapshot"]["mode"] == SpotCampaignRunMode.LIVE_CANARY.value
    assert status["latest_readiness_snapshot"]["mode"] == (
        SpotCampaignRunMode.RELEASE_GATE.value
    )
    assert status["latest_live_snapshot"]["sweep_summary"]["run_id"] == (
        "spot-sweep-live-1"
    )
    assert summary["readiness_status"] == SpotCampaignStatus.READY.value
    assert summary["ready"] is True
    assert summary["blocked"] is False
    assert summary["automation_decision"] == (
        SpotPortfolioSweepAutomationDecision.DUE.value
    )
    assert summary["operation_lock_status"] == SpotOperationLockStatus.RELEASED.value
    assert summary["recovery_status"] == SpotSweepRecoveryGateStatus.PASSED.value
    assert summary["planned_order_count"] == 2
    assert summary["planned_skip_count"] == 1
    assert summary["latest_live_run_id"] == "spot-sweep-live-1"
    assert summary["total_submitted_notional_usdc"] == "2"
    assert summary["portfolio_total_pnl"] == "0.25"


def test_spot_campaign_records_partial_sweep_as_blocked_and_dedupes_notional():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    campaign_config = _campaign_config(max_products=10)
    campaign_config_file = scratch_dir / f"spot_campaign_config_{scratch_id}.json"
    sweep_state_file = scratch_dir / f"spot_sweeps_{scratch_id}.jsonl"
    campaign_state_file = scratch_dir / f"spot_campaigns_{scratch_id}.jsonl"
    campaign_config_file.write_text(json.dumps(campaign_config), encoding="utf-8")
    config = normalize_spot_campaign_config(campaign_config)
    sweep_config = spot_campaign_config_to_sweep_config(config)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        append_sweep_run_record(
            sweep_state_file,
            build_sweep_run_record(
                config_id=config["sweep_config_id"],
                run_id="spot-sweep-partial-regression",
                status=SpotPortfolioSweepRunStatus.PARTIAL.value,
                started_at=now,
                completed_at=now,
                config=sweep_config,
                execution={
                    "live_coinbase_orders_ran": True,
                    "submitted_order_count": 9,
                    "blocked_or_error_count": 1,
                    "total_submitted_notional_usdc": "9",
                    "total_executed_notional_usdc": "8.9",
                },
            ),
        )

        for _ in range(2):
            assert run_spot_campaign_main(
                [
                    "--config-file",
                    str(campaign_config_file),
                    "--state-file",
                    str(campaign_state_file),
                    "--sweep-state-file",
                    str(sweep_state_file),
                    "--record-latest-sweep-run",
                    "--summary-only",
                ]
            ) == 0

        records = load_spot_campaign_snapshot_records(campaign_state_file)
        status = build_spot_campaign_operator_status(records=records)

        assert len(records) == 2
        assert records[-1]["status"] == SpotCampaignStatus.BLOCKED.value
        assert status["total_submitted_notional_usdc"] == "9"
        assert status["total_executed_notional_usdc"] == "8.9"
        assert status["campaigns"][0]["snapshot_count"] == 2
        assert status["campaigns"][0]["notional_snapshot_count"] == 1
    finally:
        campaign_config_file.unlink(missing_ok=True)
        sweep_state_file.unlink(missing_ok=True)
        campaign_state_file.unlink(missing_ok=True)


def test_spot_campaign_records_skip_only_partial_sweep_as_ready():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    campaign_config = _campaign_config(max_products=2)
    campaign_config_file = scratch_dir / f"spot_campaign_config_{scratch_id}.json"
    sweep_state_file = scratch_dir / f"spot_sweeps_{scratch_id}.jsonl"
    campaign_state_file = scratch_dir / f"spot_campaigns_{scratch_id}.jsonl"
    campaign_config_file.write_text(json.dumps(campaign_config), encoding="utf-8")
    config = normalize_spot_campaign_config(campaign_config)
    sweep_config = spot_campaign_config_to_sweep_config(config)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        append_sweep_run_record(
            sweep_state_file,
            build_sweep_run_record(
                config_id=config["sweep_config_id"],
                run_id="spot-sweep-skip-only-partial",
                status=SpotPortfolioSweepRunStatus.PARTIAL.value,
                started_at=now,
                completed_at=now,
                config=sweep_config,
                execution={
                    "live_coinbase_orders_ran": True,
                    "submitted_order_count": 1,
                    "blocked_or_error_count": 1,
                    "total_submitted_notional_usdc": "1",
                    "total_executed_notional_usdc": "0.99",
                    "orders": [
                        {
                            "product_id": "AAA-USDC",
                            "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                            "exchange_order_id": "exchange-aaa",
                            "submitted_notional_usdc": "1",
                            "executed_notional_usdc": "0.99",
                            "response_success": True,
                        },
                        {
                            "product_id": "BBB-USDC",
                            "status": SpotPortfolioSweepExecutionStatus.SKIPPED.value,
                            "submitted_notional_usdc": "0",
                            "executed_notional_usdc": "0",
                            "error": "requested quote notional is below product quote minimum",
                        },
                    ],
                },
            ),
        )

        assert run_spot_campaign_main(
            [
                "--config-file",
                str(campaign_config_file),
                "--state-file",
                str(campaign_state_file),
                "--sweep-state-file",
                str(sweep_state_file),
                "--record-latest-sweep-run",
                "--summary-only",
            ]
        ) == 0

        records = load_spot_campaign_snapshot_records(campaign_state_file)
        sweep_summary = records[-1]["sweep_summary"]

        assert records[-1]["status"] == SpotCampaignStatus.READY.value
        assert sweep_summary["status"] == SpotPortfolioSweepRunStatus.COMPLETED.value
        assert sweep_summary["recorded_status"] == SpotPortfolioSweepRunStatus.PARTIAL.value
        assert sweep_summary["blocked_or_error_count"] == 0
        assert sweep_summary["skipped_order_count"] == 1
    finally:
        campaign_config_file.unlink(missing_ok=True)
        sweep_state_file.unlink(missing_ok=True)
        campaign_state_file.unlink(missing_ok=True)


def test_spot_campaign_retry_plan_targets_only_not_submitted_partial_orders():
    campaign_config = _campaign_config(max_products=2)
    config = normalize_spot_campaign_config(campaign_config)
    sweep_config = spot_campaign_config_to_sweep_config(config)
    run_record = build_sweep_run_record(
        config_id=config["sweep_config_id"],
        run_id="spot-sweep-partial-retry",
        status=SpotPortfolioSweepRunStatus.PARTIAL.value,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        config=sweep_config,
        execution={
            "live_coinbase_orders_ran": True,
            "submitted_order_count": 1,
            "blocked_or_error_count": 1,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.99",
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    "exchange_order_id": "exchange-aaa",
                    "submitted_notional_usdc": "1",
                    "executed_notional_usdc": "0.99",
                    "response_success": True,
                },
                {
                    "product_id": "BBB-USDC",
                    "status": SpotPortfolioSweepExecutionStatus.BLOCKED.value,
                    "exchange_order_id": None,
                    "submitted_notional_usdc": "0",
                    "executed_notional_usdc": "0",
                    "response_success": None,
                    "guard_failure": {"reason": "wallet read failed"},
                },
            ],
        },
    )

    retry_plan = build_spot_campaign_retry_plan(
        config=campaign_config,
        sweep_records=[run_record],
    )

    assert retry_plan["retry_status"] == SpotCampaignStatus.READY.value
    assert retry_plan["retryable_product_ids"] == ["BBB-USDC"]
    assert retry_plan["submitted_or_live_product_ids"] == ["AAA-USDC"]
    assert retry_plan["retry_config"]["product_scope"]["allow_products"] == ["BBB-USDC"]
    assert retry_plan["retry_config"]["max_products"] == 1
    assert retry_plan["retry_sweep_config"]["safety_policy"]["allow_products"] == [
        "BBB-USDC"
    ]
    assert {
        row["product_id"]: row["class"]
        for row in retry_plan["order_classes"]
    } == {
        "AAA-USDC": SpotCampaignRetryOrderClass.SUBMITTED_OR_LIVE.value,
        "BBB-USDC": SpotCampaignRetryOrderClass.RETRYABLE_NOT_SUBMITTED.value,
    }


def test_spot_campaign_retry_plan_cli_writes_retry_config():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    campaign_config = _campaign_config(max_products=2)
    campaign_config_file = scratch_dir / f"spot_campaign_retry_{scratch_id}.json"
    sweep_state_file = scratch_dir / f"spot_sweep_retry_{scratch_id}.jsonl"
    retry_config_file = scratch_dir / f"spot_campaign_retry_output_{scratch_id}.json"
    campaign_config_file.write_text(json.dumps(campaign_config), encoding="utf-8")
    config = normalize_spot_campaign_config(campaign_config)
    try:
        append_sweep_run_record(
            sweep_state_file,
            build_sweep_run_record(
                config_id=config["sweep_config_id"],
                run_id="spot-sweep-partial-cli-retry",
                status=SpotPortfolioSweepRunStatus.PARTIAL.value,
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                config=spot_campaign_config_to_sweep_config(config),
                execution={
                    "live_coinbase_orders_ran": True,
                    "submitted_order_count": 0,
                    "blocked_or_error_count": 1,
                    "total_submitted_notional_usdc": "0",
                    "total_executed_notional_usdc": "0",
                    "orders": [
                        {
                            "product_id": "BBB-USDC",
                            "status": SpotPortfolioSweepExecutionStatus.BLOCKED.value,
                            "exchange_order_id": None,
                            "submitted_notional_usdc": "0",
                            "executed_notional_usdc": "0",
                        }
                    ],
                },
            ),
        )

        assert run_spot_campaign_main(
            [
                "--config-file",
                str(campaign_config_file),
                "--sweep-state-file",
                str(sweep_state_file),
                "--retry-plan",
                "--write-retry-config-file",
                str(retry_config_file),
                "--summary-only",
            ]
        ) == 0

        retry_config = json.loads(retry_config_file.read_text(encoding="utf-8"))
        assert retry_config["product_scope"]["allow_products"] == ["BBB-USDC"]
        assert retry_config["max_products"] == 1
        assert retry_config["automation"]["enabled"] is True
        assert retry_config["automation"]["max_runs"] == 1
    finally:
        campaign_config_file.unlink(missing_ok=True)
        sweep_state_file.unlink(missing_ok=True)
        retry_config_file.unlink(missing_ok=True)
