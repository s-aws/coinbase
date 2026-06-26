"""Disabled futures/perpetual resolution-plan review-input store record validations.

Each row makes the missing backend record validation for one resolution-plan
step review-input store visible as backend-owned evidence. These rows are
evidence only and do not configure validators, validate records, accept
evidence, admit commands, call Coinbase, execute reconciliation, or mutate
futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation:
    """One disabled record validation for a futures resolution-plan review-input store."""

    execution_eligibility_resolution_plan_step_review_input_store_record_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract
    )
    review_input_store_record_validation_kind: (
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation
    )
    review_input_store_record_validation_index: int
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    contextless_review_required: bool = True
    spot_rule_authority: bool = False
    record_validation_required: bool = True
    record_validation_ready: bool = False
    record_validation_configured: bool = False
    record_validation_registered: bool = False
    record_validation_gate_ready: bool = False
    record_validation_gate_passed: bool = False
    record_validation_replay_guard_ready: bool = False
    record_validation_schema_ready: bool = False
    record_validation_append_only_log_ready: bool = False
    record_validation_idempotency_bound: bool = False
    record_validation_payload_bound: bool = False
    record_validation_contextless_review_passed: bool = False
    record_validation_performed: bool = False
    record_validation_accepted: bool = False
    record_validation_recorded: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_semantic_contract: bool = False
    validation_record_admission_link_ready: bool = False
    validation_record_admitted: bool = False
    blocker_resolved: bool = False
    validation_record_execution_eligible: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    def __getattr__(self, name: str) -> Any:
        return getattr(
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract,
            name,
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref}_"
            f"{self.review_input_store_record_validation_kind.value}"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_{self.review_input_kind.value}_"
            f"{self.review_input_store_requirement_kind.value}_"
            f"{self.review_input_store_record_contract_kind.value}_"
            f"{self.review_input_store_record_validation_kind.value}"
        )

    @property
    def record_validation_gate(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref}_gate"
        )

    @property
    def record_validation_schema_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref}_schema"
        )

    @property
    def record_validation_check_refs(self) -> tuple[str, ...]:
        return (
            self.record_validation_gate,
            self.record_validation_schema_ref,
            self.required_record_schema_ref,
            self.required_append_only_log_ref,
            self.required_idempotency_key,
        )

    @property
    def required_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref
        )

    @property
    def missing_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref
        )

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step review input store record validation "
            f"{self.review_input_store_record_validation_kind.value} is not "
            f"configured for {self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} step {self.resolution_plan_step_kind.value} "
            f"input {self.review_input_kind.value} store requirement "
            f"{self.review_input_store_requirement_kind.value} record contract "
            f"{self.review_input_store_record_contract_kind.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_record_contract
                        .forbidden_execution_claims
                    ),
                    "record_validation_ready",
                    "record_validation_configured",
                    "record_validation_registered",
                    "record_validation_gate_ready",
                    "record_validation_gate_passed",
                    "record_validation_replay_guard_ready",
                    "record_validation_schema_ready",
                    "record_validation_append_only_log_ready",
                    "record_validation_idempotency_bound",
                    "record_validation_payload_bound",
                    "record_validation_contextless_review_passed",
                    "record_validation_performed",
                    "record_validation_accepted",
                    "record_validation_recorded",
                )
            )
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            *(
                self.execution_eligibility_resolution_plan_step_review_input_store_record_contract
                .required_evidence_refs
            ),
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref,
            self.record_validation_gate,
            self.record_validation_schema_ref,
            *self.record_validation_check_refs,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref,
            self.record_validation_gate,
            self.record_validation_schema_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref,
            self.execution_eligibility_resolution_plan_step_review_input_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled review-input store "
            f"record validation {self.review_input_store_record_validation_index + 1}: "
            f"{self.review_input_store_record_validation_kind.value} for record "
            f"contract {self.review_input_store_record_contract_index + 1}: "
            f"{self.review_input_store_record_contract_kind.value}, store "
            f"requirement {self.review_input_store_requirement_index + 1}: "
            f"{self.review_input_store_requirement_kind.value}, review input "
            f"{self.review_input_index + 1}: {self.review_input_kind.value}, "
            f"and resolution-plan step {self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The record validation, "
            "validation gate, validation schema, replay guard, contextless "
            "review, validation write record, and acceptance path are not "
            "configured and do not make the input present, accepted, "
            "validated, or execution eligible."
        )


_REVIEW_INPUT_STORE_RECORD_VALIDATION_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation,
    ...,
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation.INPUT_EVIDENCE_RECORD_VALIDATION,
)


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation(
        execution_eligibility_resolution_plan_step_review_input_store_record_contract=contract,
        review_input_store_record_validation_kind=review_input_store_record_validation_kind,
        review_input_store_record_validation_index=review_input_store_record_validation_index,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS
    )
    for review_input_store_record_validation_index, review_input_store_record_validation_kind in enumerate(
        _REVIEW_INPUT_STORE_RECORD_VALIDATION_KINDS
    )
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidation
]:
    """Yield disabled execution-eligibility review-input store record validations."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_CONTRACTS
    ):
        if contract.command == command:
            yield contract
