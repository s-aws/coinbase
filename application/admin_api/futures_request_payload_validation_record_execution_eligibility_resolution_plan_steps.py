"""Disabled futures/perpetual execution-eligibility resolution-plan steps.

Each row makes one ordered prerequisite in a resolution plan first-class
backend evidence. These rows are evidence only and do not validate payloads,
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

from .futures_request_payload_validation_record_execution_eligibility_resolution_plans import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract,
)


RESOLUTION_PLAN_STEP_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep,
    ...,
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.SEMANTIC_ARTIFACT_CONTRACT,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.SEMANTIC_ARTIFACT_DEFINITION_CONTRACT,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.SEMANTIC_ARTIFACT_DEFINITION_REVIEW,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACT,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACT,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.RUNTIME_READBACK,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.ADMISSION_LINK,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStep.CONTEXTLESS_REVIEW,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract:
    """One disabled ordered step for a futures execution blocker plan."""

    execution_eligibility_resolution_plan_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract
    )
    resolution_plan_step_kind: (
        AdminFuturesCommandExecutionEligibilityResolutionPlanStep
    )
    resolution_plan_step_index: int
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
        return self.execution_eligibility_resolution_plan_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.execution_eligibility_resolution_plan_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.execution_eligibility_resolution_plan_contract.blocker

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return self.execution_eligibility_resolution_plan_contract.semantic_artifact

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return self.execution_eligibility_resolution_plan_contract.semantic_ref

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_contract
            .execution_eligibility_resolution_plan_ref
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_contract
            .execution_eligibility_resolution_plan_contract_ref
        )

    @property
    def ordered_resolution_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_contract
            .ordered_resolution_step_refs[self.resolution_plan_step_index]
        )

    @property
    def ordered_resolution_step_count(self) -> int:
        return len(
            self.execution_eligibility_resolution_plan_contract
            .ordered_resolution_step_refs
        )

    @property
    def execution_eligibility_resolution_plan_step_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_ref}"
            f"_{self.resolution_plan_step_kind.value}"
        )

    @property
    def execution_eligibility_resolution_plan_step_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_step_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.ordered_resolution_step_ref

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step {self.resolution_plan_step_index + 1} "
            f"({self.resolution_plan_step_kind.value}) is not accepted for "
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_contract
                        .forbidden_execution_claims
                    ),
                    "resolution_plan_step_ready",
                    "resolution_plan_step_accepted",
                    "resolution_plan_step_runtime_observed",
                    "resolution_plan_step_browser_authority",
                    "resolution_plan_step_bff_authority",
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
            self.ordered_resolution_step_ref,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_ref,
            self.ordered_resolution_step_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires ordered resolution-plan step "
            f"{self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The step is "
            "backend-owned disabled evidence only and does not make the "
            "validation record execution-eligible."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract(
        execution_eligibility_resolution_plan_contract=contract,
        resolution_plan_step_kind=step_kind,
        resolution_plan_step_index=step_index,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS
    )
    for step_index, step_kind in enumerate(RESOLUTION_PLAN_STEP_KINDS)
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepContract
]:
    """Yield disabled execution-eligibility resolution-plan steps."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_CONTRACTS
    ):
        if contract.command == command:
            yield contract
