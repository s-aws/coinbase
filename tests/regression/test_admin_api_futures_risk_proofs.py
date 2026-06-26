from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import futures as futures_routes
from api.v1.routes.orders import _idempotency_payload_hash
from application.admin_api.approval import (
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.cap_guard import (
    CapGuardDecisionRecord,
    FileAdminApiCapGuardStore,
)
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.futures_risk_proof import FileFuturesRiskProofStore
from application.admin_api.futures_command_service import (
    AdminApiFuturesCommandService,
    FUTURES_COMMAND_SERVICE_CONTRACTS,
    FuturesCommandServiceDisabledError,
)
from application.admin_api.futures_proof_payload_fields import (
    FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS,
    iter_futures_proof_payload_field_contracts,
)
from application.admin_api.futures_proof_routes import FUTURES_PROOF_ROUTE_CONTRACTS
from application.admin_api.futures_proof_writer import FUTURES_PROOF_WRITER_CONTRACTS
from application.admin_api.futures_request_payload_contracts import (
    FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS,
    iter_futures_request_payload_contracts,
)
from application.admin_api.futures_request_payload_validators import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS,
    iter_futures_request_payload_validator_contracts,
)
from application.admin_api.futures_request_payload_validator_input_schemas import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS,
    iter_futures_request_payload_validator_input_schemas,
)
from application.admin_api.futures_request_payload_validator_output_schemas import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS,
    iter_futures_request_payload_validator_output_schemas,
)
from application.admin_api.futures_request_payload_validator_registrations import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS,
    iter_futures_request_payload_validator_registrations,
)
from application.admin_api.futures_request_payload_validation_evidence import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS,
    iter_futures_request_payload_validation_evidence,
)
from application.admin_api.futures_request_payload_validation_evidence_records import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS,
    iter_futures_request_payload_validation_evidence_records,
)
from application.admin_api.futures_request_payload_validation_record_schemas import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS,
    iter_futures_request_payload_validation_record_schemas,
)
from application.admin_api.futures_request_payload_validation_record_replay_guards import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS,
    iter_futures_request_payload_validation_record_replay_guards,
)
from application.admin_api.futures_request_payload_validation_record_audit_links import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS,
    iter_futures_request_payload_validation_record_audit_links,
)
from application.admin_api.futures_request_payload_validation_record_admission_links import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS,
    iter_futures_request_payload_validation_record_admission_links,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibilities import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS,
    iter_futures_request_payload_validation_record_execution_eligibilities,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_blockers import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS,
    iter_futures_request_payload_validation_record_execution_eligibility_blockers,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plans import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CONTRACTS,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifacts import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifacts,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_definitions import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_definitions,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_definition_reviews import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_definition_reviews,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_definition_review_inputs import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_definition_review_outputs import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_runtime_evidences import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences,
)
from application.admin_api.futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS,
    iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances,
)
from application.admin_api.futures_request_payload_validation_record_position_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_position_semantics,
)
from application.admin_api.futures_request_payload_validation_record_margin_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_margin_semantics,
)
from application.admin_api.futures_request_payload_validation_record_collateral_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_collateral_semantics,
)
from application.admin_api.futures_request_payload_validation_record_liquidation_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_liquidation_semantics,
)
from application.admin_api.futures_request_payload_validation_record_reduce_only_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_reduce_only_semantics,
)
from application.admin_api.futures_request_payload_validation_record_close_only_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_close_only_semantics,
)
from application.admin_api.futures_request_payload_validation_record_funding_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_funding_semantics,
)
from application.admin_api.futures_request_payload_validation_record_order_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_order_semantics,
)
from application.admin_api.futures_request_payload_validation_record_cancel_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_cancel_semantics,
)
from application.admin_api.futures_request_payload_validation_record_reconciliation_semantics import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS,
    iter_futures_request_payload_validation_record_reconciliation_semantics,
)
from application.admin_api.futures_reconciliation import (
    AdminApiFuturesReconciliation,
    FUTURES_RECONCILIATION_CONTRACT,
    FuturesReconciliationDisabledError,
)
from application.admin_api.futures_route_contracts import (
    FUTURES_ROUTE_CONTRACTS,
    futures_coinbase_exchange_submission_contract_ref,
    futures_live_adapter_contract_ref,
    futures_live_adapter_construction_contract_ref,
    futures_live_adapter_decision_contract_ref,
    futures_live_adapter_decision_record_contract_ref,
    futures_live_adapter_execution_contract_ref,
    futures_live_adapter_invocation_contract_ref,
    futures_post_exchange_submission_reconciliation_contract_ref,
)
from application.admin_api.futures_risk_guard import (
    AdminApiFuturesRiskGuard,
    FUTURES_RISK_GUARD_CONTRACT,
    FuturesRiskGuardDisabledError,
)
from application.admin_api.futures_risk_proof_service import (
    AdminApiFuturesRiskProofService,
    FuturesRiskProofError,
)
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import (
    FUTURES_COINBASE_EXCHANGE_SUBMISSION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS,
    FUTURES_LIVE_ADAPTER_EXECUTION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACTS,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON,
    get_disabled_live_execution_service,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminLiveAdmissionDecisionEvidence,
    FuturesRiskProofRecordRequest,
)
from application.admin_api.read_service import (
    AdminApiReadService,
    FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
    FUTURES_RISK_PROOF_REQUIREMENT_API_EXCLUDE,
    futures_command_suite_api_payload,
)
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
    AdminApiRole,
    AdminFuturesCommandAction,
    AdminFuturesCommandEnablementBlocker,
    AdminFuturesCommandEvidenceRoute,
    AdminFuturesCommandExecutionEligibilityBlocker,
    AdminFuturesCommandReadinessClosureStep,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandRiskProofAcceptanceBlocker,
    AdminFuturesCommandRiskProofKind,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
    AdminFuturesRiskProofEvidenceSource,
    OrderSide,
    OrderType,
    TimeInForce,
)

# This file imports the full FastAPI app/route graph. Keep it in the serial
# regression lane so xdist cannot multiply the route-model memory footprint.
pytestmark = pytest.mark.serial


PAYLOAD_HASH = "a" * 64


def test_futures_command_service_contracts_are_disabled() -> None:
    service = AdminApiFuturesCommandService()

    assert set(FUTURES_COMMAND_SERVICE_CONTRACTS) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    }
    assert (
        FUTURES_COMMAND_SERVICE_CONTRACTS[
            AdminFuturesCommandAction.PLACE
        ].contract_ref
        == "application/admin_api/futures_command_service.py::place_futures_order"
    )
    assert (
        FUTURES_COMMAND_SERVICE_CONTRACTS[
            AdminFuturesCommandAction.RECONCILE
        ].contract_ref
        == (
            "application/admin_api/futures_command_service.py::"
            "reconcile_futures_position"
        )
    )

    with pytest.raises(FuturesCommandServiceDisabledError) as exc_info:
        service.place_futures_order()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "Coinbase calls" in message

    with pytest.raises(FuturesCommandServiceDisabledError) as exc_info:
        service.reconcile_futures_position()

    message = str(exc_info.value)
    assert "reconcile_futures_position" in message
    assert "reconciliation execution" in message
    assert "Coinbase calls" in message


def test_futures_risk_proof_route_and_writer_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()
    emitted_route_refs: set[str] = set()
    emitted_writer_refs: set[str] = set()

    assert len(FUTURES_PROOF_ROUTE_CONTRACTS) == 20
    assert len(FUTURES_PROOF_WRITER_CONTRACTS) == 20
    assert set(FUTURES_PROOF_ROUTE_CONTRACTS) == set(FUTURES_PROOF_WRITER_CONTRACTS)

    for (command, proof_kind), route_contract in FUTURES_PROOF_ROUTE_CONTRACTS.items():
        writer_contract = FUTURES_PROOF_WRITER_CONTRACTS[(command, proof_kind)]
        assert route_contract.command == command
        assert route_contract.proof_kind == proof_kind
        assert route_contract.method_name == (
            f"post_{command.value}_{proof_kind.value}_proof"
        )
        assert route_contract.contract_ref == (
            "application/admin_api/futures_proof_routes.py::"
            f"post_{command.value}_{proof_kind.value}_proof"
        )
        assert route_contract.route_path == (
            f"/api/v1/futures/proofs/{command.value}/{proof_kind.value}"
        )
        assert route_contract.method == "POST"
        assert route_contract.route_registered is False
        assert route_contract.proof_payloads_accepted is False
        assert route_contract.command_route_registered is False
        assert route_contract.command_draft_allowed is False
        assert route_contract.execution_allowed is False
        assert route_contract.live_coinbase_orders_ran is False

        assert writer_contract.command == command
        assert writer_contract.proof_kind == proof_kind
        assert writer_contract.method_name == (
            f"write_{command.value}_{proof_kind.value}_proof"
        )
        assert writer_contract.contract_ref == (
            "application/admin_api/futures_proof_writer.py::"
            f"write_{command.value}_{proof_kind.value}_proof"
        )
        assert writer_contract.method == "LOCAL"
        assert writer_contract.writer_enabled is False
        assert writer_contract.proof_records_accepted is False
        assert writer_contract.proof_records_write_allowed is False
        assert writer_contract.command_route_registered is False
        assert writer_contract.command_draft_allowed is False
        assert writer_contract.execution_allowed is False
        assert writer_contract.live_coinbase_orders_ran is False

    for command in command_suite.commands:
        for proof_requirement in command.risk_proof_requirements:
            route_contract = FUTURES_PROOF_ROUTE_CONTRACTS[
                (command.command, proof_requirement.proof_kind)
            ]
            writer_contract = FUTURES_PROOF_WRITER_CONTRACTS[
                (command.command, proof_requirement.proof_kind)
            ]
            assert proof_requirement.proof_contract_count == 2
            assert proof_requirement.blocking_proof_contract_count == 2
            assert proof_requirement.registered_proof_route_count == 0
            assert proof_requirement.enabled_proof_writer_count == 0
            assert proof_requirement.proof_contracts[0].required_backend_contract == (
                route_contract.contract_ref
            )
            assert proof_requirement.proof_contracts[0].required_route_path == (
                route_contract.route_path
            )
            assert proof_requirement.proof_contracts[0].required_method == (
                route_contract.method
            )
            assert proof_requirement.proof_contracts[0].route_registered is False
            assert proof_requirement.proof_contracts[0].proof_route_registered is False
            assert proof_requirement.proof_contracts[1].required_backend_contract == (
                writer_contract.contract_ref
            )
            assert proof_requirement.proof_contracts[1].required_method == (
                writer_contract.method
            )
            assert proof_requirement.proof_contracts[1].writer_enabled is False
            assert proof_requirement.proof_contracts[1].proof_writer_enabled is False
            assert all(
                contract.execution_allowed is False
                and contract.command_route_registered is False
                and contract.command_draft_allowed is False
                and contract.backend_owned is True
                and contract.browser_authority == "display_only"
                and contract.bff_authority == "forward_only_no_execution"
                for contract in proof_requirement.proof_contracts
            )
            emitted_route_refs.add(route_contract.contract_ref)
            emitted_writer_refs.add(writer_contract.contract_ref)

    assert emitted_route_refs == {
        contract.contract_ref for contract in FUTURES_PROOF_ROUTE_CONTRACTS.values()
    }
    assert emitted_writer_refs == {
        contract.contract_ref for contract in FUTURES_PROOF_WRITER_CONTRACTS.values()
    }


def test_futures_risk_proof_payload_field_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS) == 10
    first_payload_fields = command_suite.commands[0].risk_proof_requirements[
        0
    ].payload_fields
    assert [contract.sequence for contract in first_payload_fields] == list(
        range(1, 11)
    )
    assert all(
        contract.payload_field_present is False
        and contract.validation_registered is False
        and contract.command_route_registered is False
        and contract.command_draft_allowed is False
        and contract.execution_allowed is False
        and contract.proof_route_registered is False
        and contract.proof_writer_enabled is False
        and contract.live_coinbase_orders_ran is False
        for contract in FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS
    )

    for command in command_suite.commands:
        for proof_requirement in command.risk_proof_requirements:
            registry_rows = list(
                iter_futures_proof_payload_field_contracts(
                    command=command.command,
                    proof_kind=proof_requirement.proof_kind,
                    identity_key=command.identity_key,
                )
            )
            assert proof_requirement.payload_field_count == len(registry_rows)
            assert proof_requirement.blocking_payload_field_count == len(
                registry_rows
            )
            assert proof_requirement.present_payload_field_count == 0
            for emitted, (
                contract,
                validation_rule,
                required_evidence_ref,
            ) in zip(proof_requirement.payload_fields, registry_rows, strict=True):
                assert emitted.field == contract.field
                assert emitted.payload_path == contract.payload_path
                assert emitted.validation_rule == validation_rule
                assert emitted.required_evidence_ref == required_evidence_ref
                assert emitted.missing_evidence_ref == required_evidence_ref
                assert emitted.payload_field_present is False
                assert emitted.validation_registered is False
                assert emitted.command_route_registered is False
                assert emitted.command_draft_allowed is False
                assert emitted.execution_allowed is False
                assert emitted.proof_route_registered is False
                assert emitted.proof_writer_enabled is False
                assert emitted.backend_owned is True
                assert emitted.read_only is True
                assert emitted.spot_rule_authority is False
                assert emitted.browser_authority == "display_only"
                assert emitted.bff_authority == "forward_only_no_execution"


