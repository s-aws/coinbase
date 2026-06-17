"""Regression coverage check for the focused spot-readiness gate."""

from pathlib import Path

import pytest

from core.enums import SpotFeatureIntakeGateStatus
from tools.run_spot_readiness_regression import SPOT_READINESS_TESTS
from tools.run_spot_feature_intake_gate import build_spot_feature_intake_summary
from tools.run_spot_release_gate import (
    SUMMARY_PREFIX,
    build_parser,
    build_release_gate_steps,
)
from tools.run_autonomous_work_queue_check import (
    APPROVED_PHASES as AUTONOMOUS_APPROVED_PHASES,
    MAX_EXECUTED_NOTIONAL_USDC as AUTONOMOUS_MAX_EXECUTED_NOTIONAL_USDC,
    MAX_SUBMITTED_NOTIONAL_USDC as AUTONOMOUS_MAX_SUBMITTED_NOTIONAL_USDC,
    SUMMARY_PREFIX as AUTONOMOUS_WORK_QUEUE_SUMMARY_PREFIX,
    build_autonomous_work_queue_summary,
    build_parser as build_autonomous_work_queue_parser,
)


pytestmark = pytest.mark.regression


def test_spot_readiness_runner_covers_required_focus_files():
    required = {
        "tests/regression/test_size_validation.py",
        "tests/regression/test_fee_multiplier_by_product_type.py",
        "tests/regression/test_product_capability_policy.py",
        "tests/regression/test_stealth_action_condition_guard.py",
        "tests/regression/test_spot_planned_budget_guard.py",
        "tests/regression/test_spot_follow_up_policy.py",
        "tests/regression/test_stealth_move_revealed.py",
        "tests/regression/test_spot_inventory_authority.py",
        "tests/regression/test_spot_portfolio_sweep.py",
        "tests/regression/test_spot_paper_mode_replay.py",
        "tests/regression/test_dashboard_action_condition_guard.py",
        "tests/regression/test_dashboard_spot_readiness.py",
        "tests/regression/test_dashboard_spot_sweep_status.py",
        "tests/regression/test_spot_direct_order_audit.py",
        "tests/regression/test_spot_campaign.py",
        "tests/regression/test_live_spot_usdc_smoke_runner.py",
        "tests/regression/test_spot_readiness_gate.py",
    }

    configured = set(SPOT_READINESS_TESTS)

    assert required <= configured
    assert len(SPOT_READINESS_TESTS) == len(configured)
    for relative_path in SPOT_READINESS_TESTS:
        assert relative_path.startswith("tests/regression/")
        assert Path(relative_path).exists(), relative_path


def test_spot_release_gate_command_is_read_only_by_default():
    parser = build_parser()
    args = parser.parse_args([])

    assert SUMMARY_PREFIX == "SPOT_RELEASE_GATE_SUMMARY "
    assert args.include_browser is False
    assert args.include_coinbase_readonly is False


def test_autonomous_work_queue_check_covers_approved_20_phase_batch():
    parser = build_autonomous_work_queue_parser()
    args = parser.parse_args(["--summary-only"])
    summary = build_autonomous_work_queue_summary()

    assert args.summary_only is True
    assert AUTONOMOUS_WORK_QUEUE_SUMMARY_PREFIX == (
        "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
    )
    assert AUTONOMOUS_APPROVED_PHASES == tuple(range(3521, 3541))
    assert summary["status"] == "passed"
    assert summary["approved_phase_range"] == "3521-3540"
    assert summary["approved_phase_count"] == 20
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["max_submitted_notional_usdc"] == (
        AUTONOMOUS_MAX_SUBMITTED_NOTIONAL_USDC
    )
    assert summary["max_executed_notional_usdc"] == (
        AUTONOMOUS_MAX_EXECUTED_NOTIONAL_USDC
    )
    assert all(check["passed"] for check in summary["checks"])


