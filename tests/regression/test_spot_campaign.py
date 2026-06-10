"""Regression tests for read-only USDC spot campaign orchestration."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from business.spot_campaign import (
    apply_spot_campaign_sell_authority_profile,
    append_spot_campaign_snapshot_record,
    build_spot_campaign_all_usdc_readiness_gate,
    build_spot_campaign_config_template,
    build_spot_campaign_config_validation_report,
    build_spot_campaign_dry_run_matrix,
    build_spot_campaign_dry_run_diff,
    build_spot_campaign_intake_request,
    build_spot_campaign_ledger_cleanup_apply,
    build_spot_campaign_ledger_cleanup_plan,
    build_spot_campaign_no_order_recovery_drill,
    build_spot_campaign_operator_status,
    build_spot_campaign_pnl_checkpoints,
    build_spot_campaign_pnl_delta_report,
    build_spot_campaign_release_gate,
    build_spot_campaign_retry_plan,
    build_spot_campaign_run_index,
    build_spot_campaign_scheduler_status,
    build_spot_campaign_sell_authority_drift_report,
    build_spot_campaign_sell_authority_allowlist,
    build_spot_campaign_sell_authority_operator_report,
    build_spot_campaign_snapshot_record,
    build_spot_campaign_strict_sell_canary_candidates,
    load_spot_campaign_snapshot_records,
    normalize_spot_campaign_config,
    spot_campaign_config_to_sweep_config,
)
from business.spot_portfolio_sweep import append_sweep_run_record, build_sweep_run_record
from core.enums import (
    InventoryAuthorityStatus,
    SpotCampaignGateStatus,
    SpotCampaignRetryOrderClass,
    SpotCampaignRunMode,
    SpotCampaignSellAuthorityProfile,
    SpotCampaignStatus,
    SpotCampaignTemplateProfile,
    SpotCostBasisSource,
    SpotOperationLockStatus,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
    SpotSellAuthorityAllowlistFreshness,
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


class _FakeFillLedgerRepo:
    def __init__(self, fills):
        self.fills = fills

    def get_fills_by_product(self, product_id, side=None):
        rows = [
            fill
            for fill in self.fills
            if fill.get("product_id") == product_id
            or fill.get("instrument") == product_id
        ]
        if side:
            rows = [fill for fill in rows if fill.get("side") == side.upper()]
        return rows


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


def test_spot_campaign_template_and_validation_reports_ready():
    template = build_spot_campaign_config_template(
        profile=SpotCampaignTemplateProfile.BUY_CANARY,
    )
    report = build_spot_campaign_config_validation_report(config=template)
    incomplete = build_spot_campaign_config_validation_report(
        config=_campaign_config(safety_policy={})
    )

    assert template["side"] == "BUY"
    assert template["safety_policy"]["max_total_notional_per_run"] == "5"
    assert template["live_approval"]["required"] is True
    assert report["phase_90_ready"] is True
    assert report["live_coinbase_orders_ran"] is False
    assert incomplete["phase_90_ready"] is False
    assert {
        error["code"]
        for error in incomplete["errors"]
    } == {"missing_safety_cap"}


def test_spot_campaign_sell_authority_profiles_normalize_policy():
    sell_config = _campaign_config(
        side="SELL",
        safety_policy={
            "max_total_notional_per_run": "2",
            "max_notional_per_order": "1",
            "max_planned_orders": 2,
        },
    )
    strict = apply_spot_campaign_sell_authority_profile(
        config=sell_config,
        profile=SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT,
    )
    buffered = apply_spot_campaign_sell_authority_profile(
        config=sell_config,
        profile=(
            SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED
        ),
    )

    assert strict["sell_authority_profile"] == (
        SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value
    )
    assert strict["safety_policy"]["require_known_profitable_inventory"] is True
    assert strict["safety_policy"]["allow_coinbase_average_cost_basis"] is False
    assert SpotCostBasisSource.COINBASE_AVERAGE_COST.value not in (
        strict["cost_basis_authority"]["allowed_sources"]
    )
    assert buffered["sell_authority_profile"] == (
        SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
    )
    assert buffered["safety_policy"]["require_known_profitable_inventory"] is True
    assert buffered["safety_policy"]["allow_coinbase_average_cost_basis"] is True
    assert SpotCostBasisSource.COINBASE_AVERAGE_COST.value in (
        buffered["cost_basis_authority"]["allowed_sources"]
    )


def _sell_allowlist_matrix():
    return {
        "plan": {
            "planned_count": 3,
            "skipped_count": 1,
            "estimated_planned_quote_notional": "3.02",
        },
        "plan_explain": {
            "items": [
                {
                    "product_id": "AAA-USDC",
                    "side": "SELL",
                    "status": "planned",
                    "skip_reason": "none",
                    "requested_quote_notional": "1.01",
                    "estimated_quote_notional": "1.01",
                    "estimated_price": "10",
                    "planned_base_size": "0.101",
                    "sell_authority": {
                        "allowed": True,
                        "status": "known_profitable",
                        "cost_basis_authority": "fill_ledger",
                        "reason": "known profitable lots cover requested spot sweep sell size",
                        "limit_price": "10",
                        "known_quantity": "1",
                        "known_profitable_quantity": "1",
                    },
                },
                {
                    "product_id": "BBB-USDC",
                    "side": "SELL",
                    "status": "planned",
                    "skip_reason": "none",
                    "requested_quote_notional": "1.01",
                    "estimated_quote_notional": "1",
                    "estimated_price": "20",
                    "planned_base_size": "0.05",
                    "sell_authority": {
                        "allowed": True,
                        "status": "coinbase_average_profitable",
                        "cost_basis_authority": "coinbase_average_cost",
                        "reason": "Coinbase average cost basis covers requested spot sweep sell",
                        "limit_price": "20",
                        "coinbase_average_cost_quantity": "1",
                        "coinbase_average_profitable_quantity": "1",
                    },
                },
                {
                    "product_id": "CCC-USDC",
                    "side": "SELL",
                    "status": "planned",
                    "skip_reason": "none",
                    "requested_quote_notional": "1.01",
                    "estimated_quote_notional": "1.01",
                    "estimated_price": "30",
                    "planned_base_size": "0.033666",
                    "sell_authority": {
                        "allowed": False,
                        "status": "insufficient_known_profitable",
                        "cost_basis_authority": "wallet_only",
                        "reason": "known lots exist but are insufficient or not profitable",
                        "limit_price": "30",
                    },
                },
                {
                    "product_id": "DDD-USDC",
                    "side": "SELL",
                    "status": "skipped",
                    "skip_reason": "below_quote_min",
                    "requested_quote_notional": "1.01",
                    "estimated_quote_notional": "0",
                    "planned_base_size": "0",
                    "reason": "requested notional rounds below quote minimum",
                },
            ],
        },
    }


def test_spot_campaign_sell_authority_allowlist_builds_narrow_config():
    config = apply_spot_campaign_sell_authority_profile(
        config=_campaign_config(
            side="SELL",
            safety_policy={
                "max_total_notional_per_run": "5",
                "max_notional_per_order": "2",
                "max_planned_orders": 5,
            },
        ),
        profile=SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED,
    )
    allowlist = build_spot_campaign_sell_authority_allowlist(
        config=config,
        dry_run_matrix=_sell_allowlist_matrix(),
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert allowlist["status"] == SpotCampaignStatus.READY.value
    assert allowlist["allowlist_count"] == 2
    assert allowlist["blocked_count"] == 1
    assert allowlist["skipped_count"] == 1
    assert allowlist["estimated_allowlisted_quote_notional"] == "2.01"
    assert allowlist["authority_source_counts"] == {
        "coinbase_average_cost": 1,
        "fill_ledger": 1,
        "wallet_only": 1,
    }
    assert allowlist["allow_products"] == ["AAA-USDC", "BBB-USDC"]
    assert allowlist["allowlist_config"]["product_scope"]["allow_products"] == [
        "AAA-USDC",
        "BBB-USDC",
    ]
    assert allowlist["allowlist_sweep_config"]["safety_policy"]["allow_products"] == [
        "AAA-USDC",
        "BBB-USDC",
    ]
    metadata = allowlist["allowlist_metadata"]
    assert metadata["freshness_status"] == SpotSellAuthorityAllowlistFreshness.FRESH.value
    assert metadata["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert metadata["max_age_seconds"] == 300
    assert metadata["expires_at"] == "2026-01-01T00:05:00+00:00"
    assert allowlist["allowlist_sweep_config"]["sell_authority_allowlist"] == metadata


def test_spot_campaign_sell_authority_allowlist_excludes_average_cost_gate_blocks():
    config = apply_spot_campaign_sell_authority_profile(
        config=_campaign_config(side="SELL"),
        profile=SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED,
    )
    matrix = _sell_allowlist_matrix()
    matrix["safety_evaluation"] = {
        "coinbase_average_cost_authority_gate": {
            "violations": [
                {
                    "code": "coinbase_average_cost_drift",
                    "product_id": "BBB-USDC",
                    "reason": "Coinbase average cost authority has stale drift",
                }
            ]
        }
    }

    allowlist = build_spot_campaign_sell_authority_allowlist(
        config=config,
        dry_run_matrix=matrix,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert allowlist["allowlist_count"] == 1
    assert allowlist["blocked_count"] == 2
    assert allowlist["allow_products"] == ["AAA-USDC"]
    assert allowlist["allowlist_config"]["product_scope"]["allow_products"] == [
        "AAA-USDC"
    ]
    assert allowlist["authority_status_counts"] == {
        "insufficient_known_profitable": 1,
        InventoryAuthorityStatus.KNOWN_PROFITABLE.value: 1,
        InventoryAuthorityStatus.UNAVAILABLE.value: 1,
    }
    blocked_by_gate = [
        row for row in allowlist["blocked_rows"] if row["product_id"] == "BBB-USDC"
    ][0]
    assert blocked_by_gate["authority_source"] == (
        SpotCostBasisSource.COINBASE_AVERAGE_COST.value
    )
    assert blocked_by_gate["authority_status"] == (
        InventoryAuthorityStatus.UNAVAILABLE.value
    )
    assert blocked_by_gate["authority_pre_gate_status"] == "coinbase_average_profitable"
    assert blocked_by_gate["authority_gate_violations"][0]["code"] == (
        "coinbase_average_cost_drift"
    )
    assert "stale drift" in blocked_by_gate["authority_reason"]


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


def test_spot_campaign_diff_recovery_drill_and_all_usdc_gate():
    baseline = build_spot_campaign_dry_run_matrix(
        config=_campaign_config(max_products=1),
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=True,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    current = build_spot_campaign_dry_run_matrix(
        config=_campaign_config(max_products=2),
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=True,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    diff = build_spot_campaign_dry_run_diff(
        baseline_matrix=baseline,
        current_matrix=current,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    drill = build_spot_campaign_no_order_recovery_drill(
        config=_campaign_config(max_products=2),
        dry_run_matrix=current,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    restricted_gate = build_spot_campaign_all_usdc_readiness_gate(
        config=_campaign_config(max_products=2),
        dry_run_matrix=current,
        release_gate={"gate_status": SpotCampaignGateStatus.PASSED.value},
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    broad_config = _campaign_config(max_products=None)
    broad_matrix = build_spot_campaign_dry_run_matrix(
        config=broad_config,
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=False,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    broad_release = build_spot_campaign_release_gate(
        config=broad_config,
        dry_run_matrix=broad_matrix,
        intake_summary=build_spot_feature_intake_summary(
            request=build_spot_campaign_intake_request(broad_config)
        ),
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    broad_gate = build_spot_campaign_all_usdc_readiness_gate(
        config=broad_config,
        dry_run_matrix=broad_matrix,
        release_gate=broad_release,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert diff["planned_count_delta"] == 1
    assert diff["estimated_notional_delta_usdc"] == "1"
    assert drill["passed"] is True
    assert drill["retry_plan"]["retryable_product_count"] == 2
    assert drill["live_coinbase_orders_ran"] is False
    assert restricted_gate["gate_status"] == SpotCampaignGateStatus.FAILED.value
    assert restricted_gate["failures"][0]["code"] == "max_products_restricts_all_usdc"
    assert broad_gate["gate_status"] == SpotCampaignGateStatus.PASSED.value
    assert broad_gate["plan_summary"]["planned_count"] == 2


def test_all_usdc_gate_blocks_narrow_sell_authority_allowlist_scope():
    sell_config = apply_spot_campaign_sell_authority_profile(
        config=_campaign_config(
            side="SELL",
            max_products=None,
            product_scope={
                "quote_currency": "USDC",
                "us_customer_available": True,
                "selection_rule": "all_coinbase_usdc_spot_us_customer_available",
                "allow_products": ["AAA-USDC"],
            },
            safety_policy={
                "max_total_notional_per_run": "2",
                "max_notional_per_order": "1",
                "max_planned_orders": 2,
            },
        ),
        profile=SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT,
    )
    matrix = build_spot_campaign_dry_run_matrix(
        config=sell_config,
        products=PRODUCTS,
        wallets=WALLETS,
        include_items=False,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    gate = build_spot_campaign_all_usdc_readiness_gate(
        config=sell_config,
        dry_run_matrix=matrix,
        release_gate={"gate_status": SpotCampaignGateStatus.PASSED.value},
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    failure_codes = {failure["code"] for failure in gate["failures"]}

    assert gate["gate_status"] == SpotCampaignGateStatus.FAILED.value
    assert "allow_or_deny_products_present" in failure_codes
    assert "selected_product_count_mismatch" in failure_codes
    assert "max_products_restricts_all_usdc" not in failure_codes


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


def test_spot_campaign_run_index_scheduler_and_pnl_checkpoints():
    config = _campaign_config()
    normalized = normalize_spot_campaign_config(config)
    first = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 2},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
            "pnl_snapshot": {
                "portfolio": {
                    "total_pnl": "0.10",
                    "mark_value": "5",
                    "fees": "0.01",
                },
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 2},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
            "pnl_snapshot": {
                "portfolio": {
                    "total_pnl": "0.25",
                    "mark_value": "6",
                    "fees": "0.02",
                },
            },
        },
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    sweep_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id="spot-sweep-index-regression",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        config=spot_campaign_config_to_sweep_config(config),
        execution={
            "live_coinbase_orders_ran": True,
            "total_submitted_notional_usdc": "2",
            "total_executed_notional_usdc": "1.99",
        },
    )
    run_index = build_spot_campaign_run_index(
        campaign_records=[first, second],
        sweep_records=[sweep_run],
        generated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    checkpoints = build_spot_campaign_pnl_checkpoints(
        records=[first, second],
        generated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    scheduler_due = build_spot_campaign_scheduler_status(
        config=config,
        sweep_records=[],
        generated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    scheduler_not_due = build_spot_campaign_scheduler_status(
        config=config,
        sweep_records=[sweep_run],
        generated_at=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
    )

    assert run_index["campaign_count"] == 1
    assert run_index["campaigns"][0]["sweep_run_count"] == 1
    assert run_index["campaigns"][0]["unrecorded_sweep_run_count"] == 1
    assert checkpoints["checkpoint_count"] == 2
    assert checkpoints["campaigns"][0]["checkpoints"][1]["delta_total_pnl"] == "0.15"
    assert scheduler_due["scheduler_decision"]["decision"] == (
        SpotPortfolioSweepAutomationDecision.DUE.value
    )
    assert scheduler_not_due["scheduler_decision"]["decision"] == (
        SpotPortfolioSweepAutomationDecision.NOT_DUE.value
    )


def test_spot_campaign_ledger_cleanup_plan_classifies_unrecorded_runs():
    config = _campaign_config()
    normalized = normalize_spot_campaign_config(config)
    campaign_record = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 2},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    live_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id="spot-sweep-unrecorded-live",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        config=spot_campaign_config_to_sweep_config(config),
        execution={
            "live_coinbase_orders_ran": True,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.99",
        },
    )
    no_order_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id="spot-sweep-unrecorded-no-order",
        status=SpotPortfolioSweepRunStatus.FAILED.value,
        started_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        config=spot_campaign_config_to_sweep_config(config),
        execution={
            "live_coinbase_orders_ran": False,
            "total_submitted_notional_usdc": "0",
            "total_executed_notional_usdc": "0",
        },
    )

    cleanup = build_spot_campaign_ledger_cleanup_plan(
        campaign_records=[campaign_record],
        sweep_records=[live_run, no_order_run],
        generated_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )

    assert cleanup["mode"] == SpotCampaignRunMode.LEDGER_CLEANUP_PLAN.value
    assert cleanup["status"] == SpotCampaignStatus.READY.value
    assert cleanup["planned_record_count"] == 1
    assert cleanup["planned_ignore_count"] == 1
    assert cleanup["recordable_runs"][0]["run_id"] == "spot-sweep-unrecorded-live"
    assert cleanup["ignore_candidates"][0]["run_id"] == (
        "spot-sweep-unrecorded-no-order"
    )
    assert cleanup["live_coinbase_orders_ran"] is False


def test_spot_campaign_ledger_cleanup_apply_builds_local_records():
    config = _campaign_config()
    normalized = normalize_spot_campaign_config(config)
    campaign_record = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 1},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    live_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id="spot-sweep-unrecorded-live",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        config=spot_campaign_config_to_sweep_config(config),
        execution={
            "live_coinbase_orders_ran": True,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.99",
        },
    )

    apply_plan = build_spot_campaign_ledger_cleanup_apply(
        campaign_records=[campaign_record],
        sweep_records=[live_run],
        approved_run_ids=["spot-sweep-unrecorded-live"],
        dry_run=True,
        actor_id="operator-001",
        generated_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )

    assert apply_plan["mode"] == SpotCampaignRunMode.LEDGER_CLEANUP_APPLY.value
    assert apply_plan["status"] == SpotCampaignStatus.READY.value
    assert apply_plan["dry_run"] is True
    assert apply_plan["append_record_count"] == 1
    assert apply_plan["records_to_append"][0]["mode"] == (
        SpotCampaignRunMode.LEDGER_CLEANUP_APPLY.value
    )
    assert apply_plan["records_to_append"][0]["sweep_summary"]["run_id"] == (
        "spot-sweep-unrecorded-live"
    )
    assert apply_plan["records_to_append"][0]["cleanup_approval"]["local_only"] is True
    assert apply_plan["live_coinbase_orders_ran"] is False


def test_spot_campaign_ledger_cleanup_apply_cli_appends_approved_local_record():
    scratch_id = uuid4().hex
    config = _campaign_config()
    normalized = normalize_spot_campaign_config(config)
    scratch_dir = Path("runtime_state") / "test_spot_campaign"
    campaign_state_file = scratch_dir / f"cleanup_campaign_{scratch_id}.jsonl"
    sweep_state_file = scratch_dir / f"cleanup_sweep_{scratch_id}.jsonl"
    campaign_record = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 1},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    sweep_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id="spot-sweep-unrecorded-live",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        config=spot_campaign_config_to_sweep_config(config),
        execution={
            "live_coinbase_orders_ran": True,
            "total_submitted_notional_usdc": "1",
            "total_executed_notional_usdc": "0.99",
        },
    )
    append_spot_campaign_snapshot_record(campaign_state_file, campaign_record)
    append_sweep_run_record(sweep_state_file, sweep_run)

    rc = run_spot_campaign_main([
        "--apply-ledger-cleanup-plan",
        "--approved-cleanup-run-id",
        "spot-sweep-unrecorded-live",
        "--execute-local-cleanup-apply",
        "--state-file",
        str(campaign_state_file),
        "--sweep-state-file",
        str(sweep_state_file),
    ])

    assert rc == 0
    records = load_spot_campaign_snapshot_records(campaign_state_file)
    assert records[-1]["mode"] == SpotCampaignRunMode.LEDGER_CLEANUP_APPLY.value
    assert records[-1]["sweep_summary"]["run_id"] == "spot-sweep-unrecorded-live"
    assert records[-1]["cleanup_approval"]["local_only"] is True


def test_spot_campaign_authority_drift_report_blocks_removed_products():
    previous = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "sell_authority_profile": SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
        "allow_products": ["AAA-USDC", "BBB-USDC", "POWR-USDC"],
    }
    current = {
        "generated_at": "2026-06-10T12:05:00+00:00",
        "sell_authority_profile": SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
        "allow_products": ["AAA-USDC", "BBB-USDC"],
    }

    report = build_spot_campaign_sell_authority_drift_report(
        previous_allowlist=previous,
        current_allowlist=current,
        generated_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )

    assert report["mode"] == SpotCampaignRunMode.SELL_AUTHORITY_DRIFT.value
    assert report["status"] == SpotCampaignStatus.BLOCKED.value
    assert report["gate_status"] == SpotCampaignGateStatus.FAILED.value
    assert report["removed_products"] == ["POWR-USDC"]
    assert report["failures"][0]["code"] == "allowlist_products_removed"
    assert "regenerate" in report["operator_action"]


def test_spot_campaign_authority_operator_report_separates_average_cost_drift():
    strict = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "status": SpotCampaignStatus.READY.value,
        "sell_authority_profile": SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
        "allow_products": ["AAA-USDC"],
        "authority_source_counts": {SpotCostBasisSource.FILL_LEDGER.value: 1},
        "authority_status_counts": {
            InventoryAuthorityStatus.KNOWN_PROFITABLE.value: 1,
        },
    }
    average_cost = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "status": SpotCampaignStatus.READY.value,
        "sell_authority_profile": (
            SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        ),
        "allow_products": ["AAA-USDC", "BBB-USDC"],
        "authority_source_counts": {
            SpotCostBasisSource.COINBASE_AVERAGE_COST.value: 2,
        },
        "authority_status_counts": {"coinbase_average_profitable": 2},
        "blocked_rows": [
            {
                "product_id": "CCC-USDC",
                "authority_status": InventoryAuthorityStatus.UNAVAILABLE.value,
                "authority_reason": "Coinbase average cost authority has stale drift",
            }
        ],
    }

    report = build_spot_campaign_sell_authority_operator_report(
        strict_allowlist=strict,
        average_cost_allowlist=average_cost,
        generated_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )

    assert report["mode"] == (
        SpotCampaignRunMode.SELL_AUTHORITY_OPERATOR_REPORT.value
    )
    assert report["strict_count"] == 1
    assert report["average_cost_count"] == 2
    assert report["average_cost_only_products"] == ["BBB-USDC"]
    assert report["coinbase_average_cost"]["stale_or_drift_blocked_products"] == [
        "CCC-USDC"
    ]
    assert report["stale_or_drift_blocked_count"] == 1


def test_spot_campaign_strict_sell_canary_candidates_exclude_recent_sells():
    allowlist = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "sell_authority_profile": SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
        "allowlist_rows": [
            {
                "product_id": "AAA-USDC",
                "authority_source": SpotCostBasisSource.FILL_LEDGER.value,
                "authority_status": InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
                "estimated_quote_notional": "1.01",
            },
            {
                "product_id": "BBB-USDC",
                "authority_source": SpotCostBasisSource.FILL_LEDGER.value,
                "authority_status": InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
                "estimated_quote_notional": "1.01",
            },
            {
                "product_id": "CCC-USDC",
                "authority_source": SpotCostBasisSource.FILL_LEDGER.value,
                "authority_status": InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
                "estimated_quote_notional": "1.01",
            },
        ],
    }
    recent_sell = build_sweep_run_record(
        config_id="strict-sell-sweep",
        run_id="spot-sweep-recent-sell",
        status=SpotPortfolioSweepRunStatus.COMPLETED.value,
        started_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        completed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        config={
            "side": "SELL",
            "sell_authority_allowlist": {
                "sell_authority_profile": (
                    SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value
                ),
            },
        },
        execution={
            "live_coinbase_orders_ran": True,
            "orders": [
                {
                    "product_id": "AAA-USDC",
                    "status": SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    "exchange_order_id": "exchange-aaa",
                    "submitted_notional_usdc": "1.01",
                    "executed_notional_usdc": "1.00",
                    "response_success": True,
                }
            ],
        },
    )

    candidates = build_spot_campaign_strict_sell_canary_candidates(
        allowlist=allowlist,
        sweep_records=[recent_sell],
        max_candidates=2,
        recent_run_limit=5,
        generated_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )

    assert candidates["status"] == SpotCampaignStatus.READY.value
    assert candidates["candidate_count"] == 2
    assert [row["product_id"] for row in candidates["candidates"]] == [
        "BBB-USDC",
        "CCC-USDC",
    ]
    assert candidates["excluded_recent_products"][0]["product_id"] == "AAA-USDC"
    assert candidates["live_coinbase_orders_ran"] is False


def test_spot_campaign_pnl_delta_report_compares_durable_scopes():
    config = _campaign_config()
    first = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 1},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
            "pnl_snapshot": {
                "portfolio": {
                    "total_pnl": "0.10",
                    "since_last_purchase_pnl": "0.04",
                    "realized_lot": {"realized_pnl": "0.01"},
                },
                "average_cost_portfolio": {"total_pnl": "0.09"},
                "products": [
                    {"product_id": "AAA-USDC", "total_pnl": "0.05"},
                ],
            },
        },
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = build_spot_campaign_snapshot_record(
        config=config,
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix={
            "plan": {"planned_count": 1},
            "safety_evaluation": {
                "decision": SpotPortfolioSweepSafetyDecision.ALLOWED.value,
            },
            "pnl_snapshot": {
                "portfolio": {
                    "total_pnl": "0.35",
                    "since_last_purchase_pnl": "0.14",
                    "realized_lot": {"realized_pnl": "0.03"},
                },
                "average_cost_portfolio": {"total_pnl": "0.31"},
                "products": [
                    {"product_id": "AAA-USDC", "total_pnl": "0.22"},
                ],
            },
        },
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    report = build_spot_campaign_pnl_delta_report(
        records=[first, second],
        generated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    deltas = {
        (row["scope"], row["name"]): row["delta"]
        for row in report["campaigns"][0]["deltas"]
    }
    assert report["mode"] == SpotCampaignRunMode.PNL_DELTA_REPORT.value
    assert deltas[("portfolio", "portfolio_total_pnl")] == "0.25"
    assert deltas[("portfolio", "since_last_purchase_pnl")] == "0.1"
    assert deltas[("realized_lot", "portfolio_realized_pnl")] == "0.02"
    assert deltas[("average_cost", "average_cost_total_pnl")] == "0.22"
    assert deltas[("product", "AAA-USDC")] == "0.17"


def test_spot_campaign_pnl_product_rows_are_explicit_opt_in():
    fills = [
        {
            "product_id": "AAA-USDC",
            "side": "BUY",
            "quantity": "1",
            "price": "8",
            "fees": "0",
            "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ]
    default_matrix = build_spot_campaign_dry_run_matrix(
        config=_campaign_config(max_products=1),
        products=PRODUCTS,
        wallets=WALLETS,
        fill_ledger_repo=_FakeFillLedgerRepo(fills),
        include_items=False,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    opt_in_matrix = build_spot_campaign_dry_run_matrix(
        config=_campaign_config(max_products=1),
        products=PRODUCTS,
        wallets=WALLETS,
        fill_ledger_repo=_FakeFillLedgerRepo(fills),
        include_items=False,
        include_pnl_products=True,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert "products" not in default_matrix["pnl_snapshot"]
    assert opt_in_matrix["pnl_snapshot"]["products"][0]["product_id"] == "AAA-USDC"

    default_record = build_spot_campaign_snapshot_record(
        config=_campaign_config(max_products=1),
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix=default_matrix,
    )
    opt_in_record = build_spot_campaign_snapshot_record(
        config=_campaign_config(max_products=1),
        mode=SpotCampaignRunMode.DRY_RUN,
        status=SpotCampaignStatus.READY,
        dry_run_matrix=opt_in_matrix,
    )

    assert "products" not in default_record["dry_run"]["pnl_snapshot"]
    assert opt_in_record["dry_run"]["pnl_snapshot"]["products"][0]["product_id"] == (
        "AAA-USDC"
    )


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


def test_spot_campaign_retry_plan_public_fixture_classifies_rows():
    fixture = json.loads(
        Path("docs/examples/spot-campaign-retry-plan-fixture.json").read_text(
            encoding="utf-8"
        )
    )

    retry_plan = build_spot_campaign_retry_plan(
        config=fixture["config"],
        sweep_records=fixture["sweep_records"],
        run_id=fixture["sweep_records"][0]["run_id"],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert retry_plan["retry_status"] == SpotCampaignStatus.READY.value
    assert retry_plan["retryable_product_ids"] == ["BBB-USDC"]
    assert retry_plan["submitted_or_live_product_ids"] == ["AAA-USDC"]
    assert retry_plan["not_retryable_product_ids"] == ["CCC-USDC"]
    assert retry_plan["retry_config"]["product_scope"]["allow_products"] == [
        "BBB-USDC"
    ]
    assert {
        row["product_id"]: row["class"]
        for row in retry_plan["order_classes"]
    } == fixture["expected"]["order_classes"]


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


def test_spot_campaign_scheduler_status_cli_rehearses_due_and_not_due(capsys):
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    campaign_config = _campaign_config(
        campaign_id=f"spot-campaign-scheduler-{scratch_id}",
        sweep_config_id=f"spot-sweep-scheduler-{scratch_id}",
        max_products=2,
    )
    campaign_config_file = scratch_dir / f"spot_campaign_scheduler_{scratch_id}.json"
    sweep_state_file = scratch_dir / f"spot_sweep_scheduler_{scratch_id}.jsonl"
    campaign_config_file.write_text(json.dumps(campaign_config), encoding="utf-8")
    config = normalize_spot_campaign_config(campaign_config)
    try:
        due_rc = run_spot_campaign_main([
            "--config-file",
            str(campaign_config_file),
            "--sweep-state-file",
            str(sweep_state_file),
            "--scheduler-status",
        ])
        due_payload = json.loads(
            capsys.readouterr().out.strip().splitlines()[-1].removeprefix(
                "SPOT_CAMPAIGN "
            )
        )
        assert due_rc == 0
        assert due_payload["scheduler_status"]["scheduler_decision"]["decision"] == (
            SpotPortfolioSweepAutomationDecision.DUE.value
        )

        append_sweep_run_record(
            sweep_state_file,
            build_sweep_run_record(
                config_id=config["sweep_config_id"],
                run_id="spot-sweep-scheduler-not-due",
                status=SpotPortfolioSweepRunStatus.COMPLETED.value,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                config=spot_campaign_config_to_sweep_config(config),
                execution={
                    "live_coinbase_orders_ran": True,
                    "total_submitted_notional_usdc": "1",
                    "total_executed_notional_usdc": "1",
                },
            ),
        )
        not_due_rc = run_spot_campaign_main([
            "--config-file",
            str(campaign_config_file),
            "--sweep-state-file",
            str(sweep_state_file),
            "--scheduler-status",
        ])
        not_due_payload = json.loads(
            capsys.readouterr().out.strip().splitlines()[-1].removeprefix(
                "SPOT_CAMPAIGN "
            )
        )
        assert not_due_rc == 1
        assert not_due_payload["scheduler_status"]["scheduler_decision"]["decision"] == (
            SpotPortfolioSweepAutomationDecision.NOT_DUE.value
        )
    finally:
        campaign_config_file.unlink(missing_ok=True)
        sweep_state_file.unlink(missing_ok=True)


def test_spot_campaign_read_only_report_cli_modes():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    previous_allowlist_file = scratch_dir / f"previous_allowlist_{scratch_id}.json"
    current_allowlist_file = scratch_dir / f"current_allowlist_{scratch_id}.json"
    average_allowlist_file = scratch_dir / f"average_allowlist_{scratch_id}.json"
    sweep_state_file = scratch_dir / f"candidate_sweeps_{scratch_id}.jsonl"
    strict_allowlist = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "status": SpotCampaignStatus.READY.value,
        "sell_authority_profile": SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
        "allow_products": ["AAA-USDC", "POWR-USDC"],
        "allowlist_rows": [
            {
                "product_id": "AAA-USDC",
                "authority_source": SpotCostBasisSource.FILL_LEDGER.value,
                "authority_status": InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
                "estimated_quote_notional": "1.01",
            },
            {
                "product_id": "POWR-USDC",
                "authority_source": SpotCostBasisSource.FILL_LEDGER.value,
                "authority_status": InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
                "estimated_quote_notional": "1.01",
            },
        ],
    }
    current_allowlist = {
        **strict_allowlist,
        "allow_products": ["AAA-USDC"],
        "allowlist_rows": [strict_allowlist["allowlist_rows"][0]],
    }
    average_allowlist = {
        "generated_at": "2026-06-10T12:00:00+00:00",
        "status": SpotCampaignStatus.READY.value,
        "sell_authority_profile": (
            SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        ),
        "allow_products": ["AAA-USDC", "BBB-USDC"],
    }
    previous_allowlist_file.write_text(
        json.dumps(strict_allowlist),
        encoding="utf-8",
    )
    current_allowlist_file.write_text(
        json.dumps(current_allowlist),
        encoding="utf-8",
    )
    average_allowlist_file.write_text(
        json.dumps(average_allowlist),
        encoding="utf-8",
    )
    try:
        assert run_spot_campaign_main(
            [
                "--sell-authority-drift-report",
                "--baseline-allowlist-file",
                str(previous_allowlist_file),
                "--current-allowlist-file",
                str(current_allowlist_file),
                "--summary-only",
            ]
        ) == 1
        assert run_spot_campaign_main(
            [
                "--authority-operator-report",
                "--strict-allowlist-file",
                str(previous_allowlist_file),
                "--average-cost-allowlist-file",
                str(average_allowlist_file),
                "--summary-only",
            ]
        ) == 0
        assert run_spot_campaign_main(
            [
                "--strict-sell-canary-candidates",
                "--input-allowlist-file",
                str(previous_allowlist_file),
                "--sweep-state-file",
                str(sweep_state_file),
                "--max-candidates",
                "1",
                "--summary-only",
            ]
        ) == 0
    finally:
        previous_allowlist_file.unlink(missing_ok=True)
        current_allowlist_file.unlink(missing_ok=True)
        average_allowlist_file.unlink(missing_ok=True)
        sweep_state_file.unlink(missing_ok=True)


def test_spot_campaign_allowlist_cli_writes_artifacts(monkeypatch):
    import configuration
    import tools.run_spot_campaign as campaign_tool

    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    config_file = scratch_dir / f"spot_campaign_allowlist_{scratch_id}.json"
    state_file = scratch_dir / f"spot_campaign_allowlist_state_{scratch_id}.jsonl"
    allowlist_file = scratch_dir / f"spot_campaign_allowlist_{scratch_id}.allowlist.json"
    allowlist_config_file = (
        scratch_dir / f"spot_campaign_allowlist_{scratch_id}.config.json"
    )
    allowlist_sweep_file = (
        scratch_dir / f"spot_campaign_allowlist_{scratch_id}.sweep.json"
    )
    config_file.write_text(
        json.dumps(
            _campaign_config(
                side="SELL",
                safety_policy={
                    "max_total_notional_per_run": "5",
                    "max_notional_per_order": "2",
                    "max_planned_orders": 5,
                },
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COINBASE_API_KEY", "test-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "test-secret")
    monkeypatch.setattr(configuration, "get_rest_client", lambda: object())
    monkeypatch.setattr(campaign_tool, "_load_public_products", lambda: [])
    monkeypatch.setattr(campaign_tool, "_load_wallets", lambda _client: {})
    monkeypatch.setattr(campaign_tool, "_build_fill_repo_or_none", lambda: object())
    monkeypatch.setattr(
        campaign_tool,
        "build_spot_campaign_dry_run_matrix",
        lambda **_kwargs: _sell_allowlist_matrix(),
    )
    try:
        assert run_spot_campaign_main(
            [
                "--config-file",
                str(config_file),
                "--sell-authority-profile",
                SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
                "--sell-authority-allowlist",
                "--write-allowlist-file",
                str(allowlist_file),
                "--write-allowlist-config-file",
                str(allowlist_config_file),
                "--write-allowlist-sweep-config-file",
                str(allowlist_sweep_file),
                "--state-file",
                str(state_file),
                "--record-snapshot",
                "--summary-only",
            ]
        ) == 0

        allowlist = json.loads(allowlist_file.read_text(encoding="utf-8"))
        allowlist_config = json.loads(
            allowlist_config_file.read_text(encoding="utf-8")
        )
        sweep_config = json.loads(allowlist_sweep_file.read_text(encoding="utf-8"))
        records = load_spot_campaign_snapshot_records(state_file)

        assert allowlist["allowlist_count"] == 2
        assert allowlist_config["product_scope"]["allow_products"] == [
            "AAA-USDC",
            "BBB-USDC",
        ]
        assert sweep_config["safety_policy"]["allow_products"] == [
            "AAA-USDC",
            "BBB-USDC",
        ]
        assert sweep_config["sell_authority_allowlist"]["freshness_status"] == (
            SpotSellAuthorityAllowlistFreshness.FRESH.value
        )
        assert sweep_config["sell_authority_allowlist"]["max_age_seconds"] == 300
        assert records[-1]["mode"] == (
            SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST.value
        )
        assert records[-1]["sell_authority_allowlist"]["allowlist_count"] == 2
    finally:
        config_file.unlink(missing_ok=True)
        state_file.unlink(missing_ok=True)
        allowlist_file.unlink(missing_ok=True)
        allowlist_config_file.unlink(missing_ok=True)
        allowlist_sweep_file.unlink(missing_ok=True)


def test_spot_campaign_cli_template_validation_and_profile_output():
    scratch_dir = Path("genai_tools")
    scratch_dir.mkdir(exist_ok=True)
    scratch_id = uuid4().hex
    template_file = scratch_dir / f"spot_campaign_template_{scratch_id}.json"
    invalid_config_file = scratch_dir / f"spot_campaign_invalid_{scratch_id}.json"
    sell_config_file = scratch_dir / f"spot_campaign_sell_{scratch_id}.json"
    profiled_file = scratch_dir / f"spot_campaign_profiled_{scratch_id}.json"
    invalid_config_file.write_text(
        json.dumps(_campaign_config(safety_policy={})),
        encoding="utf-8",
    )
    sell_config_file.write_text(
        json.dumps(
            _campaign_config(
                side="SELL",
                safety_policy={
                    "max_total_notional_per_run": "2",
                    "max_notional_per_order": "1",
                    "max_planned_orders": 2,
                },
            )
        ),
        encoding="utf-8",
    )
    try:
        assert run_spot_campaign_main(
            [
                "--template-profile",
                SpotCampaignTemplateProfile.BUY_CANARY.value,
                "--write-template-file",
                str(template_file),
            ]
        ) == 0
        assert run_spot_campaign_main(
            [
                "--config-file",
                str(invalid_config_file),
                "--validate-config-report",
            ]
        ) == 1
        assert run_spot_campaign_main(
            [
                "--config-file",
                str(sell_config_file),
                "--sell-authority-profile",
                SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value,
                "--write-profiled-config-file",
                str(profiled_file),
            ]
        ) == 0

        template = json.loads(template_file.read_text(encoding="utf-8"))
        profiled = json.loads(profiled_file.read_text(encoding="utf-8"))
        assert template["campaign_name"] == "spot_buy_canary_campaign"
        assert profiled["sell_authority_profile"] == (
            SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        )
    finally:
        template_file.unlink(missing_ok=True)
        invalid_config_file.unlink(missing_ok=True)
        sell_config_file.unlink(missing_ok=True)
        profiled_file.unlink(missing_ok=True)