def test_futures_request_payload_field_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS) == 22
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
    )
    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.spot_rule_authority is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.validation_registered is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_gate_ref.endswith("_request_payload_validation_gate")
        and contract.validator_contract_ref.endswith(
            "_request_payload_validator_contract"
        )
        and contract.validator_registration_ref.endswith(
            "_request_payload_validator_registration"
        )
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.spot_rule_authority is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.validation_gate_ready is False
        and contract.validation_gate_passed is False
        and contract.validator_contract_registered is False
        and contract.validator_input_schema_registered is False
        and contract.validator_output_schema_registered is False
        and contract.validator_registered is False
        and contract.request_payload_validated is False
        and contract.live_coinbase_orders_ran is False
        and contract.validator_contract_ref.endswith(
            "_request_payload_validator_contract"
        )
        and contract.validator_input_schema_ref.endswith(
            "_request_payload_validator_input_schema"
        )
        and contract.validator_output_schema_ref.endswith(
            "_request_payload_validator_output_schema"
        )
        and contract.validator_registration_ref.endswith(
            "_request_payload_validator_registration"
        )
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.input_schema_registered is False
        and contract.validator_contract_registered is False
        and contract.validator_registered is False
        and contract.request_payload_validated is False
        and contract.live_coinbase_orders_ran is False
        and contract.validator_input_schema_ref.endswith(
            "_request_payload_validator_input_schema"
        )
        and len(contract.input_schema_field_refs) == 5
        and all(
            field_ref.startswith(contract.validator_input_schema_ref)
            for field_ref in contract.input_schema_field_refs
        )
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.output_schema_registered is False
        and contract.validator_contract_registered is False
        and contract.validator_registered is False
        and contract.request_payload_validated is False
        and contract.live_coinbase_orders_ran is False
        and contract.validator_output_schema_ref.endswith(
            "_request_payload_validator_output_schema"
        )
        and contract.validator_output_schema_ref.startswith(
            "application/admin_api/futures_request_payload_validator_output_schemas.py::"
        )
        and len(contract.output_schema_field_refs) == 5
        and all(
            field_ref.startswith(contract.validator_output_schema_ref)
            for field_ref in contract.output_schema_field_refs
        )
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validator_registration is False
        and contract.validator_contract_registered is False
        and contract.input_schema_registered is False
        and contract.output_schema_registered is False
        and contract.validator_registration_ready is False
        and contract.validator_registered is False
        and contract.request_payload_validated is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validator_registration_ref.endswith(
            "_request_payload_validator_registration"
        )
        and contract.validator_registration_ref.startswith(
            "application/admin_api/futures_request_payload_validator_registrations.py::"
        )
        and len(contract.validator_registration_field_refs) == 6
        and all(
            field_ref.startswith(contract.validator_registration_ref)
            for field_ref in contract.validator_registration_field_refs
        )
        and len(contract.required_evidence_refs) == 6
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validation_evidence is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_gate_ready is False
        and contract.validation_gate_passed is False
        and contract.validator_registration_ready is False
        and contract.validator_registered is False
        and contract.request_payload_validated is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_evidence_contract_ref.endswith(
            "_request_payload_validation_evidence"
        )
        and contract.validation_evidence_contract_ref.startswith(
            "application/admin_api/futures_request_payload_validation_evidence.py::"
        )
        and len(contract.validation_evidence_field_refs) == 6
        and all(
            field_ref.startswith(contract.validation_evidence_contract_ref)
            for field_ref in contract.validation_evidence_field_refs
        )
        and len(contract.required_evidence_refs) == 7
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validation_record is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.validation_record_idempotency_bound is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_contract_ref.endswith(
            "_request_payload_validation_evidence_record"
        )
        and contract.validation_record_contract_ref.startswith(
            "application/admin_api/futures_request_payload_validation_evidence_records.py::"
        )
        and contract.validation_record_store_ref.endswith(
            "_request_payload_validation_evidence_record_store"
        )
        and contract.validation_record_writer_ref.endswith(
            "_request_payload_validation_evidence_record_writer"
        )
        and contract.validation_record_replay_guard_ref.endswith(
            "_request_payload_validation_evidence_record_replay_guard"
        )
        and len(contract.validation_record_field_refs) == 8
        and all(
            field_ref.startswith(contract.validation_record_contract_ref)
            for field_ref in contract.validation_record_field_refs
        )
        and len(contract.required_evidence_refs) == 11
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validation_record_schema is False
        and contract.validation_record_schema_ready is False
        and contract.validation_record_schema_registered is False
        and contract.validation_record_append_only_log_ready is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.validation_record_idempotency_bound is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_schema_ref.endswith(
            "_request_payload_validation_record_schema"
        )
        and contract.validation_record_schema_ref.startswith(
            "application/admin_api/futures_request_payload_validation_record_schemas.py::"
        )
        and contract.validation_record_append_only_log_ref.endswith(
            "_request_payload_validation_record_schema_append_only_log"
        )
        and len(contract.validation_record_schema_field_refs) == 10
        and all(
            field_ref.startswith(contract.validation_record_schema_ref)
            for field_ref in contract.validation_record_schema_field_refs
        )
        and len(contract.required_evidence_refs) == 10
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validation_record_replay_guard
        is False
        and contract.validation_record_replay_guard_contract_ready is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_record_idempotency_contract_ready is False
        and contract.validation_record_idempotency_bound is False
        and contract.validation_record_replay_protected is False
        and contract.validation_record_schema_ready is False
        and contract.validation_record_schema_registered is False
        and contract.validation_record_append_only_log_ready is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_replay_guard_contract_ref.endswith(
            "_request_payload_validation_record_replay_guard"
        )
        and contract.validation_record_replay_guard_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_replay_guards.py::"
        )
        and contract.validation_record_idempotency_contract_ref.endswith(
            "_request_payload_validation_record_replay_guard_idempotency_contract"
        )
        and contract.validation_record_replay_window_ref.endswith(
            "_request_payload_validation_record_replay_guard_replay_window"
        )
        and contract.validation_record_duplicate_policy_ref.endswith(
            "_request_payload_validation_record_replay_guard_duplicate_policy"
        )
        and len(contract.validation_record_replay_guard_field_refs) == 11
        and all(
            field_ref.startswith(contract.validation_record_replay_guard_contract_ref)
            for field_ref in contract.validation_record_replay_guard_field_refs
        )
        and len(contract.required_evidence_refs) == 13
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_validation_record_audit_link is False
        and contract.validation_record_audit_link_contract_ready is False
        and contract.validation_record_audit_link_ready is False
        and contract.validation_record_actor_bound is False
        and contract.validation_record_operator_intent_bound is False
        and contract.validation_record_correlation_bound is False
        and contract.validation_record_admission_audit_bound is False
        and contract.validation_record_audit_recorded is False
        and contract.validation_record_replay_guard_contract_ready is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_record_idempotency_contract_ready is False
        and contract.validation_record_idempotency_bound is False
        and contract.validation_record_replay_protected is False
        and contract.validation_record_schema_ready is False
        and contract.validation_record_schema_registered is False
        and contract.validation_record_append_only_log_ready is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_audit_link_contract_ref.endswith(
            "_request_payload_validation_record_audit_link"
        )
        and contract.validation_record_audit_link_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_audit_links.py::"
        )
        and contract.validation_record_actor_ref.endswith(
            "_request_payload_validation_record_audit_link_actor"
        )
        and contract.validation_record_operator_intent_ref.endswith(
            "_request_payload_validation_record_audit_link_operator_intent"
        )
        and contract.validation_record_correlation_ref.endswith(
            "_request_payload_validation_record_audit_link_correlation"
        )
        and contract.validation_record_admission_audit_ref.endswith(
            "_request_payload_validation_record_audit_link_admission_audit"
        )
        and contract.validation_record_audit_record_ref.endswith(
            "_request_payload_validation_record_audit_link_audit_record"
        )
        and len(contract.validation_record_audit_link_field_refs) == 11
        and all(
            field_ref.startswith(contract.validation_record_audit_link_contract_ref)
            for field_ref in contract.validation_record_audit_link_field_refs
        )
        and len(contract.required_evidence_refs) == 17
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and (
            contract.runtime_evidence_satisfies_validation_record_admission_link
            is False
        )
        and contract.validation_record_admission_link_contract_ready is False
        and contract.validation_record_admission_link_ready is False
        and contract.validation_record_approval_snapshot_bound is False
        and contract.validation_record_cap_guard_decision_bound is False
        and contract.validation_record_reconciliation_plan_bound is False
        and contract.validation_record_live_intent_bound is False
        and contract.validation_record_command_admission_bound is False
        and contract.validation_record_admitted is False
        and contract.validation_record_audit_link_contract_ready is False
        and contract.validation_record_audit_link_ready is False
        and contract.validation_record_actor_bound is False
        and contract.validation_record_operator_intent_bound is False
        and contract.validation_record_correlation_bound is False
        and contract.validation_record_admission_audit_bound is False
        and contract.validation_record_audit_recorded is False
        and contract.validation_record_replay_guard_contract_ready is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_record_idempotency_contract_ready is False
        and contract.validation_record_idempotency_bound is False
        and contract.validation_record_replay_protected is False
        and contract.validation_record_schema_ready is False
        and contract.validation_record_schema_registered is False
        and contract.validation_record_append_only_log_ready is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_admission_link_contract_ref.endswith(
            "_request_payload_validation_record_admission_link"
        )
        and contract.validation_record_admission_link_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_admission_links.py::"
        )
        and contract.validation_record_approval_snapshot_ref.endswith(
            "_request_payload_validation_record_admission_link_approval_snapshot"
        )
        and contract.validation_record_cap_guard_decision_ref.endswith(
            "_request_payload_validation_record_admission_link_cap_guard_decision"
        )
        and contract.validation_record_reconciliation_plan_ref.endswith(
            "_request_payload_validation_record_admission_link_reconciliation_plan"
        )
        and contract.validation_record_live_intent_ref.endswith(
            "_request_payload_validation_record_admission_link_live_intent"
        )
        and contract.validation_record_command_admission_ref.endswith(
            "_request_payload_validation_record_admission_link_command_admission"
        )
        and len(contract.validation_record_admission_link_field_refs) == 12
        and all(
            field_ref.startswith(contract.validation_record_admission_link_contract_ref)
            for field_ref in contract.validation_record_admission_link_field_refs
        )
        and len(contract.required_evidence_refs) == 25
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS
    )
    assert all(
        contract.required is True
        and contract.blocking is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.runtime_evidence_observed is False
        and (
            contract.runtime_evidence_satisfies_validation_record_execution_eligibility
            is False
        )
        and contract.validation_record_execution_eligibility_contract_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.validation_record_position_semantics_ready is False
        and contract.validation_record_margin_semantics_ready is False
        and contract.validation_record_collateral_semantics_ready is False
        and contract.validation_record_liquidation_semantics_ready is False
        and contract.validation_record_reduce_only_semantics_ready is False
        and contract.validation_record_close_only_semantics_ready is False
        and contract.validation_record_funding_semantics_ready is False
        and contract.validation_record_order_semantics_ready is False
        and contract.validation_record_cancel_semantics_ready is False
        and contract.validation_record_reconciliation_semantics_ready is False
        and contract.validation_record_semantic_contracts_present is True
        and contract.validation_record_semantic_contracts_ready is False
        and contract.validation_record_admission_link_contract_ready is False
        and contract.validation_record_admission_link_ready is False
        and contract.validation_record_approval_snapshot_bound is False
        and contract.validation_record_cap_guard_decision_bound is False
        and contract.validation_record_reconciliation_plan_bound is False
        and contract.validation_record_live_intent_bound is False
        and contract.validation_record_command_admission_bound is False
        and contract.validation_record_admitted is False
        and contract.validation_record_audit_link_contract_ready is False
        and contract.validation_record_audit_link_ready is False
        and contract.validation_record_actor_bound is False
        and contract.validation_record_operator_intent_bound is False
        and contract.validation_record_correlation_bound is False
        and contract.validation_record_admission_audit_bound is False
        and contract.validation_record_audit_recorded is False
        and contract.validation_record_replay_guard_contract_ready is False
        and contract.validation_record_replay_guard_ready is False
        and contract.validation_record_idempotency_contract_ready is False
        and contract.validation_record_idempotency_bound is False
        and contract.validation_record_replay_protected is False
        and contract.validation_record_schema_ready is False
        and contract.validation_record_schema_registered is False
        and contract.validation_record_append_only_log_ready is False
        and contract.validation_record_contract_ready is False
        and contract.validation_record_store_ready is False
        and contract.validation_record_writer_enabled is False
        and contract.validation_evidence_ready is False
        and contract.validation_evidence_recorded is False
        and contract.validation_recorded is False
        and contract.append_only_validation_record is False
        and contract.request_payload_validated is False
        and contract.validator_registered is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_execution_eligibility_contract_ref.endswith(
            "_request_payload_validation_record_execution_eligibility"
        )
        and contract.validation_record_execution_eligibility_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibilities.py::"
        )
        and contract.validation_record_position_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_position_semantics"
        )
        and contract.validation_record_margin_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_margin_semantics"
        )
        and contract.validation_record_collateral_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_collateral_semantics"
        )
        and contract.validation_record_liquidation_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_liquidation_semantics"
        )
        and contract.validation_record_reduce_only_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_reduce_only_semantics"
        )
        and contract.validation_record_close_only_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_close_only_semantics"
        )
        and contract.validation_record_funding_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_funding_semantics"
        )
        and contract.validation_record_order_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_order_semantics"
        )
        and contract.validation_record_cancel_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_cancel_semantics"
        )
        and contract.validation_record_reconciliation_semantics_ref.endswith(
            "_request_payload_validation_record_execution_eligibility_reconciliation_semantics"
        )
        and contract.validation_record_position_semantics_contract_ref.endswith(
            "_position_semantics_contract"
        )
        and contract.validation_record_margin_semantics_contract_ref.endswith(
            "_margin_semantics_contract"
        )
        and contract.validation_record_collateral_semantics_contract_ref.endswith(
            "_collateral_semantics_contract"
        )
        and contract.validation_record_liquidation_semantics_contract_ref.endswith(
            "_liquidation_semantics_contract"
        )
        and contract.validation_record_reduce_only_semantics_contract_ref.endswith(
            "_reduce_only_semantics_contract"
        )
        and contract.validation_record_close_only_semantics_contract_ref.endswith(
            "_close_only_semantics_contract"
        )
        and contract.validation_record_funding_semantics_contract_ref.endswith(
            "_funding_semantics_contract"
        )
        and contract.validation_record_order_semantics_contract_ref.endswith(
            "_order_semantics_contract"
        )
        and contract.validation_record_cancel_semantics_contract_ref.endswith(
            "_cancel_semantics_contract"
        )
        and contract.validation_record_reconciliation_semantics_contract_ref.endswith(
            "_reconciliation_semantics_contract"
        )
        and len(contract.validation_record_semantic_contract_refs) == 10
        and all(
            semantic_contract_ref.endswith("_semantics_contract")
            for semantic_contract_ref in contract.validation_record_semantic_contract_refs
        )
        and len(contract.validation_record_execution_eligibility_field_refs) == 13
        and all(
            field_ref.startswith(
                contract.validation_record_execution_eligibility_contract_ref
            )
            for field_ref in contract.validation_record_execution_eligibility_field_refs
        )
        and len(contract.required_evidence_refs) == 48
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    ) * len(
        AdminFuturesCommandExecutionEligibilityBlocker
    )
    eligibility_refs = {
        contract.validation_record_execution_eligibility_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    }
    assert all(
        contract.validation_record_execution_eligibility_contract_ref
        in eligibility_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.semantic_contract_present is True
        and contract.semantic_contract_ready is False
        and contract.semantic_ready is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_execution_eligibility_blocker
        is False
        and contract.blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.validation_record_execution_eligibility_blocker_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_blockers.py::"
        )
        and contract.semantic_ref.startswith(
            contract.validation_record_execution_eligibility_contract_ref
        )
        and contract.semantic_contract_ref.startswith("application/admin_api/")
        and contract.semantic_contract_ref.endswith("_semantics_contract")
        and contract.required_backend_artifact_ref.endswith("_backend_contract")
        and contract.required_backend_contract
        == contract.validation_record_execution_eligibility_blocker_ref
        and contract.missing_backend_contract
        == contract.required_backend_artifact_ref
        and len(contract.forbidden_execution_claims) == 7
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 6
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
    )
    blocker_refs = {
        contract.validation_record_execution_eligibility_blocker_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
    }
    assert {
        contract.semantic_artifact
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS
    } == set(AdminFuturesCommandSemanticArtifact)
    assert all(
        contract.validation_record_execution_eligibility_blocker_ref
        in blocker_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifacts.py::"
        )
        and contract.semantic_artifact_ref.endswith("_backend_contract")
        and contract.required_backend_contract
        == contract.semantic_artifact_contract_ref
        and contract.missing_backend_contract == contract.semantic_artifact_ref
        and len(contract.forbidden_execution_claims) == 9
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 6
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS)
    semantic_artifact_contract_refs = {
        contract.semantic_artifact_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_contract_ref in semantic_artifact_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_reviewed is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_definition_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definitions.py::"
        )
        and contract.semantic_artifact_definition_ref.endswith("_definition")
        and contract.semantic_artifact_definition_review_ref.endswith(
            "_contextless_review"
        )
        and contract.semantic_artifact_runtime_evidence_ref.endswith(
            "_runtime_evidence"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_definition_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_definition_ref
        and len(contract.forbidden_execution_claims) == 12
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 10
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
    )
    semantic_artifact_definition_contract_refs = {
        contract.semantic_artifact_definition_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_definition_contract_ref
        in semantic_artifact_definition_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_reviewed is False
        and contract.semantic_artifact_definition_review_passed is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_definition_review_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definition_reviews.py::"
        )
        and contract.semantic_artifact_definition_review_ref.endswith(
            "_contextless_review"
        )
        and contract.semantic_artifact_definition_review_input_ref.endswith(
            "_input"
        )
        and contract.semantic_artifact_definition_review_output_ref.endswith(
            "_output"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_definition_review_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_definition_review_ref
        and len(contract.forbidden_execution_claims) == 14
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 14
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    )
    semantic_artifact_definition_review_contract_refs = {
        contract.semantic_artifact_definition_review_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_definition_review_contract_ref
        in semantic_artifact_definition_review_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_review_input_available is False
        and contract.semantic_artifact_definition_review_input_accepted is False
        and contract.semantic_artifact_definition_reviewed is False
        and contract.semantic_artifact_definition_review_passed is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_definition_review_input_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definition_review_inputs.py::"
        )
        and contract.semantic_artifact_definition_review_input_ref.endswith(
            "_input"
        )
        and contract.semantic_artifact_definition_review_output_ref.endswith(
            "_output"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_definition_review_input_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_definition_review_input_ref
        and len(contract.forbidden_execution_claims) == 16
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 14
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
    )
    semantic_artifact_definition_review_input_contract_refs = {
        contract.semantic_artifact_definition_review_input_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_definition_review_input_contract_ref
        in semantic_artifact_definition_review_input_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_review_input_available is False
        and contract.semantic_artifact_definition_review_input_accepted is False
        and contract.semantic_artifact_definition_review_output_available is False
        and contract.semantic_artifact_definition_review_output_accepted is False
        and contract.semantic_artifact_definition_reviewed is False
        and contract.semantic_artifact_definition_review_passed is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_definition_review_output_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definition_review_outputs.py::"
        )
        and contract.semantic_artifact_definition_review_input_ref.endswith(
            "_input"
        )
        and contract.semantic_artifact_definition_review_output_ref.endswith(
            "_output"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_definition_review_output_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_definition_review_output_ref
        and len(contract.forbidden_execution_claims) == 18
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 15
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
    )
    semantic_artifact_definition_review_output_contract_refs = {
        contract.semantic_artifact_definition_review_output_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_definition_review_output_contract_ref
        in semantic_artifact_definition_review_output_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_review_input_available is False
        and contract.semantic_artifact_definition_review_input_accepted is False
        and contract.semantic_artifact_definition_review_output_available is False
        and contract.semantic_artifact_definition_review_output_accepted is False
        and contract.semantic_artifact_definition_review_output_acceptance_available is False
        and contract.semantic_artifact_definition_review_output_acceptance_accepted is False
        and contract.semantic_artifact_definition_reviewed is False
        and contract.semantic_artifact_definition_review_passed is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_definition_review_output_acceptance_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances.py::"
        )
        and contract.semantic_artifact_definition_review_output_ref.endswith(
            "_output"
        )
        and contract.semantic_artifact_definition_review_output_acceptance_ref.endswith(
            "_output_acceptance"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_definition_review_output_acceptance_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_definition_review_output_acceptance_ref
        and len(contract.forbidden_execution_claims) == 20
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 17
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
    )
    semantic_artifact_definition_review_output_acceptance_contract_refs = {
        contract.semantic_artifact_definition_review_output_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_definition_review_output_acceptance_contract_ref
        in semantic_artifact_definition_review_output_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_review_input_available is False
        and contract.semantic_artifact_definition_review_input_accepted is False
        and contract.semantic_artifact_definition_review_output_available is False
        and contract.semantic_artifact_definition_review_output_accepted is False
        and contract.semantic_artifact_definition_review_output_acceptance_available is False
        and contract.semantic_artifact_definition_review_output_acceptance_accepted is False
        and contract.semantic_artifact_runtime_evidence_available is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.semantic_artifact_runtime_evidence_accepted is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_runtime_evidence_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py::"
        )
        and contract.semantic_artifact_definition_review_output_acceptance_ref.endswith(
            "_output_acceptance"
        )
        and contract.semantic_artifact_runtime_evidence_ref.endswith(
            "_runtime_evidence"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_runtime_evidence_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_runtime_evidence_ref
        and len(contract.forbidden_execution_claims) == 23
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 18
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
    ) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
    )
    semantic_artifact_runtime_evidence_contract_refs = {
        contract.semantic_artifact_runtime_evidence_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
    }
    assert all(
        contract.semantic_artifact_runtime_evidence_contract_ref
        in semantic_artifact_runtime_evidence_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.semantic_artifact_definition_available is False
        and contract.semantic_artifact_definition_review_available is False
        and contract.semantic_artifact_definition_review_input_available is False
        and contract.semantic_artifact_definition_review_input_accepted is False
        and contract.semantic_artifact_definition_review_output_available is False
        and contract.semantic_artifact_definition_review_output_accepted is False
        and contract.semantic_artifact_definition_review_output_acceptance_available is False
        and contract.semantic_artifact_definition_review_output_acceptance_accepted is False
        and contract.semantic_artifact_runtime_evidence_available is False
        and contract.semantic_artifact_runtime_evidence_bound is False
        and contract.semantic_artifact_runtime_evidence_accepted is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted is False
        and contract.runtime_evidence_observed is False
        and contract.runtime_evidence_satisfies_semantic_artifact_definition is False
        and contract.semantic_artifact_defined is False
        and contract.semantic_artifact_reviewed is False
        and contract.execution_eligibility_blocker_resolved is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py::"
        )
        and contract.semantic_artifact_runtime_evidence_ref.endswith(
            "_runtime_evidence"
        )
        and contract.semantic_artifact_runtime_evidence_acceptance_ref.endswith(
            "_runtime_evidence_acceptance"
        )
        and contract.required_backend_contract
        == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        and contract.missing_backend_contract
        == contract.semantic_artifact_runtime_evidence_acceptance_ref
        and len(contract.forbidden_execution_claims) == 25
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) == 20
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
    )

    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    )
    semantic_artifact_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.POSITION_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in semantic_artifact_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.position_semantics_contract_available is False
        and contract.position_semantics_contract_ready is False
        and contract.position_identity_bound is False
        and contract.position_scope_bound is False
        and contract.position_side_derivation_bound is False
        and contract.position_size_bound is False
        and contract.position_notional_bound is False
        and contract.runtime_position_evidence_observed is False
        and contract.runtime_evidence_satisfies_position_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_position_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.position_semantics_ref == contract.semantic_ref
        and contract.position_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_position_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.position_semantics_contract_ref
        and contract.missing_backend_contract == contract.position_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_POSITIONS
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_POSITION_DETAIL
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 18
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS
    )

    assert len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS) == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    )
    margin_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.MARGIN_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.MARGIN_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.MARGIN_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in margin_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.margin_semantics_contract_available is False
        and contract.margin_semantics_contract_ready is False
        and contract.margin_account_bound is False
        and contract.margin_requirement_bound is False
        and contract.margin_mode_bound is False
        and contract.margin_buffer_bound is False
        and contract.runtime_margin_evidence_observed is False
        and contract.runtime_evidence_satisfies_margin_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_margin_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.margin_semantics_ref == contract.semantic_ref
        and contract.margin_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_margin_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.margin_semantics_contract_ref
        and contract.missing_backend_contract == contract.margin_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 29
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    collateral_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.COLLATERAL_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.COLLATERAL_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.COLLATERAL_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in collateral_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.collateral_semantics_contract_available is False
        and contract.collateral_semantics_contract_ready is False
        and contract.collateral_balance_bound is False
        and contract.collateral_currency_bound is False
        and contract.collateral_requirement_bound is False
        and contract.collateral_source_bound is False
        and contract.runtime_collateral_evidence_observed is False
        and contract.runtime_evidence_satisfies_collateral_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_collateral_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.collateral_semantics_ref == contract.semantic_ref
        and contract.collateral_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_collateral_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.collateral_semantics_contract_ref
        and contract.missing_backend_contract == contract.collateral_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    liquidation_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.LIQUIDATION_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.LIQUIDATION_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.LIQUIDATION_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in liquidation_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.liquidation_semantics_contract_available is False
        and contract.liquidation_semantics_contract_ready is False
        and contract.liquidation_buffer_bound is False
        and contract.liquidation_price_bound is False
        and contract.liquidation_distance_bound is False
        and contract.liquidation_threshold_bound is False
        and contract.runtime_liquidation_evidence_observed is False
        and contract.runtime_evidence_satisfies_liquidation_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_liquidation_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.liquidation_semantics_ref == contract.semantic_ref
        and contract.liquidation_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_liquidation_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.liquidation_semantics_contract_ref
        and contract.missing_backend_contract == contract.liquidation_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    reduce_only_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.REDUCE_ONLY_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.REDUCE_ONLY_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.REDUCE_ONLY_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in reduce_only_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.reduce_only_semantics_contract_available is False
        and contract.reduce_only_semantics_contract_ready is False
        and contract.reduce_only_flag_bound is False
        and contract.reduce_only_position_side_bound is False
        and contract.reduce_only_position_size_bound is False
        and contract.reduce_only_order_side_bound is False
        and contract.runtime_reduce_only_evidence_observed is False
        and contract.runtime_evidence_satisfies_reduce_only_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_reduce_only_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.reduce_only_semantics_ref == contract.semantic_ref
        and contract.reduce_only_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_reduce_only_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.reduce_only_semantics_contract_ref
        and contract.missing_backend_contract == contract.reduce_only_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    close_only_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.CLOSE_ONLY_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.CLOSE_ONLY_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.CLOSE_ONLY_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in close_only_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.close_only_semantics_contract_available is False
        and contract.close_only_semantics_contract_ready is False
        and contract.close_only_flag_bound is False
        and contract.close_only_position_side_bound is False
        and contract.close_only_position_size_bound is False
        and contract.close_only_order_side_bound is False
        and contract.runtime_close_only_evidence_observed is False
        and contract.runtime_evidence_satisfies_close_only_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_close_only_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.close_only_semantics_ref == contract.semantic_ref
        and contract.close_only_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_close_only_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.close_only_semantics_contract_ref
        and contract.missing_backend_contract == contract.close_only_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    funding_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.FUNDING_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.FUNDING_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.FUNDING_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in funding_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.funding_semantics_contract_available is False
        and contract.funding_semantics_contract_ready is False
        and contract.funding_rate_bound is False
        and contract.funding_fee_bound is False
        and contract.funding_interval_bound is False
        and contract.funding_cost_bound is False
        and contract.runtime_funding_evidence_observed is False
        and contract.runtime_evidence_satisfies_funding_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_funding_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.funding_semantics_ref == contract.semantic_ref
        and contract.funding_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_funding_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.funding_semantics_contract_ref
        and contract.missing_backend_contract == contract.funding_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 17
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 28
        and f"{contract.funding_semantics_contract_ref}.funding_rate"
        in contract.required_evidence_refs
        and f"{contract.funding_semantics_contract_ref}.funding_fee"
        in contract.required_evidence_refs
        and f"{contract.funding_semantics_contract_ref}.funding_interval"
        in contract.required_evidence_refs
        and f"{contract.funding_semantics_contract_ref}.funding_cost"
        in contract.required_evidence_refs
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS
    )

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    order_semantic_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.ORDER_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.ORDER_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.ORDER_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in order_semantic_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.order_semantics_contract_available is False
        and contract.order_semantics_contract_ready is False
        and contract.order_identity_bound is False
        and contract.order_side_bound is False
        and contract.order_size_bound is False
        and contract.order_price_bound is False
        and contract.order_type_bound is False
        and contract.runtime_order_evidence_observed is False
        and contract.runtime_evidence_satisfies_order_semantics is False
        and contract.semantic_artifact_runtime_evidence_acceptance_available
        is False
        and contract.semantic_artifact_runtime_evidence_acceptance_accepted
        is False
        and contract.validation_record_order_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.order_semantics_ref == contract.semantic_ref
        and contract.order_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_order_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.order_semantics_contract_ref
        and contract.missing_backend_contract == contract.order_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 18
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 29
        and f"{contract.order_semantics_contract_ref}.order_identity"
        in contract.required_evidence_refs
        and f"{contract.order_semantics_contract_ref}.order_side"
        in contract.required_evidence_refs
        and f"{contract.order_semantics_contract_ref}.order_size"
        in contract.required_evidence_refs
        and f"{contract.order_semantics_contract_ref}.order_price"
        in contract.required_evidence_refs
        and f"{contract.order_semantics_contract_ref}.order_type"
        in contract.required_evidence_refs
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS
    )

    emitted_count = 0
    validator_emitted_count = 0
    input_schema_emitted_count = 0
    output_schema_emitted_count = 0
    registration_emitted_count = 0
    validation_evidence_emitted_count = 0
    validation_evidence_record_emitted_count = 0
    validation_record_schema_emitted_count = 0
    validation_record_replay_guard_emitted_count = 0
    validation_record_audit_link_emitted_count = 0
    validation_record_admission_link_emitted_count = 0
    validation_record_execution_eligibility_emitted_count = 0
    validation_record_execution_eligibility_blocker_emitted_count = 0
    validation_record_semantic_artifact_emitted_count = 0
    validation_record_semantic_artifact_definition_emitted_count = 0
    validation_record_semantic_artifact_definition_review_emitted_count = 0
    validation_record_semantic_artifact_definition_review_input_emitted_count = 0
    validation_record_semantic_artifact_definition_review_output_emitted_count = 0
    validation_record_semantic_artifact_definition_review_output_acceptance_emitted_count = 0
    validation_record_semantic_artifact_runtime_evidence_emitted_count = 0
    validation_record_semantic_artifact_runtime_evidence_acceptance_emitted_count = 0
    validation_record_position_semantic_emitted_count = 0
    validation_record_margin_semantic_emitted_count = 0
    validation_record_collateral_semantic_emitted_count = 0
    validation_record_liquidation_semantic_emitted_count = 0
    validation_record_reduce_only_semantic_emitted_count = 0
    validation_record_close_only_semantic_emitted_count = 0
    validation_record_funding_semantic_emitted_count = 0
    validation_record_order_semantic_emitted_count = 0
    for command in command_suite.commands:
        registry_rows = list(iter_futures_request_payload_contracts(command.command))
        validator_registry_rows = list(
            iter_futures_request_payload_validator_contracts(command.command)
        )
        input_schema_registry_rows = list(
            iter_futures_request_payload_validator_input_schemas(command.command)
        )
        output_schema_registry_rows = list(
            iter_futures_request_payload_validator_output_schemas(command.command)
        )
        registration_registry_rows = list(
            iter_futures_request_payload_validator_registrations(command.command)
        )
        validation_evidence_registry_rows = list(
            iter_futures_request_payload_validation_evidence(command.command)
        )
        validation_evidence_record_registry_rows = list(
            iter_futures_request_payload_validation_evidence_records(command.command)
        )
        validation_record_schema_registry_rows = list(
            iter_futures_request_payload_validation_record_schemas(command.command)
        )
        validation_record_replay_guard_registry_rows = list(
            iter_futures_request_payload_validation_record_replay_guards(
                command.command
            )
        )
        validation_record_audit_link_registry_rows = list(
            iter_futures_request_payload_validation_record_audit_links(
                command.command
            )
        )
        validation_record_admission_link_registry_rows = list(
            iter_futures_request_payload_validation_record_admission_links(
                command.command
            )
        )
        validation_record_execution_eligibility_registry_rows = list(
            iter_futures_request_payload_validation_record_execution_eligibilities(
                command.command
            )
        )
        validation_record_execution_eligibility_blocker_registry_rows = list(
            iter_futures_request_payload_validation_record_execution_eligibility_blockers(
                command.command
            )
        )
        validation_record_semantic_artifact_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifacts(
                command.command
            )
        )
        validation_record_semantic_artifact_definition_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_definitions(
                command.command
            )
        )
        validation_record_semantic_artifact_definition_review_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_definition_reviews(
                command.command
            )
        )
        validation_record_semantic_artifact_definition_review_input_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs(
                command.command
            )
        )
        validation_record_semantic_artifact_definition_review_output_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs(
                command.command
            )
        )
        validation_record_semantic_artifact_definition_review_output_acceptance_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances(
                command.command
            )
        )
        validation_record_semantic_artifact_runtime_evidence_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences(
                command.command
            )
        )
        validation_record_semantic_artifact_runtime_evidence_acceptance_registry_rows = list(
            iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances(
                command.command
            )
        )
        validation_record_position_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_position_semantics(
                command.command
            )
        )
        validation_record_margin_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_margin_semantics(
                command.command
            )
        )
        validation_record_collateral_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_collateral_semantics(
                command.command
            )
        )
        validation_record_liquidation_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_liquidation_semantics(
                command.command
            )
        )
        validation_record_reduce_only_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_reduce_only_semantics(
                command.command
            )
        )
        validation_record_close_only_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_close_only_semantics(
                command.command
            )
        )
        validation_record_funding_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_funding_semantics(
                command.command
            )
        )
        validation_record_order_semantic_registry_rows = list(
            iter_futures_request_payload_validation_record_order_semantics(
                command.command
            )
        )
        emitted_count += len(command.request_fields)
        validator_emitted_count += len(command.request_payload_validator_contracts)
        input_schema_emitted_count += len(
            command.request_payload_validator_input_schemas
        )
        output_schema_emitted_count += len(
            command.request_payload_validator_output_schemas
        )
        registration_emitted_count += len(
            command.request_payload_validator_registrations
        )
        validation_evidence_emitted_count += len(
            command.request_payload_validation_evidence
        )
        validation_evidence_record_emitted_count += len(
            command.request_payload_validation_evidence_records
        )
        validation_record_schema_emitted_count += len(
            command.request_payload_validation_record_schemas
        )
        validation_record_replay_guard_emitted_count += len(
            command.request_payload_validation_record_replay_guards
        )
        validation_record_audit_link_emitted_count += len(
            command.request_payload_validation_record_audit_links
        )
        validation_record_admission_link_emitted_count += len(
            command.request_payload_validation_record_admission_links
        )
        validation_record_execution_eligibility_emitted_count += len(
            command.request_payload_validation_record_execution_eligibilities
        )
        validation_record_execution_eligibility_blocker_emitted_count += len(
            command.request_payload_validation_record_execution_eligibility_blockers
        )
        validation_record_semantic_artifact_emitted_count += len(
            command.request_payload_validation_record_semantic_artifacts
        )
        validation_record_semantic_artifact_definition_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_definitions
        )
        validation_record_semantic_artifact_definition_review_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_definition_reviews
        )
        validation_record_semantic_artifact_definition_review_input_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_definition_review_inputs
        )
        validation_record_semantic_artifact_definition_review_output_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_definition_review_outputs
        )
        validation_record_semantic_artifact_definition_review_output_acceptance_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_definition_review_output_acceptances
        )
        validation_record_semantic_artifact_runtime_evidence_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_runtime_evidences
        )
        validation_record_semantic_artifact_runtime_evidence_acceptance_emitted_count += len(
            command.request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances
        )
        validation_record_position_semantic_emitted_count += len(
            command.request_payload_validation_record_position_semantics
        )
        validation_record_margin_semantic_emitted_count += len(
            command.request_payload_validation_record_margin_semantics
        )
        validation_record_collateral_semantic_emitted_count += len(
            command.request_payload_validation_record_collateral_semantics
        )
        validation_record_liquidation_semantic_emitted_count += len(
            command.request_payload_validation_record_liquidation_semantics
        )
        validation_record_reduce_only_semantic_emitted_count += len(
            command.request_payload_validation_record_reduce_only_semantics
        )
        validation_record_close_only_semantic_emitted_count += len(
            command.request_payload_validation_record_close_only_semantics
        )
        validation_record_funding_semantic_emitted_count += len(
            command.request_payload_validation_record_funding_semantics
        )
        validation_record_order_semantic_emitted_count += len(
            command.request_payload_validation_record_order_semantics
        )
        assert command.request_field_count == len(registry_rows)
        assert command.required_request_field_count == len(registry_rows)
        assert command.blocking_request_field_count == len(registry_rows)
        assert command.request_payload_validator_contract_count == len(
            validator_registry_rows
        )
        assert command.blocking_request_payload_validator_contract_count == len(
            validator_registry_rows
        )
        assert command.ready_request_payload_validator_contract_count == 0
        assert command.registered_request_payload_validator_contract_count == 0
        assert command.request_payload_validator_input_schema_count == len(
            input_schema_registry_rows
        )
        assert command.blocking_request_payload_validator_input_schema_count == len(
            input_schema_registry_rows
        )
        assert command.ready_request_payload_validator_input_schema_count == 0
        assert command.registered_request_payload_validator_input_schema_count == 0
        assert command.request_payload_validator_output_schema_count == len(
            output_schema_registry_rows
        )
        assert command.blocking_request_payload_validator_output_schema_count == len(
            output_schema_registry_rows
        )
        assert command.ready_request_payload_validator_output_schema_count == 0
        assert command.registered_request_payload_validator_output_schema_count == 0
        assert command.request_payload_validator_registration_count == len(
            registration_registry_rows
        )
        assert command.blocking_request_payload_validator_registration_count == len(
            registration_registry_rows
        )
        assert command.ready_request_payload_validator_registration_count == 0
        assert command.registered_request_payload_validator_registration_count == 0
        assert (
            command.runtime_observed_request_payload_validator_registration_count == 0
        )
        assert command.request_payload_validation_evidence_count == len(
            validation_evidence_registry_rows
        )
        assert command.blocking_request_payload_validation_evidence_count == len(
            validation_evidence_registry_rows
        )
        assert command.ready_request_payload_validation_evidence_count == 0
        assert command.recorded_request_payload_validation_evidence_count == 0
        assert (
            command.runtime_observed_request_payload_validation_evidence_count == 0
        )
        assert command.request_payload_validation_evidence_record_count == len(
            validation_evidence_record_registry_rows
        )
        assert command.blocking_request_payload_validation_evidence_record_count == len(
            validation_evidence_record_registry_rows
        )
        assert command.ready_request_payload_validation_evidence_record_count == 0
        assert command.stored_request_payload_validation_evidence_record_count == 0
        assert (
            command.runtime_observed_request_payload_validation_evidence_record_count
            == 0
        )
        assert command.request_payload_validation_record_schema_count == len(
            validation_record_schema_registry_rows
        )
        assert command.blocking_request_payload_validation_record_schema_count == len(
            validation_record_schema_registry_rows
        )
        assert command.ready_request_payload_validation_record_schema_count == 0
        assert command.registered_request_payload_validation_record_schema_count == 0
        assert (
            command.runtime_observed_request_payload_validation_record_schema_count
            == 0
        )
        assert command.request_payload_validation_record_replay_guard_count == len(
            validation_record_replay_guard_registry_rows
        )
        assert (
            command.blocking_request_payload_validation_record_replay_guard_count
            == len(validation_record_replay_guard_registry_rows)
        )
        assert command.ready_request_payload_validation_record_replay_guard_count == 0
        assert (
            command.idempotency_bound_request_payload_validation_record_count == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_replay_guard_count
            == 0
        )
        assert command.request_payload_validation_record_audit_link_count == len(
            validation_record_audit_link_registry_rows
        )
        assert (
            command.blocking_request_payload_validation_record_audit_link_count
            == len(validation_record_audit_link_registry_rows)
        )
        assert command.ready_request_payload_validation_record_audit_link_count == 0
        assert command.audit_bound_request_payload_validation_record_count == 0
        assert (
            command.runtime_observed_request_payload_validation_record_audit_link_count
            == 0
        )
        assert command.request_payload_validation_record_admission_link_count == len(
            validation_record_admission_link_registry_rows
        )
        assert (
            command.blocking_request_payload_validation_record_admission_link_count
            == len(validation_record_admission_link_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_admission_link_count == 0
        )
        assert command.admission_bound_request_payload_validation_record_count == 0
        assert (
            command.runtime_observed_request_payload_validation_record_admission_link_count
            == 0
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_count
            == len(validation_record_execution_eligibility_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_execution_eligibility_count
            == len(validation_record_execution_eligibility_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_execution_eligibility_count
            == 0
        )
        assert (
            command.execution_eligible_request_payload_validation_record_count == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_execution_eligibility_count
            == 0
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_blocker_count
            == len(validation_record_execution_eligibility_blocker_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_execution_eligibility_blocker_count
            == len(validation_record_execution_eligibility_blocker_registry_rows)
        )
        assert (
            command.resolved_request_payload_validation_record_execution_eligibility_blocker_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_execution_eligibility_blocker_count
            == 0
        )
        assert command.request_payload_validation_record_semantic_artifact_count == len(
            validation_record_semantic_artifact_registry_rows
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_count
            == len(validation_record_semantic_artifact_registry_rows)
        )
        assert command.ready_request_payload_validation_record_semantic_artifact_count == 0
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_definition_count
            == len(validation_record_semantic_artifact_definition_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_definition_count
            == len(validation_record_semantic_artifact_definition_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_definition_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_definition_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_definition_review_count
            == len(validation_record_semantic_artifact_definition_review_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_definition_review_count
            == len(validation_record_semantic_artifact_definition_review_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_definition_review_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_definition_review_input_count
            == len(
                validation_record_semantic_artifact_definition_review_input_registry_rows
            )
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_definition_review_input_count
            == len(
                validation_record_semantic_artifact_definition_review_input_registry_rows
            )
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_definition_review_input_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_input_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_definition_review_output_count
            == len(
                validation_record_semantic_artifact_definition_review_output_registry_rows
            )
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count
            == len(
                validation_record_semantic_artifact_definition_review_output_registry_rows
            )
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_definition_review_output_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
            == len(
                validation_record_semantic_artifact_definition_review_output_acceptance_registry_rows
            )
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
            == len(
                validation_record_semantic_artifact_definition_review_output_acceptance_registry_rows
            )
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_runtime_evidence_count
            == len(validation_record_semantic_artifact_runtime_evidence_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count
            == len(validation_record_semantic_artifact_runtime_evidence_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count
            == 0
        )
        assert (
            command.request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
            == len(
                validation_record_semantic_artifact_runtime_evidence_acceptance_registry_rows
            )
        )
        assert (
            command.blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
            == len(
                validation_record_semantic_artifact_runtime_evidence_acceptance_registry_rows
            )
        )
        assert (
            command.ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
            == 0
        )
        assert (
            command.request_payload_validation_record_position_semantic_count
            == len(validation_record_position_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_position_semantic_count
            == len(validation_record_position_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_position_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_position_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_margin_semantic_count
            == len(validation_record_margin_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_margin_semantic_count
            == len(validation_record_margin_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_margin_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_margin_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_collateral_semantic_count
            == len(validation_record_collateral_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_collateral_semantic_count
            == len(validation_record_collateral_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_collateral_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_collateral_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_liquidation_semantic_count
            == len(validation_record_liquidation_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_liquidation_semantic_count
            == len(validation_record_liquidation_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_liquidation_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_liquidation_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_reduce_only_semantic_count
            == len(validation_record_reduce_only_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_reduce_only_semantic_count
            == len(validation_record_reduce_only_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_reduce_only_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_reduce_only_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_close_only_semantic_count
            == len(validation_record_close_only_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_close_only_semantic_count
            == len(validation_record_close_only_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_close_only_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_close_only_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_funding_semantic_count
            == len(validation_record_funding_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_funding_semantic_count
            == len(validation_record_funding_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_funding_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_funding_semantic_count
            == 0
        )
        assert (
            command.request_payload_validation_record_order_semantic_count
            == len(validation_record_order_semantic_registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_order_semantic_count
            == len(validation_record_order_semantic_registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_order_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_order_semantic_count
            == 0
        )
        assert all(
            contract.contract_ref in command.required_backend_contracts
            for contract in registry_rows
        )
        assert all(
            contract.validator_contract_ref in command.required_backend_contracts
            for contract in validator_registry_rows
        )
        assert all(
            contract.validator_input_schema_ref in command.required_backend_contracts
            for contract in input_schema_registry_rows
        )
        assert all(
            contract.validator_output_schema_ref in command.required_backend_contracts
            for contract in output_schema_registry_rows
        )
        assert all(
            contract.validator_registration_ref in command.required_backend_contracts
            for contract in registration_registry_rows
        )
        assert all(
            contract.validation_evidence_contract_ref
            in command.required_backend_contracts
            for contract in validation_evidence_registry_rows
        )
        assert all(
            contract.validation_record_contract_ref in command.required_backend_contracts
            for contract in validation_evidence_record_registry_rows
        )
        assert all(
            contract.validation_record_schema_ref in command.required_backend_contracts
            for contract in validation_record_schema_registry_rows
        )
        assert all(
            contract.validation_record_replay_guard_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_replay_guard_registry_rows
        )
        assert all(
            contract.validation_record_audit_link_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_audit_link_registry_rows
        )
        assert all(
            contract.validation_record_admission_link_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_admission_link_registry_rows
        )
        assert all(
            contract.validation_record_execution_eligibility_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_execution_eligibility_registry_rows
        )
        assert all(
            contract.validation_record_execution_eligibility_blocker_ref
            in command.required_backend_contracts
            for contract in validation_record_execution_eligibility_blocker_registry_rows
        )
        assert all(
            contract.semantic_artifact_contract_ref in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_registry_rows
        )
        assert all(
            contract.semantic_artifact_definition_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_definition_registry_rows
        )
        assert all(
            contract.semantic_artifact_definition_review_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_definition_review_registry_rows
        )
        assert all(
            contract.semantic_artifact_definition_review_input_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_definition_review_input_registry_rows
        )
        assert all(
            contract.semantic_artifact_definition_review_output_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_definition_review_output_registry_rows
        )
        assert all(
            contract.semantic_artifact_definition_review_output_acceptance_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_definition_review_output_acceptance_registry_rows
        )
        assert all(
            contract.semantic_artifact_runtime_evidence_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_runtime_evidence_registry_rows
        )
        assert all(
            contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_semantic_artifact_runtime_evidence_acceptance_registry_rows
        )
        assert all(
            contract.position_semantics_contract_ref in command.required_backend_contracts
            for contract in validation_record_position_semantic_registry_rows
        )
        assert all(
            contract.margin_semantics_contract_ref in command.required_backend_contracts
            for contract in validation_record_margin_semantic_registry_rows
        )
        assert all(
            contract.collateral_semantics_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_collateral_semantic_registry_rows
        )
        assert all(
            contract.liquidation_semantics_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_liquidation_semantic_registry_rows
        )
        assert all(
            contract.reduce_only_semantics_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_reduce_only_semantic_registry_rows
        )
        assert all(
            contract.close_only_semantics_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_close_only_semantic_registry_rows
        )
        assert all(
            contract.funding_semantics_contract_ref
            in command.required_backend_contracts
            for contract in validation_record_funding_semantic_registry_rows
        )
        assert all(
            contract.order_semantics_contract_ref in command.required_backend_contracts
            for contract in validation_record_order_semantic_registry_rows
        )
        for emitted, contract in zip(
            command.request_fields,
            registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.identity_field == contract.identity_field
            assert emitted.risk_field == contract.risk_field
            assert emitted.payload_field == contract.payload_field
            assert emitted.request_payload_contract_ref == contract.contract_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.validation_gate_ready is False
            assert emitted.validation_gate_passed is False
            assert emitted.validator_contract_registered is False
            assert emitted.validator_registered is False
            assert emitted.validation_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validator_contracts,
            validator_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.validation_gate_ready is False
            assert emitted.validation_gate_passed is False
            assert emitted.validator_contract_registered is False
            assert emitted.validator_input_schema_registered is False
            assert emitted.validator_output_schema_registered is False
            assert emitted.validator_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validator_input_schemas,
            input_schema_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.input_schema_field_refs == list(
                contract.input_schema_field_refs
            )
            assert emitted.input_schema_field_count == len(
                contract.input_schema_field_refs
            )
            assert emitted.input_schema_registered is False
            assert emitted.validator_contract_registered is False
            assert emitted.validator_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validator_output_schemas,
            output_schema_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.output_schema_field_refs == list(
                contract.output_schema_field_refs
            )
            assert emitted.output_schema_field_count == len(
                contract.output_schema_field_refs
            )
            assert emitted.output_schema_registered is False
            assert emitted.validator_contract_registered is False
            assert emitted.validator_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validator_registrations,
            registration_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validator_registration_field_refs == list(
                contract.validator_registration_field_refs
            )
            assert emitted.validator_registration_field_count == len(
                contract.validator_registration_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_validator_registration is False
            assert emitted.validator_contract_registered is False
            assert emitted.input_schema_registered is False
            assert emitted.output_schema_registered is False
            assert emitted.validator_registration_ready is False
            assert emitted.validator_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_evidence,
            validation_evidence_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_evidence_field_refs == list(
                contract.validation_evidence_field_refs
            )
            assert emitted.validation_evidence_field_count == len(
                contract.validation_evidence_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_validation_evidence is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_gate_ready is False
            assert emitted.validation_gate_passed is False
            assert emitted.validator_registration_ready is False
            assert emitted.validator_registered is False
            assert emitted.request_payload_validated is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_evidence_records,
            validation_evidence_record_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_field_refs == list(
                contract.validation_record_field_refs
            )
            assert emitted.validation_record_field_count == len(
                contract.validation_record_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_validation_record is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_schemas,
            validation_record_schema_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert (
                emitted.validation_record_schema_ref
                == contract.validation_record_schema_ref
            )
            assert (
                emitted.validation_record_append_only_log_ref
                == contract.validation_record_append_only_log_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_schema_field_refs == list(
                contract.validation_record_schema_field_refs
            )
            assert emitted.validation_record_schema_field_count == len(
                contract.validation_record_schema_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_validation_record_schema
                is False
            )
            assert emitted.validation_record_schema_ready is False
            assert emitted.validation_record_schema_registered is False
            assert emitted.validation_record_append_only_log_ready is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_replay_guards,
            validation_record_replay_guard_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert (
                emitted.validation_record_schema_ref
                == contract.validation_record_schema_ref
            )
            assert (
                emitted.validation_record_append_only_log_ref
                == contract.validation_record_append_only_log_ref
            )
            assert (
                emitted.validation_record_replay_guard_contract_ref
                == contract.validation_record_replay_guard_contract_ref
            )
            assert (
                emitted.validation_record_idempotency_contract_ref
                == contract.validation_record_idempotency_contract_ref
            )
            assert (
                emitted.validation_record_replay_window_ref
                == contract.validation_record_replay_window_ref
            )
            assert (
                emitted.validation_record_duplicate_policy_ref
                == contract.validation_record_duplicate_policy_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_replay_guard_field_refs == list(
                contract.validation_record_replay_guard_field_refs
            )
            assert emitted.validation_record_replay_guard_field_count == len(
                contract.validation_record_replay_guard_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_validation_record_replay_guard
                is False
            )
            assert emitted.validation_record_replay_guard_contract_ready is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_record_idempotency_contract_ready is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.validation_record_replay_protected is False
            assert emitted.validation_record_schema_ready is False
            assert emitted.validation_record_schema_registered is False
            assert emitted.validation_record_append_only_log_ready is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_audit_links,
            validation_record_audit_link_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert (
                emitted.validation_record_schema_ref
                == contract.validation_record_schema_ref
            )
            assert (
                emitted.validation_record_append_only_log_ref
                == contract.validation_record_append_only_log_ref
            )
            assert (
                emitted.validation_record_replay_guard_contract_ref
                == contract.validation_record_replay_guard_contract_ref
            )
            assert (
                emitted.validation_record_idempotency_contract_ref
                == contract.validation_record_idempotency_contract_ref
            )
            assert (
                emitted.validation_record_replay_window_ref
                == contract.validation_record_replay_window_ref
            )
            assert (
                emitted.validation_record_duplicate_policy_ref
                == contract.validation_record_duplicate_policy_ref
            )
            assert (
                emitted.validation_record_audit_link_contract_ref
                == contract.validation_record_audit_link_contract_ref
            )
            assert (
                emitted.validation_record_actor_ref
                == contract.validation_record_actor_ref
            )
            assert (
                emitted.validation_record_operator_intent_ref
                == contract.validation_record_operator_intent_ref
            )
            assert (
                emitted.validation_record_correlation_ref
                == contract.validation_record_correlation_ref
            )
            assert (
                emitted.validation_record_admission_audit_ref
                == contract.validation_record_admission_audit_ref
            )
            assert (
                emitted.validation_record_audit_record_ref
                == contract.validation_record_audit_record_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_audit_link_field_refs == list(
                contract.validation_record_audit_link_field_refs
            )
            assert emitted.validation_record_audit_link_field_count == len(
                contract.validation_record_audit_link_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_validation_record_audit_link
                is False
            )
            assert emitted.validation_record_audit_link_contract_ready is False
            assert emitted.validation_record_audit_link_ready is False
            assert emitted.validation_record_actor_bound is False
            assert emitted.validation_record_operator_intent_bound is False
            assert emitted.validation_record_correlation_bound is False
            assert emitted.validation_record_admission_audit_bound is False
            assert emitted.validation_record_audit_recorded is False
            assert emitted.validation_record_replay_guard_contract_ready is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_record_idempotency_contract_ready is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.validation_record_replay_protected is False
            assert emitted.validation_record_schema_ready is False
            assert emitted.validation_record_schema_registered is False
            assert emitted.validation_record_append_only_log_ready is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_admission_links,
            validation_record_admission_link_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert (
                emitted.validation_record_schema_ref
                == contract.validation_record_schema_ref
            )
            assert (
                emitted.validation_record_append_only_log_ref
                == contract.validation_record_append_only_log_ref
            )
            assert (
                emitted.validation_record_replay_guard_contract_ref
                == contract.validation_record_replay_guard_contract_ref
            )
            assert (
                emitted.validation_record_idempotency_contract_ref
                == contract.validation_record_idempotency_contract_ref
            )
            assert (
                emitted.validation_record_replay_window_ref
                == contract.validation_record_replay_window_ref
            )
            assert (
                emitted.validation_record_duplicate_policy_ref
                == contract.validation_record_duplicate_policy_ref
            )
            assert (
                emitted.validation_record_audit_link_contract_ref
                == contract.validation_record_audit_link_contract_ref
            )
            assert (
                emitted.validation_record_actor_ref
                == contract.validation_record_actor_ref
            )
            assert (
                emitted.validation_record_operator_intent_ref
                == contract.validation_record_operator_intent_ref
            )
            assert (
                emitted.validation_record_correlation_ref
                == contract.validation_record_correlation_ref
            )
            assert (
                emitted.validation_record_admission_audit_ref
                == contract.validation_record_admission_audit_ref
            )
            assert (
                emitted.validation_record_audit_record_ref
                == contract.validation_record_audit_record_ref
            )
            assert (
                emitted.validation_record_admission_link_contract_ref
                == contract.validation_record_admission_link_contract_ref
            )
            assert (
                emitted.validation_record_approval_snapshot_ref
                == contract.validation_record_approval_snapshot_ref
            )
            assert (
                emitted.validation_record_cap_guard_decision_ref
                == contract.validation_record_cap_guard_decision_ref
            )
            assert (
                emitted.validation_record_reconciliation_plan_ref
                == contract.validation_record_reconciliation_plan_ref
            )
            assert (
                emitted.validation_record_live_intent_ref
                == contract.validation_record_live_intent_ref
            )
            assert (
                emitted.validation_record_command_admission_ref
                == contract.validation_record_command_admission_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_admission_link_field_refs == list(
                contract.validation_record_admission_link_field_refs
            )
            assert emitted.validation_record_admission_link_field_count == len(
                contract.validation_record_admission_link_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_validation_record_admission_link
                is False
            )
            assert emitted.validation_record_admission_link_contract_ready is False
            assert emitted.validation_record_admission_link_ready is False
            assert emitted.validation_record_approval_snapshot_bound is False
            assert emitted.validation_record_cap_guard_decision_bound is False
            assert emitted.validation_record_reconciliation_plan_bound is False
            assert emitted.validation_record_live_intent_bound is False
            assert emitted.validation_record_command_admission_bound is False
            assert emitted.validation_record_admitted is False
            assert emitted.validation_record_audit_link_contract_ready is False
            assert emitted.validation_record_audit_link_ready is False
            assert emitted.validation_record_actor_bound is False
            assert emitted.validation_record_operator_intent_bound is False
            assert emitted.validation_record_correlation_bound is False
            assert emitted.validation_record_admission_audit_bound is False
            assert emitted.validation_record_audit_recorded is False
            assert emitted.validation_record_replay_guard_contract_ready is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_record_idempotency_contract_ready is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.validation_record_replay_protected is False
            assert emitted.validation_record_schema_ready is False
            assert emitted.validation_record_schema_registered is False
            assert emitted.validation_record_append_only_log_ready is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_execution_eligibilities,
            validation_record_execution_eligibility_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.request_payload_contract_ref
                == contract.request_payload_contract_ref
            )
            assert emitted.validation_gate_ref == contract.validation_gate_ref
            assert emitted.validation_evidence_ref == contract.validation_evidence_ref
            assert (
                emitted.validation_evidence_contract_ref
                == contract.validation_evidence_contract_ref
            )
            assert emitted.validator_contract_ref == contract.validator_contract_ref
            assert (
                emitted.validator_input_schema_ref
                == contract.validator_input_schema_ref
            )
            assert (
                emitted.validator_output_schema_ref
                == contract.validator_output_schema_ref
            )
            assert (
                emitted.validator_registration_ref
                == contract.validator_registration_ref
            )
            assert (
                emitted.validation_record_contract_ref
                == contract.validation_record_contract_ref
            )
            assert (
                emitted.validation_record_store_ref
                == contract.validation_record_store_ref
            )
            assert (
                emitted.validation_record_writer_ref
                == contract.validation_record_writer_ref
            )
            assert (
                emitted.validation_record_replay_guard_ref
                == contract.validation_record_replay_guard_ref
            )
            assert (
                emitted.validation_record_schema_ref
                == contract.validation_record_schema_ref
            )
            assert (
                emitted.validation_record_append_only_log_ref
                == contract.validation_record_append_only_log_ref
            )
            assert (
                emitted.validation_record_replay_guard_contract_ref
                == contract.validation_record_replay_guard_contract_ref
            )
            assert (
                emitted.validation_record_idempotency_contract_ref
                == contract.validation_record_idempotency_contract_ref
            )
            assert (
                emitted.validation_record_replay_window_ref
                == contract.validation_record_replay_window_ref
            )
            assert (
                emitted.validation_record_duplicate_policy_ref
                == contract.validation_record_duplicate_policy_ref
            )
            assert (
                emitted.validation_record_audit_link_contract_ref
                == contract.validation_record_audit_link_contract_ref
            )
            assert (
                emitted.validation_record_actor_ref
                == contract.validation_record_actor_ref
            )
            assert (
                emitted.validation_record_operator_intent_ref
                == contract.validation_record_operator_intent_ref
            )
            assert (
                emitted.validation_record_correlation_ref
                == contract.validation_record_correlation_ref
            )
            assert (
                emitted.validation_record_admission_audit_ref
                == contract.validation_record_admission_audit_ref
            )
            assert (
                emitted.validation_record_audit_record_ref
                == contract.validation_record_audit_record_ref
            )
            assert (
                emitted.validation_record_admission_link_contract_ref
                == contract.validation_record_admission_link_contract_ref
            )
            assert (
                emitted.validation_record_approval_snapshot_ref
                == contract.validation_record_approval_snapshot_ref
            )
            assert (
                emitted.validation_record_cap_guard_decision_ref
                == contract.validation_record_cap_guard_decision_ref
            )
            assert (
                emitted.validation_record_reconciliation_plan_ref
                == contract.validation_record_reconciliation_plan_ref
            )
            assert (
                emitted.validation_record_live_intent_ref
                == contract.validation_record_live_intent_ref
            )
            assert (
                emitted.validation_record_command_admission_ref
                == contract.validation_record_command_admission_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_position_semantics_ref
                == contract.validation_record_position_semantics_ref
            )
            assert (
                emitted.validation_record_margin_semantics_ref
                == contract.validation_record_margin_semantics_ref
            )
            assert (
                emitted.validation_record_collateral_semantics_ref
                == contract.validation_record_collateral_semantics_ref
            )
            assert (
                emitted.validation_record_liquidation_semantics_ref
                == contract.validation_record_liquidation_semantics_ref
            )
            assert (
                emitted.validation_record_reduce_only_semantics_ref
                == contract.validation_record_reduce_only_semantics_ref
            )
            assert (
                emitted.validation_record_close_only_semantics_ref
                == contract.validation_record_close_only_semantics_ref
            )
            assert (
                emitted.validation_record_funding_semantics_ref
                == contract.validation_record_funding_semantics_ref
            )
            assert (
                emitted.validation_record_order_semantics_ref
                == contract.validation_record_order_semantics_ref
            )
            assert (
                emitted.validation_record_cancel_semantics_ref
                == contract.validation_record_cancel_semantics_ref
            )
            assert (
                emitted.validation_record_reconciliation_semantics_ref
                == contract.validation_record_reconciliation_semantics_ref
            )
            assert (
                emitted.validation_record_position_semantics_contract_ref
                == contract.validation_record_position_semantics_contract_ref
            )
            assert (
                emitted.validation_record_margin_semantics_contract_ref
                == contract.validation_record_margin_semantics_contract_ref
            )
            assert (
                emitted.validation_record_collateral_semantics_contract_ref
                == contract.validation_record_collateral_semantics_contract_ref
            )
            assert (
                emitted.validation_record_liquidation_semantics_contract_ref
                == contract.validation_record_liquidation_semantics_contract_ref
            )
            assert (
                emitted.validation_record_reduce_only_semantics_contract_ref
                == contract.validation_record_reduce_only_semantics_contract_ref
            )
            assert (
                emitted.validation_record_close_only_semantics_contract_ref
                == contract.validation_record_close_only_semantics_contract_ref
            )
            assert (
                emitted.validation_record_funding_semantics_contract_ref
                == contract.validation_record_funding_semantics_contract_ref
            )
            assert (
                emitted.validation_record_order_semantics_contract_ref
                == contract.validation_record_order_semantics_contract_ref
            )
            assert (
                emitted.validation_record_cancel_semantics_contract_ref
                == contract.validation_record_cancel_semantics_contract_ref
            )
            assert (
                emitted.validation_record_reconciliation_semantics_contract_ref
                == contract.validation_record_reconciliation_semantics_contract_ref
            )
            assert emitted.validation_record_semantic_contract_refs == list(
                contract.validation_record_semantic_contract_refs
            )
            assert emitted.validation_record_semantic_contract_ref_count == len(
                contract.validation_record_semantic_contract_refs
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.validation_record_execution_eligibility_field_refs == list(
                contract.validation_record_execution_eligibility_field_refs
            )
            assert emitted.validation_record_execution_eligibility_field_count == len(
                contract.validation_record_execution_eligibility_field_refs
            )
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_validation_record_execution_eligibility
                is False
            )
            assert (
                emitted.validation_record_execution_eligibility_contract_ready
                is False
            )
            assert emitted.validation_record_execution_eligible is False
            assert emitted.validation_record_position_semantics_ready is False
            assert emitted.validation_record_margin_semantics_ready is False
            assert emitted.validation_record_collateral_semantics_ready is False
            assert emitted.validation_record_liquidation_semantics_ready is False
            assert emitted.validation_record_reduce_only_semantics_ready is False
            assert emitted.validation_record_close_only_semantics_ready is False
            assert emitted.validation_record_funding_semantics_ready is False
            assert emitted.validation_record_order_semantics_ready is False
            assert emitted.validation_record_cancel_semantics_ready is False
            assert emitted.validation_record_reconciliation_semantics_ready is False
            assert emitted.validation_record_semantic_contracts_present is True
            assert emitted.validation_record_semantic_contracts_ready is False
            assert emitted.validation_record_admission_link_contract_ready is False
            assert emitted.validation_record_admission_link_ready is False
            assert emitted.validation_record_approval_snapshot_bound is False
            assert emitted.validation_record_cap_guard_decision_bound is False
            assert emitted.validation_record_reconciliation_plan_bound is False
            assert emitted.validation_record_live_intent_bound is False
            assert emitted.validation_record_command_admission_bound is False
            assert emitted.validation_record_admitted is False
            assert emitted.validation_record_audit_link_contract_ready is False
            assert emitted.validation_record_audit_link_ready is False
            assert emitted.validation_record_actor_bound is False
            assert emitted.validation_record_operator_intent_bound is False
            assert emitted.validation_record_correlation_bound is False
            assert emitted.validation_record_admission_audit_bound is False
            assert emitted.validation_record_audit_recorded is False
            assert emitted.validation_record_replay_guard_contract_ready is False
            assert emitted.validation_record_replay_guard_ready is False
            assert emitted.validation_record_idempotency_contract_ready is False
            assert emitted.validation_record_idempotency_bound is False
            assert emitted.validation_record_replay_protected is False
            assert emitted.validation_record_schema_ready is False
            assert emitted.validation_record_schema_registered is False
            assert emitted.validation_record_append_only_log_ready is False
            assert emitted.validation_record_contract_ready is False
            assert emitted.validation_record_store_ready is False
            assert emitted.validation_record_writer_enabled is False
            assert emitted.validation_evidence_ready is False
            assert emitted.validation_evidence_recorded is False
            assert emitted.validation_recorded is False
            assert emitted.append_only_validation_record is False
            assert emitted.request_payload_validated is False
            assert emitted.validator_registered is False
            assert emitted.command_route_registered is True
            assert emitted.command_draft_allowed is True
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_execution_eligibility_blockers,
            validation_record_execution_eligibility_blocker_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_contract_ref == contract.semantic_contract_ref
            assert (
                emitted.required_backend_artifact_ref
                == contract.required_backend_artifact_ref
            )
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(
                contract.required_evidence_refs
            )
            assert emitted.required_evidence_count == len(
                contract.required_evidence_refs
            )
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(
                contract.missing_evidence_refs
            )
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.semantic_contract_present is True
            assert emitted.semantic_contract_ready is False
            assert emitted.semantic_ready is False
            assert emitted.runtime_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_execution_eligibility_blocker
                is False
            )
            assert emitted.blocker_resolved is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_position_semantics,
            validation_record_position_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert emitted.position_semantics_ref == contract.position_semantics_ref
            assert (
                emitted.position_semantics_contract_ref
                == contract.position_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.position_semantics_contract_available is False
            assert emitted.position_semantics_contract_ready is False
            assert emitted.position_identity_bound is False
            assert emitted.position_scope_bound is False
            assert emitted.position_side_derivation_bound is False
            assert emitted.position_size_bound is False
            assert emitted.position_notional_bound is False
            assert emitted.runtime_position_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_position_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_position_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_margin_semantics,
            validation_record_margin_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert emitted.margin_semantics_ref == contract.margin_semantics_ref
            assert (
                emitted.margin_semantics_contract_ref
                == contract.margin_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.margin_semantics_contract_available is False
            assert emitted.margin_semantics_contract_ready is False
            assert emitted.margin_account_bound is False
            assert emitted.margin_requirement_bound is False
            assert emitted.margin_mode_bound is False
            assert emitted.margin_buffer_bound is False
            assert emitted.runtime_margin_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_margin_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_margin_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_collateral_semantics,
            validation_record_collateral_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert (
                emitted.collateral_semantics_ref
                == contract.collateral_semantics_ref
            )
            assert (
                emitted.collateral_semantics_contract_ref
                == contract.collateral_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.collateral_semantics_contract_available is False
            assert emitted.collateral_semantics_contract_ready is False
            assert emitted.collateral_balance_bound is False
            assert emitted.collateral_currency_bound is False
            assert emitted.collateral_requirement_bound is False
            assert emitted.collateral_source_bound is False
            assert emitted.runtime_collateral_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_collateral_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_collateral_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_liquidation_semantics,
            validation_record_liquidation_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert (
                emitted.liquidation_semantics_ref
                == contract.liquidation_semantics_ref
            )
            assert (
                emitted.liquidation_semantics_contract_ref
                == contract.liquidation_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.liquidation_semantics_contract_available is False
            assert emitted.liquidation_semantics_contract_ready is False
            assert emitted.liquidation_buffer_bound is False
            assert emitted.liquidation_price_bound is False
            assert emitted.liquidation_distance_bound is False
            assert emitted.liquidation_threshold_bound is False
            assert emitted.runtime_liquidation_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_liquidation_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_liquidation_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_reduce_only_semantics,
            validation_record_reduce_only_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert (
                emitted.reduce_only_semantics_ref
                == contract.reduce_only_semantics_ref
            )
            assert (
                emitted.reduce_only_semantics_contract_ref
                == contract.reduce_only_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.reduce_only_semantics_contract_available is False
            assert emitted.reduce_only_semantics_contract_ready is False
            assert emitted.reduce_only_flag_bound is False
            assert emitted.reduce_only_position_side_bound is False
            assert emitted.reduce_only_position_size_bound is False
            assert emitted.reduce_only_order_side_bound is False
            assert emitted.runtime_reduce_only_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_reduce_only_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_reduce_only_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_close_only_semantics,
            validation_record_close_only_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert (
                emitted.close_only_semantics_ref
                == contract.close_only_semantics_ref
            )
            assert (
                emitted.close_only_semantics_contract_ref
                == contract.close_only_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.close_only_semantics_contract_available is False
            assert emitted.close_only_semantics_contract_ready is False
            assert emitted.close_only_flag_bound is False
            assert emitted.close_only_position_side_bound is False
            assert emitted.close_only_position_size_bound is False
            assert emitted.close_only_order_side_bound is False
            assert emitted.runtime_close_only_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_close_only_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_close_only_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_funding_semantics,
            validation_record_funding_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert emitted.funding_semantics_ref == contract.funding_semantics_ref
            assert (
                emitted.funding_semantics_contract_ref
                == contract.funding_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.funding_semantics_contract_available is False
            assert emitted.funding_semantics_contract_ready is False
            assert emitted.funding_rate_bound is False
            assert emitted.funding_fee_bound is False
            assert emitted.funding_interval_bound is False
            assert emitted.funding_cost_bound is False
            assert emitted.runtime_funding_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_funding_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_funding_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

        for emitted, contract in zip(
            command.request_payload_validation_record_order_semantics,
            validation_record_order_semantic_registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.blocking == contract.blocking
            assert (
                emitted.validation_record_execution_eligibility_contract_ref
                == contract.validation_record_execution_eligibility_contract_ref
            )
            assert (
                emitted.validation_record_execution_eligibility_blocker_ref
                == contract.validation_record_execution_eligibility_blocker_ref
            )
            assert emitted.semantic_ref == contract.semantic_ref
            assert emitted.semantic_artifact_ref == contract.semantic_artifact_ref
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_contract_ref
                == contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
            )
            assert emitted.order_semantics_ref == contract.order_semantics_ref
            assert (
                emitted.order_semantics_contract_ref
                == contract.order_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.evidence_route_count == len(contract.evidence_routes)
            assert emitted.required_backend_contract == contract.required_backend_contract
            assert emitted.missing_backend_contract == contract.missing_backend_contract
            assert emitted.missing_reason == contract.missing_reason
            assert emitted.required_evidence_refs == list(contract.required_evidence_refs)
            assert emitted.required_evidence_count == len(contract.required_evidence_refs)
            assert emitted.missing_evidence_refs == list(contract.missing_evidence_refs)
            assert emitted.missing_evidence_count == len(contract.missing_evidence_refs)
            assert emitted.forbidden_execution_claims == list(
                contract.forbidden_execution_claims
            )
            assert emitted.forbidden_execution_claim_count == len(
                contract.forbidden_execution_claims
            )
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.read_only == contract.read_only
            assert (
                emitted.contextless_review_required
                == contract.contextless_review_required
            )
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.order_semantics_contract_available is False
            assert emitted.order_semantics_contract_ready is False
            assert emitted.order_identity_bound is False
            assert emitted.order_side_bound is False
            assert emitted.order_size_bound is False
            assert emitted.order_price_bound is False
            assert emitted.order_type_bound is False
            assert emitted.runtime_order_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_order_semantics is False
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_available
                is False
            )
            assert (
                emitted.semantic_artifact_runtime_evidence_acceptance_accepted
                is False
            )
            assert emitted.validation_record_order_semantics_ready is False
            assert emitted.validation_record_execution_eligible is False
            assert emitted.execution_allowed is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

    assert emitted_count == len(FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS)
    assert validator_emitted_count == len(FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS)
    assert input_schema_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS
    )
    assert output_schema_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS
    )
    assert registration_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
    )
    assert validation_evidence_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
    )
    assert validation_evidence_record_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS
    )
    assert validation_record_schema_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS
    )
    assert validation_record_replay_guard_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS
    )
    assert validation_record_audit_link_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS
    )
    assert validation_record_admission_link_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS
    )
    assert validation_record_execution_eligibility_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    )
    assert validation_record_execution_eligibility_blocker_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
    )
    assert validation_record_semantic_artifact_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS
    )
    assert validation_record_semantic_artifact_definition_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
    )
    assert validation_record_semantic_artifact_definition_review_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    )
    assert (
        validation_record_semantic_artifact_definition_review_input_emitted_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
        )
    )
    assert (
        validation_record_semantic_artifact_definition_review_output_emitted_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
        )
    )
    assert (
        validation_record_semantic_artifact_definition_review_output_acceptance_emitted_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
        )
    )
    assert (
        validation_record_semantic_artifact_runtime_evidence_emitted_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
        )
    )
    assert (
        validation_record_semantic_artifact_runtime_evidence_acceptance_emitted_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        )
    )
    assert validation_record_position_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS
    )
    assert validation_record_margin_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS
    )
    assert validation_record_collateral_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS
    )
    assert validation_record_liquidation_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS
    )
    assert validation_record_reduce_only_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS
    )
    assert validation_record_close_only_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS
    )
    assert validation_record_funding_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS
    )
    assert validation_record_order_semantic_emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS
    )
    assert command_suite.request_field_count == len(
        FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )
    assert command_suite.blocking_request_field_count == len(
        FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )
    assert command_suite.request_payload_validator_contract_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validator_contract_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
    )
    assert command_suite.ready_request_payload_validator_contract_count == 0
    assert command_suite.registered_request_payload_validator_contract_count == 0
    assert command_suite.request_payload_validator_input_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validator_input_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS
    )
    assert command_suite.ready_request_payload_validator_input_schema_count == 0
    assert command_suite.registered_request_payload_validator_input_schema_count == 0
    assert command_suite.request_payload_validator_output_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validator_output_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS
    )
    assert command_suite.ready_request_payload_validator_output_schema_count == 0
    assert command_suite.registered_request_payload_validator_output_schema_count == 0
    assert command_suite.request_payload_validator_registration_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validator_registration_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
    )
    assert command_suite.ready_request_payload_validator_registration_count == 0
    assert command_suite.registered_request_payload_validator_registration_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validator_registration_count
        == 0
    )
    assert command_suite.request_payload_validation_evidence_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validation_evidence_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
    )
    assert command_suite.ready_request_payload_validation_evidence_count == 0
    assert command_suite.recorded_request_payload_validation_evidence_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_evidence_count
        == 0
    )
    assert command_suite.request_payload_validation_evidence_record_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validation_evidence_record_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS
    )
    assert command_suite.ready_request_payload_validation_evidence_record_count == 0
    assert command_suite.stored_request_payload_validation_evidence_record_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_evidence_record_count
        == 0
    )
    assert command_suite.request_payload_validation_record_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS
    )
    assert command_suite.blocking_request_payload_validation_record_schema_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS
    )
    assert command_suite.ready_request_payload_validation_record_schema_count == 0
    assert command_suite.registered_request_payload_validation_record_schema_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_schema_count
        == 0
    )
    assert command_suite.request_payload_validation_record_replay_guard_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS
    )
    assert (
        command_suite.blocking_request_payload_validation_record_replay_guard_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS)
    )
    assert command_suite.ready_request_payload_validation_record_replay_guard_count == 0
    assert command_suite.idempotency_bound_request_payload_validation_record_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_replay_guard_count
        == 0
    )
    assert command_suite.request_payload_validation_record_audit_link_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS
    )
    assert (
        command_suite.blocking_request_payload_validation_record_audit_link_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS)
    )
    assert command_suite.ready_request_payload_validation_record_audit_link_count == 0
    assert command_suite.audit_bound_request_payload_validation_record_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_audit_link_count
        == 0
    )
    assert command_suite.request_payload_validation_record_admission_link_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS
    )
    assert (
        command_suite.blocking_request_payload_validation_record_admission_link_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_admission_link_count
        == 0
    )
    assert command_suite.admission_bound_request_payload_validation_record_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_admission_link_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_count
        == 0
    )
    assert command_suite.execution_eligible_request_payload_validation_record_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_execution_eligibility_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_blocker_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_blocker_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
        )
    )
    assert (
        command_suite.resolved_request_payload_validation_record_execution_eligibility_blocker_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_execution_eligibility_blocker_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_execution_eligibility_resolution_plan_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS
        )
    )
    assert (
        command_suite.present_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        == 0
    )
    assert (
        command_suite.validated_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS
        )
    )
    assert (
        command_suite.available_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
        == 0
    )
    assert (
        command_suite.writer_available_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS
        )
    )
    assert (
        command_suite.available_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        == 0
    )
    assert (
        command_suite.configured_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        == 0
    )
    assert (
        command_suite.accepted_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
        == 0
    )
    assert (
        command_suite.recorded_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
        == 0
    )
    assert (
        command_suite.performed_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        == 0
    )
    assert (
        command_suite.created_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        == 0
    )
    assert (
        command_suite.claimed_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        == 0
    )
    assert (
        command_suite.created_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        == 0
    )
    assert (
        command_suite.resolved_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        == 0
    )
    for command in command_suite.commands:
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plans
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_count
        )
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_steps
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_count
        )
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_count
        )
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_count
        )
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirement_count
        )
        for store_requirement in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements
        ):
            assert store_requirement.blocking is True
            assert (
                store_requirement.resolution_plan_step_review_input_store_requirement_required
                is True
            )
            assert (
                store_requirement.resolution_plan_step_review_input_store_available
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_writer_available
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_record_key_available
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_validation_gate_ready
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_replay_gate_ready
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_present
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_accepted
                is False
            )
            assert (
                store_requirement.resolution_plan_step_review_input_validated
                is False
            )
            assert store_requirement.blocker_resolved is False
            assert store_requirement.validation_record_execution_eligible is False
            assert store_requirement.execution_allowed is False
            assert store_requirement.live_coinbase_orders_ran is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contract_count
        )
        for record_contract in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts
        ):
            assert record_contract.blocking is True
            assert record_contract.record_contract_required is True
            assert record_contract.record_contract_available is False
            assert record_contract.record_schema_available is False
            assert record_contract.append_only_log_available is False
            assert record_contract.idempotency_key_bound is False
            assert record_contract.payload_schema_validated is False
            assert record_contract.replay_protected is False
            assert record_contract.store_available is False
            assert record_contract.writer_available is False
            assert record_contract.writer_allowed is False
            assert record_contract.write_allowed is False
            assert record_contract.record_present is False
            assert record_contract.record_accepted is False
            assert record_contract.record_validated is False
            assert record_contract.validation_configured is False
            assert record_contract.replay_protection_configured is False
            assert (
                record_contract.resolution_plan_step_review_input_store_available
                is False
            )
            assert (
                record_contract.resolution_plan_step_review_input_writer_available
                is False
            )
            assert (
                record_contract.resolution_plan_step_review_input_record_key_available
                is False
            )
            assert (
                record_contract.resolution_plan_step_review_input_validation_gate_ready
                is False
            )
            assert (
                record_contract.resolution_plan_step_review_input_replay_gate_ready
                is False
            )
            assert record_contract.resolution_plan_step_review_input_present is False
            assert record_contract.resolution_plan_step_review_input_accepted is False
            assert record_contract.resolution_plan_step_review_input_validated is False
            assert record_contract.blocker_resolved is False
            assert record_contract.validation_record_execution_eligible is False
            assert record_contract.execution_allowed is False
            assert record_contract.live_coinbase_orders_ran is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_count
        )
        for record_validation in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations
        ):
            assert record_validation.blocking is True
            assert record_validation.record_validation_required is True
            assert record_validation.record_validation_ready is False
            assert record_validation.record_validation_configured is False
            assert record_validation.record_validation_registered is False
            assert record_validation.record_validation_gate_ready is False
            assert record_validation.record_validation_gate_passed is False
            assert record_validation.record_validation_replay_guard_ready is False
            assert record_validation.record_validation_schema_ready is False
            assert record_validation.record_validation_append_only_log_ready is False
            assert record_validation.record_validation_idempotency_bound is False
            assert record_validation.record_validation_payload_bound is False
            assert record_validation.record_validation_contextless_review_passed is False
            assert record_validation.record_validation_performed is False
            assert record_validation.record_validation_accepted is False
            assert record_validation.record_validation_recorded is False
            assert record_validation.record_present is False
            assert record_validation.record_accepted is False
            assert record_validation.record_validated is False
            assert record_validation.validation_configured is False
            assert record_validation.replay_protection_configured is False
            assert (
                record_validation.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref
            )
            assert (
                record_validation.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref
            )
            assert record_validation.blocker_resolved is False
            assert record_validation.validation_record_execution_eligible is False
            assert record_validation.execution_allowed is False
            assert record_validation.live_coinbase_orders_ran is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_count
        )
        for remediation in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations
        ):
            assert remediation.blocking is True
            assert remediation.record_validation_remediation_required is True
            assert remediation.record_validation_remediation_ready is False
            assert remediation.record_validation_remediation_configured is False
            assert remediation.record_validation_remediation_performed is False
            assert remediation.record_validation_remediation_recorded is False
            assert remediation.record_validation_remediation_accepted is False
            assert (
                remediation.record_validation_remediation_work_item_created is False
            )
            assert (
                remediation.record_validation_remediation_dependency_ready is False
            )
            assert remediation.record_validation_required is True
            assert remediation.record_validation_ready is False
            assert remediation.record_validation_accepted is False
            assert (
                remediation.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref
            )
            assert (
                remediation.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref
            )
            assert remediation.blocker_resolved is False
            assert remediation.validation_record_execution_eligible is False
            assert remediation.execution_allowed is False
            assert remediation.live_coinbase_orders_ran is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_count
        )
        for dependency in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies
        ):
            assert dependency.blocking is True
            assert dependency.record_validation_remediation_dependency_required is True
            assert dependency.record_validation_remediation_dependency_ready is False
            assert dependency.record_validation_remediation_dependency_resolved is False
            assert dependency.record_validation_remediation_dependency_performed is False
            assert dependency.record_validation_remediation_dependency_graph_ready is False
            assert (
                dependency.record_validation_remediation_dependency_work_item_created
                is False
            )
            assert (
                dependency.record_validation_remediation_dependency_work_item_claimed
                is False
            )
            assert (
                dependency.record_validation_remediation_dependency_claim_trace_created
                is False
            )
            assert dependency.record_validation_remediation_dependency_action_count == len(
                dependency.record_validation_remediation_dependency_action_refs
            )
            assert dependency.record_validation_remediation_dependency_blocker_count == len(
                dependency.record_validation_remediation_dependency_blockers
            )
            assert (
                dependency.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_ref
            )
            assert (
                dependency.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_contract_ref
            )
            assert (
                dependency.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref
            )
            assert dependency.blocker_resolved is False
            assert dependency.validation_record_execution_eligible is False
            assert dependency.execution_allowed is False
            assert dependency.live_coinbase_orders_ran is False
            assert dependency.browser_authority == "display_only"
            assert dependency.bff_authority == "forward_only_no_execution"
            assert dependency.spot_rule_authority is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_count
        )
        for work_item in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items
        ):
            assert work_item.blocking is True
            assert (
                work_item.record_validation_remediation_dependency_work_item_required
                is True
            )
            assert (
                work_item.record_validation_remediation_dependency_work_item_ready
                is False
            )
            assert (
                work_item.record_validation_remediation_dependency_work_item_created
                is False
            )
            assert (
                work_item.record_validation_remediation_dependency_work_item_claimed
                is False
            )
            assert work_item.work_item_created is False
            assert work_item.work_item_claimed is False
            assert work_item.claim_ledger_registered is False
            assert work_item.owner_review_accepted is False
            assert work_item.contextless_review_passed is False
            assert work_item.accepts_evidence is False
            assert work_item.writes_evidence is False
            assert (
                work_item.record_validation_remediation_dependency_work_item_action_count
                == len(
                    work_item.record_validation_remediation_dependency_work_item_action_refs
                )
            )
            assert (
                work_item.record_validation_remediation_dependency_work_item_blocker_count
                == len(
                    work_item.record_validation_remediation_dependency_work_item_blockers
                )
            )
            assert (
                work_item.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref
            )
            assert (
                work_item.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref
            )
            assert (
                work_item.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_ref
            )
            assert work_item.blocker_resolved is False
            assert work_item.validation_record_execution_eligible is False
            assert work_item.execution_allowed is False
            assert work_item.live_coinbase_orders_ran is False
            assert work_item.browser_authority == "display_only"
            assert work_item.bff_authority == "forward_only_no_execution"
            assert work_item.spot_rule_authority is False
        assert (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
            == min(
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count,
                FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT,
            )
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_detail_row_limit
            == FUTURES_COMMAND_SUITE_RESOLUTION_PLAN_DETAIL_ROW_LIMIT
        )
        assert (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_detail_rows_limited
            is (
                command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
                > command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
            )
        )
        assert len(
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces
        ) == (
            command.materialized_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count
        )
        for claim_trace in (
            command.request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces
        ):
            assert claim_trace.blocking is True
            assert (
                claim_trace.record_validation_remediation_dependency_work_item_claim_trace_required
                is True
            )
            assert (
                claim_trace.record_validation_remediation_dependency_work_item_claim_trace_ready
                is False
            )
            assert (
                claim_trace.record_validation_remediation_dependency_work_item_claim_trace_created
                is False
            )
            assert claim_trace.claim_trace_created is False
            assert claim_trace.claim_trace_ready is False
            assert claim_trace.claim_allowed is False
            assert claim_trace.claim_resolved is False
            assert claim_trace.work_item_created is False
            assert claim_trace.work_item_claimed is False
            assert claim_trace.claim_ledger_registered is False
            assert claim_trace.claim_review_accepted is False
            assert claim_trace.contextless_review_passed is False
            assert claim_trace.accepts_evidence is False
            assert claim_trace.writes_evidence is False
            assert (
                claim_trace.record_validation_remediation_dependency_work_item_claim_trace_action_count
                == len(
                    claim_trace.record_validation_remediation_dependency_work_item_claim_trace_action_refs
                )
            )
            assert (
                claim_trace.record_validation_remediation_dependency_work_item_claim_trace_blocker_count
                == len(
                    claim_trace.record_validation_remediation_dependency_work_item_claim_trace_blockers
                )
            )
            assert (
                claim_trace.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_ref
            )
            assert (
                claim_trace.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_contract_ref
            )
            assert (
                claim_trace.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref
            )
            assert claim_trace.claim_trace_target_ref
            assert claim_trace.claim_trace_source_ref
            assert claim_trace.blocker_resolved is False
            assert claim_trace.validation_record_execution_eligible is False
            assert claim_trace.execution_allowed is False
            assert claim_trace.live_coinbase_orders_ran is False
            assert claim_trace.browser_authority == "display_only"
            assert claim_trace.bff_authority == "forward_only_no_execution"
            assert claim_trace.spot_rule_authority is False
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS)
    )
    assert command_suite.ready_request_payload_validation_record_semantic_artifact_count == 0
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_definition_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_definition_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_definition_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_definition_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_definition_review_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_definition_review_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_definition_review_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_definition_review_input_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_definition_review_input_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_definition_review_input_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_input_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_definition_review_output_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_definition_review_output_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_runtime_evidence_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        )
    )
    assert (
        command_suite.blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
        == len(
            FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        )
    )
    assert (
        command_suite.ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_position_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_position_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_position_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_position_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_margin_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_margin_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_margin_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_margin_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_collateral_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_collateral_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_collateral_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_collateral_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_liquidation_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_liquidation_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_liquidation_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_liquidation_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_reduce_only_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_reduce_only_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_reduce_only_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_reduce_only_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_close_only_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_close_only_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_close_only_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_close_only_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_funding_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_funding_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_funding_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_funding_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_order_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_order_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_order_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_order_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_cancel_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_cancel_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_cancel_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_cancel_semantic_count
        == 0
    )
    assert (
        command_suite.request_payload_validation_record_reconciliation_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.blocking_request_payload_validation_record_reconciliation_semantic_count
        == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS)
    )
    assert (
        command_suite.ready_request_payload_validation_record_reconciliation_semantic_count
        == 0
    )
    assert (
        command_suite.runtime_observed_request_payload_validation_record_reconciliation_semantic_count
        == 0
    )


