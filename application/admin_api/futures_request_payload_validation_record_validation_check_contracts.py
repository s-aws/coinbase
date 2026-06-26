"""Disabled futures/perpetual validation-check contract evidence.

Each row makes one missing backend contract dependency for a clearance-step
review input store record-validation check visible as backend-owned evidence.
These rows are evidence only and do not declare validators, pass validation or
replay gates, accept records, admit commands, call Coinbase, execute
reconciliation, or mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContract,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_checks import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CHECK_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepReviewInputStoreRecordValidationCheck,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordValidationCheckContract:
    """One disabled backend contract dependency for a futures validation check."""

    execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepReviewInputStoreRecordValidationCheck
    )
    clearance_step_review_input_store_record_validation_check_contract_kind: AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContract
    clearance_step_review_input_store_record_validation_check_contract_index: int
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    contextless_review_required: bool = True
    spot_rule_authority: bool = False
    validation_check_contract_required: bool = True
    validation_check_contract_ready: bool = False
    validation_check_contract_declared: bool = False
    validation_check_input_schema_declared: bool = False
    validation_check_output_schema_declared: bool = False
    validation_check_gate_declared: bool = False
    validation_check_replay_guard_declared: bool = False
    validation_check_evidence_record_declared: bool = False
    validation_check_idempotency_binding_declared: bool = False
    validation_check_contextless_review_passed: bool = False
    validation_check_contract_accepted: bool = False
    validation_check_contract_recorded: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_semantic_contract: bool = False
    validation_record_admission_link_ready: bool = False
    blocker_resolved: bool = False
    validation_record_execution_eligible: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    def __getattr__(self, name: str) -> Any:
        return getattr(
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check,
            name,
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_ref}_"
            f"{self.clearance_step_review_input_store_record_validation_check_contract_kind.value}"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_validation_check_contracts.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_{self.review_input_kind.value}_"
            f"{self.review_input_store_requirement_kind.value}_"
            f"{self.review_input_store_record_contract_kind.value}_"
            f"{self.review_input_store_record_validation_kind.value}_"
            f"{self.clearance_step_review_input_store_record_validation_check_kind.value}_"
            f"{self.clearance_step_review_input_store_record_validation_check_contract_kind.value}"
        )

    @property
    def record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_gate(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref}_gate"
        )

    @property
    def required_clearance_step_review_input_store_record_validation_check_contract(
        self,
    ) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_ref
        )

    @property
    def validation_check_contract_claim(self) -> str:
        return (
            "declare validation-check contract "
            f"{self.clearance_step_review_input_store_record_validation_check_contract_kind.value} "
            f"for {self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_ref}"
        )

    @property
    def validation_check_contract_target_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_ref
        )

    @property
    def validation_check_contract_source_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref
        )

    @property
    def predecessor_clearance_step_review_input_store_record_validation_check_contract_refs(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            f"{predecessor_ref}_{self.clearance_step_review_input_store_record_validation_check_contract_kind.value}"
            for predecessor_ref in self.predecessor_clearance_step_review_input_store_record_validation_check_refs
        )

    @property
    def successor_clearance_step_review_input_store_record_validation_check_contract_refs(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            f"{successor_ref}_{self.clearance_step_review_input_store_record_validation_check_contract_kind.value}"
            for successor_ref in self.successor_clearance_step_review_input_store_record_validation_check_refs
        )

    @property
    def record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_blockers(
        self,
    ) -> tuple[
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker,
        ...,
    ]:
        return (
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.VALIDATION_CHECK_NOT_READY,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_CONTRACT_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_INPUT_SCHEMA_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_OUTPUT_SCHEMA_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_GATE_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_REPLAY_GUARD_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_EVIDENCE_RECORD_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CHECK_IDEMPOTENCY_BINDING_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContractBlocker.CONTEXTLESS_REVIEW_MISSING,
        )

    @property
    def inherited_clearance_step_review_input_store_record_validation_check_blockers(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            blocker.value
            for blocker in self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_blockers
        )

    @property
    def required_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_contract_ref
        )

    @property
    def missing_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref
        )

    @property
    def missing_reason(self) -> str:
        return (
            "resolution-plan step review input store record validation check "
            f"contract {self.clearance_step_review_input_store_record_validation_check_contract_kind.value} "
            f"is not declared for validation check {self.clearance_step_review_input_store_record_validation_check_kind.value} "
            f"on {self.command.value}.{self.field.value} blocker {self.blocker.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check
                        .forbidden_execution_claims
                    ),
                    "validation_check_contract_ready",
                    "validation_check_contract_declared",
                    "validation_check_input_schema_declared",
                    "validation_check_output_schema_declared",
                    "validation_check_gate_declared",
                    "validation_check_replay_guard_declared",
                    "validation_check_evidence_record_declared",
                    "validation_check_idempotency_binding_declared",
                    "validation_check_contextless_review_passed",
                    "validation_check_contract_accepted",
                    "validation_check_contract_recorded",
                )
            )
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check
                        .required_evidence_refs
                    ),
                    self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref,
                    self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_contract_ref,
                    self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_gate,
                    self.required_clearance_step_review_input_store_record_validation_check_contract,
                    self.validation_check_contract_target_ref,
                    self.validation_check_contract_source_ref,
                    self.clearance_step_review_input_store_record_validation_check_contract_kind.value,
                    *self.predecessor_clearance_step_review_input_store_record_validation_check_contract_refs,
                    *self.successor_clearance_step_review_input_store_record_validation_check_contract_refs,
                    *(
                        blocker.value
                        for blocker in self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_blockers
                    ),
                )
            )
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_evidence_ref,
            self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check_contract_gate,
            self.required_clearance_step_review_input_store_record_validation_check_contract,
            self.validation_check_contract_target_ref,
            *self.predecessor_clearance_step_review_input_store_record_validation_check_contract_refs,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires validation-check contract "
            f"{self.clearance_step_review_input_store_record_validation_check_contract_kind.value} "
            f"for check {self.clearance_step_review_input_store_record_validation_check_kind.value}. "
            "The backend contract, schemas, gates, replay guard, evidence "
            "record, idempotency binding, and contextless review are not "
            "declared. This row does not configure validators, accept records, "
            "admit commands, call Coinbase, or execute anything."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_VALIDATION_CHECK_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordValidationCheckContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordValidationCheckContract(
        execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_check=validation_check,
        clearance_step_review_input_store_record_validation_check_contract_kind=AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContract(
            contract
        ),
        clearance_step_review_input_store_record_validation_check_contract_index=index,
    )
    for validation_check in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CHECK_CONTRACTS
    )
    for index, contract in enumerate(
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationCheckContract
    )
)


def iter_futures_request_payload_validation_record_validation_check_contracts(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordValidationCheckContract]:
    """Yield disabled contract dependencies for clearance-step validation checks."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_VALIDATION_CHECK_CONTRACTS:
        if contract.command == command:
            yield contract
