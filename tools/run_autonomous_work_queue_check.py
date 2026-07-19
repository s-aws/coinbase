"""Validate current MVP goal alignment without reactivating historical phases."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT.parent / "coinbase-frontend"
BACKEND_GOAL_DOC = PROJECT_ROOT / "genai_data" / "AGENT_MVP_REBUILD_GOAL.md"
FRONTEND_GOAL_DOC = FRONTEND_ROOT / "docs" / "CURRENT_MVP_GOAL.md"
BACKEND_QUEUE_DOC = PROJECT_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
BACKEND_E2E_PLAN = PROJECT_ROOT / "docs" / "plans" / "ADMIN_API_E2E_PLAN.md"
POST_R10_DIRECTION_DOC = (
    PROJECT_ROOT / "docs" / "FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md"
)
R11_PREPARATION_DOC = (
    PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R11_PREPARATION.md"
)
R11_TERMINAL_DOC = (
    PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md"
)
R12_PREPARATION_DOC = (
    PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R12_PREPARATION.md"
)
FRONTEND_QUEUE_DOC = FRONTEND_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
SUMMARY_PREFIX = "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
GOAL_ID = "operator_follow_up_operations_queue_and_single_live_proof"
CURRENT_ALIGNMENT_TOKEN = "operator_follow_up_operations_queue_single_proof_v1"
CURRENT_ACTION = "complete_zero_candidates_all_live_allowances_unconsumed"
CURRENT_WORK_MODE = CURRENT_ACTION
NEXT_ACTION = "await_operator_direction_for_next_mvp"
HISTORICAL_R12_GOAL_ID = "futures_preview_acceptance_recovery_r12"
HISTORICAL_R11_GOAL_ID = "futures_preview_acceptance_recovery_r11"
HISTORICAL_POST_R10_GOAL_ID = (
    "futures_post_r10_preview_compatibility_and_direction_selection"
)
HISTORICAL_R8_R10_GOAL_ID = (
    "futures_preview_acceptance_recovery_r8_r10_and_"
    "conditional_terminal_roundtrip_slice_3"
)
HISTORICAL_PHASE_RANGE = "7961-7980"
HISTORICAL_PHASES = tuple(range(7961, 7981))
PHASE_RANGE_STATUS = "historical_not_work_authority"
POST_R10_COMPLETION_ALIGNMENT_TOKEN = (
    "official_wire_schema_and_project_acceptance_separated_prospectively"
)
R12_ALIGNMENT_TOKEN = (
    "r12_separate_eligibility_and_single_use_attempt_v1"
)
HISTORICAL_R11_ALIGNMENT_TOKEN = (
    "r11_terminal_pre_preview_v3_operator_policy_rejection"
)
CLOSED_LOOPHOLE_RULE = (
    "A candidate blocker cannot make itself in scope by generating evidence "
    "about the candidate blocker."
)
SLICE_STATUS = "complete_zero_candidates"
SLICE_BLOCKERS: tuple[str, ...] = ()
HISTORICAL_R12_SLICE_STATUS = "complete_terminal_unknown_consumed"
HISTORICAL_R12_SLICE_BLOCKERS: tuple[str, ...] = (
    "claim_only_recovery_unknown_consumed",
)
DEFAULT_NEXT_ACTION = CURRENT_ACTION
HISTORICAL_R12_SUCCESSOR_ACTION = (
    "await_operator_authorization_for_operator_attach_single_follow_up_intent"
)
OPERATOR_QUESTION = "Await operator direction for the next MVP."
OPERATOR_PROGRESS_WORDING = (
    "Follow-up Operations workspace deployed; exact post-gate candidate count 0; "
    "all live allowances remain unconsumed"
)
HISTORICAL_R11_STATUS = "complete_terminal_no_retry"
HISTORICAL_R11_NEXT_ACTION = "stop_and_await_operator_direction"
SUCCESSOR_MAPPING_INVARIANT = (
    "A future successor must pass the raw SDK envelope to the shallow "
    "validator before any recursive `_plain()` normalization."
)
PREVIEW_ID_INVARIANT = (
    "`preview_id` must remain ephemeral and restricted, then be hashed or "
    "withheld before persistence or readback."
)
R7_TERMINAL_BLOCKER = "slice_2r7_consumed_without_accepted_preview_evidence"
R7_TERMINAL_NEXT_ACTION = (
    "await_operator_scope_change_decision_after_slice_2r7_closeout"
)
R7_TERMINAL_DIAGNOSTIC = (
    "sdk_returned__post_preview_value_error__before_acceptance"
)
MVP_SCOPE = {
    "work_mode": CURRENT_WORK_MODE,
    "product_goal": (
        "Record the deployed passive local-SQL Follow-up Operations workspace "
        "and its terminal zero-candidate closeout without consuming live allowances."
    ),
    "compatibility_result": POST_R10_COMPLETION_ALIGNMENT_TOKEN,
    "goal_authority": str(FRONTEND_GOAL_DOC),
    "frontend_authority": "operator_ui_only",
    "live_action_path": "auditable_backend_admin_interfaces_only",
    "phase_range_policy": "parked_unless_direct_current_slice_blocker",
    "current_vertical_slice": GOAL_ID,
    "direct_blocker_rule": (
        "stop_for_product_order_policy_caps_eligible_routes_or_exchange_"
        "call_limit_expansion"
    ),
    "scope_posture": CURRENT_ALIGNMENT_TOKEN,
    "operator_progress_wording": OPERATOR_PROGRESS_WORDING,
    "operator_question": OPERATOR_QUESTION,
    "focused_blast_radius_tests_required": True,
    "full_suite_at_durable_milestone_only": True,
    "active_work_policy": {
        "current_priority": NEXT_ACTION,
        "current_action": CURRENT_ACTION,
        "approved_phase_range_status": PHASE_RANGE_STATUS,
        "phase_range_work_allowed": False,
        "slice_status": SLICE_STATUS,
        "blockers": list(SLICE_BLOCKERS),
        "default_next_action": DEFAULT_NEXT_ACTION,
        "next_action": NEXT_ACTION,
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
FOLLOW_UP_OPERATIONS_PROOF = {
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
    "controlled_live_stack_posture": "remain_available",
}
HISTORICAL_MATERIALIZATION_CLOSEOUT = {
    "authority_status": "historical_predecessor_not_current_authority",
    "status": "complete",
    "eligible_candidate_count": 0,
    "durable_attempts_claims": 0,
    "materialized_children": 0,
    "coinbase_eligibility_reads": 0,
    "coinbase_reconciliation_reads": 0,
    "coinbase_create_calls": 0,
    "coinbase_cancel_calls": 0,
    "unknown_live_outcome": False,
    "live_proof_allowances_consumed": False,
    "synthetic_validation_is_live_proof": False,
}
STANDING_LIMITS = {
    "preferred_spot_notional_under_usdc": "10.00",
    "preferred_perpetual_notional_under_usdc": "30.00",
    "active_futures_slice": {
        "slice_id": "futures_exact_no_live_preview_slice_2r12",
        "recovery_id": "R12",
        "status": HISTORICAL_R12_SLICE_STATUS,
        "policy": "V3",
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "opening_reference_notional_under_usdc": "100.00",
        "exposure_and_buffered_close_under_usdc": "150.00",
        "branch_turnover_under_usdc": "300.00",
        "workflow_claims_consumed": 1,
        "claim_created": True,
        "release_gate_ready": False,
        "eligibility_evidence_status": "cycle_2_exact_v3_eligible",
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
        "status": HISTORICAL_R12_SLICE_STATUS,
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
REQUIRED_STOP_CONDITIONS = [
    "focused current-slice test fails",
    "npm run release:gate fails when required at durable milestone closeout",
    (
        "python3.13 tools/run_parallel_regression.py --workers 4 fails when "
        "required at durable milestone closeout"
    ),
    (
        "security review finds browser-trusted authority, secret exposure, "
        "or live command bypass risk"
    ),
    "queue implementation, deployment validation, or either audit fails",
    "worktree contains unrelated changes affecting files in scope",
    (
        "requested change would create frontend trading behavior or bypass "
        "backend Admin API contract"
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
REQUIRED_GATES = [
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


@dataclass(frozen=True)
class QueueCheck:
    """One goal-alignment validation result."""

    name: str
    passed: bool
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence": self.evidence,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate current MVP goal and historical queue posture.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the machine-readable summary line.",
    )
    return parser


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _contains_all(path: Path, required: Sequence[str]) -> QueueCheck:
    body = " ".join(_read(path).split())
    missing = [
        text
        for text in required
        if " ".join(text.split()) not in body
    ]
    return QueueCheck(
        name=path.name,
        passed=path.exists() and not missing,
        evidence={"path": str(path), "missing": missing},
    )


def _current_goal_alignment() -> QueueCheck:
    backend = _contains_all(
        BACKEND_GOAL_DOC,
        (
            GOAL_ID,
            CURRENT_ALIGNMENT_TOKEN,
            "Status: `complete_zero_candidates`",
            DEFAULT_NEXT_ACTION,
            NEXT_ACTION,
            CURRENT_WORK_MODE,
            OPERATOR_PROGRESS_WORDING,
            "passive local SQL",
            "never live eligibility",
            "exact post-gate local `materialization_review` candidate count",
            "goal-scoped single-candidate proof claim",
            "not created and was not required",
            "all live allowances remain unconsumed",
            "goal authority is closed",
            "Eligibility, reconciliation, Create, and Cancel did not run",
            "Controlled-live",
            "remain available",
            "operator_authorize_and_materialize_follow_up_intent",
            "historical predecessor",
            HISTORICAL_R12_GOAL_ID,
            R12_ALIGNMENT_TOKEN,
            CLOSED_LOOPHOLE_RULE,
            SUCCESSOR_MAPPING_INVARIANT,
            PREVIEW_ID_INVARIANT,
            HISTORICAL_R12_SLICE_STATUS,
            "R12_RELEASE_READY=False",
            "Eligibility cycle 2",
            "exact_v3_eligible",
            "claim_only_recovery_unknown_consumed",
            "generic Preview-attempt counter is conservative",
            "does not prove network reach",
            "offline claim recovery",
            "no client or factory",
            "no further Coinbase call",
            "operator_attach_single_follow_up_intent",
            "R13 attempt",
            "Slice 3, Slice 4, or Slice 5 activation",
            "Use focused tests",
        ),
    )
    frontend = _contains_all(
        FRONTEND_GOAL_DOC,
        (
            GOAL_ID,
            CURRENT_ALIGNMENT_TOKEN,
            "Status: `complete_zero_candidates`",
            DEFAULT_NEXT_ACTION,
            NEXT_ACTION,
            OPERATOR_PROGRESS_WORDING,
            "passive local SQL",
            "never live eligibility",
            "exact local `materialization_review` candidates only",
            "goal-scoped single-candidate proof claim",
            "all live allowances remain unconsumed",
            "operator_authorize_and_materialize_follow_up_intent",
            "historical predecessor",
            HISTORICAL_R12_GOAL_ID,
            CLOSED_LOOPHOLE_RULE,
            SUCCESSOR_MAPPING_INVARIANT,
            PREVIEW_ID_INVARIANT,
            R12_ALIGNMENT_TOKEN,
            HISTORICAL_R12_SLICE_STATUS,
            "R12_RELEASE_READY = False",
            "eligibility cycle 2",
            "exact_v3_eligible",
            "claim_only_recovery_unknown_consumed",
            "generic Preview-attempt counter is conservative",
            "does not prove network reach",
            "operator_attach_single_follow_up_intent",
            "R13 attempt",
            "Focused tests are the default",
        ),
    )
    return QueueCheck(
        name="current_goal_alignment",
        passed=backend.passed and frontend.passed,
        evidence={"backend": backend.evidence, "frontend": frontend.evidence},
    )


def _slice_2r12_prepared_posture() -> QueueCheck:
    preparation = _contains_all(
        R12_PREPARATION_DOC,
        (
            HISTORICAL_R12_GOAL_ID,
            R12_ALIGNMENT_TOKEN,
            HISTORICAL_R12_SUCCESSOR_ACTION,
            HISTORICAL_R12_SLICE_STATUS,
            "R12_RELEASE_READY",
            "at most ten durably counted cycles",
            "eligibility cycle 2",
            "exact_v3_eligible",
            "six categories at most once",
            "exactly nine GETs",
            "INTRADAY_MARGIN_SETTING_INTRADAY",
            "AVP-20DEC30-CDE",
            "<100 USDC",
            "<150 USDC",
            "<300 USDC",
            "coinbase-advanced-py==1.8.4",
            "Preview calls after claim: at most one",
            "consumes R12 and cannot be retried",
            "post-claim Coinbase reads: zero",
            "tests/unit/test_admin_api_futures_order_preview_r12_concurrency.py",
            "tests/unit/test_admin_api_futures_order_preview_r12_persistence.py",
            "tests/unit/FuturesOrderPreviewR12Readback.test.tsx",
            "claim_only_recovery_unknown_consumed",
            "generic Preview-attempt counter is conservative",
            "does not prove network reach",
            "offline claim recovery",
            "no client or factory",
            "No further Coinbase call",
            "operator_attach_single_follow_up_intent",
            "R13 attempt",
            "Slice 3, Slice 4, or Slice 5 activation",
        ),
    )
    backend = _contains_all(
        BACKEND_GOAL_DOC,
        (
            HISTORICAL_R12_GOAL_ID,
            R12_ALIGNMENT_TOKEN,
            HISTORICAL_R12_SLICE_STATUS,
            HISTORICAL_R12_SUCCESSOR_ACTION,
            "R12_RELEASE_READY=False",
            "Eligibility cycle 2",
            "exact_v3_eligible",
            "claim_only_recovery_unknown_consumed",
            "does not prove network reach",
            "operator_attach_single_follow_up_intent",
            "R13 attempt",
        ),
    )
    frontend = _contains_all(
        FRONTEND_GOAL_DOC,
        (
            HISTORICAL_R12_GOAL_ID,
            R12_ALIGNMENT_TOKEN,
            HISTORICAL_R12_SLICE_STATUS,
            HISTORICAL_R12_SUCCESSOR_ACTION,
            "R12_RELEASE_READY = False",
            "eligibility cycle 2",
            "exact_v3_eligible",
            "claim_only_recovery_unknown_consumed",
            "does not prove network reach",
            "operator_attach_single_follow_up_intent",
            "R13 attempt",
        ),
    )
    return QueueCheck(
        name="slice_2r12_prepared_posture",
        passed=preparation.passed and backend.passed and frontend.passed,
        evidence={
            "preparation": preparation.evidence,
            "backend": backend.evidence,
            "frontend": frontend.evidence,
        },
    )


def _historical_queue_posture() -> QueueCheck:
    required = (
        "Historical planning record; not current work authority.",
        HISTORICAL_PHASE_RANGE,
    )
    documents = [
        _contains_all(BACKEND_QUEUE_DOC, required),
        _contains_all(BACKEND_E2E_PLAN, required),
        _contains_all(FRONTEND_QUEUE_DOC, required),
    ]
    return QueueCheck(
        name="historical_queue_posture",
        passed=all(document.passed for document in documents),
        evidence={"documents": [document.evidence for document in documents]},
    )


def _slice_2r7_terminal_closeout() -> QueueCheck:
    required = (
        R7_TERMINAL_BLOCKER,
        R7_TERMINAL_NEXT_ACTION,
        R7_TERMINAL_DIAGNOSTIC,
        "not_persisted_and_unrecoverable",
    )
    documents = [
        _contains_all(BACKEND_GOAL_DOC, required),
        _contains_all(
            PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R7_PREPARATION.md",
            required,
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R7_TERMINAL_DIAGNOSIS.md",
            required,
        ),
    ]
    return QueueCheck(
        name="slice_2r7_terminal_closeout",
        passed=all(document.passed for document in documents),
        evidence={"documents": [document.evidence for document in documents]},
    )


def _r8_r10_recovery_terminal_closeout() -> QueueCheck:
    required = (
        "R8 is terminally consumed",
        "R9 is terminally consumed",
        "R10 is terminally consumed",
        "Slice 3 did not run",
    )
    documents = [
        _contains_all(
            BACKEND_GOAL_DOC,
            (
                *required,
                HISTORICAL_R8_R10_GOAL_ID,
                "R8 content/hash remain inaccessible",
            ),
        ),
        _contains_all(
            FRONTEND_GOAL_DOC,
            (
                *required,
                "R8 content and hash remain inaccessible",
            ),
        ),
    ]
    return QueueCheck(
        name="r8_r10_recovery_terminal_closeout",
        passed=all(document.passed for document in documents),
        evidence={"documents": [document.evidence for document in documents]},
    )


def _post_r10_compatibility_direction_closeout() -> QueueCheck:
    historical_next_action = (
        "await_operator_decision_on_one_post_r10_successor_or_official_clarification"
    )
    historical_record_required = (
        HISTORICAL_POST_R10_GOAL_ID,
        POST_R10_COMPLETION_ALIGNMENT_TOKEN,
        historical_next_action,
    )
    direction = _contains_all(
        POST_R10_DIRECTION_DOC,
        (
            *historical_record_required,
            "No R11 exists",
            "https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders",
            "https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/advanced-trade-spec.yaml",
            "7115b6b13132565a0a65371aadc9a0e09c725860ae5119655d8cd4d8c226a6b7",
            "2026-07-16",
            "coinbase-advanced-py 1.8.4",
            SUCCESSOR_MAPPING_INVARIANT,
            PREVIEW_ID_INVARIANT,
            "Final independent safety and blind-contextless audits passed",
            "Ten future attempts are not warranted",
        ),
    )
    backend = _contains_all(BACKEND_GOAL_DOC, historical_record_required)
    frontend = _contains_all(
        FRONTEND_GOAL_DOC,
        (
            POST_R10_COMPLETION_ALIGNMENT_TOKEN,
            historical_next_action,
        ),
    )
    return QueueCheck(
        name="post_r10_compatibility_direction_closeout",
        passed=direction.passed and backend.passed and frontend.passed,
        evidence={
            "direction": direction.evidence,
            "backend": backend.evidence,
            "frontend": frontend.evidence,
        },
    )


def _historical_slice_2r11_terminal_posture() -> QueueCheck:
    historical_preparation_required = (
        HISTORICAL_R11_GOAL_ID,
        "coinbase-advanced-py==1.8.4",
        "raw SDK envelope before any recursive `_plain()` normalization",
        "converter-only envelopes",
        "hashed or withheld",
        "fixed value-blind diagnostics",
        "AVP-20DEC30-CDE",
        "<100 / <150 / <300 USDC",
        "Historical Readiness And Audit Gate",
        "R11 remained absent and unconsumed",
    )
    terminal_required = (
        HISTORICAL_R11_GOAL_ID,
        HISTORICAL_R11_ALIGNMENT_TOKEN,
        HISTORICAL_R11_NEXT_ACTION,
        HISTORICAL_R11_STATUS,
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
    )
    preparation = _contains_all(
        R11_PREPARATION_DOC,
        historical_preparation_required,
    )
    terminal = _contains_all(R11_TERMINAL_DOC, terminal_required)
    backend = _contains_all(
        BACKEND_GOAL_DOC,
        (
            HISTORICAL_R11_ALIGNMENT_TOKEN,
            HISTORICAL_R11_NEXT_ACTION,
            "R11 is consumed",
            "remaining_margin_validation",
            "futures_preview_margin_windows_ambiguous",
            "margin_window_type_documented_but_operator_rejected",
            "no second R11 call",
            "R12 is governed by the completed terminal",
            (
                "independent successor authority, Slice 3, Slice 4, or "
                "Slice 5 activation"
            ),
        ),
    )
    frontend = _contains_all(
        FRONTEND_GOAL_DOC,
        (
            "Historical Terminal R11 Predecessor",
            "R11 is consumed",
            "remaining_margin_validation",
            "futures_preview_margin_windows_ambiguous",
            "later R12 authorization does not reinterpret, retry, or reopen R11",
        ),
    )
    return QueueCheck(
        name="historical_slice_2r11_terminal_posture",
        passed=(
            preparation.passed
            and terminal.passed
            and backend.passed
            and frontend.passed
        ),
        evidence={
            "historical_preparation": preparation.evidence,
            "terminal": terminal.evidence,
            "backend": backend.evidence,
            "frontend": frontend.evidence,
        },
    )


def _entry_point_alignment() -> QueueCheck:
    documents = [
        _contains_all(
            PROJECT_ROOT / "README.admin-api.md",
            (
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                "Current Status",
                "Historical predecessor goal",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "README.md",
            (
                HISTORICAL_R12_GOAL_ID,
                HISTORICAL_POST_R10_GOAL_ID,
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                "Current MVP Goal",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "README.md",
            (
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                HISTORICAL_R12_GOAL_ID,
                HISTORICAL_POST_R10_GOAL_ID,
                "Current MVP Goal",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "MAINTAINER_HANDOFF.md",
            (
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                HISTORICAL_R12_GOAL_ID,
                HISTORICAL_POST_R10_GOAL_ID,
                "Current Handoff State",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "PUBLIC_ROADMAP.md",
            (
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                "Historical predecessor goal",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "agents" / "AGENT_ADMIN_API_CONTRACT.md",
            (
                GOAL_ID,
                DEFAULT_NEXT_ACTION,
                NEXT_ACTION,
                "complete_zero_candidates",
                "four installed Controlled-live mutation routes",
                "current post-lease service decision",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "genai_data" / "README.md",
            (
                HISTORICAL_R12_GOAL_ID,
                HISTORICAL_POST_R10_GOAL_ID,
                "Current work authority",
            ),
        ),
    ]
    return QueueCheck(
        name="entry_point_alignment",
        passed=all(document.passed for document in documents),
        evidence={"documents": [document.evidence for document in documents]},
    )


def _previous_version_sources() -> QueueCheck:
    return QueueCheck(
        name="previous_version_sources",
        passed=_contains_all(
            BACKEND_GOAL_DOC,
            (
                "origin/prod",
                "configuration.py::get_futures_positions",
                "core/order_engine.py::refresh_positions_if_needed",
                "core/order_engine.py::process_user_snapshot",
            ),
        ).passed,
        evidence={"path": str(BACKEND_GOAL_DOC)},
    )


def _github_workflows_retired() -> QueueCheck:
    workflow_paths = [
        PROJECT_ROOT / ".github" / "workflows" / "quality.yml",
        PROJECT_ROOT / ".github" / "workflows" / "public-agent-checks.yml",
        FRONTEND_ROOT / ".github" / "workflows" / "quality.yml",
        FRONTEND_ROOT / ".github" / "workflows" / "deploy.yml",
    ]
    present = [str(path) for path in workflow_paths if path.exists()]
    return QueueCheck(
        name="github_workflows_retired",
        passed=not present,
        evidence={
            "unexpected_present_paths": present,
            "execution_authority": "local_linux_docker",
        },
    )


def build_autonomous_work_queue_summary() -> dict[str, Any]:
    """Return current-goal compatibility evidence without selecting new work."""

    checks = [
        _current_goal_alignment(),
        _slice_2r12_prepared_posture(),
        _historical_queue_posture(),
        _slice_2r7_terminal_closeout(),
        _r8_r10_recovery_terminal_closeout(),
        _post_r10_compatibility_direction_closeout(),
        _historical_slice_2r11_terminal_posture(),
        _entry_point_alignment(),
        _previous_version_sources(),
        _github_workflows_retired(),
    ]
    passed = all(check.passed for check in checks)
    return {
        "status": "passed" if passed else "blocked",
        "goal_id": GOAL_ID,
        "historical_phase_range": HISTORICAL_PHASE_RANGE,
        "historical_phase_count": len(HISTORICAL_PHASES),
        "phase_range_status": PHASE_RANGE_STATUS,
        "slice_status": SLICE_STATUS,
        "blockers": list(SLICE_BLOCKERS),
        "current_action": CURRENT_ACTION,
        "default_next_action": DEFAULT_NEXT_ACTION,
        "next_action": NEXT_ACTION,
        "mvp_scope": MVP_SCOPE,
        "standing_limits": STANDING_LIMITS,
        "r12_workflow_claims_consumed": 1,
        "r12_claim_created": True,
        "r12_eligibility_cycles_consumed": 2,
        "r12_preview_attempts_consumed": 1,
        "r12_release_gate_ready": False,
        "follow_up_operations_proof": FOLLOW_UP_OPERATIONS_PROOF,
        "historical_materialization_closeout": HISTORICAL_MATERIALIZATION_CLOSEOUT,
        "live_coinbase_eligibility_reads_ran": False,
        "live_coinbase_preview_ran": None,
        "live_coinbase_preview_outcome": "unknown_consumed",
        "live_coinbase_orders_ran": False,
        "live_coinbase_mutations_ran": False,
        "live_order_notional_usdc": "0",
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "historical_r12": {
            "goal_id": HISTORICAL_R12_GOAL_ID,
            "alignment_token": R12_ALIGNMENT_TOKEN,
            "slice_status": HISTORICAL_R12_SLICE_STATUS,
            "blockers": list(HISTORICAL_R12_SLICE_BLOCKERS),
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
        },
        "historical_r11": {
            "status": HISTORICAL_R11_STATUS,
            "workflow_claims_consumed": 1,
            "preview_attempts_consumed": 0,
            "terminal": True,
            "terminal_before_preview": True,
            "historical_successor_authorized": False,
        },
        "required_stop_conditions": REQUIRED_STOP_CONDITIONS,
        "required_gates": REQUIRED_GATES,
        "progress": {
            "goal_id": GOAL_ID,
            "slice_status": SLICE_STATUS,
            "work_mode": MVP_SCOPE["work_mode"],
            "live_coinbase_execution": "not_run",
            "blockers": list(SLICE_BLOCKERS),
            "current_action": CURRENT_ACTION,
            "next_action": NEXT_ACTION,
            "operator_wording": OPERATOR_PROGRESS_WORDING,
        },
        "checks": [check.to_dict() for check in checks],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_autonomous_work_queue_summary()
    if not args.summary_only:
        print("MVP goal compatibility check complete")
        print(f"Goal: {GOAL_ID}")
        print(
            f"Historical phases: {HISTORICAL_PHASE_RANGE} "
            "(not work authority)"
        )
        print(
            f"Slice status: {SLICE_STATUS}; blockers: "
            f"{list(SLICE_BLOCKERS)}"
        )
        print(f"Current/default action: {DEFAULT_NEXT_ACTION}")
        print(f"Next action: {NEXT_ACTION}")
        print(
            "Follow-up Operations: passive local SQL; exact post-gate candidate "
            "count 0; proof claim not created or required; goal authority closed; "
            "allowances unconsumed"
        )
        print("Historical materialization predecessor: complete; live calls 0")
        print(
            "R12: terminal unknown-consumed/release disabled; eligibility "
            "cycles 2; workflow claims 1; conservative Preview-attempt "
            "counter 1; network reach unknown"
        )
        print(
            "Historical R11: terminal before Preview; workflow claim "
            "consumed; Preview calls 0"
        )
        print(
            "Live Coinbase Preview reach: unknown; order execution: not run; "
            "submitted/executed notional $0"
        )
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