def test_futures_request_payload_validation_record_cancel_semantics_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    cancel_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.CANCEL_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.CANCEL_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.CANCEL_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in cancel_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.cancel_semantics_contract_available is False
        and contract.cancel_semantics_contract_ready is False
        and contract.cancel_identity_bound is False
        and contract.cancel_client_order_id_bound is False
        and contract.cancel_order_wrapper_bound is False
        and contract.cancel_active_placement_bound is False
        and contract.cancel_audit_bound is False
        and contract.runtime_cancel_evidence_observed is False
        and contract.runtime_evidence_satisfies_cancel_semantics is False
        and contract.validation_record_cancel_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.cancel_semantics_ref == contract.semantic_ref
        and contract.cancel_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_cancel_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.cancel_semantics_contract_ref
        and contract.missing_backend_contract == contract.cancel_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.ADMIN_ADMISSION_AUDITS
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.ADMIN_RECONCILIATION_PLANS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 18
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and "cancel_client_order_id_bound" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 30
        and f"{contract.cancel_semantics_contract_ref}.client_order_id"
        in contract.required_evidence_refs
        and (
            f"{contract.cancel_semantics_contract_ref}."
            "cancel_order_client_order_id_wrapper"
        )
        in contract.required_evidence_refs
        and "/api/v1/futures/orders/{client_order_id}/cancel"
        in contract.required_evidence_refs
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS
    )

    emitted_count = 0
    for command in command_suite.commands:
        registry_rows = list(
            iter_futures_request_payload_validation_record_cancel_semantics(
                command.command
            )
        )
        emitted_count += len(command.request_payload_validation_record_cancel_semantics)
        assert command.request_payload_validation_record_cancel_semantic_count == len(
            registry_rows
        )
        assert (
            command.blocking_request_payload_validation_record_cancel_semantic_count
            == len(registry_rows)
        )
        assert command.ready_request_payload_validation_record_cancel_semantic_count == 0
        assert (
            command.runtime_observed_request_payload_validation_record_cancel_semantic_count
            == 0
        )
        assert all(
            contract.cancel_semantics_contract_ref in command.required_backend_contracts
            for contract in registry_rows
        )
        for emitted, contract in zip(
            command.request_payload_validation_record_cancel_semantics,
            registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert emitted.cancel_semantics_ref == contract.cancel_semantics_ref
            assert (
                emitted.cancel_semantics_contract_ref
                == contract.cancel_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.required_backend_contract == (
                contract.required_backend_contract
            )
            assert emitted.missing_backend_contract == (
                contract.missing_backend_contract
            )
            assert emitted.cancel_semantics_contract_available is False
            assert emitted.cancel_semantics_contract_ready is False
            assert emitted.cancel_identity_bound is False
            assert emitted.cancel_client_order_id_bound is False
            assert emitted.cancel_order_wrapper_bound is False
            assert emitted.cancel_active_placement_bound is False
            assert emitted.cancel_audit_bound is False
            assert emitted.runtime_cancel_evidence_observed is False
            assert emitted.runtime_evidence_satisfies_cancel_semantics is False
            assert emitted.validation_record_cancel_semantics_ready is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.spot_rule_authority is False

    assert emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS
    )


def test_futures_request_payload_validation_record_reconciliation_semantics_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS
    ) == len(FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS)
    reconciliation_runtime_evidence_acceptance_contract_refs = {
        contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
        if contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.RECONCILIATION_SEMANTICS
    }
    assert all(
        contract.semantic_artifact
        == AdminFuturesCommandSemanticArtifact.RECONCILIATION_SEMANTICS
        and contract.blocker
        == AdminFuturesCommandExecutionEligibilityBlocker.RECONCILIATION_SEMANTICS_MISSING
        and contract.semantic_artifact_runtime_evidence_acceptance_contract_ref
        in reconciliation_runtime_evidence_acceptance_contract_refs
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.required is True
        and contract.blocking is True
        and contract.backend_owned is True
        and contract.read_only is True
        and contract.contextless_review_required is True
        and contract.spot_rule_authority is False
        and contract.reconciliation_semantics_contract_available is False
        and contract.reconciliation_semantics_contract_ready is False
        and contract.reconciliation_identity_bound is False
        and contract.reconciliation_position_key_bound is False
        and contract.reconciliation_plan_bound is False
        and contract.reconciliation_reason_bound is False
        and contract.post_exchange_reconciliation_bound is False
        and contract.reconciliation_audit_bound is False
        and contract.runtime_reconciliation_evidence_observed is False
        and contract.runtime_evidence_satisfies_reconciliation_semantics is False
        and contract.validation_record_reconciliation_semantics_ready is False
        and contract.validation_record_execution_eligible is False
        and contract.execution_allowed is False
        and contract.live_coinbase_orders_ran is False
        and contract.reconciliation_semantics_ref == contract.semantic_ref
        and contract.reconciliation_semantics_contract_ref.startswith(
            "application/admin_api/"
            "futures_request_payload_validation_record_reconciliation_semantics.py::"
        )
        and contract.required_backend_contract
        == contract.reconciliation_semantics_contract_ref
        and contract.missing_backend_contract == contract.reconciliation_semantics_ref
        and len(contract.evidence_routes) == 2
        and AdminFuturesCommandEvidenceRoute.ADMIN_ADMISSION_AUDITS
        in contract.evidence_routes
        and AdminFuturesCommandEvidenceRoute.ADMIN_RECONCILIATION_PLANS
        in contract.evidence_routes
        and len(contract.forbidden_execution_claims) == 19
        and "spot_rule_authority" in contract.forbidden_execution_claims
        and "reconciliation_position_key_bound" in contract.forbidden_execution_claims
        and "reconciliation_reason_bound" in contract.forbidden_execution_claims
        and len(contract.required_evidence_refs) >= 31
        and f"{contract.reconciliation_semantics_contract_ref}.position_key"
        in contract.required_evidence_refs
        and (
            f"{contract.reconciliation_semantics_contract_ref}."
            "reconciliation_reason"
        )
        in contract.required_evidence_refs
        and "/api/v1/futures/positions/{position_key}/reconciliation"
        in contract.required_evidence_refs
        and contract.missing_evidence_refs == contract.required_evidence_refs
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS
    )

    emitted_count = 0
    for command in command_suite.commands:
        registry_rows = list(
            iter_futures_request_payload_validation_record_reconciliation_semantics(
                command.command
            )
        )
        emitted_count += len(
            command.request_payload_validation_record_reconciliation_semantics
        )
        assert (
            command.request_payload_validation_record_reconciliation_semantic_count
            == len(registry_rows)
        )
        assert (
            command.blocking_request_payload_validation_record_reconciliation_semantic_count
            == len(registry_rows)
        )
        assert (
            command.ready_request_payload_validation_record_reconciliation_semantic_count
            == 0
        )
        assert (
            command.runtime_observed_request_payload_validation_record_reconciliation_semantic_count
            == 0
        )
        assert all(
            contract.reconciliation_semantics_contract_ref
            in command.required_backend_contracts
            for contract in registry_rows
        )
        for emitted, contract in zip(
            command.request_payload_validation_record_reconciliation_semantics,
            registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.blocker == contract.blocker
            assert emitted.semantic_artifact == contract.semantic_artifact
            assert (
                emitted.reconciliation_semantics_ref
                == contract.reconciliation_semantics_ref
            )
            assert (
                emitted.reconciliation_semantics_contract_ref
                == contract.reconciliation_semantics_contract_ref
            )
            assert emitted.evidence_routes == list(contract.evidence_routes)
            assert emitted.required_backend_contract == (
                contract.required_backend_contract
            )
            assert emitted.missing_backend_contract == (
                contract.missing_backend_contract
            )
            assert emitted.reconciliation_semantics_contract_available is False
            assert emitted.reconciliation_semantics_contract_ready is False
            assert emitted.reconciliation_identity_bound is False
            assert emitted.reconciliation_position_key_bound is False
            assert emitted.reconciliation_plan_bound is False
            assert emitted.reconciliation_reason_bound is False
            assert emitted.post_exchange_reconciliation_bound is False
            assert emitted.reconciliation_audit_bound is False
            assert emitted.runtime_reconciliation_evidence_observed is False
            assert (
                emitted.runtime_evidence_satisfies_reconciliation_semantics
                is False
            )
            assert emitted.validation_record_reconciliation_semantics_ready is False
            assert emitted.live_coinbase_orders_ran is False
            assert emitted.spot_rule_authority is False

    assert emitted_count == len(
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS
    )


def test_futures_risk_guard_contract_is_disabled() -> None:
    guard = AdminApiFuturesRiskGuard()

    assert FUTURES_RISK_GUARD_CONTRACT.method_name == (
        "evaluate_futures_margin_collateral_liquidation"
    )
    assert FUTURES_RISK_GUARD_CONTRACT.contract_ref == (
        "application/admin_api/futures_risk_guard.py::"
        "evaluate_futures_margin_collateral_liquidation"
    )
    assert set(FUTURES_RISK_GUARD_CONTRACT.commands) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.RECONCILE,
    }

    with pytest.raises(FuturesRiskGuardDisabledError) as exc_info:
        guard.evaluate_futures_margin_collateral_liquidation()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "risk proof acceptance" in message
    assert "Coinbase calls" in message


