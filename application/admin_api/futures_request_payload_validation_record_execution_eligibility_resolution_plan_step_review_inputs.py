"""Disabled futures/perpetual resolution-plan step review inputs.

Each row makes one missing input for a resolution-plan step review visible as
backend-owned evidence. These rows are evidence only and do not accept inputs,
complete reviews, admit commands, call Coinbase, execute reconciliation, or
mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityBlocker,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract:
    """One disabled input row for a futures resolution-plan step review."""

    execution_eligibility_resolution_plan_step_review_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract
    )
    review_input_kind: (
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput
    )
    review_input_index: int
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    contextless_review_required: bool = True
    spot_rule_authority: bool = False
    resolution_plan_present: bool = True
    resolution_plan_step_ready: bool = False
    resolution_plan_step_accepted: bool = False
    resolution_plan_step_review_required: bool = True
    resolution_plan_step_review_ready: bool = False
    resolution_plan_step_reviewed: bool = False
    resolution_plan_step_review_accepted: bool = False
    resolution_plan_step_review_input_required: bool = True
    resolution_plan_step_review_input_present: bool = False
    resolution_plan_step_review_input_accepted: bool = False
    resolution_plan_step_review_input_validated: bool = False
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

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.execution_eligibility_resolution_plan_step_review_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.execution_eligibility_resolution_plan_step_review_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.execution_eligibility_resolution_plan_step_review_contract.blocker

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .semantic_artifact
        )

    @property
    def resolution_plan_step_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStep:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .resolution_plan_step_kind
        )

    @property
    def resolution_plan_step_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .resolution_plan_step_index
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .semantic_ref
        )

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_ref
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_step_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_step_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_step_review_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .execution_eligibility_resolution_plan_step_review_contract_ref
        )

    @property
    def ordered_resolution_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .ordered_resolution_step_ref
        )

    @property
    def ordered_resolution_step_count(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_contract
            .ordered_resolution_step_count
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_ref}_"
            f"{self.review_input_kind.value}_input"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_"
            f"{self.review_input_kind.value}_review_input"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_step_review_input_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_step_review_input_ref

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step review input {self.review_input_kind.value} "
            f"is not present for {self.command.value}.{self.field.value} "
            f"blocker {self.blocker.value} step "
            f"{self.resolution_plan_step_kind.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_contract
                        .forbidden_execution_claims
                    ),
                    "resolution_plan_step_review_input_present",
                    "resolution_plan_step_review_input_accepted",
                    "resolution_plan_step_review_input_validated",
                    "resolution_plan_step_review_input_browser_authority",
                    "resolution_plan_step_review_input_bff_authority",
                )
            )
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_ref,
            self.execution_eligibility_resolution_plan_contract_ref,
            self.execution_eligibility_resolution_plan_step_ref,
            self.execution_eligibility_resolution_plan_step_contract_ref,
            self.execution_eligibility_resolution_plan_step_review_ref,
            self.execution_eligibility_resolution_plan_step_review_contract_ref,
            self.execution_eligibility_resolution_plan_step_review_input_ref,
            self.execution_eligibility_resolution_plan_step_review_input_contract_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_ref,
            self.execution_eligibility_resolution_plan_step_review_ref,
            self.execution_eligibility_resolution_plan_step_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled review input "
            f"{self.review_input_index + 1}: {self.review_input_kind.value} "
            f"for resolution-plan step {self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The input is not "
            "present, accepted, or validated and does not make the review "
            "ready or the validation record execution-eligible."
        )


_REVIEW_INPUT_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput, ...
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput.OWNER_REVIEW_EVIDENCE,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput.CONTEXTLESS_REVIEW_EVIDENCE,
)


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract(
        execution_eligibility_resolution_plan_step_review_contract=contract,
        review_input_kind=review_input_kind,
        review_input_index=review_input_index,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS
    )
    for review_input_index, review_input_kind in enumerate(_REVIEW_INPUT_KINDS)
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract
]:
    """Yield disabled execution-eligibility resolution-plan step review inputs."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS
    ):
        if contract.command == command:
            yield contract
