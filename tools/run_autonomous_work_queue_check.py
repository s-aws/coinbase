"""Validate the durable autonomous work queue contract."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE_DOC = PROJECT_ROOT / "docs" / "plans" / "AUTONOMOUS_WORK_QUEUE.md"
PUBLIC_RELEASE_DOC = PROJECT_ROOT / "docs" / "PUBLIC_RELEASE_READINESS.md"
FRONTEND_ASSOCIATION_DOC = PROJECT_ROOT / "docs" / "FRONTEND_ASSOCIATION.md"
ADMIN_API_README = PROJECT_ROOT / "README.admin-api.md"
FUTURES_PERPETUALS_README = PROJECT_ROOT / "README.futures-perpetuals.md"
ADMIN_API_EXAMPLES_DOC = PROJECT_ROOT / "docs" / "examples" / "admin-api.md"
API_REFERENCE_DOC = PROJECT_ROOT / "genai_data" / "API_REFERENCE.md"
STEALTH_COMMAND_SUITE_EXAMPLES_DOC = (
    PROJECT_ROOT / "docs" / "examples" / "stealth-command-suite.md"
)
FUTURES_PERPETUALS_EXAMPLES_DOC = (
    PROJECT_ROOT / "docs" / "examples" / "futures-perpetuals.md"
)
DOCS_INDEX = PROJECT_ROOT / "docs" / "README.md"
MAINTAINER_HANDOFF_DOC = PROJECT_ROOT / "docs" / "MAINTAINER_HANDOFF.md"
ADMIN_MODULE_CAPABILITY_MATRIX_DOC = (
    PROJECT_ROOT / "docs" / "ADMIN_MODULE_CAPABILITY_MATRIX.md"
)
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
APPROVED_PHASE_RANGE = "7781-7800"
APPROVED_PHASES = tuple(range(7781, 7801))
PREVIOUS_COMPLETED_PHASE_RANGE = "7761-7780"
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
        _check_futures_resolved_contracts_not_reported_missing(),
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
    missing_history = [
        text
        for text in (
            "## Historical Plan - Phases 6441-6460",
            "Futures/Perpetuals Request Payload Validator Output Schema Evidence",
            "## Historical Plan - Phases 6461-6480",
            "Futures/Perpetuals Request Payload Validator Registration Evidence",
            "## Historical Plan - Phases 6481-6500",
            "Futures/Perpetuals Request Payload Validation Evidence",
            "## Historical Plan - Phases 6501-6520",
            "Futures/Perpetuals Request Payload Validation Evidence Record Contract Evidence",
            "## Historical Plan - Phases 6521-6540",
            "Futures/Perpetuals Request Payload Validation Record Schema Evidence",
            "## Historical Plan - Phases 6541-6560",
            "Futures/Perpetuals Request Payload Validation Record Replay Guard Evidence",
            "## Historical Plan - Phases 6561-6580",
            "Futures/Perpetuals Request Payload Validation Evidence Record Audit Link Evidence",
            "## Historical Phases 6701-6720",
            "Futures/Perpetuals Request Payload Validation Record Semantic Artifact Definition Review Input Evidence",
            "## Historical Plan - Phases 6421-6440",
            "Futures/Perpetuals Request Payload Validator Input Schema Evidence",
        )
        if text not in body
    ]
    return QueueCheck(
        name=f"approved_phase_range_{APPROVED_PHASE_RANGE.replace('-', '_')}",
        passed=f"Approved phase range: **{APPROVED_PHASE_RANGE}**" in body
        and not missing
        and not missing_history,
        evidence={
            "expected_first_phase": APPROVED_PHASES[0],
            "expected_last_phase": APPROVED_PHASES[-1],
            "missing_phase_headings": missing,
            "missing_history_text": missing_history,
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
            "`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_request_payload_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`",
            "`iter_futures_request_payload_validator_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_input_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_output_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`",
            "`iter_futures_request_payload_validator_registrations`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence_records`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence_records`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence_records`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence_records`",
            '"request_field_count"',
            '"blocking_request_field_count"',
            '"request_payload_validator_contract_count"',
            '"blocking_request_payload_validator_contract_count"',
            '"ready_request_payload_validator_contract_count"',
            '"registered_request_payload_validator_contract_count"',
            '"request_payload_validator_contracts"',
            '"request_payload_validator_input_schema_count"',
            '"blocking_request_payload_validator_input_schema_count"',
            '"ready_request_payload_validator_input_schema_count"',
            '"registered_request_payload_validator_input_schema_count"',
            '"request_payload_validator_input_schemas"',
            '"request_payload_validator_output_schema_count"',
            '"blocking_request_payload_validator_output_schema_count"',
            '"ready_request_payload_validator_output_schema_count"',
            '"registered_request_payload_validator_output_schema_count"',
            '"request_payload_validator_output_schemas"',
            '"request_payload_validator_registration_count"',
            '"blocking_request_payload_validator_registration_count"',
            '"ready_request_payload_validator_registration_count"',
            '"registered_request_payload_validator_registration_count"',
            '"runtime_observed_request_payload_validator_registration_count"',
            '"request_payload_validator_registrations"',
            '"request_payload_validation_evidence_count"',
            '"blocking_request_payload_validation_evidence_count"',
            '"ready_request_payload_validation_evidence_count"',
            '"recorded_request_payload_validation_evidence_count"',
            '"runtime_observed_request_payload_validation_evidence_count"',
            '"request_payload_validation_evidence"',
            '"request_payload_validation_evidence_record_count"',
            '"blocking_request_payload_validation_evidence_record_count"',
            '"ready_request_payload_validation_evidence_record_count"',
            '"stored_request_payload_validation_evidence_record_count"',
            '"runtime_observed_request_payload_validation_evidence_record_count"',
            '"request_payload_validation_evidence_records"',
            "futures request payload contract registry evidence",
            "futures request payload validation gate evidence",
            "futures request payload validator contract registry evidence",
            "futures request payload validator input-schema evidence",
            "futures request payload validator output-schema evidence",
            "futures request payload validator registration evidence",
            "futures request payload validation evidence",
            "futures request payload validation evidence record contract evidence",
            "futures request payload validation record schema evidence",
            "futures request payload validation record replay guard evidence",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_replay_guards`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_replay_guards`",
            "`request_payload_validation_record_schema_count`",
            "`blocking_request_payload_validation_record_schema_count`",
            "`request_payload_validation_record_replay_guard_count`",
            "`blocking_request_payload_validation_record_replay_guard_count`",
            "`ready_request_payload_validation_record_schema_count`",
            "`registered_request_payload_validation_record_schema_count`",
            "`runtime_observed_request_payload_validation_record_schema_count`",
            "`request_payload_validation_record_schemas`",
            "`request_payload_validation_record_replay_guard_count`",
            "`blocking_request_payload_validation_record_replay_guard_count`",
            "`ready_request_payload_validation_record_replay_guard_count`",
            "`idempotency_bound_request_payload_validation_record_count`",
            "`runtime_observed_request_payload_validation_record_replay_guard_count`",
            "`request_payload_validation_record_replay_guards`",
            '"validation_gate_ref"',
            '"validation_evidence_ref"',
            '"validator_contract_ref"',
            '"validator_input_schema_ref"',
            '"validator_output_schema_ref"',
            '"output_schema_field_refs"',
            '"output_schema_field_count"',
            '"validator_registration_ref"',
            '"validator_registration_field_refs"',
            '"validator_registration_field_count"',
            '"validation_evidence_contract_ref"',
            '"validation_evidence_field_refs"',
            '"validation_evidence_field_count"',
            '"validation_record_contract_ref"',
            '"validation_record_store_ref"',
            '"validation_record_writer_ref"',
            '"validation_record_replay_guard_ref"',
            '"validation_record_field_refs"',
            '"validation_record_field_count"',
            '"validation_record_schema_ref"',
            '"validation_record_append_only_log_ref"',
            '"validation_record_replay_guard_contract_ref"',
            '"validation_record_idempotency_contract_ref"',
            '"validation_record_replay_window_ref"',
            '"validation_record_duplicate_policy_ref"',
            '"validation_record_schema_field_refs"',
            '"validation_record_schema_field_count"',
            '"validation_record_replay_guard_field_refs"',
            '"validation_record_replay_guard_field_count"',
            '"validation_gate_ready": false',
            '"validation_gate_passed": false',
            '"validator_contract_registered": false',
            '"validator_input_schema_registered": false',
            '"validator_output_schema_registered": false',
            '"output_schema_registered": false',
            '"validator_registration_ready": false',
            '"runtime_evidence_satisfies_validator_registration": false',
            '"runtime_evidence_satisfies_validation_evidence": false',
            '"validation_evidence_ready": false',
            '"validation_evidence_recorded": false',
            '"validation_record_contract_ready": false',
            '"validation_record_store_ready": false',
            '"validation_record_writer_enabled": false',
            '"validation_record_replay_guard_ready": false',
            '"validation_record_schema_ready": false',
            '"validation_record_schema_registered": false',
            '"validation_record_append_only_log_ready": false',
            '"runtime_evidence_satisfies_validation_record_schema": false',
            '"runtime_evidence_satisfies_validation_record_replay_guard": false',
            '"validation_record_replay_guard_contract_ready": false',
            '"validation_record_idempotency_contract_ready": false',
            '"validation_record_replay_protected": false',
            '"validation_recorded": false',
            '"append_only_validation_record": false',
            '"validation_record_idempotency_bound": false',
            '"validator_registered": false',
            '"request_payload_validated": false',
            "route/draft flags remain true while execution remains false",
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
            '"risk_proof_semantic_validator_input_schema_count"',
            '"risk_proof_semantic_validator_output_schema_count"',
            '"semantic_contract_definitions"',
            '"semantic_contract_validation_gates"',
            '"semantic_contract_validator_contracts"',
            '"semantic_validator_input_schemas"',
            '"semantic_validator_output_schemas"',
            '"command_enablement_blocker_summaries"',
            '"command_enablement_blocker_summary_count"',
            '"command_enablement_sequence_steps"',
            '"command_enablement_sequence_step_count"',
            '"command_enablement_sequence_step_blocking_count"',
            '"proof_payload.command"',
            '"proof_payload.validation.status"',
            '"futures_place_margin_collateral_payload_command_validated"',
            '"payload_field_present": false',
            '"validation_registered": false',
        ],
        FUTURES_PERPETUALS_README: [
            "`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_request_payload_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`",
            "`iter_futures_request_payload_validator_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_input_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_output_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`",
            "`iter_futures_request_payload_validator_registrations`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence_records`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_audit_links`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_admission_links`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_execution_eligibilities`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_execution_eligibility_blockers`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifacts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_definitions`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_definition_reviews`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`",
            "futures request payload contract registry evidence",
            "futures request payload validator contract registry evidence",
            "futures request payload validator input-schema evidence",
            "futures request payload validator output-schema evidence",
            "futures request payload validator registration evidence",
            "futures request payload validation evidence",
            "futures request payload validation evidence record contract evidence",
            "futures request payload validation record schema evidence",
            "futures request payload validation record replay guard evidence",
            "futures request payload validation record audit-link evidence",
            "futures request payload validation record admission-link evidence",
            "Active M57 `7781-7800` evidence adds futures command risk-proof requirement summary evidence while completed M57 `7761-7780` carries forward futures command semantic-guard summary evidence.",
            "futures request payload validation record execution-eligibility blocker evidence",
            "futures request payload validation record execution-eligibility evidence",
            "futures request payload validation record admission-link evidence",
            "futures request payload validation record audit-link evidence",
            "`request_payload_validator_contract_count`",
            "`blocking_request_payload_validator_contract_count`",
            "`request_payload_validator_input_schema_count`",
            "`blocking_request_payload_validator_input_schema_count`",
            "`request_payload_validator_output_schema_count`",
            "`blocking_request_payload_validator_output_schema_count`",
            "`request_payload_validator_registration_count`",
            "`blocking_request_payload_validator_registration_count`",
            "`request_payload_validation_evidence_count`",
            "`blocking_request_payload_validation_evidence_count`",
            "`request_payload_validation_evidence_record_count`",
            "`blocking_request_payload_validation_evidence_record_count`",
            "`request_payload_validation_evidence_record_count`",
            "`blocking_request_payload_validation_evidence_record_count`",
            "`request_payload_validation_record_audit_link_count`",
            "`blocking_request_payload_validation_record_audit_link_count`",
            "`request_payload_validation_record_audit_links`",
            "`request_payload_validation_record_admission_link_count`",
            "`blocking_request_payload_validation_record_admission_link_count`",
            "`request_payload_validation_record_admission_links`",
            "`request_payload_validation_record_execution_eligibility_count`",
            "`blocking_request_payload_validation_record_execution_eligibility_count`",
            "`request_payload_validation_record_execution_eligibilities`",
            "`request_payload_validation_record_execution_eligibility_blocker_count`",
            "`blocking_request_payload_validation_record_execution_eligibility_blocker_count`",
            "`request_payload_validation_record_execution_eligibility_blockers`",
            "`request_payload_validation_record_semantic_artifact_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_count`",
            "`ready_request_payload_validation_record_semantic_artifact_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_count`",
            "`request_payload_validation_record_semantic_artifacts`",
            "`request_payload_validation_record_semantic_artifact_definition_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_definition_count`",
            "`ready_request_payload_validation_record_semantic_artifact_definition_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_definition_count`",
            "`request_payload_validation_record_semantic_artifact_definitions`",
            "`request_payload_validation_record_semantic_artifact_definition_review_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_definition_review_count`",
            "`ready_request_payload_validation_record_semantic_artifact_definition_review_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_count`",
            "`request_payload_validation_record_semantic_artifact_definition_reviews`",
            "`request_payload_validation_record_semantic_artifact_definition_review_input_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_definition_review_input_count`",
            "`ready_request_payload_validation_record_semantic_artifact_definition_review_input_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_input_count`",
            "`request_payload_validation_record_semantic_artifact_definition_review_inputs`",
            "`request_payload_validation_record_semantic_artifact_definition_review_output_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count`",
            "`ready_request_payload_validation_record_semantic_artifact_definition_review_output_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count`",
            "`request_payload_validation_record_semantic_artifact_definition_review_outputs`",
            "`request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`",
            "`ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`",
            "`request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`",
            "`request_payload_validation_record_semantic_artifact_runtime_evidence_count`",
            "`blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`",
            "`ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`",
            "`runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`",
            "`request_payload_validation_record_semantic_artifact_runtime_evidences`",
            "`semantic_artifact_ref`",
            "`semantic_artifact_contract_ref`",
            "`semantic_artifact_definition_ref`",
            "`semantic_artifact_definition_contract_ref`",
            "`semantic_artifact_definition_review_ref`",
            "`semantic_artifact_definition_review_contract_ref`",
            "`semantic_artifact_definition_review_input_ref`",
            "`semantic_artifact_definition_review_input_contract_ref`",
            "`semantic_artifact_definition_review_output_ref`",
            "`semantic_artifact_definition_review_output_contract_ref`",
            "`semantic_artifact_definition_review_output_acceptance_ref`",
            "`semantic_artifact_definition_review_output_acceptance_contract_ref`",
            "`semantic_artifact_runtime_evidence_ref`",
            "`semantic_artifact_runtime_evidence_contract_ref`",
            "`contextless_review_required=true`",
            "`semantic_artifact_definition_available=false`",
            "`semantic_artifact_definition_review_available=false`",
            "`semantic_artifact_definition_review_input_available=false`",
            "`semantic_artifact_definition_review_input_accepted=false`",
            "`semantic_artifact_definition_review_output_available=false`",
            "`semantic_artifact_definition_review_output_accepted=false`",
            "`semantic_artifact_definition_review_output_acceptance_available=false`",
            "`semantic_artifact_definition_review_output_acceptance_accepted=false`",
            "`semantic_artifact_runtime_evidence_available=false`",
            "`semantic_artifact_definition_reviewed=false`",
            "`semantic_artifact_definition_review_passed=false`",
            "`semantic_artifact_runtime_evidence_bound=false`",
            "`semantic_artifact_runtime_evidence_accepted=false`",
            "`semantic_artifact_defined=false`",
            "`semantic_artifact_reviewed=false`",
            "`execution_eligibility_blocker_resolved=false`",
            "`validation_gate_ref`",
            "`validation_evidence_ref`",
            "`validator_contract_ref`",
            "`validator_input_schema_ref`",
            "`validator_output_schema_ref`",
            "`output_schema_field_refs`",
            "`output_schema_field_count`",
            "`validator_registration_ref`",
            "`validator_registration_field_refs`",
            "`validator_registration_field_count`",
            "`validation_evidence_contract_ref`",
            "`validation_evidence_field_refs`",
            "`validation_evidence_field_count`",
            "`validation_record_contract_ref`",
            "`validation_record_store_ref`",
            "`validation_record_writer_ref`",
            "`validation_record_replay_guard_ref`",
            "`validation_record_field_refs`",
            "`validation_record_field_count`",
            "`validation_record_contract_ref`",
            "`validation_record_store_ref`",
            "`validation_record_writer_ref`",
            "`validation_record_replay_guard_ref`",
            "`validation_record_field_refs`",
            "`validation_record_field_count`",
            "`validation_record_audit_link_contract_ref`",
            "`validation_record_actor_ref`",
            "`validation_record_operator_intent_ref`",
            "`validation_record_correlation_ref`",
            "`validation_record_admission_audit_ref`",
            "`validation_record_audit_record_ref`",
            "`validation_record_audit_link_field_refs`",
            "`validation_record_audit_link_field_count`",
            "`validation_record_admission_link_contract_ref`",
            "`validation_record_approval_snapshot_ref`",
            "`validation_record_cap_guard_decision_ref`",
            "`validation_record_reconciliation_plan_ref`",
            "`validation_record_live_intent_ref`",
            "`validation_record_command_admission_ref`",
            "`validation_record_admission_link_field_refs`",
            "`validation_record_admission_link_field_count`",
            "`validation_record_execution_eligibility_contract_ref`",
            "`validation_record_position_semantics_ref`",
            "`validation_record_margin_semantics_ref`",
            "`validation_record_collateral_semantics_ref`",
            "`validation_record_liquidation_semantics_ref`",
            "`validation_record_reduce_only_semantics_ref`",
            "`validation_record_close_only_semantics_ref`",
            "`validation_record_funding_semantics_ref`",
            "`validation_record_order_semantics_ref`",
            "`validation_record_cancel_semantics_ref`",
            "`validation_record_reconciliation_semantics_ref`",
            "`validation_record_execution_eligibility_field_refs`",
            "`validation_record_execution_eligibility_field_count`",
            "validation_gate_ready=false",
            "validation_gate_passed=false",
            "output_schema_registered=false",
            "validator_registration_ready=false",
            "runtime_evidence_satisfies_validator_registration=false",
            "runtime_evidence_satisfies_validation_evidence=false",
            "validation_evidence_ready=false",
            "validation_evidence_recorded=false",
            "validation_record_contract_ready=false",
            "validation_record_store_ready=false",
            "validation_record_writer_enabled=false",
            "validation_record_replay_guard_ready=false",
            "runtime_evidence_satisfies_validation_record_audit_link=false",
            "validation_record_audit_link_contract_ready=false",
            "validation_record_audit_link_ready=false",
            "validation_record_actor_bound=false",
            "validation_record_operator_intent_bound=false",
            "validation_record_correlation_bound=false",
            "validation_record_admission_audit_bound=false",
            "validation_record_audit_recorded=false",
            "runtime_evidence_satisfies_validation_record_admission_link=false",
            "validation_record_admission_link_contract_ready=false",
            "validation_record_admission_link_ready=false",
            "validation_record_approval_snapshot_bound=false",
            "validation_record_cap_guard_decision_bound=false",
            "validation_record_reconciliation_plan_bound=false",
            "validation_record_live_intent_bound=false",
            "validation_record_command_admission_bound=false",
            "validation_record_admitted=false",
            "runtime_evidence_satisfies_validation_record_execution_eligibility=false",
            "validation_record_execution_eligibility_contract_ready=false",
            "validation_record_execution_eligible=false",
            "validation_record_position_semantics_ready=false",
            "validation_record_margin_semantics_ready=false",
            "validation_record_collateral_semantics_ready=false",
            "validation_record_liquidation_semantics_ready=false",
            "validation_record_reduce_only_semantics_ready=false",
            "validation_record_close_only_semantics_ready=false",
            "validation_record_funding_semantics_ready=false",
            "validation_record_order_semantics_ready=false",
            "validation_record_cancel_semantics_ready=false",
            "validation_record_reconciliation_semantics_ready=false",
            "validation_recorded=false",
            "append_only_validation_record=false",
            "validation_record_idempotency_bound=false",
            "request_payload_validated=false",
            "route/draft true and execution false flags",
            "validate command request payloads",
            "register payload validators",
            "`FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_proof_payload_field_contracts`",
            "`proof_payload.command`",
            "`proof_payload.validation.status`",
            "`futures_place_margin_collateral_payload_command_validated`",
            "proof payload-field contract registry evidence",
            "backend-owned read-only evidence",
            "validate submitted proof payloads",
            "accept risk proofs",
            "payload_field_present=false",
            "validation_registered=false",
            "route-bound command drafts",
            "route/draft true and execution false flags",
            "make route-bound command drafts executable",
            "register proof routes",
            "create proof writers",
            "call Coinbase",
            "execute reconciliation",
            "mutate futures/order/exchange state",
            "spot-rule authority",
        ],
        API_REFERENCE_DOC: [
            "`GET /api/v1/futures/command-suite`",
            "`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_request_payload_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`",
            "`iter_futures_request_payload_validator_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_input_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_output_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`",
            "`iter_futures_request_payload_validator_registrations`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence`",
            "futures request payload contract registry evidence",
            "futures request payload validator contract registry evidence",
            "futures request payload validator input-schema evidence",
            "futures request payload validator output-schema evidence",
            "futures request payload validator registration evidence",
            "futures request payload validation evidence",
            "futures request payload validation record execution-eligibility evidence",
            "`request_payload_validator_contract_count`",
            "`blocking_request_payload_validator_contract_count`",
            "`request_payload_validator_input_schema_count`",
            "`blocking_request_payload_validator_input_schema_count`",
            "`request_payload_validator_output_schema_count`",
            "`blocking_request_payload_validator_output_schema_count`",
            "`request_payload_validator_registration_count`",
            "`blocking_request_payload_validator_registration_count`",
            "`request_payload_validation_evidence_count`",
            "`blocking_request_payload_validation_evidence_count`",
            "`request_payload_validation_evidence_record_count`",
            "`blocking_request_payload_validation_evidence_record_count`",
            "`request_payload_validation_record_schema_count`",
            "`blocking_request_payload_validation_record_schema_count`",
            "`validation_gate_ref`",
            "`validation_evidence_ref`",
            "`validator_contract_ref`",
            "`validator_input_schema_ref`",
            "`validator_output_schema_ref`",
            "`output_schema_field_refs`",
            "`output_schema_field_count`",
            "`validator_registration_ref`",
            "`validator_registration_field_refs`",
            "`validator_registration_field_count`",
            "`validation_evidence_contract_ref`",
            "`validation_evidence_field_refs`",
            "`validation_evidence_field_count`",
            "`validation_record_contract_ref`",
            "`validation_record_store_ref`",
            "`validation_record_writer_ref`",
            "`validation_record_replay_guard_ref`",
            "`validation_record_field_refs`",
            "`validation_record_field_count`",
            "`validation_record_schema_ref`",
            "`validation_record_append_only_log_ref`",
            "`validation_record_replay_guard_contract_ref`",
            "`validation_record_idempotency_contract_ref`",
            "`validation_record_replay_window_ref`",
            "`validation_record_duplicate_policy_ref`",
            "`validation_record_schema_field_refs`",
            "`validation_record_schema_field_count`",
            "`validation_record_replay_guard_field_refs`",
            "`validation_record_replay_guard_field_count`",
            "`validation_record_execution_eligibility_contract_ref`",
            "`validation_record_position_semantics_ref`",
            "`validation_record_margin_semantics_ref`",
            "`validation_record_collateral_semantics_ref`",
            "`validation_record_liquidation_semantics_ref`",
            "`validation_record_reduce_only_semantics_ref`",
            "`validation_record_close_only_semantics_ref`",
            "`validation_record_funding_semantics_ref`",
            "`validation_record_order_semantics_ref`",
            "`validation_record_cancel_semantics_ref`",
            "`validation_record_reconciliation_semantics_ref`",
            "`validation_record_execution_eligibility_field_refs`",
            "validation_gate_ready=false",
            "validation_gate_passed=false",
            "output_schema_registered=false",
            "validator_registration_ready=false",
            "runtime_evidence_satisfies_validator_registration=false",
            "runtime_evidence_satisfies_validation_evidence=false",
            "validation_evidence_ready=false",
            "validation_evidence_recorded=false",
            "validation_record_contract_ready=false",
            "validation_record_store_ready=false",
            "validation_record_writer_enabled=false",
            "validation_record_replay_guard_ready=false",
            "runtime_evidence_satisfies_validation_record_schema=false",
            "runtime_evidence_satisfies_validation_record_replay_guard=false",
            "validation_record_schema_ready=false",
            "validation_record_schema_registered=false",
            "validation_record_replay_guard_contract_ready=false",
            "validation_record_idempotency_contract_ready=false",
            "validation_record_replay_protected=false",
            "runtime_evidence_satisfies_validation_record_execution_eligibility=false",
            "validation_record_execution_eligibility_contract_ready=false",
            "validation_record_execution_eligible=false",
            "validation_record_append_only_log_ready=false",
            "validation_recorded=false",
            "append_only_validation_record=false",
            "validation_record_idempotency_bound=false",
            "request_payload_validated=false",
            "route/draft flags true while execution remains",
            "validate command request payloads",
            "register payload validators",
            "`FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_proof_payload_field_contracts`",
            "`proof_payload.command`",
            "`proof_payload.validation.status`",
            "`futures_place_margin_collateral_payload_command_validated`",
            "proof payload-field contract registry evidence",
            "validate submitted proof payloads",
            "accept risk proofs",
            "payload_field_present=false",
            "validation_registered=false",
            "route-bound command drafts",
            "route/draft flags true while execution remains",
            "make route-bound command drafts executable",
            "register proof routes",
            "create proof writers",
            "call Coinbase",
            "execute reconciliation",
            "mutate",
            "spot-rule authority",
        ],
        FUTURES_PERPETUALS_EXAMPLES_DOC: [
            f'"approved_phase_range": "{APPROVED_PHASE_RANGE}"',
            f"active {APPROVED_PHASE_RANGE} range",
            "`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`",
            "`iter_futures_request_payload_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`",
            "`iter_futures_request_payload_validator_contracts`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_input_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`",
            "`iter_futures_request_payload_validator_output_schemas`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`",
            "`iter_futures_request_payload_validator_registrations`",
            "`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`",
            "`iter_futures_request_payload_validation_evidence`",
            "futures request payload contract registry evidence",
            "futures request payload validation gate evidence",
            "futures request payload validator contract registry evidence",
            "futures request payload validator input-schema evidence",
            "futures request payload validator output-schema evidence",
            "futures request payload validator registration evidence",
            "futures request payload validation evidence",
            '"request_field_count": 22',
            '"blocking_request_field_count": 22',
            '"request_payload_validator_contract_count": 22',
            '"blocking_request_payload_validator_contract_count": 22',
            '"ready_request_payload_validator_contract_count": 0',
            '"registered_request_payload_validator_contract_count": 0',
            '"request_payload_validator_contracts"',
            '"request_payload_validator_input_schema_count": 22',
            '"blocking_request_payload_validator_input_schema_count": 22',
            '"ready_request_payload_validator_input_schema_count": 0',
            '"registered_request_payload_validator_input_schema_count": 0',
            '"request_payload_validator_input_schemas"',
            '"request_payload_validator_output_schema_count": 22',
            '"blocking_request_payload_validator_output_schema_count": 22',
            '"ready_request_payload_validator_output_schema_count": 0',
            '"registered_request_payload_validator_output_schema_count": 0',
            '"request_payload_validator_output_schemas"',
            '"request_payload_validator_registration_count": 22',
            '"blocking_request_payload_validator_registration_count": 22',
            '"ready_request_payload_validator_registration_count": 0',
            '"registered_request_payload_validator_registration_count": 0',
            '"runtime_observed_request_payload_validator_registration_count": 0',
            '"request_payload_validator_registrations"',
            '"request_payload_validation_evidence_count": 22',
            '"blocking_request_payload_validation_evidence_count": 22',
            '"ready_request_payload_validation_evidence_count": 0',
            '"recorded_request_payload_validation_evidence_count": 0',
            '"runtime_observed_request_payload_validation_evidence_count": 0',
            '"request_payload_validation_evidence"',
            '"request_payload_validation_evidence_record_count": 22',
            '"blocking_request_payload_validation_evidence_record_count": 22',
            '"ready_request_payload_validation_evidence_record_count": 0',
            '"stored_request_payload_validation_evidence_record_count": 0',
            '"runtime_observed_request_payload_validation_evidence_record_count": 0',
            '"request_payload_validation_evidence_records"',
            '"validation_gate_ref"',
            '"validation_evidence_ref"',
            '"validator_contract_ref"',
            '"validator_input_schema_ref"',
            '"validator_output_schema_ref"',
            '"output_schema_field_refs"',
            '"output_schema_field_count"',
            '"validator_registration_ref"',
            '"validator_registration_field_refs"',
            '"validator_registration_field_count"',
            '"validation_evidence_contract_ref"',
            '"validation_evidence_field_refs"',
            '"validation_evidence_field_count"',
            '"validation_record_contract_ref"',
            '"validation_record_store_ref"',
            '"validation_record_writer_ref"',
            '"validation_record_replay_guard_ref"',
            '"validation_record_field_refs"',
            '"validation_record_field_count"',
            '"validation_gate_ready": false',
            '"validation_gate_passed": false',
            '"validator_contract_registered": false',
            '"validator_input_schema_registered": false',
            '"validator_output_schema_registered": false',
            '"output_schema_registered": false',
            '"validator_registration_ready": false',
            '"runtime_evidence_satisfies_validator_registration": false',
            '"runtime_evidence_satisfies_validation_evidence": false',
            '"validation_evidence_ready": false',
            '"validation_evidence_recorded": false',
            '"validation_record_contract_ready": false',
            '"validation_record_store_ready": false',
            '"validation_record_writer_enabled": false',
            '"validation_record_replay_guard_ready": false',
            '"validation_recorded": false',
            '"append_only_validation_record": false',
            '"validation_record_idempotency_bound": false',
            '"validator_registered": false',
            '"request_payload_validated": false',
            "application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_contract",
            "route/draft flags are",
            "true while execution remains false",
            '"proof_payload.command"',
            '"proof_payload.validation.status"',
            '"futures_place_margin_collateral_payload_command_validated"',
            '"payload_field_present": false',
            '"validation_registered": false',
            "proof payload-field contract registry evidence",
            "semantic_guard_evidence",
            "risk_proof_acceptance",
            "live_service_adapter",
            "contextless_review_gate",
            '"command_enablement_blocker_summary_count": 6',
            '"command_route_count": 4',
            '"command_draft_allowed_count": 4',
            "make route-bound command drafts executable",
            "adapter contract refs are required/present disabled evidence",
            "adapter construction refs are required/present disabled evidence",
            "adapter decision refs are required/present disabled evidence",
            "adapter decision-record refs are required/present disabled evidence",
            "adapter invocation refs are required/present disabled evidence",
            "adapter execution refs are required/present disabled evidence",
            "Coinbase exchange-submission refs are required/present disabled evidence",
            "post-exchange-submission reconciliation refs are required/present disabled evidence",
            "application/admin_api/live_execution.py::futures_place_adapter_construction_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_adapter_construction_contract",
            "application/admin_api/live_execution.py::futures_cancel_adapter_construction_contract",
            "application/admin_api/live_execution.py::futures_reconcile_adapter_construction_contract",
            "application/admin_api/live_execution.py::futures_place_adapter_decision_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_contract",
            "application/admin_api/live_execution.py::futures_cancel_adapter_decision_contract",
            "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_contract",
            "application/admin_api/live_execution.py::futures_place_adapter_decision_record_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_record_contract",
            "application/admin_api/live_execution.py::futures_cancel_adapter_decision_record_contract",
            "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_record_contract",
            "application/admin_api/live_execution.py::futures_place_adapter_invocation_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_adapter_invocation_contract",
            "application/admin_api/live_execution.py::futures_cancel_adapter_invocation_contract",
            "application/admin_api/live_execution.py::futures_reconcile_adapter_invocation_contract",
            "application/admin_api/live_execution.py::futures_place_adapter_execution_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_adapter_execution_contract",
            "application/admin_api/live_execution.py::futures_cancel_adapter_execution_contract",
            "application/admin_api/live_execution.py::futures_reconcile_adapter_execution_contract",
            "application/admin_api/live_execution.py::futures_place_coinbase_exchange_submission_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_coinbase_exchange_submission_contract",
            "application/admin_api/live_execution.py::futures_cancel_coinbase_exchange_submission_contract",
            "application/admin_api/live_execution.py::futures_reconcile_coinbase_exchange_submission_contract",
            "application/admin_api/live_execution.py::futures_place_post_exchange_submission_reconciliation_contract",
            "application/admin_api/live_execution.py::futures_close_reduce_post_exchange_submission_reconciliation_contract",
            "application/admin_api/live_execution.py::futures_cancel_post_exchange_submission_reconciliation_contract",
            "application/admin_api/live_execution.py::futures_reconcile_post_exchange_submission_reconciliation_contract",
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
            '"risk_proof_semantic_validator_input_schema_count"',
            '"risk_proof_semantic_validator_output_schema_count"',
            '"semantic_contract_definitions"',
            '"semantic_contract_validation_gates"',
            '"semantic_contract_validator_contracts"',
            '"semantic_validator_input_schemas"',
            '"semantic_validator_output_schemas"',
            '"semantic_contract_definition_ref"',
            '"definition_ready": false',
            '"validation_ready": false',
            '"runtime_evidence_satisfies_definition": false',
            '"validation_contract_ref"',
            '"validator_registered": false',
            '"runtime_evidence_satisfies_validation": false',
            '"validator_input_schema_ref"',
            '"validator_output_schema_ref"',
            '"input_schema_registered": false',
            '"output_schema_registered": false',
            '"runtime_evidence_satisfies_input_schema": false',
            '"runtime_evidence_satisfies_output_schema": false',
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


def _check_futures_resolved_contracts_not_reported_missing() -> QueueCheck:
    body = (
        FUTURES_PERPETUALS_EXAMPLES_DOC.read_text(encoding="utf-8")
        if FUTURES_PERPETUALS_EXAMPLES_DOC.exists()
        else ""
    )
    risk_guard_ref = (
        "application/admin_api/futures_risk_guard.py::"
        "evaluate_futures_margin_collateral_liquidation"
    )
    reconciliation_ref = (
        "application/admin_api/futures_reconciliation.py::"
        "record_futures_reconciliation_plan"
    )
    route_refs = (
        "api/v1/routes/futures.py::futures_place_route_contract",
        "api/v1/routes/futures.py::futures_close_reduce_route_contract",
        "api/v1/routes/futures.py::futures_cancel_route_contract",
        "api/v1/routes/futures.py::futures_reconcile_route_contract",
    )
    live_adapter_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_contract",
    )
    live_adapter_construction_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_construction_contract",
    )
    live_adapter_decision_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_contract",
    )
    live_adapter_decision_record_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_record_contract",
    )
    live_adapter_invocation_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_invocation_contract",
    )
    live_adapter_execution_refs = (
        "application/admin_api/live_execution.py::futures_place_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_execution_contract",
    )
    coinbase_exchange_submission_refs = (
        "application/admin_api/live_execution.py::futures_place_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_cancel_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_reconcile_coinbase_exchange_submission_contract",
    )
    post_exchange_submission_reconciliation_refs = (
        "application/admin_api/live_execution.py::futures_place_post_exchange_submission_reconciliation_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_post_exchange_submission_reconciliation_contract",
        "application/admin_api/live_execution.py::futures_cancel_post_exchange_submission_reconciliation_contract",
        "application/admin_api/live_execution.py::futures_reconcile_post_exchange_submission_reconciliation_contract",
    )
    stale_patterns: list[str] = []
    for label, contract_ref in (
        ("risk_guard", risk_guard_ref),
        ("reconciliation", reconciliation_ref),
        *(
            (f"route_contract_{index}", route_ref)
            for index, route_ref in enumerate(route_refs, start=1)
        ),
        *(
            (f"live_adapter_contract_{index}", live_adapter_ref)
            for index, live_adapter_ref in enumerate(live_adapter_refs, start=1)
        ),
        *(
            (f"live_adapter_construction_contract_{index}", construction_ref)
            for index, construction_ref in enumerate(
                live_adapter_construction_refs,
                start=1,
            )
        ),
        *(
            (f"live_adapter_decision_contract_{index}", decision_ref)
            for index, decision_ref in enumerate(live_adapter_decision_refs, start=1)
        ),
        *(
            (f"live_adapter_decision_record_contract_{index}", decision_record_ref)
            for index, decision_record_ref in enumerate(
                live_adapter_decision_record_refs,
                start=1,
            )
        ),
        *(
            (f"live_adapter_invocation_contract_{index}", invocation_ref)
            for index, invocation_ref in enumerate(
                live_adapter_invocation_refs,
                start=1,
            )
        ),
        *(
            (f"live_adapter_execution_contract_{index}", execution_ref)
            for index, execution_ref in enumerate(
                live_adapter_execution_refs,
                start=1,
            )
        ),
        *(
            (
                f"coinbase_exchange_submission_contract_{index}",
                submission_ref,
            )
            for index, submission_ref in enumerate(
                coinbase_exchange_submission_refs,
                start=1,
            )
        ),
    ):
        if re.search(
            r'"missing_backend_contracts"\s*:\s*\[[^\]]*'
            + re.escape(contract_ref),
            body,
            flags=re.DOTALL,
        ):
            stale_patterns.append(f"{label}_ref_in_missing_backend_contracts")
        if f'"next_required_backend_contract": "{contract_ref}"' in body:
            stale_patterns.append(
                f"{label}_ref_as_next_required_backend_contract"
            )
        if re.search(
            r'"step"\s*:\s*"define_backend_command_service"'
            r'(?:(?!"step"\s*:)[\s\S]){0,600}'
            r'"required_backend_contract"\s*:\s*"'
            + re.escape(contract_ref)
            + r'"',
            body,
        ):
            stale_patterns.append(
                f"{label}_ref_as_define_backend_command_service_contract"
            )
    missing_live_adapter_refs = [
        contract_ref for contract_ref in live_adapter_refs if contract_ref not in body
    ]
    missing_live_adapter_construction_refs = [
        contract_ref
        for contract_ref in live_adapter_construction_refs
        if contract_ref not in body
    ]
    missing_live_adapter_decision_refs = [
        contract_ref
        for contract_ref in live_adapter_decision_refs
        if contract_ref not in body
    ]
    missing_live_adapter_decision_record_refs = [
        contract_ref
        for contract_ref in live_adapter_decision_record_refs
        if contract_ref not in body
    ]
    missing_live_adapter_invocation_refs = [
        contract_ref
        for contract_ref in live_adapter_invocation_refs
        if contract_ref not in body
    ]
    missing_live_adapter_execution_refs = [
        contract_ref
        for contract_ref in live_adapter_execution_refs
        if contract_ref not in body
    ]
    missing_coinbase_exchange_submission_refs = [
        contract_ref
        for contract_ref in coinbase_exchange_submission_refs
        if contract_ref not in body
    ]
    missing_post_exchange_submission_reconciliation_refs = [
        contract_ref
        for contract_ref in post_exchange_submission_reconciliation_refs
        if contract_ref not in body
    ]
    post_exchange_submission_reconciliation_refs_reported_missing = [
        contract_ref
        for contract_ref in post_exchange_submission_reconciliation_refs
        if re.search(
            r'"missing_backend_contracts"\s*:\s*\[[^\]]*'
            + re.escape(contract_ref),
            body,
            flags=re.DOTALL,
        )
    ]
    return QueueCheck(
        name="futures_resolved_contracts_not_reported_missing",
        passed=FUTURES_PERPETUALS_EXAMPLES_DOC.exists()
        and not stale_patterns
        and not missing_live_adapter_refs
        and not missing_live_adapter_construction_refs
        and not missing_live_adapter_decision_refs
        and not missing_live_adapter_decision_record_refs
        and not missing_live_adapter_invocation_refs
        and not missing_live_adapter_execution_refs
        and not missing_coinbase_exchange_submission_refs
        and not missing_post_exchange_submission_reconciliation_refs
        and not post_exchange_submission_reconciliation_refs_reported_missing,
        evidence={
            "path": str(FUTURES_PERPETUALS_EXAMPLES_DOC.relative_to(PROJECT_ROOT)),
            "stale_patterns": stale_patterns,
            "missing_live_adapter_refs": missing_live_adapter_refs,
            "missing_live_adapter_construction_refs": (
                missing_live_adapter_construction_refs
            ),
            "missing_live_adapter_decision_refs": missing_live_adapter_decision_refs,
            "missing_live_adapter_decision_record_refs": (
                missing_live_adapter_decision_record_refs
            ),
            "missing_live_adapter_invocation_refs": (
                missing_live_adapter_invocation_refs
            ),
            "missing_live_adapter_execution_refs": (
                missing_live_adapter_execution_refs
            ),
            "missing_coinbase_exchange_submission_refs": (
                missing_coinbase_exchange_submission_refs
            ),
            "missing_post_exchange_submission_reconciliation_refs": (
                missing_post_exchange_submission_reconciliation_refs
            ),
            "post_exchange_submission_reconciliation_refs_reported_missing": (
                post_exchange_submission_reconciliation_refs_reported_missing
            ),
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
        ADMIN_MODULE_CAPABILITY_MATRIX_DOC: [
            f"Current futures/perpetual M57 scope: `{APPROVED_PHASE_RANGE}`",
            "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item evidence",
            "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency evidence",
            "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation evidence",
            "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation evidence",
            "futures request payload validation record execution-eligibility resolution-plan step review input store record-contract evidence",
            "futures request payload validation record execution-eligibility resolution-plan step review input store requirement evidence",
            "resolution plan step review input store record-validation remediation dependency work-item presence",
            "resolution plan step review input store record-validation remediation dependency presence",
            "resolution plan step review input store record-validation remediation presence",
            "resolution plan step review input store record-validation presence",
            "resolution plan step review input store record-contract presence",
            "create dependency graphs",
            "create work items",
            "claim work",
            "create stores",
            "configure writers",
            "create record keys",
            "enable validation or replay gates",
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
        f"Active approved range: `{APPROVED_PHASE_RANGE}`",
        f"Latest completed and pushed range before this work: `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
        "futures command risk-proof requirement summary evidence",
        "risk_proof_requirement_summaries",
        "risk-proof requirement summaries cannot accept risk proofs",
        "register proof routes",
        "enable proof writers",
        "clear command enablement",
        "approval passage",
        "cap/guard passage",
        "reconciliation passage",
        "admission, Coinbase execution",
        "Coinbase execution",
        "browser/BFF",
        "spot-rule authority",
    ]
    stale = [
        f"API active approved phase range remains `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
        f"approved_phase_range: \"{PREVIOUS_COMPLETED_PHASE_RANGE}\"",
        f"validator evidence make `{PREVIOUS_COMPLETED_PHASE_RANGE}` the active range",
        f"now leads with `{PREVIOUS_COMPLETED_PHASE_RANGE}`",
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
    heading, first_section = _first_review_section(body)
    has_pass_result = (
        "Result: PASS." in first_section
        or "Result: PASS after remediation." in first_section
        or "Result: PASS after hygiene remediation." in first_section
        or "Result: PASS after phase-close verification." in first_section
    )
    has_pending_result = (
        "Result: pending." in first_section
        or "Result: PENDING." in first_section
        or "Result: planned." in first_section
        or "Result: PLANNED." in first_section
    )
    section = first_section
    required = [
        APPROVED_PHASE_RANGE,
        PREVIOUS_COMPLETED_PHASE_RANGE,
        "completed history",
        "No live Coinbase execution is planned",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item display",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency display",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation display",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-validation display",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-contract evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store record-contract display",
        "futures request payload validation record execution-eligibility resolution-plan step review input store requirement evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input store requirement display",
        "futures request payload validation record execution-eligibility resolution-plan step review input evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review input display",
        "futures request payload validation record execution-eligibility resolution-plan step review evidence",
        "futures request payload validation record execution-eligibility resolution-plan step review display",
        "futures request payload validation record execution-eligibility resolution-plan step evidence",
        "futures request payload validation record execution-eligibility resolution-plan step display",
        "futures request payload validation record execution-eligibility resolution-plan evidence",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies.py",
        "application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items.py",
        "execution_eligibility_resolution_plan_ref",
        "execution_eligibility_resolution_plan_contract_ref",
        "execution_eligibility_resolution_plan_step_ref",
        "execution_eligibility_resolution_plan_step_contract_ref",
        "execution_eligibility_resolution_plan_step_review_ref",
        "execution_eligibility_resolution_plan_step_review_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_ref",
        "execution_eligibility_resolution_plan_step_review_input_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_requirement_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_contract_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref",
        "execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref",
        "review_input_store_record_validation_remediation_dependency_kind",
        "review_input_store_record_validation_remediation_dependency_work_item_kind",
        "record_validation_remediation_dependency_gate",
        "record_validation_remediation_dependency_work_item_gate",
        "record_validation_remediation_dependency_required=true",
        "record_validation_remediation_dependency_ready=false",
        "record_validation_remediation_dependency_resolved=false",
        "record_validation_remediation_dependency_performed=false",
        "record_validation_remediation_dependency_graph_ready=false",
        "record_validation_remediation_dependency_work_item_created=false",
        "record_validation_remediation_dependency_work_item_claimed=false",
        "record_validation_remediation_dependency_claim_trace_created=false",
        "record_validation_remediation_dependency_work_item_required=true",
        "record_validation_remediation_dependency_work_item_ready=false",
        "record_validation_remediation_dependency_work_item_created=false",
        "record_validation_remediation_dependency_work_item_claimed=false",
        "claim_ledger_registered=false",
        "owner_review_accepted=false",
        "contextless_review_passed=false",
        "accepts_evidence=false",
        "writes_evidence=false",
        "claim_trace_created=false",
        "claim_trace_ready=false",
        "claim_allowed=false",
        "claim_resolved=false",
        "claim_review_accepted=false",
        "clearance_plan_created=false",
        "clearance_plan_ready=false",
        "clearance_plan_sequence_ready=false",
        "resolution_plan_step_kind",
        "resolution_plan_step_ready=false",
        "resolution_plan_step_accepted=false",
        "resolution_plan_step_review_required=true",
        "resolution_plan_step_review_ready=false",
        "resolution_plan_step_reviewed=false",
        "resolution_plan_step_review_accepted=false",
        "review_input_kind",
        "review_input_index",
        "input_evidence_store",
        "resolution_plan_step_review_input_required=true",
        "resolution_plan_step_review_input_present=false",
        "resolution_plan_step_review_input_accepted=false",
        "resolution_plan_step_review_input_validated=false",
        "resolution_plan_step_review_input_store_requirement_required=true",
        "resolution_plan_step_review_input_store_available=false",
        "resolution_plan_step_review_input_writer_available=false",
        "resolution_plan_step_review_input_record_key_available=false",
        "resolution_plan_step_review_input_validation_gate_ready=false",
        "resolution_plan_step_review_input_replay_gate_ready=false",
        "record_contract_required=true",
        "record_contract_available=false",
        "record_validation_required=true",
        "record_validation_ready=false",
        "record_validation_configured=false",
        "record_validation_registered=false",
        "record_validation_gate_ready=false",
        "record_validation_gate_passed=false",
        "record_validation_accepted=false",
        "record_validation_recorded=false",
        "record_schema_available=false",
        "append_only_log_available=false",
        "idempotency_key_bound=false",
        "payload_schema_validated=false",
        "replay_protected=false",
        "store_available=false",
        "writer_available=false",
        "writer_allowed=false",
        "write_allowed=false",
        "record_present=false",
        "record_accepted=false",
        "record_validated=false",
        "validation_configured=false",
        "replay_protection_configured=false",
        "ordered_resolution_step_refs",
        "ordered_resolution_step_count",
        "resolution_plan_present=true",
        "resolution_plan_ready=false",
        "resolution_plan_accepted=false",
        "runtime_evidence_satisfies_semantic_contract=false",
        "validation_record_admission_link_ready=false",
        "blocker_resolved=false",
        "dependency work-item claim-trace clearance-plan presence is not claim-trace clearance",
        "dependency work-item claim-trace presence is not dependency resolution",
        "dependency work-item presence is not dependency resolution",
        "resolution plan step review input store record-validation remediation dependency presence is not blocker resolution",
        "resolution plan step review input store record-validation remediation presence is not blocker resolution",
        "resolution plan step review input store record-validation presence is not blocker resolution",
        "resolution plan step review input store record-contract presence is not blocker resolution",
        "resolution plan step review input store requirement presence is not blocker resolution",
        "resolution plan step review input presence is not blocker resolution",
        "resolution plan step review presence is not blocker resolution",
        "Fresh blind/contextless backend re-review",
        "Fresh blind/contextless frontend re-review",
        "Phase-end stale-subagent sweep completed",
        "no dependency graph creation",
        "no work item creation",
        "no claim trace creation",
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
    if has_pending_result or has_pass_result:
        required = [
            APPROVED_PHASE_RANGE,
            PREVIOUS_COMPLETED_PHASE_RANGE,
            "completed history",
            "No live Coinbase execution is planned",
            "actual submitted/executed notional remains `0` USDC",
            "Boundary evidence for current",
            "futures command risk-proof requirement summary evidence",
            "risk_proof_requirement_summaries",
            "not risk-proof acceptance",
            "not proof-route registration",
            "not proof-writer enablement",
            "not command enablement clearance",
            "not Coinbase execution",
            "not reconciliation execution",
            "not futures/order/exchange state mutation",
            "not browser authority",
            "not BFF execution authority",
            "not spot-rule authority",
        ]
    missing = [text for text in required if text not in section]
    if not has_pass_result and not has_pending_result:
        missing.append("Result: PASS/PENDING/PLANNED")
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