def test_futures_reconciliation_contract_is_disabled() -> None:
    reconciliation = AdminApiFuturesReconciliation()

    assert FUTURES_RECONCILIATION_CONTRACT.method_name == (
        "record_futures_reconciliation_plan"
    )
    assert FUTURES_RECONCILIATION_CONTRACT.contract_ref == (
        "application/admin_api/futures_reconciliation.py::"
        "record_futures_reconciliation_plan"
    )
    assert set(FUTURES_RECONCILIATION_CONTRACT.commands) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    }

    with pytest.raises(FuturesReconciliationDisabledError) as exc_info:
        reconciliation.record_futures_reconciliation_plan()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "reconciliation execution" in message
    assert "Coinbase calls" in message


def test_futures_route_contracts_register_no_live_command_drafts() -> None:
    expected_refs = {
        AdminFuturesCommandAction.PLACE: (
            "api/v1/routes/futures.py::futures_place_route_contract"
        ),
        AdminFuturesCommandAction.CLOSE_REDUCE: (
            "api/v1/routes/futures.py::futures_close_reduce_route_contract"
        ),
        AdminFuturesCommandAction.CANCEL: (
            "api/v1/routes/futures.py::futures_cancel_route_contract"
        ),
        AdminFuturesCommandAction.RECONCILE: (
            "api/v1/routes/futures.py::futures_reconcile_route_contract"
        ),
    }
    expected_routes = {
        AdminFuturesCommandAction.PLACE: "/api/v1/futures/orders",
        AdminFuturesCommandAction.CLOSE_REDUCE: (
            "/api/v1/futures/positions/{position_key}/close-reduce"
        ),
        AdminFuturesCommandAction.CANCEL: (
            "/api/v1/futures/orders/{client_order_id}/cancel"
        ),
        AdminFuturesCommandAction.RECONCILE: (
            "/api/v1/futures/positions/{position_key}/reconciliation"
        ),
    }

    assert set(FUTURES_ROUTE_CONTRACTS) == set(AdminFuturesCommandAction)
    assert futures_routes.futures_place_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.PLACE]
    )
    assert futures_routes.futures_close_reduce_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.CLOSE_REDUCE]
    )
    assert futures_routes.futures_cancel_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.CANCEL]
    )
    assert futures_routes.futures_reconcile_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.RECONCILE]
    )

    for command, contract in FUTURES_ROUTE_CONTRACTS.items():
        assert contract.contract_ref == expected_refs[command]
        assert contract.route_template == expected_routes[command]
        assert contract.method == "POST"
        assert contract.route_registered is True
        assert contract.command_draft_allowed is True
        assert contract.live_adapter_bound is False
        assert contract.execution_allowed is False
        assert contract.reconciliation_execution_enabled is False
        assert contract.state_mutation_allowed is False
        assert contract.live_coinbase_orders_ran is False
        assert contract.browser_authority == "display_only"
        assert contract.bff_authority == "forward_only_no_execution"
        assert futures_live_adapter_contract_ref(command) == (
            f"application/admin_api/live_execution.py::{command.value}_adapter_contract"
        )
        adapter_contract = FUTURES_LIVE_ADAPTER_CONTRACTS[command]
        assert adapter_contract.contract_ref == futures_live_adapter_contract_ref(command)
        assert adapter_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert adapter_contract.present is True
        assert adapter_contract.adapter_configured is False
        assert adapter_contract.adapter_constructed is False
        assert adapter_contract.invocation_allowed is False
        assert adapter_contract.execution_allowed is False
        assert adapter_contract.live_coinbase_orders_ran is False
        assert adapter_contract.browser_authority == "display_only"
        assert adapter_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in adapter_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in adapter_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in adapter_contract.blockers
        )

        construction_contract = FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS[
            command
        ]
        assert construction_contract.contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert construction_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert construction_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert construction_contract.present is True
        assert construction_contract.construction_allowed is False
        assert construction_contract.adapter_constructed is False
        assert construction_contract.invocation_allowed is False
        assert construction_contract.execution_allowed is False
        assert construction_contract.live_coinbase_orders_ran is False
        assert construction_contract.browser_authority == "display_only"
        assert construction_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in construction_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in construction_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in construction_contract.blockers
        )

        decision_contract = FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS[command]
        assert decision_contract.contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert decision_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert decision_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert decision_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert decision_contract.present is True
        assert decision_contract.decision_allowed is False
        assert decision_contract.decision_record_required is True
        assert decision_contract.decision_record_available is False
        assert decision_contract.adapter_constructed is False
        assert decision_contract.invocation_allowed is False
        assert decision_contract.execution_allowed is False
        assert decision_contract.live_coinbase_orders_ran is False
        assert decision_contract.browser_authority == "display_only"
        assert decision_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in decision_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in decision_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in decision_contract.blockers
        )

        decision_record_contract = FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS[
            command
        ]
        assert decision_record_contract.contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert decision_record_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert decision_record_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert decision_record_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert decision_record_contract.invocation_contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert decision_record_contract.present is True
        assert decision_record_contract.decision_record_writer_configured is False
        assert decision_record_contract.decision_record_allowed is False
        assert decision_record_contract.decision_record_available is False
        assert decision_record_contract.adapter_constructed is False
        assert decision_record_contract.invocation_allowed is False
        assert decision_record_contract.execution_allowed is False
        assert decision_record_contract.live_coinbase_orders_ran is False
        assert decision_record_contract.browser_authority == "display_only"
        assert decision_record_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in decision_record_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in decision_record_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in decision_record_contract.blockers
        )

        invocation_contract = FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS[command]
        assert invocation_contract.contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert invocation_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert invocation_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert invocation_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert invocation_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert invocation_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert invocation_contract.present is True
        assert invocation_contract.invocation_adapter_configured is False
        assert invocation_contract.invocation_allowed is False
        assert invocation_contract.invocation_performed is False
        assert invocation_contract.execution_allowed is False
        assert invocation_contract.live_coinbase_orders_ran is False
        assert invocation_contract.browser_authority == "display_only"
        assert invocation_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in invocation_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in invocation_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in invocation_contract.blockers
        )

        execution_contract = FUTURES_LIVE_ADAPTER_EXECUTION_CONTRACTS[command]
        assert execution_contract.contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert execution_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert execution_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert execution_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert execution_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert execution_contract.invocation_contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert execution_contract.coinbase_exchange_submission_contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert execution_contract.present is True
        assert execution_contract.execution_adapter_configured is False
        assert execution_contract.execution_allowed is False
        assert execution_contract.execution_performed is False
        assert execution_contract.coinbase_submission_allowed is False
        assert execution_contract.coinbase_order_submit_ran is False
        assert execution_contract.live_coinbase_orders_ran is False
        assert execution_contract.browser_authority == "display_only"
        assert execution_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in execution_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in execution_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in execution_contract.blockers
        )

        submission_contract = FUTURES_COINBASE_EXCHANGE_SUBMISSION_CONTRACTS[command]
        assert submission_contract.contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert submission_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert submission_contract.post_exchange_submission_reconciliation_contract_ref == (
            futures_post_exchange_submission_reconciliation_contract_ref(command)
        )
        assert submission_contract.present is True
        assert submission_contract.coinbase_submission_allowed is False
        assert submission_contract.coinbase_order_submit_ran is False
        assert submission_contract.coinbase_cancel_submit_ran is False
        assert submission_contract.exchange_order_acknowledged is False
        assert submission_contract.post_exchange_reconciliation_required is True
        assert submission_contract.post_exchange_reconciliation_available is True
        assert submission_contract.command_route_registered is False
        assert submission_contract.command_draft_allowed is False
        assert submission_contract.execution_allowed is False
        assert submission_contract.reconciliation_execution_enabled is False
        assert submission_contract.state_mutation_allowed is False
        assert submission_contract.live_coinbase_orders_ran is False
        assert submission_contract.browser_authority == "display_only"
        assert submission_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in submission_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in submission_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in submission_contract.blockers
        )

        reconciliation_contract = (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACTS[command]
        )
        assert reconciliation_contract.contract_ref == (
            futures_post_exchange_submission_reconciliation_contract_ref(command)
        )
        assert reconciliation_contract.coinbase_exchange_submission_contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert reconciliation_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert reconciliation_contract.present is True
        assert reconciliation_contract.reconciliation_required is True
        assert reconciliation_contract.reconciliation_available is True
        assert reconciliation_contract.exchange_order_acknowledgement_required is True
        assert reconciliation_contract.exchange_order_acknowledged is False
        assert reconciliation_contract.reconciliation_execution_enabled is False
        assert reconciliation_contract.reconciliation_executed is False
        assert reconciliation_contract.command_route_registered is False
        assert reconciliation_contract.command_draft_allowed is False
        assert reconciliation_contract.execution_allowed is False
        assert reconciliation_contract.coinbase_submission_allowed is False
        assert reconciliation_contract.coinbase_order_submit_ran is False
        assert reconciliation_contract.coinbase_cancel_submit_ran is False
        assert reconciliation_contract.state_mutation_allowed is False
        assert reconciliation_contract.live_coinbase_orders_ran is False
        assert reconciliation_contract.browser_authority == "display_only"
        assert reconciliation_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in reconciliation_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in reconciliation_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in reconciliation_contract.blockers
        )


