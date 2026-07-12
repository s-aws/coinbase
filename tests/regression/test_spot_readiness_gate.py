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
    GOAL_ID as AUTONOMOUS_GOAL_ID,
    HISTORICAL_PHASES as AUTONOMOUS_HISTORICAL_PHASES,
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


def test_autonomous_work_queue_check_preserves_historical_phases_without_reactivating_them():
    parser = build_autonomous_work_queue_parser()
    args = parser.parse_args(["--summary-only"])
    summary = build_autonomous_work_queue_summary()

    assert args.summary_only is True
    assert AUTONOMOUS_WORK_QUEUE_SUMMARY_PREFIX == (
        "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
    )
    assert AUTONOMOUS_GOAL_ID == "selected_order_execution_closeout_slice"
    assert AUTONOMOUS_HISTORICAL_PHASES == tuple(range(7961, 7981))
    check_results = {check["name"]: check for check in summary["checks"]}
    failed_checks = {
        name: check for name, check in check_results.items() if not check["passed"]
    }

    assert failed_checks == {}
    assert summary["status"] == "passed"
    assert summary["goal_id"] == "selected_order_execution_closeout_slice"
    assert summary["historical_phase_range"] == "7961-7980"
    assert summary["historical_phase_count"] == 20
    assert summary["phase_range_status"] == "historical_not_work_authority"
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["mvp_scope"] == {
        "work_mode": "selected_order_execution_closeout_slice",
        "goal_authority": (
            "/home/ec2-user/coinbase-frontend/docs/CURRENT_MVP_GOAL.md"
        ),
        "frontend_authority": "operator_ui_only",
        "live_action_path": "auditable_backend_admin_interfaces_only",
        "phase_range_policy": "parked_unless_direct_current_slice_blocker",
        "focused_blast_radius_tests_required": True,
        "full_suite_at_durable_milestone_only": True,
        "active_work_policy": {
            "current_priority": "selected_order_execution_closeout_slice",
            "approved_phase_range_status": "historical_not_work_authority",
            "phase_range_work_allowed": False,
            "default_next_action": "none_current_slice_complete",
            "allow_only_when_directly_blocks": [
                "current vertical slice runtime behavior",
                "current vertical slice focused test",
                "live-safety or duplicate-order prevention",
                "cap, wallet, authorization, data-loss, or traceability prevention",
            ],
            "forbidden_default_actions": [
                "complete_current_approved_range",
                "candidate_blocker_self_justification",
                "fanout_or_scheduler_expansion",
                "unrelated futures/perpetuals summaries",
                "evidence-tightening batches",
                "contextless-hardening without a direct MVP blocker",
            ],
        },
    }
    assert summary["standing_limits"] == {
        "preferred_spot_notional_under_usdc": "10.00",
        "preferred_perpetual_notional_under_usdc": "30.00",
        "max_fan_out_notional_usdc": "100.00",
        "default_max_orders_per_second": 5,
        "non_fill_snapshot_distance_percent": 10,
    }
    assert check_results["current_goal_alignment"]["passed"] is True
    assert check_results["historical_queue_posture"]["passed"] is True
    assert check_results["github_workflows_retired"]["passed"] is True


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
