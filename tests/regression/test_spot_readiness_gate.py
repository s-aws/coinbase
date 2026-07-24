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
    assert AUTONOMOUS_GOAL_ID == (
        "operator_follow_up_operations_queue_and_single_live_proof"
    )
    assert AUTONOMOUS_HISTORICAL_PHASES == tuple(range(7961, 7981))
    check_results = {check["name"]: check for check in summary["checks"]}
    failed_checks = {
        name: check for name, check in check_results.items() if not check["passed"]
    }

    assert failed_checks == {}
    assert summary["status"] == "passed"
    assert summary["goal_id"] == (
        "operator_follow_up_operations_queue_and_single_live_proof"
    )
    assert summary["historical_phase_range"] == "7961-7980"
    assert summary["historical_phase_count"] == 20
    assert summary["phase_range_status"] == "historical_not_work_authority"
    assert summary["slice_status"] == "complete_zero_candidates"
    assert summary["blockers"] == []
    assert summary["current_action"] == (
        "complete_zero_candidates_all_live_allowances_unconsumed"
    )
    assert summary["default_next_action"] == (
        "complete_zero_candidates_all_live_allowances_unconsumed"
    )
    assert summary["next_action"] == "await_operator_direction_for_next_mvp"
    assert summary["r12_workflow_claims_consumed"] == 1
    assert summary["r12_claim_created"] is True
    assert summary["r12_eligibility_cycles_consumed"] == 2
    assert summary["r12_preview_attempts_consumed"] == 1
    assert summary["r12_release_gate_ready"] is False
    assert summary["follow_up_operations_proof"]["candidate_count"] == 0
    assert summary["follow_up_operations_proof"]["allowances_consumed"] is False
    assert summary["historical_materialization_closeout"][
        "authority_status"
    ] == "historical_predecessor_not_current_authority"
    assert summary["live_coinbase_eligibility_reads_ran"] is False
    assert summary["live_coinbase_preview_ran"] is None
    assert summary["live_coinbase_preview_outcome"] == "unknown_consumed"
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_mutations_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["historical_r12"] == {
        "goal_id": "futures_preview_acceptance_recovery_r12",
        "alignment_token": "r12_separate_eligibility_and_single_use_attempt_v1",
        "slice_status": "complete_terminal_unknown_consumed",
        "blockers": ["claim_only_recovery_unknown_consumed"],
        "workflow_claims_consumed": 1,
        "claim_created": True,
        "eligibility_cycles_consumed": 2,
        "preview_attempts_consumed": 1,
        "release_gate_ready": False,
        "preview_network_reach": "unknown",
        "preview_outcome": "unknown_consumed",
        "coinbase_mutations_ran": False,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
    }
    assert summary["historical_r11"] == {
        "status": "complete_terminal_no_retry",
        "workflow_claims_consumed": 1,
        "preview_attempts_consumed": 0,
        "terminal": True,
        "terminal_before_preview": True,
        "historical_successor_authorized": False,
    }
    assert summary["mvp_scope"] == {
        "work_mode": "complete_zero_candidates_all_live_allowances_unconsumed",
        "product_goal": (
            "Record the deployed passive local-SQL Follow-up Operations workspace "
            "and its terminal zero-candidate closeout without consuming live allowances."
        ),
        "compatibility_result": (
            "official_wire_schema_and_project_acceptance_separated_"
            "prospectively"
        ),
        "goal_authority": (
            "/home/developer/coinbase/coinbase-frontend/docs/CURRENT_MVP_GOAL.md"
        ),
        "frontend_authority": "operator_ui_only",
        "live_action_path": "auditable_backend_admin_interfaces_only",
        "phase_range_policy": "parked_unless_direct_current_slice_blocker",
        "current_vertical_slice": (
            "operator_follow_up_operations_queue_and_single_live_proof"
        ),
        "direct_blocker_rule": (
            "stop_for_product_order_policy_caps_eligible_routes_or_exchange_"
            "call_limit_expansion"
        ),
        "scope_posture": "operator_follow_up_operations_queue_single_proof_v1",
        "operator_progress_wording": (
            "Follow-up Operations workspace deployed; exact post-gate candidate "
            "count 0; all live allowances remain unconsumed"
        ),
        "operator_question": "Await operator direction for the next MVP.",
        "focused_blast_radius_tests_required": True,
        "full_suite_at_durable_milestone_only": True,
        "active_work_policy": {
            "current_priority": "await_operator_direction_for_next_mvp",
            "current_action": (
                "complete_zero_candidates_all_live_allowances_unconsumed"
            ),
            "approved_phase_range_status": "historical_not_work_authority",
            "phase_range_work_allowed": False,
            "slice_status": "complete_zero_candidates",
            "blockers": [],
            "default_next_action": (
                "complete_zero_candidates_all_live_allowances_unconsumed"
            ),
            "next_action": "await_operator_direction_for_next_mvp",
            "ordered_successors": [],
            "allow_only_when_directly_blocks": [],
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
        "active_futures_slice": {
            "slice_id": "futures_exact_no_live_preview_slice_2r12",
            "recovery_id": "R12",
            "status": "complete_terminal_unknown_consumed",
            "policy": "V3",
            "product_id": "AVP-20DEC30-CDE",
            "contract_count": "1",
            "opening_reference_notional_under_usdc": "100.00",
            "exposure_and_buffered_close_under_usdc": "150.00",
            "branch_turnover_under_usdc": "300.00",
            "workflow_claims_consumed": 1,
            "claim_created": True,
            "release_gate_ready": False,
            "eligibility_evidence_status": (
                "cycle_2_exact_v3_eligible"
            ),
            "eligibility_cycles_authorized_max": 10,
            "eligibility_cycles_consumed": 2,
            "eligibility_read_categories_per_cycle_max": 6,
            "eligibility_authenticated_gets_per_cycle_max": 9,
            "futures_sweep_reads_max": 0,
            "other_coinbase_endpoint_calls_max": 0,
            "authorized_coinbase_preview_attempts_max": 1,
            "coinbase_preview_attempts_max": 1,
            "coinbase_preview_attempts_consumed": 1,
            "preview_attempt_counter_policy": (
                "conservative_consumed_not_network_reach_proof"
            ),
            "preview_network_reach": "unknown",
            "terminal_outcome": "unknown",
            "terminal_blocker": "claim_only_recovery_unknown_consumed",
            "post_claim_non_preview_coinbase_calls_max": 0,
            "bounded_read_counts_per_cycle": {
                "api_key_permissions": 1,
                "portfolio_catalog": 1,
                "product": 1,
                "best_bid_ask": 1,
                "futures_positions": 1,
                "futures_margin_collateral": 1,
            },
            "margin_collateral_read_breakdown_per_cycle": {
                "balance_summary": 1,
                "intraday_margin_setting": 1,
                "current_margin_windows": 2,
            },
            "sdk_package": "coinbase-advanced-py==1.8.4",
            "response_envelope_ordering": (
                "shallow_raw_sdk_envelope_before_recursive_plain_normalization"
            ),
            "converter_only_envelope_policy": "reject_without_invoking_converter",
            "preview_id_policy": "hash_or_withhold_before_persistence_or_readback",
            "diagnostic_policy": "fixed_value_blind_only",
            "unknown_outcome_policy": "consumes_r12_after_claim_no_retry",
            "retry_attempts_max": 0,
            "retry_attempts_consumed": 0,
            "fallback_attempts_max": 0,
            "fallback_attempts_consumed": 0,
            "redirect_attempts_max": 0,
            "redirect_attempts_consumed": 0,
            "create_attempts_max": 0,
            "cancel_attempts_max": 0,
            "close_attempts_max": 0,
            "reduce_attempts_max": 0,
            "exchange_mutation_attempts_max": 0,
            "exchange_mutation_attempts_consumed": 0,
            "orders_submitted": 0,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "successor_authority": "distinct_operator_authorization_required",
            "successor_authorized": False,
            "r13_attempt_allowed": False,
            "slice3_through_5_activation_allowed": False,
        },
        "terminal_futures_slice": {
            "slice": "2R12",
            "status": "complete_terminal_unknown_consumed",
            "product_id": "AVP-20DEC30-CDE",
            "contract_count": "1",
            "opening_reference_notional_under_usdc": "100.00",
            "exposure_and_buffered_close_under_usdc": "150.00",
            "branch_turnover_under_usdc": "300.00",
            "eligibility_cycles_consumed": 2,
            "eligibility_evidence_status": "cycle_2_exact_v3_eligible",
            "coinbase_preview_attempts_max": 1,
            "coinbase_preview_attempts_consumed": 1,
            "preview_network_reach": "unknown",
            "workflow_claims_consumed": 1,
            "claim_created": True,
            "exchange_mutation_attempts_max": 0,
            "successor_authorized": False,
            "terminal": True,
            "terminal_outcome": "unknown",
            "terminal_reason_code": "claim_only_recovery_unknown_consumed",
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "conditional_slice_3": {
                "status": "not_run_terminally_inactive",
                "exchange_mutation_attempts_max": 0,
            },
        },
        "max_fan_out_notional_usdc": "100.00",
        "default_max_orders_per_second": 5,
        "non_fill_snapshot_distance_percent": 10,
    }
    assert summary["required_stop_conditions"] == [
        "focused current-slice test fails",
        "npm run release:gate fails when required at durable milestone closeout",
        (
            "python3.13 tools/run_parallel_regression.py --workers 4 fails "
            "when required at durable milestone closeout"
        ),
        (
            "security review finds browser-trusted authority, secret "
            "exposure, or live command bypass risk"
        ),
        "queue implementation, deployment validation, or either audit fails",
        "worktree contains unrelated changes affecting files in scope",
        (
            "requested change would create frontend trading behavior or "
            "bypass backend Admin API contract"
        ),
        "zero or multiple exact local candidates permit no live read, Create, or Cancel",
        (
            "closed current-goal authority permits no continuing eligibility, "
            "reconciliation, Create, or Cancel call"
        ),
        (
            "proceeding would broaden the product, order count, policy, caps, "
            "eligible routes, or exchange-call limits"
        ),
    ]
    assert summary["required_gates"] == [
        "npm run mvp:goal:check",
        "focused backend and frontend Follow-up Operations queue validation",
        "generated OpenAPI and client contract synchronization",
        "full backend and frontend durable-milestone gates",
        "local Controlled-live deployment validation without queue Coinbase calls",
        "independent Follow-up Operations safety audit",
        "blind-contextless Follow-up Operations audit",
        "post-gate exact local materialization_review candidate count",
        "terminal zero-candidate closeout with no proof claim or live phase activity",
    ]
    assert summary["progress"] == {
        "goal_id": "operator_follow_up_operations_queue_and_single_live_proof",
        "slice_status": "complete_zero_candidates",
        "work_mode": "complete_zero_candidates_all_live_allowances_unconsumed",
        "live_coinbase_execution": "not_run",
        "blockers": [],
        "current_action": (
            "complete_zero_candidates_all_live_allowances_unconsumed"
        ),
        "next_action": "await_operator_direction_for_next_mvp",
        "operator_wording": (
            "Follow-up Operations workspace deployed; exact post-gate candidate "
            "count 0; all live allowances remain unconsumed"
        ),
    }
    assert check_results["current_goal_alignment"]["passed"] is True
    assert check_results["slice_2r12_prepared_posture"]["passed"] is True
    assert check_results["historical_queue_posture"]["passed"] is True
    assert check_results["slice_2r7_terminal_closeout"]["passed"] is True
    assert check_results["r8_r10_recovery_terminal_closeout"]["passed"] is True
    assert [
        Path(document["path"]).name
        for document in check_results["r8_r10_recovery_terminal_closeout"][
            "evidence"
        ]["documents"]
    ] == ["AGENT_MVP_REBUILD_GOAL.md", "CURRENT_MVP_GOAL.md"]
    assert check_results["post_r10_compatibility_direction_closeout"][
        "passed"
    ] is True
    assert check_results["historical_slice_2r11_terminal_posture"][
        "passed"
    ] is True
    assert check_results["github_workflows_retired"]["passed"] is True
    assert check_results["github_workflows_retired"]["evidence"][
        "execution_authority"
    ] == "local_linux_docker"


def test_current_follow_up_operations_goal_records_zero_candidate_terminal_closeout():
    summary = build_autonomous_work_queue_summary()

    assert summary["goal_id"] == (
        "operator_follow_up_operations_queue_and_single_live_proof"
    )
    assert summary["slice_status"] == "complete_zero_candidates"
    assert summary["follow_up_operations_proof"]["candidate_count"] == 0
    assert summary["follow_up_operations_proof"][
        "goal_scoped_single_candidate_proof_claim"
    ] == {
        "required_for_observed_candidate_count": False,
        "status": "not_created",
        "reason": "zero_candidates",
    }
    assert summary["follow_up_operations_proof"]["goal_authority"] == "closed"
    assert summary["follow_up_operations_proof"][
        "continuing_live_proof_authority"
    ] is False
    assert summary["follow_up_operations_proof"]["terminal_goal_seal"] == {
        "status": "source_policy_declared_durably_sealed",
        "evidence_scope": "tracked_source_policy_only",
        "installed_database_verification": "not_performed",
        "late_candidate_actionability": "blocked",
        "late_claim_behavior": "blocked_before_live_read",
        "diagnostic_code": "follow_up_live_proof_goal_terminal",
    }
    assert summary["historical_materialization_closeout"]["authority_status"] == (
        "historical_predecessor_not_current_authority"
    )
    assert summary["progress"] == {
        "goal_id": "operator_follow_up_operations_queue_and_single_live_proof",
        "slice_status": "complete_zero_candidates",
        "work_mode": "complete_zero_candidates_all_live_allowances_unconsumed",
        "live_coinbase_execution": "not_run",
        "blockers": [],
        "current_action": (
            "complete_zero_candidates_all_live_allowances_unconsumed"
        ),
        "next_action": "await_operator_direction_for_next_mvp",
        "operator_wording": (
            "Follow-up Operations workspace deployed; exact post-gate candidate "
            "count 0; all live allowances remain unconsumed"
        ),
    }


def test_follow_up_operations_zero_candidate_closeout_is_terminal_and_preserves_allowances():
    summary = build_autonomous_work_queue_summary()

    assert summary["slice_status"] == "complete_zero_candidates"
    assert summary["blockers"] == []
    assert summary["current_action"] == (
        "complete_zero_candidates_all_live_allowances_unconsumed"
    )
    assert summary["default_next_action"] == (
        "complete_zero_candidates_all_live_allowances_unconsumed"
    )
    assert summary["next_action"] == "await_operator_direction_for_next_mvp"
    assert summary["follow_up_operations_proof"] == {
        "status": "complete_zero_candidates",
        "queue_posture": "passive_local_sql_only",
        "candidate_count": 0,
        "candidate_count_status": "exact_post_gate_local_count_complete",
        "candidate_count_meaning": (
            "exact_local_materialization_review_candidates_only_never_live_eligibility"
        ),
        "live_eligibility_status": "not_run_zero_candidates",
        "queue_live_coinbase_read_calls": 0,
        "queue_coinbase_create_calls": 0,
        "queue_coinbase_cancel_calls": 0,
        "proof_allowances": {
            "eligibility_reads": "unconsumed",
            "reconciliation_reads": "unconsumed",
            "create_call": "unconsumed",
            "cancel_call": "unconsumed",
        },
        "goal_scoped_single_candidate_proof_claim": {
            "required_for_observed_candidate_count": False,
            "status": "not_created",
            "reason": "zero_candidates",
        },
        "phase_activity": {
            "eligibility_reads": "not_run",
            "reconciliation_reads": "not_run",
            "create_call": "not_run",
            "cancel_call": "not_run",
        },
        "allowances_consumed": False,
        "goal_authority": "closed",
        "continuing_live_proof_authority": False,
        "terminal_goal_seal": {
            "status": "source_policy_declared_durably_sealed",
            "evidence_scope": "tracked_source_policy_only",
            "installed_database_verification": "not_performed",
            "late_candidate_actionability": "blocked",
            "late_claim_behavior": "blocked_before_live_read",
            "diagnostic_code": "follow_up_live_proof_goal_terminal",
        },
        "controlled_live_stack_posture": "remain_available",
    }
    assert summary["progress"] == {
        "goal_id": "operator_follow_up_operations_queue_and_single_live_proof",
        "slice_status": "complete_zero_candidates",
        "work_mode": "complete_zero_candidates_all_live_allowances_unconsumed",
        "live_coinbase_execution": "not_run",
        "blockers": [],
        "current_action": (
            "complete_zero_candidates_all_live_allowances_unconsumed"
        ),
        "next_action": "await_operator_direction_for_next_mvp",
        "operator_wording": (
            "Follow-up Operations workspace deployed; exact post-gate candidate "
            "count 0; all live allowances remain unconsumed"
        ),
    }


def test_autonomous_work_queue_check_reports_terminal_r12_without_inventing_preview_network_reach():
    summary = build_autonomous_work_queue_summary()
    active_slice = summary["standing_limits"]["active_futures_slice"]

    assert summary["slice_status"] == "complete_zero_candidates"
    assert summary["blockers"] == []
    assert summary["default_next_action"] == (
        "complete_zero_candidates_all_live_allowances_unconsumed"
    )
    assert summary["next_action"] == "await_operator_direction_for_next_mvp"
    assert summary["historical_r12"]["slice_status"] == (
        "complete_terminal_unknown_consumed"
    )
    assert summary["historical_r12"]["blockers"] == [
        "claim_only_recovery_unknown_consumed"
    ]
    assert summary["r12_eligibility_cycles_consumed"] == 2
    assert summary["r12_workflow_claims_consumed"] == 1
    assert summary["r12_claim_created"] is True
    assert summary["r12_preview_attempts_consumed"] == 1
    assert summary["r12_release_gate_ready"] is False
    assert summary["live_coinbase_eligibility_reads_ran"] is False
    assert summary["live_coinbase_preview_ran"] is None
    assert summary["live_coinbase_preview_outcome"] == "unknown_consumed"
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_mutations_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["executed_notional_usdc"] == "0"

    assert active_slice["status"] == "complete_terminal_unknown_consumed"
    assert active_slice["eligibility_evidence_status"] == (
        "cycle_2_exact_v3_eligible"
    )
    assert active_slice["eligibility_cycles_consumed"] == 2
    assert active_slice["workflow_claims_consumed"] == 1
    assert active_slice["claim_created"] is True
    assert active_slice["terminal_outcome"] == "unknown"
    assert active_slice["terminal_blocker"] == (
        "claim_only_recovery_unknown_consumed"
    )
    assert active_slice["coinbase_preview_attempts_consumed"] == 1
    assert active_slice["preview_attempt_counter_policy"] == (
        "conservative_consumed_not_network_reach_proof"
    )
    assert active_slice["preview_network_reach"] == "unknown"
    assert active_slice["retry_attempts_consumed"] == 0
    assert active_slice["fallback_attempts_consumed"] == 0
    assert active_slice["redirect_attempts_consumed"] == 0
    assert active_slice["exchange_mutation_attempts_consumed"] == 0
    assert active_slice["orders_submitted"] == 0
    assert active_slice["submitted_notional_usdc"] == "0"
    assert active_slice["executed_notional_usdc"] == "0"

    assert summary["progress"] == {
        "goal_id": "operator_follow_up_operations_queue_and_single_live_proof",
        "slice_status": "complete_zero_candidates",
        "work_mode": "complete_zero_candidates_all_live_allowances_unconsumed",
        "live_coinbase_execution": "not_run",
        "blockers": [],
        "current_action": (
            "complete_zero_candidates_all_live_allowances_unconsumed"
        ),
        "next_action": "await_operator_direction_for_next_mvp",
        "operator_wording": (
            "Follow-up Operations workspace deployed; exact post-gate candidate "
            "count 0; all live allowances remain unconsumed"
        ),
    }


def test_post_r10_closeout_records_integration_invariants_and_gate_evidence():
    direction = Path(
        "docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md"
    ).read_text(encoding="utf-8")
    backend_goal = Path("genai_data/AGENT_MVP_REBUILD_GOAL.md").read_text(
        encoding="utf-8"
    )
    normalized_direction = " ".join(direction.split())
    normalized_backend_goal = " ".join(backend_goal.split())

    for text in (
        "policy-relevant optional field types",
        "before any recursive `_plain()` normalization",
        "`preview_id` must remain ephemeral and restricted, then be hashed or withheld before persistence or readback",
        "1,017 parallel and 456 serial regression cases passed",
        "604 unit/component tests and 8 Playwright scenarios passed",
        "Final independent safety and blind-contextless audits passed",
    ):
        assert text in normalized_direction
    assert "before any recursive `_plain()` normalization" in (
        normalized_backend_goal
    )
    assert "`preview_id` must remain ephemeral and restricted" in (
        normalized_backend_goal
    )


def test_operator_materialization_terminal_records_are_aligned():
    documents = {
        "goal": Path("genai_data/AGENT_MVP_REBUILD_GOAL.md").read_text(
            encoding="utf-8"
        ),
        "handoff": Path("docs/MAINTAINER_HANDOFF.md").read_text(
            encoding="utf-8"
        ),
        "roadmap": Path("docs/PUBLIC_ROADMAP.md").read_text(encoding="utf-8"),
        "admin_readme": Path("README.admin-api.md").read_text(encoding="utf-8"),
    }
    normalized = {
        name: " ".join(text.split()) for name, text in documents.items()
    }

    shared_terminal_facts = (
        "operator_authorize_and_materialize_follow_up_intent",
        "await_operator_direction_for_next_mvp",
        "no eligible filled attached intent",
        "Coinbase eligibility/reconciliation reads: `0`",
        "Coinbase Create calls: `0`",
        "Coinbase Cancel calls: `0`",
        "durable materialization attempts/claims: `0`",
        "materialized children: `0`",
        "submitted/executed notional: `0 USDC` / `0 USDC`",
        "no unknown live outcome",
        "live-proof allowances remain unconsumed",
        "Synthetic tests are not live proof",
        "backend focused: `164 passed`",
        "backend canonical full: `1102 passed, 6 skipped` parallel",
        "`457 passed, 150 skipped` serial",
        "frontend focused: `179 passed`",
        "independent safety audit: `PASS`",
        "blind-contextless audit: `PASS`",
    )
    for fact in shared_terminal_facts:
        assert fact in normalized["goal"]
        assert fact in normalized["handoff"]

    assert "Historical Completed Operator Follow-Up Materialization Goal" in (
        normalized["goal"]
    )
    assert "Status: `complete`" in normalized["handoff"]

    for name in ("roadmap", "admin_readme"):
        assert "operator_authorize_and_materialize_follow_up_intent" in normalized[name]
        assert "Status: `complete`" in normalized[name]
        assert "no eligible filled attached intent" in normalized[name]
        assert "live-proof allowances remain unconsumed" in normalized[name]
        assert "Synthetic tests are not live proof" in normalized[name]

    assert "Historical Slice 2R12 Terminal" in normalized["goal"]
    assert "Historical R12 terminal" in normalized["handoff"]
    operational_handoff = (
        "Bounded Controlled-live observation for candidate counting: the audited "
        "installed operator review stack reported runtime mode `controlled_live`, frontend "
        "`0.0.0.0:3000`, backend `127.0.0.1:8787`, and approved Test portfolio "
        "configuration without exposing its identifier."
    )
    deployment_boundary = (
        "This observation made zero Coinbase calls and does not claim final "
        "post-closeout deployment health."
    )
    zero_call_handoff = (
        "Release, startup, and status made zero Coinbase calls and consumed no "
        "live-proof allowance."
    )
    for name in ("goal", "handoff", "roadmap", "admin_readme"):
        assert operational_handoff in normalized[name]
        assert deployment_boundary in normalized[name]
        assert zero_call_handoff in normalized[name]


def test_core_workspaces_goal_is_discoverable_from_backend_entry_points():
    documents = {
        "root_readme": Path("README.md").read_text(encoding="utf-8"),
        "admin_readme": Path("README.admin-api.md").read_text(encoding="utf-8"),
        "docs_index": Path("docs/README.md").read_text(encoding="utf-8"),
        "handoff": Path("docs/MAINTAINER_HANDOFF.md").read_text(encoding="utf-8"),
        "roadmap": Path("docs/PUBLIC_ROADMAP.md").read_text(encoding="utf-8"),
        "capability_matrix": Path(
            "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md"
        ).read_text(encoding="utf-8"),
        "contract_agent": Path(
            "docs/agents/AGENT_ADMIN_API_CONTRACT.md"
        ).read_text(encoding="utf-8"),
        "genai_index": Path("genai_data/README.md").read_text(encoding="utf-8"),
        "goal": Path("genai_data/AGENT_MVP_REBUILD_GOAL.md").read_text(
            encoding="utf-8"
        ),
    }
    current_goal = "operator_core_workspaces_origin_prod_alignment_v1"
    current_action = "complete_core_operator_workspaces_origin_prod_alignment"
    default_action = "await_operator_direction_for_next_mvp"
    completion_marker = (
        "Goal `operator_core_workspaces_origin_prod_alignment_v1` is complete."
    )
    completed_scope = (
        "Portfolio, Spot Operations, Futures Operations, Orders-detail, "
        "Automation, and System Operations"
    )
    refresh_boundary = (
        "The one authorized account-reality refresh completed and is consumed "
        "and sealed; its evidence is stale for live eligibility and cannot be "
        "rerun under this goal."
    )
    no_live_proof = "No goal-scoped Create, Cancel, or live proof has run."
    optional_allowances = (
        "The optional Spot Create and exact-order Cancel allowances remain "
        "unconsumed."
    )
    historical_goal = "operator_follow_up_operations_queue_and_single_live_proof"

    for body in documents.values():
        normalized = " ".join(body.split())
        assert current_goal in normalized
        assert "Status: `complete`" in normalized
        assert completion_marker in normalized
        assert current_action in normalized
        assert default_action in normalized
        assert completed_scope in normalized
        assert refresh_boundary in normalized
        assert no_live_proof in normalized
        assert optional_allowances in normalized
        assert "Futures is source-disabled and call-free" in normalized
        assert "Automation is GET-only" in normalized
        assert "`1109 passed, 6 skipped` parallel" in normalized
        assert "`599 passed, 150 skipped` serial" in normalized
        assert "frontend full `1440 passed`" in normalized
        assert "E2E `13 passed`" in normalized
        assert "independent safety audit `PASS`" in normalized
        assert "final blind re-audit is not claimed as passed" in normalized

    for name, body in documents.items():
        if name == "capability_matrix":
            continue
        normalized = " ".join(body.split())
        assert historical_goal in normalized
        assert "complete_zero_candidates" in normalized

    assert "six installed Controlled-live mutation routes" in documents[
        "contract_agent"
    ]
    assert "sole Controlled-live command surface" not in documents[
        "contract_agent"
    ]


def test_r11_terminal_doc_records_exact_bounded_closeout_posture():
    terminal = Path("docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(terminal.split())

    for text in (
        "futures_preview_acceptance_recovery_r11",
        "r11_terminal_pre_preview_v3_operator_policy_rejection",
        "stop_and_await_operator_direction",
        "complete_terminal_no_retry",
        "coinbase-advanced-py==1.8.4",
        "AVP-20DEC30-CDE",
        "<100 / <150 / <300 USDC",
        "R11 is terminally consumed",
        "remaining_margin_validation",
        "futures_preview_margin_windows_ambiguous",
        "margin_window_type_documented_but_operator_rejected",
        "retail_intraday_margin_1",
        "Preview attempts: `0`",
        "Exchange submission attempts: `0`",
        "no retry",
        "no R12 attempt",
        "no Slice 3, Slice 4, or Slice 5 activation",
    ):
        assert text in normalized


def test_terminal_recovery_metadata_does_not_reactivate_consumed_successors():
    current_goal = Path("genai_data/AGENT_MVP_REBUILD_GOAL.md").read_text(
        encoding="utf-8"
    )
    maintainer_handoff = Path("docs/MAINTAINER_HANDOFF.md").read_text(
        encoding="utf-8"
    )

    assert "R8 is terminally consumed" in current_goal
    assert "R9 is terminally consumed" in current_goal
    assert "R10 is terminally consumed" in current_goal
    assert "R8 content/hash remain inaccessible" in current_goal
    assert "Slice 3 did not run" in current_goal
    assert "- Current slice:" not in maintainer_handoff
    assert "- Ordered successors:" not in maintainer_handoff
    assert "- Historical predecessor slice:" in maintainer_handoff
    assert "- Historical ordered successor design:" in maintainer_handoff


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