def _headers(*, roles: str = "viewer") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "X-Admin-Actor": "operator-001",
        "X-Admin-Roles": roles,
    }


def _command_headers(
    *,
    idempotency_key: str,
    operator_intent: str,
    roles: str = AdminApiRole.ADMIN.value,
) -> dict[str, str]:
    headers = _headers(roles=roles)
    headers.update({
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-futures-risk-proof-route-001",
        "X-Operator-Intent": operator_intent,
    })
    return headers


def _risk_proof_request() -> FuturesRiskProofRecordRequest:
    return FuturesRiskProofRecordRequest(
        command=AdminFuturesCommandAction.PLACE,
        proof_kind=AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        proof_contract_ref="futures_place.margin_collateral.proof_contract",
        evidence_ref="futures_place.margin_collateral.runtime_margin_review",
        evidence_source=AdminFuturesRiskProofEvidenceSource.TEST_EVIDENCE,
        risk_evidence_refs=[
            "futures.account.margin",
            "futures.account.collateral",
        ],
        product_id="BIT-20DEC30-CDE",
        reconciliation_plan_id="futures-reconciliation-plan-001",
        approval_snapshot_id="futures-approval-snapshot-001",
        admission_audit_id="futures-admission-audit-001",
        cap_guard_decision_id="futures-cap-guard-001",
        operator_reason="focused regression proof",
    )


