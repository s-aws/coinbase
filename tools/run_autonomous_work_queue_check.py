"""Validate the durable autonomous work queue contract."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE_DOC = PROJECT_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
SUMMARY_PREFIX = "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
APPROVED_PHASES = tuple(range(501, 521))
MAX_SUBMITTED_NOTIONAL_USDC = "3.10"
MAX_EXECUTED_NOTIONAL_USDC = "1.00"


@dataclass(frozen=True)
class QueueCheck:
    """One autonomous queue validation result."""

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
        description="Validate the approved unattended work queue contract.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the machine-readable summary line.",
    )
    return parser


def build_autonomous_work_queue_summary() -> dict[str, Any]:
    """Return no-live validation evidence for the autonomous work queue."""

    body = QUEUE_DOC.read_text(encoding="utf-8") if QUEUE_DOC.exists() else ""
    checks = [
        _check_doc_exists(body),
        _check_phase_range(body),
        _check_live_caps(body),
        _check_stop_conditions(body),
        _check_required_gates(body),
    ]
    passed = all(check.passed for check in checks)
    return {
        "status": "passed" if passed else "blocked",
        "approved_phase_range": "501-520",
        "approved_phase_count": len(APPROVED_PHASES),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "max_submitted_notional_usdc": MAX_SUBMITTED_NOTIONAL_USDC,
        "max_executed_notional_usdc": MAX_EXECUTED_NOTIONAL_USDC,
        "checks": [check.to_dict() for check in checks],
    }


def _check_doc_exists(body: str) -> QueueCheck:
    return QueueCheck(
        name="queue_doc_exists",
        passed=QUEUE_DOC.exists() and bool(body.strip()),
        evidence={"path": str(QUEUE_DOC.relative_to(PROJECT_ROOT))},
    )


def _check_phase_range(body: str) -> QueueCheck:
    missing = [
        phase
        for phase in APPROVED_PHASES
        if f"Phase {phase} -" not in body
    ]
    return QueueCheck(
        name="approved_phase_range_501_520",
        passed="Approved phase range: **501-520**" in body and not missing,
        evidence={
            "expected_first_phase": APPROVED_PHASES[0],
            "expected_last_phase": APPROVED_PHASES[-1],
            "missing_phase_headings": missing,
        },
    )


def _check_live_caps(body: str) -> QueueCheck:
    required = [
        "Default: no live Coinbase execution.",
        f"Maximum total submitted notional: `{MAX_SUBMITTED_NOTIONAL_USDC}` USDC.",
        f"Maximum total executed notional: `{MAX_EXECUTED_NOTIONAL_USDC}` USDC.",
        "cheapest Coinbase `USDC` spot product available to US",
        "Reconciliation gate must pass",
        "Frontend release, deployment, artifact, and smoke gates remain no-live",
    ]
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name="live_cap_policy",
        passed=not missing,
        evidence={
            "max_submitted_notional_usdc": MAX_SUBMITTED_NOTIONAL_USDC,
            "max_executed_notional_usdc": MAX_EXECUTED_NOTIONAL_USDC,
            "missing_evidence_text": missing,
        },
    )


def _check_stop_conditions(body: str) -> QueueCheck:
    required = [
        "pytest tests\\regression\\ -v --tb=short",
        "npm run release:gate",
        "blind/contextless review",
        "Live Coinbase reconciliation fails",
        "parallel implementation",
    ]
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name="stop_conditions",
        passed=not missing,
        evidence={"missing_stop_condition_text": missing},
    )


def _check_required_gates(body: str) -> QueueCheck:
    required = [
        "python tools\\run_autonomous_work_queue_check.py --summary-only",
        "pytest tests\\regression\\ -v --tb=short",
        "python3 -m pytest tests/regression/ -v",
        "npm run release:gate",
    ]
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name="required_final_gates",
        passed=not missing,
        evidence={"missing_gate_text": missing},
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_autonomous_work_queue_summary()
    if not args.summary_only:
        print("Autonomous work queue check complete")
        print("Live Coinbase execution: not run; notional $0")
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