def test_spot_release_gate_coinbase_readonly_includes_cost_basis_checks():
    parser = build_parser()
    args = parser.parse_args(["--include-coinbase-readonly"])

    steps = build_release_gate_steps(args=args, python="python")
    names = [step.name for step in steps]

    assert "spot_cost_basis_inventory_coverage" in names
    assert "spot_cost_basis_drift_audit" in names
    coverage = next(step for step in steps if step.name == "spot_cost_basis_inventory_coverage")
    assert "--include-coinbase-average-cost" in coverage.command


def test_spot_release_gate_can_include_campaign_config():
    parser = build_parser()
    args = parser.parse_args([
        "--campaign-config-file",
        "runtime_state/spot_campaign_buy.json",
        "--campaign-all-usdc-readiness",
    ])

    steps = build_release_gate_steps(args=args, python="python")
    campaign = next(step for step in steps if step.name == "spot_campaign_release_gate")
    broad = next(
        step
        for step in steps
        if step.name == "spot_campaign_all_usdc_readiness_gate"
    )

    assert "tools/run_spot_campaign.py" in campaign.command
    assert "--release-gate" in campaign.command
    assert "--summary-only" in campaign.command
    assert "--all-usdc-readiness-gate" in broad.command
    assert "--summary-only" in broad.command


def test_spot_feature_intake_gate_blocks_missing_request_details():
    summary = build_spot_feature_intake_summary(request={})

    assert summary["status"] == SpotFeatureIntakeGateStatus.INCOMPLETE.value
    assert summary["phase_50_ready"] is False
    assert "feature_name" in summary["missing_fields"]
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"


def test_spot_feature_intake_gate_passes_complete_usdc_scope():
    summary = build_spot_feature_intake_summary(
        request={
            "feature_name": "example_spot_feature",
            "goal": "Buy and sell approved USDC spot products under caps.",
            "product_scope": {
                "quote_currency": "USDC",
                "us_customer_available": True,
                "selection_rule": "all_coinbase_usdc_spot_us_customer_available",
            },
            "order_sides": ["BUY", "SELL"],
            "order_types": ["market_ioc", "limit_gtc"],
            "automation": {
                "repeat_every_hours": "6",
                "max_runs": 3,
            },
            "live_approval": {"required": True},
            "safety": {
                "max_notional_per_order": "1",
                "max_total_notional_per_run": "10",
            },
            "inventory_policy": {"retention": "retain"},
            "cost_basis_authority": {
                "allowed_sources": ["fill_ledger", "imported_baseline"],
            },
            "audit": {
                "required_evidence": [
                    "client_order_id",
                    "exchange_order_id",
                    "submitted_notional_usdc",
                    "executed_notional_usdc",
                    "fill_ledger_reconciliation",
                ],
            },
        }
    )

    assert summary["status"] == SpotFeatureIntakeGateStatus.PASSED.value
    assert summary["phase_50_ready"] is True
    assert summary["read_only_coinbase_requests"] == []


def test_spot_feature_intake_gate_requires_average_cost_buffer_when_enabled():
    summary = build_spot_feature_intake_summary(
        request={
            "feature_name": "example_spot_feature",
            "goal": "Sell with average cost authority.",
            "product_scope": {
                "quote_currency": "USDC",
                "us_customer_available": True,
                "selection_rule": "all_coinbase_usdc_spot_us_customer_available",
            },
            "order_sides": ["SELL"],
            "order_types": ["market_ioc"],
            "automation": {"repeat_every_hours": "6", "max_runs": 1},
            "live_approval": {"required": True},
            "safety": {
                "max_notional_per_order": "1",
                "max_total_notional_per_run": "10",
            },
            "inventory_policy": {"retention": "retain"},
            "cost_basis_authority": {
                "allowed_sources": ["coinbase_average_cost"],
            },
            "audit": {
                "required_evidence": [
                    "client_order_id",
                    "exchange_order_id",
                    "submitted_notional_usdc",
                    "executed_notional_usdc",
                    "fill_ledger_reconciliation",
                ],
            },
        }
    )

    assert summary["status"] == SpotFeatureIntakeGateStatus.FAILED.value
    assert summary["invalid_fields"][0]["field"] == (
        "cost_basis_authority.coinbase_average_cost_profit_buffer_pct"
    )