def _admission_decision(
    request: FuturesRiskProofRecordRequest,
) -> AdminLiveAdmissionDecisionEvidence:
    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route="/api/v1/futures/risk-proofs",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="futures_risk_proof",
        identity_value=f"{request.command.value}:{request.proof_kind.value}",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        service_method="record_futures_risk_proof",
        actor_id="operator-001",
        idempotency_key="futures-risk-proof-idem-001",
        operator_intent="record futures risk proof evidence",
        payload_hash=PAYLOAD_HASH,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=request.approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id="risk-reviewer-001",
        approval_snapshot_requested_by_actor_id="operator-001",
        approval_snapshot_expires_at="2099-01-01T00:00:00+00:00",
        admission_audit_present=True,
        admission_audit_id=request.admission_audit_id,
        cap_guard_present=True,
        cap_guard_decision_id=request.cap_guard_decision_id,
        reconciliation_plan_present=True,
        reconciliation_plan_id=request.reconciliation_plan_id,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["futures risk proof append-only contract test evidence"],
        detail="Futures risk proof admission evidence remains live-disabled.",
    )


def _payload_hash_for_route(
    *,
    request: FuturesRiskProofRecordRequest,
    idempotency_key: str,
    operator_intent: str,
) -> str:
    del idempotency_key
    actor = AdminApiActor(
        actor_id="operator-001",
        roles=[AdminApiRole.ADMIN],
    )
    return _idempotency_payload_hash(
        endpoint="POST /api/v1/futures/risk-proofs",
        actor=actor,
        operator_intent=operator_intent,
        body=request.model_dump(mode="json"),
    )


def _append_futures_risk_proof_admission_chain(
    *,
    request: FuturesRiskProofRecordRequest,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
) -> None:
    route = "/api/v1/futures/risk-proofs"
    method = "POST"
    module_id = "futures_perpetuals"
    identity_key = "futures_risk_proof"
    identity_value = f"{request.command.value}:{request.proof_kind.value}"
    action_class = AdminApiActionClass.LOCAL_STATE_MUTATION
    permission = AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    service_method = "record_futures_risk_proof"
    approval = AdminApiApprovalRecord(
        approval_id=request.approval_snapshot_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        approved_by_actor_id="risk-reviewer-001",
        requested_by_actor_id="operator-001",
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        cap_guard_decision_ref=request.cap_guard_decision_id,
        reconciliation_plan_ref=request.reconciliation_plan_id,
    )
    approval_store.append(approval)
    admission_decision = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        actor_id="operator-001",
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=approval.approval_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id=approval.approved_by_actor_id,
        approval_snapshot_requested_by_actor_id=approval.requested_by_actor_id,
        approval_snapshot_expires_at=approval.expires_at.isoformat(),
        admission_audit_present=False,
        cap_guard_present=False,
        reconciliation_plan_present=False,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["prior append-only futures risk-proof admission audit"],
        detail="Prior backend-owned futures risk-proof admission audit.",
    )
    audit_store.append(
        AdminApiAuditEvent(
            audit_id=request.admission_audit_id,
            actor_id="operator-001",
            action_class=action_class,
            permission=permission,
            endpoint=f"{method} {route}",
            request_id="corr-futures-risk-proof-admission",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            approval_id=approval.approval_id,
            status=AdminApiCommandStatus.REJECTED,
            failure_stage="approval",
            message="Prior futures risk-proof admission audit.",
            admission_decision=admission_decision,
        )
    )
    cap_guard_store.append(
        CapGuardDecisionRecord(
            decision_id=request.cap_guard_decision_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            cap_policy_ref="futures_risk_proof_cap:local_only",
            guard_policy_ref="futures_risk_proof_prerequisites",
            product_scope="futures risk proof local evidence",
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof cap/guard evidence.",
        )
    )
    reconciliation_store.append(
        ReconciliationPlanRecord(
            plan_id=request.reconciliation_plan_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            cap_guard_decision_id=request.cap_guard_decision_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            reconciliation_policy_ref="futures_risk_proof_reconciliation:local_only",
            product_scope="futures risk proof local evidence",
            exchange_submission_required=False,
            post_submit_reconciliation_required=False,
            retained_inventory_required=False,
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof reconciliation evidence.",
        )
    )


def test_futures_risk_proof_service_persists_no_live_record(tmp_path) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()

    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    assert record.mutation_family.value == "futures_risk_proof"
    assert record.required_permission == AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    assert record.proof_persisted is True
    assert record.risk_proof_accepted is False
    assert record.command_route_registered is False
    assert record.command_execution_allowed is False
    assert record.coinbase_order_submitted is False
    assert record.live_coinbase_orders_ran is False
    assert store.find_by_proof_id(record.futures_risk_proof_id) == record


def test_futures_risk_proof_identity_lookup_is_not_limited_to_recent_window(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    service = AdminApiFuturesRiskProofService()
    old_record = service.record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-old-idem",
        correlation_id="corr-futures-risk-proof-old",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-old",
    )

    for index in range(501):
        store.append(
            old_record.model_copy(
                update={
                    "futures_risk_proof_id": f"futures-risk-proof-new-{index}",
                    "idempotency_key": f"futures-risk-proof-new-idem-{index}",
                    "correlation_id": f"corr-futures-risk-proof-new-{index}",
                    "audit_id": f"audit-futures-risk-proof-new-{index}",
                }
            )
        )

    assert all(
        record.futures_risk_proof_id != old_record.futures_risk_proof_id
        for record in store.read_recent(limit=500)
    )
    assert store.find_by_proof_id(old_record.futures_risk_proof_id) == old_record

    with pytest.raises(FuturesRiskProofError, match="already exists"):
        service.record_proof(
            proof_store=store,
            body=request.model_copy(
                update={
                    "futures_risk_proof_id": old_record.futures_risk_proof_id,
                }
            ),
            admission_decision=_admission_decision(request),
            actor_id="operator-001",
            operator_intent="record futures risk proof duplicate evidence",
            idempotency_key="futures-risk-proof-duplicate-idem",
            correlation_id="corr-futures-risk-proof-duplicate",
            payload_hash=PAYLOAD_HASH,
            audit_id="audit-futures-risk-proof-duplicate",
        )


