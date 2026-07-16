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
FRONTEND_QUEUE_DOC = FRONTEND_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
SUMMARY_PREFIX = "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
GOAL_ID = (
    "futures_preview_acceptance_recovery_r8_r10_and_"
    "conditional_terminal_roundtrip_slice_3"
)
HISTORICAL_PHASE_RANGE = "7961-7980"
HISTORICAL_PHASES = tuple(range(7961, 7981))
PHASE_RANGE_STATUS = "historical_not_work_authority"
CURRENT_SLICE = (
    "Default-profile Futures readback -> exact AVAX US CFM Coinbase Preview "
    "Order -> immutable operator-visible no-live preview readback"
)
CLOSED_LOOPHOLE_RULE = (
    "A candidate blocker cannot make itself in scope by generating evidence "
    "about the candidate blocker."
)
SLICE_STATUS = "complete"
SLICE_BLOCKERS: tuple[str, ...] = (
    "r10_consumed_without_accepted_preview_evidence",
    "slice3_not_run_no_accepted_preview",
)
DEFAULT_NEXT_ACTION = "await_operator_selection_of_separately_authorized_next_goal"
R7_TERMINAL_BLOCKER = "slice_2r7_consumed_without_accepted_preview_evidence"
R7_TERMINAL_NEXT_ACTION = (
    "await_operator_scope_change_decision_after_slice_2r7_closeout"
)
R7_TERMINAL_DIAGNOSTIC = (
    "sdk_returned__post_preview_value_error__before_acceptance"
)
MVP_SCOPE = {
    "work_mode": "terminal_awaiting_operator_selection",
    "goal_authority": str(FRONTEND_GOAL_DOC),
    "frontend_authority": "operator_ui_only",
    "live_action_path": "auditable_backend_admin_interfaces_only",
    "phase_range_policy": "parked_unless_direct_current_slice_blocker",
    "current_vertical_slice": None,
    "direct_blocker_rule": "no_current_slice_no_implicit_work_authority",
    "scope_posture": "completed_terminal_no_work_authority",
    "focused_blast_radius_tests_required": True,
    "full_suite_at_durable_milestone_only": True,
    "active_work_policy": {
        "current_priority": DEFAULT_NEXT_ACTION,
        "approved_phase_range_status": PHASE_RANGE_STATUS,
        "phase_range_work_allowed": False,
        "slice_status": SLICE_STATUS,
        "blockers": list(SLICE_BLOCKERS),
        "default_next_action": DEFAULT_NEXT_ACTION,
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
STANDING_LIMITS = {
    "preferred_spot_notional_under_usdc": "10.00",
    "preferred_perpetual_notional_under_usdc": "30.00",
    "active_futures_slice": None,
    "terminal_futures_slice": {
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "opening_reference_notional_under_usdc": "100.00",
        "exposure_and_buffered_close_under_usdc": "150.00",
        "branch_turnover_under_usdc": "300.00",
        "coinbase_preview_attempts_max": 0,
        "authorized_recovery_preview_attempts_max": 0,
        "exchange_mutation_attempts_max": 0,
        "conditional_slice_3": {
            "status": "not_run_terminally_inactive",
            "exchange_mutation_attempts_max": 0,
        },
    },
    "max_fan_out_notional_usdc": "100.00",
    "default_max_orders_per_second": 5,
    "non_fill_snapshot_distance_percent": 10,
}


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
    body = _read(path)
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name=path.name,
        passed=path.exists() and not missing,
        evidence={"path": str(path), "missing": missing},
    )


def _current_goal_alignment() -> QueueCheck:
    backend = _contains_all(
        BACKEND_GOAL_DOC,
        (GOAL_ID, CURRENT_SLICE, CLOSED_LOOPHOLE_RULE, "Use focused tests"),
    )
    frontend = _contains_all(
        FRONTEND_GOAL_DOC,
        (GOAL_ID, CURRENT_SLICE, CLOSED_LOOPHOLE_RULE, "Focused tests are the default"),
    )
    return QueueCheck(
        name="current_goal_alignment",
        passed=backend.passed and frontend.passed,
        evidence={"backend": backend.evidence, "frontend": frontend.evidence},
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
        GOAL_ID,
        DEFAULT_NEXT_ACTION,
        "R8 is terminally consumed",
        "R9 is terminally consumed",
        "R10 is terminally consumed",
        "no R11 exists",
        "Slice 3 did not run",
    )
    documents = [
        _contains_all(BACKEND_GOAL_DOC, required),
        _contains_all(FRONTEND_GOAL_DOC, required),
        _contains_all(
            PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R8_TERMINAL_DIAGNOSIS.md",
            (
                "b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696",
                "Preview attempts: `0`",
                "R9 is the current conditional generation",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R9_TERMINAL_DIAGNOSIS.md",
            (
                "5c7dd3f27605b623edc910a87dcc4b6c9ea6621aa9ee63dbfcc4b2994990dacf",
                "2fd73aa0059da49dfe6c836f6dea29b12158fb3dfbe8abdd6d8f4f0f7d702464",
                "Preview attempts: `1`",
                "R10 remains preparation-only",
                "no R11 is authorized",
            ),
        ),
        _contains_all(
            PROJECT_ROOT / "docs" / "FUTURES_SLICE_2R10_TERMINAL_DIAGNOSIS.md",
            (
                "5dd010a706c61e78454caeec478e05cafb1a50761e9e5a9a3d485051c4efee64",
                "5121e980ec9da81f44d9a3b14b9bbcaa7bdaf41c99189cd9234cedc08d652005",
                "futures_preview_response_economics_invalid",
                "Preview: `1`",
                "Slice 3 was",
                "no R11 authority exists",
            ),
        ),
    ]
    return QueueCheck(
        name="r8_r10_recovery_terminal_closeout",
        passed=all(document.passed for document in documents),
        evidence={"documents": [document.evidence for document in documents]},
    )


def _entry_point_alignment() -> QueueCheck:
    documents = [
        _contains_all(PROJECT_ROOT / "README.md", (GOAL_ID, "Current MVP Goal")),
        _contains_all(PROJECT_ROOT / "docs" / "README.md", (GOAL_ID, "Current MVP Goal")),
        _contains_all(
            PROJECT_ROOT / "docs" / "MAINTAINER_HANDOFF.md",
            (GOAL_ID, "Current Handoff State"),
        ),
        _contains_all(
            PROJECT_ROOT / "genai_data" / "README.md",
            (GOAL_ID, "Current work authority"),
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
        _historical_queue_posture(),
        _slice_2r7_terminal_closeout(),
        _r8_r10_recovery_terminal_closeout(),
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
        "default_next_action": DEFAULT_NEXT_ACTION,
        "mvp_scope": MVP_SCOPE,
        "standing_limits": STANDING_LIMITS,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
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
        print(f"Default next action: {DEFAULT_NEXT_ACTION}")
        print("Validation: focused local Linux Docker blast-radius tests")
        print("Live Coinbase execution: not run; notional $0")
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
