"""Validate the durable autonomous work queue contract."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE_DOC = PROJECT_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
PUBLIC_RELEASE_DOC = PROJECT_ROOT / "docs" / "PUBLIC_RELEASE_READINESS.md"
FRONTEND_ASSOCIATION_DOC = PROJECT_ROOT / "docs" / "FRONTEND_ASSOCIATION.md"
ADMIN_API_README = PROJECT_ROOT / "README.admin-api.md"
ADMIN_API_EXAMPLES_DOC = PROJECT_ROOT / "docs" / "examples" / "admin-api.md"
STEALTH_COMMAND_SUITE_EXAMPLES_DOC = (
    PROJECT_ROOT / "docs" / "examples" / "stealth-command-suite.md"
)
FUTURES_PERPETUALS_EXAMPLES_DOC = (
    PROJECT_ROOT / "docs" / "examples" / "futures-perpetuals.md"
)
DOCS_INDEX = PROJECT_ROOT / "docs" / "README.md"
MAINTAINER_HANDOFF_DOC = PROJECT_ROOT / "docs" / "MAINTAINER_HANDOFF.md"
AGENT_STATE_DOC = PROJECT_ROOT / "genai_data" / "agent_state.md"
CONTEXTLESS_REVIEW_LOG_DOC = (
    PROJECT_ROOT / "docs" / "plans" / "ADMIN_API_CONTEXTLESS_REVIEW_LOG.md"
)
REGRESSION_GATE_POLICY_DOCS = (
    PROJECT_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
    PROJECT_ROOT / ".github" / "workflows" / "public-agent-checks.yml",
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "agent.md",
    PROJECT_ROOT / "README.admin-api.md",
    PROJECT_ROOT / "docs" / "FRONTEND_ASSOCIATION.md",
    PROJECT_ROOT / "docs" / "MAINTAINER_HANDOFF.md",
    PROJECT_ROOT / "docs" / "SPOT_READINESS_TEST_GATE.md",
    PROJECT_ROOT / "docs" / "STEALTH_ORDER_READS.md",
    PROJECT_ROOT / "docs" / "agents" / "README.md",
    PROJECT_ROOT / "docs" / "agents" / "AGENT_TEST_QUALITY.md",
    PROJECT_ROOT / "docs" / "plans" / "ADMIN_API_E2E_PLAN.md",
    PROJECT_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md",
    PROJECT_ROOT / "tests" / "DEPLOYMENT_CHECKLIST.md",
    PROJECT_ROOT / "tests" / "README.md",
    PROJECT_ROOT / "tests" / "SETUP_SUMMARY.md",
)
CANONICAL_FULL_REGRESSION_COMMAND = "python tools/run_parallel_regression.py --workers 4"
SEQUENTIAL_FULL_REGRESSION_COMMANDS = (
    "pytest tests/regression/ -v --tb=short",
    "python -m pytest tests\\regression\\ -v --tb=short",
    "python3 -m pytest tests/regression/ -v --tb=short",
)
STALE_REGRESSION_POLICY_TEXT = (
    "required backend regression gate when backend files change",
    "backend regression gate when backend files changed",
    "Backend regression remains required when backend files change",
    "backend regression when backend files change",
    "Backend regression is required only when backend files change",
)
SUMMARY_PREFIX = "AUTONOMOUS_WORK_QUEUE_CHECK_SUMMARY "
APPROVED_PHASE_RANGE = "5901-5920"
APPROVED_PHASES = tuple(range(5901, 5921))
PREVIOUS_COMPLETED_PHASE_RANGE = "5881-5900"
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
        _check_subagent_hygiene_policy(body),
        _check_required_gates(body),
        _check_example_phase_range_docs(),
        _check_regression_gate_policy_docs(),
        _check_frontend_release_docs(),
        _check_maintainer_handoff_docs(),
        _check_agent_state_docs(),
        _check_contextless_review_log_docs(),
    ]
    passed = all(check.passed for check in checks)
    return {
        "status": "passed" if passed else "blocked",
        "approved_phase_range": APPROVED_PHASE_RANGE,
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
        name=f"approved_phase_range_{APPROVED_PHASE_RANGE.replace('-', '_')}",
        passed=f"Approved phase range: **{APPROVED_PHASE_RANGE}**" in body
        and not missing,
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
        "python tools/run_parallel_regression.py --workers 4",
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


def _check_subagent_hygiene_policy(body: str) -> QueueCheck:
    required = [
        "Phase-end cleanup is the canonical timing.",
        "Close phase-scoped subagents at the",
        "also close any stale or",
        "previously unused subagents discovered from earlier phases or milestones",
        "Durable milestone",
        "final audit sweep, not the first cleanup point",
        "Record the phase-end or milestone-closeout sweep",
        "before advancing",
    ]
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name="subagent_hygiene_policy",
        passed=not missing,
        evidence={"missing_hygiene_text": missing},
    )


def _check_required_gates(body: str) -> QueueCheck:
    required = [
        "python tools\\run_autonomous_work_queue_check.py --summary-only",
        "python tools/run_parallel_regression.py --workers 4",
        "npm run release:gate",
    ]
    missing = [text for text in required if text not in body]
    return QueueCheck(
        name="required_final_gates",
        passed=not missing,
        evidence={"missing_gate_text": missing},
    )


def _check_example_phase_range_docs() -> QueueCheck:
    required_by_path = {
        ADMIN_API_EXAMPLES_DOC: [
            f'"approved_phase_range": "{APPROVED_PHASE_RANGE}"',
            "GET /api/v1/futures/command-suite",
            "Futures/perpetual command-suite reads expose backend-owned",
            '"risk_proof_requirements"',
            '"proof_contracts"',
            '"payload_fields"',
            '"record_contracts"',
            '"record_validations"',
            '"record_validation_remediations"',
            '"record_validation_remediation_dependencies"',
            '"record_validation_remediation_dependency_work_items"',
            '"record_validation_remediation_dependency_work_item_claim_traces"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_plans"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contracts"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediations"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependencies"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count"',
            '"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"',
            '"acceptance_criteria"',
            '"proof_acceptance_blockers"',
            '"proof_record_resolves_acceptance"',
            '"proof_record_resolved_but_acceptance_blocked_count"',
            '"risk_proof_semantic_contract_definition_count"',
            '"risk_proof_semantic_contract_validation_gate_count"',
            '"risk_proof_semantic_contract_validator_contract_count"',
            '"semantic_contract_definitions"',
            '"semantic_contract_validation_gates"',
            '"semantic_contract_validator_contracts"',
        ],
        FUTURES_PERPETUALS_EXAMPLES_DOC: [
            f'"approved_phase_range": "{APPROVED_PHASE_RANGE}"',
            f"active {APPROVED_PHASE_RANGE} range",
            "GET /api/v1/futures/command-suite",
            '"semantic_guards"',
            '"evidence_routes"',
            '"missing_evidence_refs"',
            '"readiness_decision"',
            '"readiness_closure_steps"',
            '"risk_proof_requirements"',
            '"proof_contracts"',
            '"payload_fields"',
            '"record_contracts"',
            '"record_validations"',
            '"record_validation_remediations"',
            '"record_validation_remediation_dependencies"',
            '"record_validation_remediation_dependency_work_items"',
            '"record_validation_remediation_dependency_work_item_claim_traces"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_plans"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contracts"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediations"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependencies"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count"',
            '"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count"',
            '"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"',
            '"record_contract_required": true',
            '"record_contract_available": false',
            '"record_schema_available": false',
            '"append_only_log_available": false',
            '"idempotency_key_bound": false',
            '"payload_schema_validated": false',
            '"replay_protected": false',
            '"record_validation_required": true',
            '"record_validation_ready": false',
            '"record_validation_remediation_required": true',
            '"record_validation_remediation_ready": false',
            '"record_validation_remediation_performed": false',
            '"record_validation_remediation_recorded": false',
            '"record_validation_remediation_dependency_required": true',
            '"record_validation_remediation_dependency_ready": false',
            '"record_validation_remediation_dependency_resolved": false',
            '"record_validation_remediation_dependency_performed": false',
            '"dependency_ready": false',
            '"dependency_resolved": false',
            '"dependency_performed": false',
            '"validation_checks_passed": false',
            '"validation_configured": false',
            '"claim_trace_created": false',
            '"claim_allowed": false',
            '"claim_resolved": false',
            '"clearance_plan_created": false',
            '"clearance_plan_ready": false',
            '"clearance_step_ready": false',
            '"clearance_step_complete": false',
            '"prior_clearance_step_complete": false',
            '"next_clearance_step_enabled": false',
            '"clearance_step_review_ready": false',
            '"clearance_step_review_complete": false',
            '"clearance_step_review_inputs_present": false',
            '"clearance_step_review_gates_passed": false',
            '"clearance_step_review_input_present": false',
            '"clearance_step_review_input_accepted": false',
            '"clearance_step_review_input_validated": false',
            '"clearance_step_review_input_gate_passed": false',
            '"store_required": true',
            '"store_available": false',
            '"writer_available": false',
            '"record_key_registered": false',
            '"validation_gate_passed": false',
            '"replay_gate_passed": false',
            '"acceptance_criteria"',
            '"proof_acceptance_blocked": true',
            '"proof_acceptance_blockers"',
            '"proof_record_resolves_acceptance": false',
            '"risk_proof_acceptance_blocker_count"',
            '"proof_record_resolved_but_acceptance_blocked_count"',
            '"risk_proof_semantic_contract_definition_count"',
            '"risk_proof_semantic_contract_validation_gate_count"',
            '"risk_proof_semantic_contract_validator_contract_count"',
            '"semantic_contract_definitions"',
            '"semantic_contract_validation_gates"',
            '"semantic_contract_validator_contracts"',
            '"semantic_contract_definition_ref"',
            '"definition_ready": false',
            '"validation_ready": false',
            '"runtime_evidence_satisfies_definition": false',
            '"validation_contract_ref"',
            '"validator_registered": false',
            '"runtime_evidence_satisfies_validation": false',
            '"forbidden_spot_assumptions"',
            '"futures_place"',
            '"futures_cancel"',
            "Spot wallet, no-shorting, USDC, cost-basis, and inventory-lot rules are forbidden",
        ],
    }
    stale_active_range_text = (
        "active 4901-4920 range",
        '"approved_phase_range": "4901-4920"',
        "active 4981-5000 range",
        '"approved_phase_range": "4981-5000"',
        "active 5021-5040 range",
        '"approved_phase_range": "5021-5040"',
        "active 5041-5060 range",
        '"approved_phase_range": "5041-5060"',
        "active 5061-5080 range",
        "active 5081-5100 range",
        "active 5101-5120 range",
        "active 5121-5140 range",
        '"approved_phase_range": "5061-5080"',
        '"approved_phase_range": "5081-5100"',
        '"approved_phase_range": "5101-5120"',
        '"approved_phase_range": "5121-5140"',
        "active 5141-5160 range",
        '"approved_phase_range": "5141-5160"',
        "active 5161-5180 range",
        '"approved_phase_range": "5161-5180"',
        "active 5181-5200 range",
        '"approved_phase_range": "5181-5200"',
        "active 5201-5220 range",
        '"approved_phase_range": "5201-5220"',
        "active 5221-5240 range",
        '"approved_phase_range": "5221-5240"',
        "active 5241-5260 range",
        '"approved_phase_range": "5241-5260"',
        "active 5261-5280 range",
        '"approved_phase_range": "5261-5280"',
        "active 5281-5300 range",
        '"approved_phase_range": "5281-5300"',
        "active 5301-5320 range",
        '"approved_phase_range": "5301-5320"',
        "active 5321-5340 range",
        '"approved_phase_range": "5321-5340"',
        "active 5341-5360 range",
        '"approved_phase_range": "5341-5360"',
        "active 5361-5380 range",
        '"approved_phase_range": "5361-5380"',
        "active 5381-5400 range",
        '"approved_phase_range": "5381-5400"',
        "active 5401-5420 range",
        '"approved_phase_range": "5401-5420"',
        "active 5421-5440 range",
        '"approved_phase_range": "5421-5440"',
        "active 5441-5460 range",
        '"approved_phase_range": "5441-5460"',
        "active 5461-5480 range",
        '"approved_phase_range": "5461-5480"',
        "active 5481-5500 range",
        '"approved_phase_range": "5481-5500"',
        "active 5501-5520 range",
        '"approved_phase_range": "5501-5520"',
        "active 5521-5540 range",
        '"approved_phase_range": "5521-5540"',
        "active 5541-5560 range",
        '"approved_phase_range": "5541-5560"',
        "active 5561-5580 range",
        '"approved_phase_range": "5561-5580"',
        "active 5581-5600 range",
        '"approved_phase_range": "5581-5600"',
        "active 5601-5620 range",
        '"approved_phase_range": "5601-5620"',
        "active 5621-5640 range",
        '"approved_phase_range": "5621-5640"',
        "active 5641-5660 range",
        '"approved_phase_range": "5641-5660"',
    )
    missing: dict[str, list[str]] = {}
    stale: dict[str, list[str]] = {}
    for path, required in required_by_path.items():
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        path_missing = [text for text in required if text not in body]
        if path_missing:
            missing[str(path.relative_to(PROJECT_ROOT))] = path_missing
        path_stale = [text for text in stale_active_range_text if text in body]
        if path_stale:
            stale[str(path.relative_to(PROJECT_ROOT))] = path_stale
    return QueueCheck(
        name="example_phase_range_docs",
        passed=not missing and not stale,
        evidence={
            "missing_current_example_text": missing,
            "stale_example_text": stale,
        },
    )


def _check_regression_gate_policy_docs() -> QueueCheck:
    stale_matches: dict[str, list[str]] = {}
    missing_policy: dict[str, list[str]] = {}
    missing_canonical_command: list[str] = []
    sequential_without_fallback: dict[str, list[str]] = {}
    required_policy_text = [
        "focused",
        "ordinary",
        "milestone",
    ]
    for path in REGRESSION_GATE_POLICY_DOCS:
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        policy_body = _active_regression_policy_body(path, body)
        stale = [text for text in STALE_REGRESSION_POLICY_TEXT if text in policy_body]
        if stale:
            stale_matches[str(path.relative_to(PROJECT_ROOT))] = stale
        if "regression" in policy_body.lower():
            missing = [
                text for text in required_policy_text if text not in policy_body.lower()
            ]
            if missing:
                missing_policy[str(path.relative_to(PROJECT_ROOT))] = missing
            if CANONICAL_FULL_REGRESSION_COMMAND not in policy_body:
                missing_canonical_command.append(str(path.relative_to(PROJECT_ROOT)))
            fallback_violations = [
                command
                for command in SEQUENTIAL_FULL_REGRESSION_COMMANDS
                if command in policy_body
                and not _sequential_command_is_fallback_only(policy_body, command)
            ]
            if fallback_violations:
                sequential_without_fallback[str(path.relative_to(PROJECT_ROOT))] = (
                    fallback_violations
                )
    return QueueCheck(
        name="regression_gate_policy_docs",
        passed=not stale_matches
        and not missing_policy
        and not missing_canonical_command
        and not sequential_without_fallback,
        evidence={
            "stale_policy_text": stale_matches,
            "missing_policy_terms": missing_policy,
            "missing_canonical_command": missing_canonical_command,
            "sequential_without_fallback": sequential_without_fallback,
        },
    )


def _active_regression_policy_body(path: Path, body: str) -> str:
    """Return only active policy text for docs that also contain history."""

    if path in {QUEUE_DOC, PROJECT_ROOT / "docs" / "plans" / "ADMIN_API_E2E_PLAN.md"}:
        return body.split("\n## Completed", maxsplit=1)[0]
    return body


def _sequential_command_is_fallback_only(body: str, command: str) -> bool:
    body_lower = body.lower()
    command_lower = command.lower()
    start = 0
    while True:
        index = body_lower.find(command_lower, start)
        if index == -1:
            return True
        context = body_lower[max(0, index - 180) : index + len(command_lower) + 180]
        if "fallback" not in context:
            return False
        start = index + len(command_lower)


def _check_frontend_release_docs() -> QueueCheck:
    required = [
        "npm run release:gate",
        "runtime evidence",
        "autonomous queue",
        "artifacts/runtime-evidence.json",
        "notional `$0`",
        "not approval for live Coinbase execution",
    ]
    missing: dict[str, list[str]] = {}
    for path in [
        PUBLIC_RELEASE_DOC,
        FRONTEND_ASSOCIATION_DOC,
        ADMIN_API_README,
        ADMIN_API_EXAMPLES_DOC,
    ]:
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        path_missing = [text for text in required if text not in body]
        if path_missing:
            missing[str(path.relative_to(PROJECT_ROOT))] = path_missing
    return QueueCheck(
        name="frontend_release_doc_parity",
        passed=not missing,
        evidence={"missing_evidence_text": missing},
    )


def _check_maintainer_handoff_docs() -> QueueCheck:
    required_by_path = {
        DOCS_INDEX: ["Maintainer Handoff", "MAINTAINER_HANDOFF.md"],
        ADMIN_API_README: ["Maintainer Handoff", "docs/MAINTAINER_HANDOFF.md"],
        MAINTAINER_HANDOFF_DOC: [
            "Backend Authority Rules",
            "Adding An Admin Module",
            "Contextless Task Card",
            "docs/LIVE_ORDER_SURFACES.md",
            "python tools/run_parallel_regression.py --workers 4",
            "npm run release:gate",
            (
                "Latest completed autonomous range: "
                f"`{PREVIOUS_COMPLETED_PHASE_RANGE}`"
            ),
            f"Active autonomous range: `{APPROVED_PHASE_RANGE}`",
        ],
    }
    missing: dict[str, list[str]] = {}
    for path, required in required_by_path.items():
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        path_missing = [text for text in required if text not in body]
        if path_missing:
            missing[str(path.relative_to(PROJECT_ROOT))] = path_missing
    return QueueCheck(
        name="maintainer_handoff_docs",
        passed=not missing,
        evidence={"missing_evidence_text": missing},
    )


def _check_agent_state_docs() -> QueueCheck:
    required = [
        f"current active range is `{APPROVED_PHASE_RANGE}`",
        f"Latest completed autonomous range before current work: `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
        f"Active autonomous range: `{APPROVED_PHASE_RANGE}`",
        f"Current direction: complete phases `{APPROVED_PHASE_RANGE}`",
        f"Active `{APPROVED_PHASE_RANGE}` adds futures semantic validator contract evidence",
        "/api/v1/futures/risk-proofs",
    ]
    stale = [
        "Active `5041-5060`",
        "complete active phases `5041-5060`",
        "current active range is `5041-5060`",
        "Active autonomous range: `5041-5060`",
        "Active `5061-5080`",
        "Active `5081-5100`",
        "Active `5101-5120`",
        "Active `5121-5140`",
        "Active `5141-5160`",
        "Active `5161-5180`",
        "Active `5181-5200`",
        "Active `5201-5220`",
        "Active `5221-5240`",
        "Active `5241-5260`",
        "Active `5261-5280`",
        "Active `5281-5300`",
        "Active `5301-5320`",
        "Active `5321-5340`",
        "Active `5341-5360`",
        "Active `5401-5420`",
        "Active `5421-5440`",
        "Active `5441-5460`",
        "Active `5501-5520`",
        "Active `5521-5540`",
        "Active `5541-5560`",
        "Active `5561-5580`",
        "Active `5581-5600`",
        "complete active phases `5061-5080`",
        "complete active phases `5081-5100`",
        "complete active phases `5101-5120`",
        "complete active phases `5121-5140`",
        "complete active phases `5141-5160`",
        "complete active phases `5161-5180`",
        "complete active phases `5181-5200`",
        "complete active phases `5201-5220`",
        "complete active phases `5221-5240`",
        "complete active phases `5241-5260`",
        "complete active phases `5261-5280`",
        "complete active phases `5281-5300`",
        "complete active phases `5301-5320`",
        "complete active phases `5321-5340`",
        "complete active phases `5341-5360`",
        "complete active phases `5401-5420`",
        "complete active phases `5421-5440`",
        "complete active phases `5441-5460`",
        "complete active phases `5501-5520`",
        "complete active phases `5521-5540`",
        "complete active phases `5541-5560`",
        "complete active phases `5561-5580`",
        "complete active phases `5581-5600`",
        "complete active phases `5701-5720`",
        "M57 range `5701-5720` in progress",
        "Pending rerun after `5701-5720` remediation",
        "M57 `5701-5720` active range",
        "Continue the active M57 `5701-5720`",
        "complete active phases `5721-5740`",
        "M57 range `5721-5740` in progress",
        "Pending rerun after `5721-5740` remediation",
        "M57 `5721-5740` active range",
        "Continue the active M57 `5721-5740`",
        "current active range is `5061-5080`",
        "current active range is `5081-5100`",
        "current active range is `5101-5120`",
        "current active range is `5121-5140`",
        "current active range is `5141-5160`",
        "current active range is `5161-5180`",
        "current active range is `5181-5200`",
        "current active range is `5201-5220`",
        "current active range is `5221-5240`",
        "current active range is `5241-5260`",
        "current active range is `5261-5280`",
        "current active range is `5281-5300`",
        "current active range is `5301-5320`",
        "current active range is `5321-5340`",
        "current active range is `5341-5360`",
        "current active range is `5401-5420`",
        "current active range is `5421-5440`",
        "current active range is `5441-5460`",
        "current active range is `5501-5520`",
        "current active range is `5521-5540`",
        "current active range is `5541-5560`",
        "current active range is `5561-5580`",
        "current active range is `5581-5600`",
        "Active autonomous range: `5061-5080`",
        "Active autonomous range: `5081-5100`",
        "Active autonomous range: `5101-5120`",
        "Active autonomous range: `5121-5140`",
        "Active autonomous range: `5141-5160`",
        "Active autonomous range: `5161-5180`",
        "Active autonomous range: `5181-5200`",
        "Active autonomous range: `5201-5220`",
        "Active autonomous range: `5221-5240`",
        "Active autonomous range: `5241-5260`",
        "Active autonomous range: `5261-5280`",
        "Active autonomous range: `5281-5300`",
        "Active autonomous range: `5301-5320`",
        "Active autonomous range: `5321-5340`",
        "Active autonomous range: `5341-5360`",
        "Active autonomous range: `5401-5420`",
        "Active autonomous range: `5421-5440`",
        "Active autonomous range: `5441-5460`",
        "Active autonomous range: `5501-5520`",
        "Active autonomous range: `5521-5540`",
        "Active autonomous range: `5541-5560`",
        "Active autonomous range: `5561-5580`",
        "Active autonomous range: `5581-5600`",
    ]
    body = AGENT_STATE_DOC.read_text(encoding="utf-8") if AGENT_STATE_DOC.exists() else ""
    missing = [text for text in required if text not in body]
    stale_matches = [text for text in stale if text in body]
    return QueueCheck(
        name="agent_state_current_range_docs",
        passed=AGENT_STATE_DOC.exists() and not missing and not stale_matches,
        evidence={
            "path": str(AGENT_STATE_DOC.relative_to(PROJECT_ROOT)),
            "missing_current_state_text": missing,
            "stale_current_state_text": stale_matches,
        },
    )


def _check_contextless_review_log_docs() -> QueueCheck:
    body = (
        CONTEXTLESS_REVIEW_LOG_DOC.read_text(encoding="utf-8")
        if CONTEXTLESS_REVIEW_LOG_DOC.exists()
        else ""
    )
    heading, section = _first_review_section(body)
    required = [
        APPROVED_PHASE_RANGE,
        "Result: PASS after remediation.",
        PREVIOUS_COMPLETED_PHASE_RANGE,
        "completed history",
        "No live Coinbase execution was run",
        "Full backend regression was not run because phases",
        "futures semantic validator contract evidence",
        "/api/v1/futures/risk-proofs",
        "risk_proof_record_resolver_count",
        "risk_proof_acceptance_blocker_count",
        "risk_proof_semantic_contract_requirement_count",
        "risk_proof_semantic_contract_definition_count",
        "risk_proof_semantic_contract_validation_gate_count",
        "risk_proof_semantic_contract_validator_contract_count",
        "semantic_contract_requirements",
        "semantic_contract_definitions",
        "semantic_contract_validation_gates",
        "semantic_contract_validator_contracts",
        "proof_record_lookup_status",
        "proof_acceptance_blockers",
        "proof_record_resolves_acceptance",
        "proofRecordLookupStatus",
        "proofAcceptanceBlockers",
        "semanticContractRequirements",
        "semanticContractDefinitions",
        "semanticContractValidationGates",
        "semanticContractValidatorContracts",
        "backend_futures_risk_proof_store_read_only_no_execution",
        "backend_futures_semantics_no_execution",
        "no futures command route",
        "no command draft",
        "no Coinbase activity",
        "no reconciliation execution",
        "no futures state mutation",
        "forbidden spot assumptions",
    ]
    stale = [
        f"active range and `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
        f"approved_phase_range: \"{PREVIOUS_COMPLETED_PHASE_RANGE}\"",
        f"validator evidence make `{PREVIOUS_COMPLETED_PHASE_RANGE}` the active range",
        f"now leads with `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
    ]
    missing = [text for text in required if text not in section]
    stale_matches = [text for text in stale if text in section]
    return QueueCheck(
        name="contextless_review_log_current_range",
        passed=CONTEXTLESS_REVIEW_LOG_DOC.exists()
        and APPROVED_PHASE_RANGE in heading
        and not missing
        and not stale_matches,
        evidence={
            "path": str(CONTEXTLESS_REVIEW_LOG_DOC.relative_to(PROJECT_ROOT)),
            "first_review_heading": heading,
            "missing_current_review_text": missing,
            "stale_current_review_text": stale_matches,
        },
    )


def _first_review_section(body: str) -> tuple[str, str]:
    heading = ""
    section_lines: list[str] = []
    in_section = False
    for line in body.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            heading = line
            in_section = True
        if in_section:
            section_lines.append(line)
    return heading, "\n".join(section_lines)


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