def test_futures_risk_proof_readback_routes_return_store_records(
    monkeypatch,
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: store
    )
    client = TestClient(app)

    list_response = client.get(
        "/api/v1/futures/risk-proofs",
        headers=_headers(),
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["proof_records_created"] is True
    assert list_payload["items"][0]["futures_risk_proof_id"] == (
        record.futures_risk_proof_id
    )
    assert list_payload["items"][0]["live_coinbase_orders_ran"] is False

    detail_response = client.get(
        f"/api/v1/futures/risk-proofs/{record.futures_risk_proof_id}",
        headers=_headers(),
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["found"] is True
    assert detail_payload["record"]["command"] == AdminFuturesCommandAction.PLACE.value
    assert detail_payload["record"]["risk_proof_accepted"] is False


def test_futures_risk_proof_post_route_records_through_shared_admission(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    proof_store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    command_service = AdminApiCommandService(
        AdminApiCommandDependencies(
            futures_risk_proof_store_getter=lambda: proof_store,
            audit_store_getter=lambda: audit_store,
            uuid_factory=lambda: "futures-risk-proof-command-audit",
        )
    )
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: proof_store
    )
    app.dependency_overrides[futures_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[futures_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[futures_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[futures_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[futures_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[futures_routes.get_live_execution_service] = (
        get_disabled_live_execution_service
    )
    app.dependency_overrides[futures_routes.get_command_service] = (
        lambda: command_service
    )
    request = _risk_proof_request()
    idempotency_key = "futures-risk-proof-route-idem"
    operator_intent = "record futures risk proof evidence"
    payload_hash = _payload_hash_for_route(
        request=request,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
    )
    _append_futures_risk_proof_admission_chain(
        request=request,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/futures/risk-proofs",
        headers=_command_headers(
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
        ),
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert payload["required_permission"] == "futures_risk_proof:record"
    assert payload["service_method"] == "record_futures_risk_proof"
    assert payload["live_exchange_submitted"] is False
    admission = payload["guard"]["admission_decision"]
    assert admission["approval_snapshot_present"] is True
    assert admission["admission_audit_present"] is True
    assert admission["cap_guard_present"] is True
    assert admission["reconciliation_plan_present"] is True
    data = payload["data"]
    assert data["proof_persisted"] is True
    assert data["risk_proof_accepted"] is False
    assert data["command_route_registered"] is False
    assert data["command_draft_created"] is False
    assert data["command_execution_allowed"] is False
    assert data["coinbase_order_submitted"] is False
    assert data["coinbase_order_cancel_submitted"] is False
    assert data["live_coinbase_orders_ran"] is False
    assert data["reconciliation_executed"] is False
    assert data["order_state_mutated"] is False
    assert data["exchange_state_mutated"] is False
    assert data["browser_authority"] == "display_only"
    assert data["bff_authority"] == "forward_only_no_execution"
    assert proof_store.read_recent(limit=10)[0].futures_risk_proof_id == (
        data["futures_risk_proof_id"]
    )
    assert idempotency_store.get_record(idempotency_key) is not None


def test_futures_command_draft_routes_are_registered_and_live_disabled(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    app = create_app()
    app.dependency_overrides[futures_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[futures_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[futures_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[futures_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[futures_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[futures_routes.get_live_execution_service] = (
        get_disabled_live_execution_service
    )

    client = TestClient(app)
    cases = [
        {
            "path": "/api/v1/futures/orders",
            "idempotency_key": "futures-place-draft-idem",
            "operator_intent": "draft disabled futures placement",
            "service_method": "place_futures_order",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            "required_permission": AdminApiPermission.ORDER_CREATE,
            "command": AdminFuturesCommandAction.PLACE,
            "identity_key": "product_id",
            "identity_value": "BIT-20DEC30-CDE",
            "payload": {
                "product_id": "BIT-20DEC30-CDE",
                "side": OrderSide.BUY.value,
                "order_type": OrderType.LIMIT.value,
                "size": "1",
                "limit_price": "1",
                "time_in_force": TimeInForce.GOOD_UNTIL_CANCELLED.value,
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/positions/BIT-20DEC30-CDE:long/close-reduce",
            "idempotency_key": "futures-close-reduce-draft-idem",
            "operator_intent": "draft disabled futures close reduce",
            "service_method": "close_or_reduce_futures_position",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "required_permission": AdminApiPermission.ORDER_CANCEL,
            "command": AdminFuturesCommandAction.CLOSE_REDUCE,
            "identity_key": "position_key",
            "identity_value": "BIT-20DEC30-CDE:long",
            "payload": {
                "order_type": OrderType.MARKET.value,
                "size": "1",
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/orders/client-order-futures-001/cancel",
            "idempotency_key": "futures-cancel-draft-idem",
            "operator_intent": "draft disabled futures cancel",
            "service_method": "cancel_futures_order",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "required_permission": AdminApiPermission.ORDER_CANCEL,
            "command": AdminFuturesCommandAction.CANCEL,
            "identity_key": "client_order_id",
            "identity_value": "client-order-futures-001",
            "payload": {
                "product_id": "BIT-20DEC30-CDE",
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/positions/BIT-20DEC30-CDE:long/reconciliation",
            "idempotency_key": "futures-reconcile-draft-idem",
            "operator_intent": "draft disabled futures reconciliation",
            "service_method": "reconcile_futures_position",
            "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION,
            "required_permission": AdminApiPermission.RECONCILIATION_RECORD,
            "command": AdminFuturesCommandAction.RECONCILE,
            "identity_key": "position_key",
            "identity_value": "BIT-20DEC30-CDE:long",
            "payload": {
                "reconciliation_reason": "focused no-live route smoke",
                "expected_position_state": "not provided by fixture",
                "operator_reason": "focused no-live route smoke",
            },
        },
    ]

    for case in cases:
        response = client.post(
            str(case["path"]),
            headers=_command_headers(
                idempotency_key=str(case["idempotency_key"]),
                operator_intent=str(case["operator_intent"]),
            ),
            json=case["payload"],
        )

        assert response.status_code == 501, response.json()
        payload = response.json()
        assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
        assert payload["service_method"] == case["service_method"]
        assert payload["action_class"] == case["action_class"].value
        assert payload["required_permission"] == case["required_permission"].value
        assert payload["failure_stage"] == "approval"
        assert payload["live_exchange_submitted"] is False
        if case["identity_key"] == "client_order_id":
            assert payload["client_order_id"] == case["identity_value"]
        else:
            assert payload["client_order_id"] is None
        admission = payload["guard"]["admission_decision"]
        assert admission["allowed"] is False
        assert admission["live_exchange_submitted"] is False
        assert admission["module_id"] == "futures_perpetuals"
        assert admission["identity_key"] == case["identity_key"]
        assert admission["identity_value"] == case["identity_value"]
        data = payload["data"]
        assert data["command"] == case["command"].value
        assert data["identity_key"] == case["identity_key"]
        assert data["identity_value"] == case["identity_value"]
        assert data["coinbase_order_submitted"] is False
        assert data["coinbase_cancel_submitted"] is False
        assert data["reconciliation_executed"] is False
        assert data["futures_state_mutated"] is False
        assert data["order_state_mutated"] is False
        assert data["exchange_state_mutated"] is False
        assert data["live_adapter_invoked"] is False
        assert data["browser_authority"] == "display_only"
        assert data["bff_authority"] == "forward_only_no_execution"
        assert data["spot_rule_authority"] is False
        assert idempotency_store.get_record(str(case["idempotency_key"])) is not None


def test_futures_risk_proof_routes_are_inventory_and_openapi_bound(
    monkeypatch,
) -> None:
    surfaces = {item.surface: item for item in ADMIN_API_ROUTE_INVENTORY}
    command_surfaces = {
        "POST /api/v1/futures/orders": (
            AdminApiPermission.ORDER_CREATE,
            "place_futures_order",
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        ),
        "POST /api/v1/futures/positions/{position_key}/close-reduce": (
            AdminApiPermission.ORDER_CANCEL,
            "close_or_reduce_futures_position",
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        ),
        "POST /api/v1/futures/orders/{client_order_id}/cancel": (
            AdminApiPermission.ORDER_CANCEL,
            "cancel_futures_order",
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        ),
        "POST /api/v1/futures/positions/{position_key}/reconciliation": (
            AdminApiPermission.RECONCILIATION_RECORD,
            "reconcile_futures_position",
            AdminApiActionClass.LOCAL_STATE_MUTATION,
        ),
    }
    for surface, (
        required_permission,
        shared_method,
        action_class,
    ) in command_surfaces.items():
        assert surfaces[surface].permission == required_permission
        assert surfaces[surface].shared_method == shared_method
        assert surfaces[surface].action_class == action_class
        assert surfaces[surface].idempotency == "required"
        assert surfaces[surface].audit == "required"
        assert "route-bound draft only" in surfaces[surface].parity_test

    post_surface = "POST /api/v1/futures/risk-proofs"
    assert surfaces[post_surface].permission == (
        AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    )
    assert surfaces[post_surface].shared_method == "record_futures_risk_proof"
    assert surfaces[post_surface].action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert (
        surfaces["GET /api/v1/futures/risk-proofs"].shared_method
        == "list_futures_risk_proofs"
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    schema = create_app().openapi()
    assert "/api/v1/futures/risk-proofs" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert "get" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert "/api/v1/futures/orders" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/futures/orders"]
    assert "/api/v1/futures/orders/{client_order_id}/cancel" in schema["paths"]
    assert (
        "post"
        in schema["paths"]["/api/v1/futures/orders/{client_order_id}/cancel"]
    )
    assert (
        "/api/v1/futures/positions/{position_key}/close-reduce"
        in schema["paths"]
    )
    assert (
        "post"
        in schema["paths"][
            "/api/v1/futures/positions/{position_key}/close-reduce"
        ]
    )
    assert (
        "/api/v1/futures/positions/{position_key}/reconciliation"
        in schema["paths"]
    )
    assert (
        "post"
        in schema["paths"][
            "/api/v1/futures/positions/{position_key}/reconciliation"
        ]
    )
    assert (
        "/api/v1/futures/risk-proofs/{futures_risk_proof_id}"
        in schema["paths"]
    )


def test_futures_command_enablement_blocker_summaries_remain_read_only() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()
    summaries_by_blocker = {
        item.blocker: item for item in command_suite.command_enablement_blocker_summaries
    }

    assert command_suite.missing_backend_contracts == []
    assert all(not item.missing_backend_contracts for item in command_suite.commands)
    assert command_suite.command_enablement_blocker_summary_count == 6
    assert command_suite.command_enablement_blocker_summary_blocking_count == 6
    assert command_suite.command_enablement_sequence_step_count == 5
    assert command_suite.command_enablement_sequence_step_blocking_count == 5
    assert command_suite.command_enablement_sequence_command_trace_count == 20
    assert command_suite.command_enablement_sequence_command_trace_blocking_count == 20
    assert set(summaries_by_blocker) == {
        AdminFuturesCommandEnablementBlocker.UNRESOLVED_PREREQUISITES,
        AdminFuturesCommandEnablementBlocker.REQUEST_PAYLOAD_CONTRACTS,
        AdminFuturesCommandEnablementBlocker.SEMANTIC_GUARD_EVIDENCE,
        AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE,
        AdminFuturesCommandEnablementBlocker.LIVE_SERVICE_ADAPTER,
        AdminFuturesCommandEnablementBlocker.CONTEXTLESS_REVIEW_GATE,
    }
    affected_commands = [
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    ]

    for blocker, summary in summaries_by_blocker.items():
        assert summary.status == AdminApiGateStatus.BLOCKED
        assert summary.blocking is True
        assert summary.command_count == 4
        assert summary.affected_commands == affected_commands
        assert summary.required_evidence_refs
        assert summary.required_backend_contracts
        assert summary.evidence_ref_count == len(summary.required_evidence_refs)
        assert summary.command_route_registered is True
        assert summary.command_draft_allowed is True
        assert summary.execution_allowed is False
        assert summary.live_coinbase_orders_ran is False
        assert summary.backend_owned is True
        assert summary.read_only is True
        assert summary.spot_rule_authority is False
        assert summary.browser_authority == "display_only"
        assert summary.bff_authority == "forward_only_no_execution"

    risk_summary = summaries_by_blocker[
        AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE
    ]
    assert "futures_place_product_scope_proof_record_acceptance" in (
        risk_summary.required_evidence_refs
    )
    assert "grant command authority" in risk_summary.detail

    assert (
        AdminFuturesCommandEnablementBlocker.ADMIN_COMMAND_ROUTE
        not in summaries_by_blocker
    )

    contextless_summary = summaries_by_blocker[
        AdminFuturesCommandEnablementBlocker.CONTEXTLESS_REVIEW_GATE
    ]
    assert "blind_contextless_agent_review" in (
        contextless_summary.required_evidence_refs
    )

    sequence_steps_by_step = {
        item.step: item for item in command_suite.command_enablement_sequence_steps
    }
    assert list(sequence_steps_by_step) == [
        AdminFuturesCommandReadinessClosureStep.RESOLVE_PREREQUISITE_CONTRACTS,
        AdminFuturesCommandReadinessClosureStep.DEFINE_REQUEST_PAYLOAD_CONTRACT,
        AdminFuturesCommandReadinessClosureStep.BIND_SEMANTIC_GUARD_EVIDENCE,
        AdminFuturesCommandReadinessClosureStep.BIND_LIVE_SERVICE_ADAPTER,
        AdminFuturesCommandReadinessClosureStep.RUN_CONTEXTLESS_REVIEW_GATE,
    ]
    for index, sequence_step in enumerate(
        command_suite.command_enablement_sequence_steps,
        start=1,
    ):
        assert sequence_step.sequence == index
        assert sequence_step.status == AdminApiGateStatus.BLOCKED
        assert sequence_step.blocking is True
        assert sequence_step.command_count == 4
        assert sequence_step.affected_commands == affected_commands
        assert sequence_step.source_blockers
        assert sequence_step.command_route_registered is True
        assert sequence_step.command_draft_allowed is True
        assert sequence_step.execution_allowed is False
        assert sequence_step.live_coinbase_orders_ran is False
        assert sequence_step.backend_owned is True
        assert sequence_step.read_only is True
        assert sequence_step.spot_rule_authority is False
        assert sequence_step.browser_authority == "display_only"
        assert sequence_step.bff_authority == "forward_only_no_execution"

    semantic_step = sequence_steps_by_step[
        AdminFuturesCommandReadinessClosureStep.BIND_SEMANTIC_GUARD_EVIDENCE
    ]
    assert AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE in (
        semantic_step.source_blockers
    )
    adapter_step = sequence_steps_by_step[
        AdminFuturesCommandReadinessClosureStep.BIND_LIVE_SERVICE_ADAPTER
    ]
    assert (
        "application/admin_api/live_execution.py::futures_place_adapter_contract"
        in adapter_step.required_backend_contracts
    )

    traces_by_step = {}
    for trace in command_suite.command_enablement_sequence_command_traces:
        traces_by_step.setdefault(trace.step, []).append(trace)
        assert trace.trace_id == f"{trace.step.value}::{trace.command.value}"
        assert trace.sequence == sequence_steps_by_step[trace.step].sequence
        assert trace.status == AdminApiGateStatus.BLOCKED
        assert trace.blocking is True
        assert trace.source_blockers == sequence_steps_by_step[trace.step].source_blockers
        assert trace.required_evidence_ref_count == len(trace.required_evidence_refs)
        assert trace.command_route_registered is True
        assert trace.command_draft_allowed is True
        assert trace.execution_allowed is False
        assert trace.reconciliation_execution_allowed is False
        assert trace.futures_state_mutation_allowed is False
        assert trace.live_coinbase_orders_ran is False
        assert trace.backend_owned is True
        assert trace.read_only is True
        assert trace.spot_rule_authority is False
        assert trace.browser_authority == "display_only"
        assert trace.bff_authority == "forward_only_no_execution"
        assert "This trace row is read-only evidence" in trace.detail

    assert list(traces_by_step) == list(sequence_steps_by_step)
    for step, traces in traces_by_step.items():
        assert [trace.command for trace in traces] == [
            AdminFuturesCommandAction.PLACE,
            AdminFuturesCommandAction.CLOSE_REDUCE,
            AdminFuturesCommandAction.CANCEL,
            AdminFuturesCommandAction.RECONCILE,
        ]
        assert all(trace.sequence == sequence_steps_by_step[step].sequence for trace in traces)

    first_trace = command_suite.command_enablement_sequence_command_traces[0]
    assert first_trace.step == (
        AdminFuturesCommandReadinessClosureStep.RESOLVE_PREREQUISITE_CONTRACTS
    )
    assert first_trace.command == AdminFuturesCommandAction.PLACE
    assert first_trace.command_sequence == 1
    assert first_trace.command_step_sequence == 1
    assert first_trace.required_evidence_refs

    assert command_suite.live_coinbase_orders_ran is False
    assert command_suite.submitted_notional_usdc == "0"
    assert command_suite.executed_notional_usdc == "0"


def test_futures_command_suite_resolves_safe_risk_proof_record_without_authority(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    command_suite = AdminApiReadService(
        futures_risk_proof_store=store,
    ).build_futures_command_suite()
    place = next(
        item
        for item in command_suite.commands
        if item.command == AdminFuturesCommandAction.PLACE
    )
    margin_collateral = next(
        item
        for item in place.risk_proof_requirements
        if item.proof_kind == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL
    )

    assert command_suite.risk_proof_record_resolver_count == 20
    assert command_suite.resolved_risk_proof_record_resolver_count == 1
    assert command_suite.missing_risk_proof_record_resolver_count == 19
    assert command_suite.stale_or_invalid_risk_proof_record_resolver_count == 0
    assert command_suite.risk_proof_acceptance_blocker_count == 120
    assert command_suite.proof_record_resolved_but_acceptance_blocked_count == 1
    assert command_suite.risk_proof_semantic_contract_requirement_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_requirement_count
        == 34
    )
    assert command_suite.registered_risk_proof_semantic_contract_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_requirement_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_definition_count == 34
    assert command_suite.blocking_risk_proof_semantic_contract_definition_count == 34
    assert command_suite.ready_risk_proof_semantic_contract_definition_count == 0
    assert command_suite.registered_risk_proof_semantic_contract_definition_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_definition_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_validation_gate_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_validation_gate_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_contract_validation_gate_count == 0
    assert command_suite.registered_risk_proof_semantic_contract_validator_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_validation_gate_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_validator_contract_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_validator_contract_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_contract_validator_contract_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_contract_validator_contract_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_validator_contract_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_input_schema_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_input_schema_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_input_schema_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_input_schema_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_input_schema_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_output_schema_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_output_schema_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_output_schema_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_output_schema_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_output_schema_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_registration_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_registration_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_registration_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_registration_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_registration_count
        == 8
    )
    assert place.resolved_risk_proof_record_resolver_count == 1
    assert place.risk_proof_acceptance_blocker_count == 36
    assert place.proof_record_resolved_but_acceptance_blocked_count == 1
    assert place.risk_proof_semantic_contract_requirement_count == 10
    assert place.blocking_risk_proof_semantic_contract_requirement_count == 10
    assert place.registered_risk_proof_semantic_contract_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_requirement_count == 4
    assert place.risk_proof_semantic_contract_definition_count == 10
    assert place.blocking_risk_proof_semantic_contract_definition_count == 10
    assert place.ready_risk_proof_semantic_contract_definition_count == 0
    assert place.registered_risk_proof_semantic_contract_definition_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_definition_count == 4
    assert place.risk_proof_semantic_contract_validation_gate_count == 10
    assert place.blocking_risk_proof_semantic_contract_validation_gate_count == 10
    assert place.ready_risk_proof_semantic_contract_validation_gate_count == 0
    assert place.registered_risk_proof_semantic_contract_validator_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_validation_gate_count == 4
    assert place.risk_proof_semantic_contract_validator_contract_count == 10
    assert place.blocking_risk_proof_semantic_contract_validator_contract_count == 10
    assert place.ready_risk_proof_semantic_contract_validator_contract_count == 0
    assert place.registered_risk_proof_semantic_contract_validator_contract_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_validator_contract_count == 4
    assert place.risk_proof_semantic_validator_input_schema_count == 10
    assert place.blocking_risk_proof_semantic_validator_input_schema_count == 10
    assert place.ready_risk_proof_semantic_validator_input_schema_count == 0
    assert place.registered_risk_proof_semantic_validator_input_schema_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_input_schema_count == 4
    assert place.risk_proof_semantic_validator_output_schema_count == 10
    assert place.blocking_risk_proof_semantic_validator_output_schema_count == 10
    assert place.ready_risk_proof_semantic_validator_output_schema_count == 0
    assert place.registered_risk_proof_semantic_validator_output_schema_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_output_schema_count == 4
    assert place.risk_proof_semantic_validator_registration_count == 10
    assert place.blocking_risk_proof_semantic_validator_registration_count == 10
    assert place.ready_risk_proof_semantic_validator_registration_count == 0
    assert place.registered_risk_proof_semantic_validator_registration_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_registration_count == 4
    assert margin_collateral.proof_record_lookup_status.value == "resolved"
    assert margin_collateral.latest_futures_risk_proof_id == (
        record.futures_risk_proof_id
    )
    assert margin_collateral.proof_record_resolved is True
    assert margin_collateral.proof_record_stale_or_invalid is False
    assert margin_collateral.proof_record_satisfies_requirement is False
    assert margin_collateral.proof_acceptance_blocked is True
    assert margin_collateral.proof_acceptance_blocker_count == 6
    assert margin_collateral.proof_record_resolves_acceptance is False
    assert margin_collateral.semantic_contract_requirement_count == 2
    assert margin_collateral.blocking_semantic_contract_requirement_count == 2
    assert margin_collateral.registered_semantic_contract_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_requirement_count == 2
    assert margin_collateral.semantic_contract_definition_count == 2
    assert margin_collateral.blocking_semantic_contract_definition_count == 2
    assert margin_collateral.ready_semantic_contract_definition_count == 0
    assert margin_collateral.registered_semantic_contract_definition_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_definition_count == 2
    assert margin_collateral.semantic_contract_validation_gate_count == 2
    assert margin_collateral.blocking_semantic_contract_validation_gate_count == 2
    assert margin_collateral.ready_semantic_contract_validation_gate_count == 0
    assert margin_collateral.registered_semantic_contract_validator_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_validation_gate_count == 2
    assert margin_collateral.semantic_contract_validator_contract_count == 2
    assert margin_collateral.blocking_semantic_contract_validator_contract_count == 2
    assert margin_collateral.ready_semantic_contract_validator_contract_count == 0
    assert margin_collateral.registered_semantic_contract_validator_contract_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_validator_contract_count == 2
    assert margin_collateral.semantic_validator_input_schema_count == 2
    assert margin_collateral.blocking_semantic_validator_input_schema_count == 2
    assert margin_collateral.ready_semantic_validator_input_schema_count == 0
    assert margin_collateral.registered_semantic_validator_input_schema_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_input_schema_count == 2
    assert margin_collateral.semantic_validator_output_schema_count == 2
    assert margin_collateral.blocking_semantic_validator_output_schema_count == 2
    assert margin_collateral.ready_semantic_validator_output_schema_count == 0
    assert margin_collateral.registered_semantic_validator_output_schema_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_output_schema_count == 2
    assert margin_collateral.semantic_validator_registration_count == 2
    assert margin_collateral.blocking_semantic_validator_registration_count == 2
    assert margin_collateral.ready_semantic_validator_registration_count == 0
    assert margin_collateral.registered_semantic_validator_registration_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_registration_count == 2
    assert [
        item.required_contract_ref
        for item in margin_collateral.semantic_contract_requirements
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item.contract_ref
        for item in margin_collateral.semantic_contract_definitions
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item.semantic_contract_definition_ref
        for item in margin_collateral.semantic_contract_definitions
    ] == [
        "futures_margin_collateral_risk_contract_definition",
        "futures_cap_guard_margin_collateral_link_definition",
    ]
    assert [
        item.validation_contract_ref
        for item in margin_collateral.semantic_contract_validation_gates
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator"
        ),
    ]
    assert [
        item.validator_contract_ref
        for item in margin_collateral.semantic_contract_validator_contracts
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_contract"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_contract"
        ),
    ]
    assert [
        item.validator_input_schema_ref
        for item in margin_collateral.semantic_validator_input_schemas
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_input_schema"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_input_schema"
        ),
    ]
    assert [
        item.validator_output_schema_ref
        for item in margin_collateral.semantic_validator_output_schemas
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_output_schema"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_output_schema"
        ),
    ]
    assert [
        item.validator_registration_ref
        for item in margin_collateral.semantic_validator_registrations
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_registration"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_registration"
        ),
    ]
    assert all(
        item.blocking is True
        and item.contract_registered is False
        and item.runtime_evidence_satisfies_contract is False
        and item.acceptance_ready is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_requirements
    )
    assert all(
        item.blocking is True
        and item.contract_registered is False
        and item.definition_ready is False
        and item.validation_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_definition is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_definitions
    )
    assert all(
        item.blocking is True
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validation is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_validation_gates
    )
    assert all(
        item.blocking is True
        and item.validator_contract_registered is False
        and item.input_schema_registered is False
        and item.output_schema_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validator_contract is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_validator_contracts
    )
    assert all(
        item.blocking is True
        and item.input_schema_registered is False
        and item.validator_contract_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_input_schema is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_input_schemas
    )
    assert all(
        item.blocking is True
        and item.output_schema_registered is False
        and item.validator_contract_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_output_schema is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_output_schemas
    )
    assert all(
        item.blocking is True
        and item.validator_contract_registered is False
        and item.input_schema_registered is False
        and item.output_schema_registered is False
        and item.validator_registration_ready is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validator_registration is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_registrations
    )
    assert margin_collateral.proof_acceptance_blockers == [
        AdminFuturesCommandRiskProofAcceptanceBlocker.FUTURES_SEMANTIC_CONTRACTS_MISSING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.PROOF_RECORD_NOT_ACCEPTED,
        AdminFuturesCommandRiskProofAcceptanceBlocker.ACCEPTANCE_CRITERIA_BLOCKING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.COMMAND_ROUTE_MISSING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.COMMAND_DRAFT_DISABLED,
        AdminFuturesCommandRiskProofAcceptanceBlocker.LIVE_EXECUTION_DISABLED,
    ]
    assert (
        "futures_place_margin_collateral_acceptance_criteria"
        in margin_collateral.proof_acceptance_blocker_refs
    )
    assert margin_collateral.proof_acceptance_blocker_authority == (
        "backend_futures_semantics_no_execution"
    )
    assert margin_collateral.satisfies_risk_proof is False
    assert margin_collateral.command_route_registered is False
    assert margin_collateral.command_draft_allowed is False
    assert margin_collateral.execution_allowed is False
    assert margin_collateral.live_coinbase_orders_ran is False


def test_futures_command_suite_fails_closed_on_latest_unsafe_risk_proof_record(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    safe_record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )
    unsafe_record = safe_record.model_copy(
        update={
            "futures_risk_proof_id": "futures-risk-proof-unsafe-latest",
            "risk_proof_accepted": True,
            "command_route_registered": True,
            "command_execution_allowed": True,
            "live_coinbase_orders_ran": True,
            "idempotency_key": "futures-risk-proof-unsafe-idem",
            "correlation_id": "corr-futures-risk-proof-unsafe",
            "audit_id": "audit-futures-risk-proof-unsafe",
        }
    )
    store.append(unsafe_record)

    command_suite = AdminApiReadService(
        futures_risk_proof_store=store,
    ).build_futures_command_suite()
    place = next(
        item
        for item in command_suite.commands
        if item.command == AdminFuturesCommandAction.PLACE
    )
    margin_collateral = next(
        item
        for item in place.risk_proof_requirements
        if item.proof_kind == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL
    )

    assert command_suite.resolved_risk_proof_record_resolver_count == 0
    assert command_suite.stale_or_invalid_risk_proof_record_resolver_count == 1
    assert command_suite.risk_proof_acceptance_blocker_count == 120
    assert command_suite.proof_record_resolved_but_acceptance_blocked_count == 0
    assert command_suite.risk_proof_semantic_contract_requirement_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_count == 0
    assert command_suite.risk_proof_semantic_contract_definition_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_definition_count == 0
    assert command_suite.risk_proof_semantic_contract_validation_gate_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_validator_count == 0
    assert command_suite.risk_proof_semantic_contract_validator_contract_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_validator_contract_count == 0
    assert command_suite.risk_proof_semantic_validator_input_schema_count == 34
    assert command_suite.registered_risk_proof_semantic_validator_input_schema_count == 0
    assert command_suite.risk_proof_semantic_validator_output_schema_count == 34
    assert (
        command_suite.registered_risk_proof_semantic_validator_output_schema_count
        == 0
    )
    assert command_suite.risk_proof_semantic_validator_registration_count == 34
    assert (
        command_suite.registered_risk_proof_semantic_validator_registration_count
        == 0
    )
    assert margin_collateral.proof_record_lookup_status.value == "stale_or_invalid"
    assert margin_collateral.latest_futures_risk_proof_id == (
        unsafe_record.futures_risk_proof_id
    )
    assert margin_collateral.latest_futures_risk_proof_id != (
        safe_record.futures_risk_proof_id
    )
    assert margin_collateral.proof_record_resolved is False
    assert margin_collateral.proof_record_stale_or_invalid is True
    assert margin_collateral.proof_record_missing_reason == (
        "latest_futures_risk_proof_record_unsafe_or_authority_claimed"
    )
    assert margin_collateral.proof_record_satisfies_requirement is False
    assert margin_collateral.proof_acceptance_blocked is True
    assert margin_collateral.proof_acceptance_blocker_count == 6
    assert margin_collateral.proof_record_resolves_acceptance is False
    assert margin_collateral.semantic_contract_requirement_count == 2
    assert margin_collateral.registered_semantic_contract_count == 0
    assert margin_collateral.semantic_contract_definition_count == 2
    assert margin_collateral.registered_semantic_contract_definition_count == 0
    assert margin_collateral.semantic_contract_validation_gate_count == 2
    assert margin_collateral.registered_semantic_contract_validator_count == 0
    assert margin_collateral.semantic_contract_validator_contract_count == 2
    assert margin_collateral.registered_semantic_contract_validator_contract_count == 0
    assert margin_collateral.semantic_validator_input_schema_count == 2
    assert margin_collateral.registered_semantic_validator_input_schema_count == 0
    assert margin_collateral.semantic_validator_output_schema_count == 2
    assert margin_collateral.registered_semantic_validator_output_schema_count == 0
    assert margin_collateral.semantic_validator_registration_count == 2
    assert margin_collateral.registered_semantic_validator_registration_count == 0
    assert (
        AdminFuturesCommandRiskProofAcceptanceBlocker.PROOF_RECORD_NOT_ACCEPTED
        in margin_collateral.proof_acceptance_blockers
    )
    assert margin_collateral.satisfies_risk_proof is False
    assert margin_collateral.command_execution_allowed is False


def test_futures_command_suite_dependency_uses_futures_risk_proof_store(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )
    service = futures_routes.get_read_service(store)
    assert service.futures_risk_proof_store is store

    payload = futures_command_suite_api_payload(service.build_futures_command_suite())
    encoded_payload = json.dumps(payload, separators=(",", ":"))
    assert len(encoded_payload) < 10_000_000
    assert "required_backend_contracts" not in payload
    place = next(
        item
        for item in payload["commands"]
        if item["command"] == AdminFuturesCommandAction.PLACE.value
    )
    assert "required_backend_contracts" not in place
    review_output = next(
        item
        for item in place[
            "request_payload_validation_record_semantic_artifact_definition_review_outputs"
        ]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
        and item["semantic_artifact"]
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS.value
    )
    assert review_output["required_evidence_count"] == 15
    assert review_output["missing_evidence_count"] == 15
    assert review_output["forbidden_execution_claim_count"] == 18
    assert "required_evidence_refs" not in review_output
    assert "missing_evidence_refs" not in review_output
    assert "forbidden_execution_claims" not in review_output
    review_output_acceptance = next(
        item
        for item in place[
            "request_payload_validation_record_semantic_artifact_definition_review_output_acceptances"
        ]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
        and item["semantic_artifact"]
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS.value
    )
    assert review_output_acceptance["required_evidence_count"] == 17
    assert review_output_acceptance["missing_evidence_count"] == 17
    assert review_output_acceptance["forbidden_execution_claim_count"] == 20
    assert "required_evidence_refs" not in review_output_acceptance
    assert "missing_evidence_refs" not in review_output_acceptance
    assert "forbidden_execution_claims" not in review_output_acceptance
    runtime_evidence = next(
        item
        for item in place[
            "request_payload_validation_record_semantic_artifact_runtime_evidences"
        ]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
        and item["semantic_artifact"]
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS.value
    )
    assert runtime_evidence["required_evidence_count"] == 18
    assert runtime_evidence["missing_evidence_count"] == 18
    assert runtime_evidence["forbidden_execution_claim_count"] == 23
    assert "required_evidence_refs" not in runtime_evidence
    assert "missing_evidence_refs" not in runtime_evidence
    assert "forbidden_execution_claims" not in runtime_evidence

    runtime_evidence_acceptance = next(
        item
        for item in place[
            "request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances"
        ]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
        and item["semantic_artifact"]
        == AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS.value
    )
    assert runtime_evidence_acceptance["required_evidence_count"] == 20
    assert runtime_evidence_acceptance["missing_evidence_count"] == 20
    assert runtime_evidence_acceptance["forbidden_execution_claim_count"] == 25
    assert "required_evidence_refs" not in runtime_evidence_acceptance
    assert "missing_evidence_refs" not in runtime_evidence_acceptance
    assert "forbidden_execution_claims" not in runtime_evidence_acceptance
    position_semantic = next(
        item
        for item in place["request_payload_validation_record_position_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert position_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS.value
    )
    assert position_semantic["required_evidence_count"] >= 28
    assert position_semantic["missing_evidence_count"] >= 28
    assert position_semantic["forbidden_execution_claim_count"] == 18
    assert position_semantic["evidence_route_count"] == 2
    assert position_semantic["position_semantics_contract_available"] is False
    assert position_semantic["position_semantics_contract_ready"] is False
    assert position_semantic["validation_record_position_semantics_ready"] is False
    assert "required_evidence_refs" not in position_semantic
    assert "missing_evidence_refs" not in position_semantic
    assert "forbidden_execution_claims" not in position_semantic
    margin_semantic = next(
        item
        for item in place["request_payload_validation_record_margin_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert margin_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.MARGIN_SEMANTICS.value
    )
    assert margin_semantic["required_evidence_count"] >= 29
    assert margin_semantic["missing_evidence_count"] >= 29
    assert margin_semantic["forbidden_execution_claim_count"] == 17
    assert margin_semantic["evidence_route_count"] == 2
    assert margin_semantic["margin_semantics_contract_available"] is False
    assert margin_semantic["margin_semantics_contract_ready"] is False
    assert margin_semantic["validation_record_margin_semantics_ready"] is False
    assert "required_evidence_refs" not in margin_semantic
    assert "missing_evidence_refs" not in margin_semantic
    assert "forbidden_execution_claims" not in margin_semantic
    collateral_semantic = next(
        item
        for item in place["request_payload_validation_record_collateral_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert collateral_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.COLLATERAL_SEMANTICS.value
    )
    assert collateral_semantic["required_evidence_count"] >= 28
    assert collateral_semantic["missing_evidence_count"] >= 28
    assert collateral_semantic["forbidden_execution_claim_count"] == 17
    assert collateral_semantic["evidence_route_count"] == 2
    assert collateral_semantic["collateral_semantics_contract_available"] is False
    assert collateral_semantic["collateral_semantics_contract_ready"] is False
    assert (
        collateral_semantic["validation_record_collateral_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in collateral_semantic
    assert "missing_evidence_refs" not in collateral_semantic
    assert "forbidden_execution_claims" not in collateral_semantic
    liquidation_semantic = next(
        item
        for item in place["request_payload_validation_record_liquidation_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert liquidation_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.LIQUIDATION_SEMANTICS.value
    )
    assert liquidation_semantic["required_evidence_count"] >= 28
    assert liquidation_semantic["missing_evidence_count"] >= 28
    assert liquidation_semantic["forbidden_execution_claim_count"] == 17
    assert liquidation_semantic["evidence_route_count"] == 2
    assert liquidation_semantic["liquidation_semantics_contract_available"] is False
    assert liquidation_semantic["liquidation_semantics_contract_ready"] is False
    assert (
        liquidation_semantic["validation_record_liquidation_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in liquidation_semantic
    assert "missing_evidence_refs" not in liquidation_semantic
    assert "forbidden_execution_claims" not in liquidation_semantic
    reduce_only_semantic = next(
        item
        for item in place["request_payload_validation_record_reduce_only_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert reduce_only_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.REDUCE_ONLY_SEMANTICS.value
    )
    assert reduce_only_semantic["required_evidence_count"] >= 28
    assert reduce_only_semantic["missing_evidence_count"] >= 28
    assert reduce_only_semantic["forbidden_execution_claim_count"] == 17
    assert reduce_only_semantic["evidence_route_count"] == 2
    assert reduce_only_semantic["reduce_only_semantics_contract_available"] is False
    assert reduce_only_semantic["reduce_only_semantics_contract_ready"] is False
    assert (
        reduce_only_semantic["validation_record_reduce_only_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in reduce_only_semantic
    assert "missing_evidence_refs" not in reduce_only_semantic
    assert "forbidden_execution_claims" not in reduce_only_semantic
    close_only_semantic = next(
        item
        for item in place["request_payload_validation_record_close_only_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert close_only_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.CLOSE_ONLY_SEMANTICS.value
    )
    assert close_only_semantic["required_evidence_count"] >= 28
    assert close_only_semantic["missing_evidence_count"] >= 28
    assert close_only_semantic["forbidden_execution_claim_count"] == 17
    assert close_only_semantic["evidence_route_count"] == 2
    assert close_only_semantic["close_only_semantics_contract_available"] is False
    assert close_only_semantic["close_only_semantics_contract_ready"] is False
    assert (
        close_only_semantic["validation_record_close_only_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in close_only_semantic
    assert "missing_evidence_refs" not in close_only_semantic
    assert "forbidden_execution_claims" not in close_only_semantic
    funding_semantic = next(
        item
        for item in place["request_payload_validation_record_funding_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert funding_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.FUNDING_SEMANTICS.value
    )
    assert funding_semantic["required_evidence_count"] >= 28
    assert funding_semantic["missing_evidence_count"] >= 28
    assert funding_semantic["forbidden_execution_claim_count"] == 17
    assert funding_semantic["evidence_route_count"] == 2
    assert funding_semantic["funding_semantics_contract_available"] is False
    assert funding_semantic["funding_semantics_contract_ready"] is False
    assert funding_semantic["funding_rate_bound"] is False
    assert funding_semantic["funding_fee_bound"] is False
    assert funding_semantic["funding_interval_bound"] is False
    assert funding_semantic["funding_cost_bound"] is False
    assert funding_semantic["runtime_funding_evidence_observed"] is False
    assert (
        funding_semantic["runtime_evidence_satisfies_funding_semantics"]
        is False
    )
    assert (
        funding_semantic["validation_record_funding_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in funding_semantic
    assert "missing_evidence_refs" not in funding_semantic
    assert "forbidden_execution_claims" not in funding_semantic
    order_semantic = next(
        item
        for item in place["request_payload_validation_record_order_semantics"]
        if item["field"] == AdminFuturesCommandRequestField.PRODUCT_ID.value
    )
    assert order_semantic["semantic_artifact"] == (
        AdminFuturesCommandSemanticArtifact.ORDER_SEMANTICS.value
    )
    assert order_semantic["required_evidence_count"] >= 29
    assert order_semantic["missing_evidence_count"] >= 29
    assert order_semantic["forbidden_execution_claim_count"] == 18
    assert order_semantic["evidence_route_count"] == 2
    assert order_semantic["order_semantics_contract_available"] is False
    assert order_semantic["order_semantics_contract_ready"] is False
    assert order_semantic["order_identity_bound"] is False
    assert order_semantic["order_side_bound"] is False
    assert order_semantic["order_size_bound"] is False
    assert order_semantic["order_price_bound"] is False
    assert order_semantic["order_type_bound"] is False
    assert order_semantic["runtime_order_evidence_observed"] is False
    assert (
        order_semantic["runtime_evidence_satisfies_order_semantics"]
        is False
    )
    assert (
        order_semantic["validation_record_order_semantics_ready"]
        is False
    )
    assert "required_evidence_refs" not in order_semantic
    assert "missing_evidence_refs" not in order_semantic
    assert "forbidden_execution_claims" not in order_semantic
    margin_collateral = next(
        item
        for item in place["risk_proof_requirements"]
        if item["proof_kind"]
        == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL.value
    )
    assert margin_collateral["proof_record_lookup_status"] == "resolved"
    assert margin_collateral["latest_futures_risk_proof_id"] == (
        record.futures_risk_proof_id
    )
    assert margin_collateral["proof_record_satisfies_requirement"] is False
    assert margin_collateral["proof_acceptance_blocked"] is True
    assert margin_collateral["proof_acceptance_blocker_count"] == 6
    assert margin_collateral["proof_record_resolves_acceptance"] is False
    assert (
        "record_validation_remediation_dependency_work_item_claim_trace_clearance_plans"
        not in margin_collateral
    )
    assert margin_collateral["semantic_contract_requirement_count"] == 2
    assert margin_collateral["registered_semantic_contract_count"] == 0
    assert margin_collateral["semantic_contract_definition_count"] == 2
    assert margin_collateral["registered_semantic_contract_definition_count"] == 0
    assert margin_collateral["semantic_contract_validation_gate_count"] == 2
    assert margin_collateral["registered_semantic_contract_validator_count"] == 0
    assert margin_collateral["semantic_contract_validator_contract_count"] == 2
    assert (
        margin_collateral[
            "registered_semantic_contract_validator_contract_count"
        ]
        == 0
    )
    assert margin_collateral["semantic_validator_input_schema_count"] == 2
    assert margin_collateral["registered_semantic_validator_input_schema_count"] == 0
    assert margin_collateral["semantic_validator_output_schema_count"] == 2
    assert margin_collateral["registered_semantic_validator_output_schema_count"] == 0
    assert margin_collateral["semantic_validator_registration_count"] == 2
    assert margin_collateral["registered_semantic_validator_registration_count"] == 0
    assert [
        item["required_contract_ref"]
        for item in margin_collateral["semantic_contract_requirements"]
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item["contract_ref"]
        for item in margin_collateral["semantic_contract_definitions"]
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert (
        margin_collateral["semantic_contract_definitions"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_margin_collateral_risk_contract_definition"
        )
    )
    assert (
        margin_collateral["semantic_contract_validation_gates"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator"
        )
    )
    assert (
        margin_collateral["semantic_contract_validation_gates"][0][
            "runtime_evidence_satisfies_validation"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_contract_validator_contracts"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_contract"
        )
    )
    assert (
        margin_collateral["semantic_contract_validator_contracts"][0][
            "runtime_evidence_satisfies_validator_contract"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_input_schemas"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_input_schema"
        )
    )
    assert (
        margin_collateral["semantic_validator_input_schemas"][0][
            "runtime_evidence_satisfies_input_schema"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_output_schemas"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_output_schema"
        )
    )
    assert (
        margin_collateral["semantic_validator_output_schemas"][0][
            "runtime_evidence_satisfies_output_schema"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_registrations"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_registration"
        )
    )
    assert (
        margin_collateral["semantic_validator_registrations"][0][
            "runtime_evidence_satisfies_validator_registration"
        ]
        is False
    )
    assert "acceptance_criteria_blocking" in (
        margin_collateral["proof_acceptance_blockers"]
    )
    assert margin_collateral["command_execution_allowed"] is False


def test_futures_command_suite_raw_serialization_excludes_deep_risk_proofs() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()
    first_requirement = command_suite.commands[0].risk_proof_requirements[0]

    assert (
        first_requirement.record_validation_remediation_dependency_work_item_claim_trace_clearance_plans
    )

    payload = command_suite.model_dump(mode="json")
    encoded_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    assert len(encoded_payload) < 50_000_000
    serialized_requirement = payload["commands"][0]["risk_proof_requirements"][0]
    for excluded_field in FUTURES_RISK_PROOF_REQUIREMENT_API_EXCLUDE:
        assert excluded_field not in serialized_requirement
