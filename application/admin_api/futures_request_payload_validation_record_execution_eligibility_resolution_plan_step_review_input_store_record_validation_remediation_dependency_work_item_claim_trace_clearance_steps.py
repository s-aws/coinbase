"""Disabled futures/perpetual remediation dependency work-item claim-trace clearance steps.

Each row makes one missing clearance step visible for a disabled claim-trace
clearance plan. These rows are evidence only and do not execute clearance
steps, complete reviews, clear claim traces, resolve claims, admit commands,
call Coinbase, execute reconciliation, or mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plans import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_PLAN_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlan,
)


_CLEARANCE_STEP_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep,
    ...,
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.INSPECT_CLAIM_TRACE,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.VERIFY_CLAIM_LEDGER,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.VERIFY_CLAIM_TRACE_STORE,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.VERIFY_PREDECESSOR_SUCCESSOR_SEQUENCE,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.RUN_CONTEXTLESS_REVIEW,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep.RECORD_CLEARANCE_PLAN_EVIDENCE,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStep:
    """One disabled clearance step for a futures remediation dependency claim trace."""

    execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlan
    )
    clearance_step_name: AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearancePlanStep
    clearance_step_index: int
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    contextless_review_required: bool = True
    spot_rule_authority: bool = False
    record_validation_remediation_dependency_work_item_claim_trace_clearance_step_required: bool = True
    record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ready: bool = False
    record_validation_remediation_dependency_work_item_claim_trace_clearance_step_completed: bool = False
    clearance_step_review_ready: bool = False
    clearance_step_review_complete: bool = False
    clearance_step_review_inputs_present: bool = False
    clearance_step_review_gates_passed: bool = False
    prior_clearance_step_complete: bool = False
    next_clearance_step_enabled: bool = False
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
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan,
            name,
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref}_"
            f"{self.clearance_step_name.value}"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_{self.review_input_kind.value}_"
            f"{self.review_input_store_requirement_kind.value}_"
            f"{self.review_input_store_record_contract_kind.value}_"
            f"{self.review_input_store_record_validation_kind.value}_"
            f"{self.review_input_store_record_validation_remediation_kind.value}_"
            f"{self.review_input_store_record_validation_remediation_dependency_kind.value}_"
            f"{self.review_input_store_record_validation_remediation_dependency_work_item_kind.value}_"
            f"{self.review_input_store_record_validation_remediation_dependency_work_item_claim_trace_kind.value}_"
            f"{self.review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_kind.value}_"
            f"{self.clearance_step_name.value}"
        )

    @property
    def record_validation_remediation_dependency_work_item_claim_trace_clearance_step_gate(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref}_gate"
        )

    @property
    def required_clearance_plan_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_contract_ref
        )

    @property
    def required_clearance_step_review_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref}_review"
        )

    @property
    def clearance_step_claim(self) -> str:
        return (
            f"perform clearance step {self.clearance_step_name.value} for "
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref}"
        )

    @property
    def clearance_step_target_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref
        )

    @property
    def clearance_step_source_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref
        )

    @property
    def predecessor_clearance_step_refs(self) -> tuple[str, ...]:
        if self.clearance_step_index <= 0:
            return ()
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref}_"
            f"{_CLEARANCE_STEP_KINDS[self.clearance_step_index - 1].value}",
        )

    @property
    def successor_clearance_step_refs(self) -> tuple[str, ...]:
        if self.clearance_step_index >= len(_CLEARANCE_STEP_KINDS) - 1:
            return ()
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref}_"
            f"{_CLEARANCE_STEP_KINDS[self.clearance_step_index + 1].value}",
        )

    @property
    def record_validation_remediation_dependency_work_item_claim_trace_clearance_step_blockers(
        self,
    ) -> tuple[
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker,
        ...,
    ]:
        return (
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CLEARANCE_PLAN_NOT_CREATED,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CLEARANCE_PLAN_NOT_READY,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CLEARANCE_SEQUENCE_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.PRIOR_CLEARANCE_STEP_INCOMPLETE,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.REQUIRED_STEP_REVIEW_MISSING,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CLAIM_TRACE_NOT_READY,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CLAIM_UNRESOLVED,
            AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStepBlocker.CONTEXTLESS_REVIEW_MISSING,
        )

    @property
    def inherited_clearance_plan_blockers(self) -> tuple[str, ...]:
        return tuple(
            blocker.value
            for blocker in self.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_blockers
        )

    @property
    def required_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_contract_ref
        )

    @property
    def missing_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref
        )

    @property
    def missing_reason(self) -> str:
        return (
            "resolution-plan step review input store record validation "
            "remediation dependency work-item claim-trace clearance step "
            f"{self.clearance_step_name.value} is not configured for "
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan
                        .forbidden_execution_claims
                    ),
                    "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ready",
                    "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_completed",
                    "clearance_step_review_ready",
                    "clearance_step_review_complete",
                    "clearance_step_review_inputs_present",
                    "clearance_step_review_gates_passed",
                    "prior_clearance_step_complete",
                    "next_clearance_step_enabled",
                )
            )
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan
                        .required_evidence_refs
                    ),
                    self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref,
                    self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_contract_ref,
                    self.required_clearance_plan_contract,
                    self.required_clearance_step_review_ref,
                    self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_gate,
                    self.clearance_step_target_ref,
                    self.clearance_step_source_ref,
                    *self.predecessor_clearance_step_refs,
                    *self.successor_clearance_step_refs,
                    *(
                        blocker.value
                        for blocker in self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_blockers
                    ),
                )
            )
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref,
            self.record_validation_remediation_dependency_work_item_claim_trace_clearance_step_gate,
            self.required_clearance_step_review_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref,
            self.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_gate,
            self.execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_ref,
            self.record_validation_remediation_dependency_work_item_claim_trace_gate,
            *self.predecessor_clearance_step_refs,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled remediation dependency "
            f"work-item claim-trace clearance step {self.clearance_step_index + 1}: "
            f"{self.clearance_step_name.value}. The clearance plan is not "
            "created or ready, the step sequence is incomplete, required step "
            "review evidence is missing, and this row does not complete steps, "
            "clear traces, resolve claims, write evidence, admit commands, or "
            "execute anything."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_STEP_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStep,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStep(
        execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan=clearance_plan,
        clearance_step_name=clearance_step_name,
        clearance_step_index=clearance_step_index,
    )
    for clearance_plan in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_PLAN_CONTRACTS
    )
    for clearance_step_index, clearance_step_name in enumerate(_CLEARANCE_STEP_KINDS)
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordValidationRemediationDependencyWorkItemClaimTraceClearanceStep
]:
    """Yield disabled execution-eligibility claim-trace clearance steps."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_VALIDATION_REMEDIATION_DEPENDENCY_WORK_ITEM_CLAIM_TRACE_CLEARANCE_STEP_CONTRACTS
    ):
        if contract.command == command:
            yield contract
