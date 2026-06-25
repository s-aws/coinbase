"""Disabled futures/perpetual execution-eligibility resolution-plan step reviews.

Each row makes review of one resolution-plan step first-class backend evidence.
These rows are evidence only and do not validate payloads, accept reviews,
admit commands, call Coinbase, execute reconciliation, or mutate
futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityBlocker,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract:
    """One disabled review row for a futures resolution-plan step."""

    execution_eligibility_resolution_plan_step_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract
    )
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
        return self.execution_eligibility_resolution_plan_step_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.execution_eligibility_resolution_plan_step_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.execution_eligibility_resolution_plan_step_contract.blocker

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .semantic_artifact
        )

    @property
    def resolution_plan_step_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStep:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .resolution_plan_step_kind
        )

    @property
    def resolution_plan_step_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .resolution_plan_step_index
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return self.execution_eligibility_resolution_plan_step_contract.semantic_ref

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .execution_eligibility_resolution_plan_ref
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .execution_eligibility_resolution_plan_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .execution_eligibility_resolution_plan_step_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .execution_eligibility_resolution_plan_step_contract_ref
        )

    @property
    def ordered_resolution_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .ordered_resolution_step_ref
        )

    @property
    def ordered_resolution_step_count(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_contract
            .ordered_resolution_step_count
        )

    @property
    def execution_eligibility_resolution_plan_step_review_ref(self) -> str:
        return f"{self.execution_eligibility_resolution_plan_step_ref}_review"

    @property
    def execution_eligibility_resolution_plan_step_review_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_review"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_step_review_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_step_review_ref

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step review is not accepted for "
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} step {self.resolution_plan_step_kind.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_contract
                        .forbidden_execution_claims
                    ),
                    "resolution_plan_step_review_ready",
                    "resolution_plan_step_reviewed",
                    "resolution_plan_step_review_accepted",
                    "resolution_plan_step_review_browser_authority",
                    "resolution_plan_step_review_bff_authority",
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
            self.ordered_resolution_step_ref,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_ref,
            self.execution_eligibility_resolution_plan_step_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled review evidence for "
            f"resolution-plan step {self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The review is not "
            "accepted and does not make the validation record "
            "execution-eligible."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract(
        execution_eligibility_resolution_plan_step_contract=contract,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS
    )
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewContract
]:
    """Yield disabled execution-eligibility resolution-plan step reviews."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_CONTRACTS
    ):
        if contract.command == command:
            yield contract
