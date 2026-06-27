"""Disabled futures/perpetual resolution-plan step review input store requirements.

Each row makes the missing backend store needed for one resolution-plan step
review input visible as backend-owned evidence. These rows are evidence only
and do not create stores, allow writes, accept or validate inputs, admit
commands, call Coinbase, execute reconciliation, or mutate futures/order/
exchange state.
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
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract:
    """One disabled store requirement for a futures resolution-plan review input."""

    execution_eligibility_resolution_plan_step_review_input_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputContract
    )
    review_input_store_requirement_kind: (
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement
    )
    review_input_store_requirement_index: int
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
    resolution_plan_step_review_input_store_requirement_required: bool = True
    resolution_plan_step_review_input_store_available: bool = False
    resolution_plan_step_review_input_writer_available: bool = False
    resolution_plan_step_review_input_record_key_available: bool = False
    resolution_plan_step_review_input_validation_gate_ready: bool = False
    resolution_plan_step_review_input_replay_gate_ready: bool = False
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
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .command
        )

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .field
        )

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .blocker
        )

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .semantic_artifact
        )

    @property
    def resolution_plan_step_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStep:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .resolution_plan_step_kind
        )

    @property
    def resolution_plan_step_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .resolution_plan_step_index
        )

    @property
    def review_input_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .review_input_kind
        )

    @property
    def review_input_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .review_input_index
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .semantic_ref
        )

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_ref
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_review_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_review_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_review_input_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_contract_ref(
        self,
    ) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .execution_eligibility_resolution_plan_step_review_input_contract_ref
        )

    @property
    def ordered_resolution_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .ordered_resolution_step_ref
        )

    @property
    def ordered_resolution_step_count(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_contract
            .ordered_resolution_step_count
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_requirement_ref(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_ref}_"
            f"{self.review_input_store_requirement_kind.value}_store_requirement"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_{self.review_input_kind.value}_"
            f"{self.review_input_store_requirement_kind.value}_store_requirement"
        )

    @property
    def required_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref
        )

    @property
    def missing_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref
        )

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step review input store requirement "
            f"{self.review_input_store_requirement_kind.value} is not "
            f"available for {self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} step {self.resolution_plan_step_kind.value} "
            f"input {self.review_input_kind.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_contract
                        .forbidden_execution_claims
                    ),
                    "resolution_plan_step_review_input_store_available",
                    "resolution_plan_step_review_input_writer_available",
                    "resolution_plan_step_review_input_record_key_available",
                    "resolution_plan_step_review_input_validation_gate_ready",
                    "resolution_plan_step_review_input_replay_gate_ready",
                    "resolution_plan_step_review_input_store_browser_authority",
                    "resolution_plan_step_review_input_store_bff_authority",
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
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref,
            self.execution_eligibility_resolution_plan_step_review_input_ref,
            self.execution_eligibility_resolution_plan_step_review_ref,
            self.execution_eligibility_resolution_plan_step_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled review-input store "
            f"requirement {self.review_input_store_requirement_index + 1}: "
            f"{self.review_input_store_requirement_kind.value} for review "
            f"input {self.review_input_index + 1}: {self.review_input_kind.value} "
            f"and resolution-plan step {self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The store, writer, "
            "record key, validation gate, and replay gate are not available "
            "and do not make the input present, accepted, or validated."
        )


_REVIEW_INPUT_STORE_REQUIREMENT_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement,
    ...,
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement.INPUT_EVIDENCE_STORE,
)


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract(
        execution_eligibility_resolution_plan_step_review_input_contract=contract,
        review_input_store_requirement_kind=review_input_store_requirement_kind,
        review_input_store_requirement_index=review_input_store_requirement_index,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_CONTRACTS
    )
    for review_input_store_requirement_index, review_input_store_requirement_kind in enumerate(
        _REVIEW_INPUT_STORE_REQUIREMENT_KINDS
    )
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract
]:
    """Yield disabled execution-eligibility review-input store requirements."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS
    ):
        if contract.command == command:
            yield contract
