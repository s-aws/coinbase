"""Disabled futures/perpetual resolution-plan review-input store record contracts.

Each row makes the missing backend record contract for one resolution-plan step
review-input store visible as backend-owned evidence. These rows are evidence
only and do not create stores, configure writers, define accepted schemas,
validate records, accept evidence, admit commands, call Coinbase, execute
reconciliation, or mutate futures/order/exchange state.
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
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract,
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract:
    """One disabled record contract for a futures resolution-plan review-input store."""

    execution_eligibility_resolution_plan_step_review_input_store_requirement_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRequirementContract
    )
    review_input_store_record_contract_kind: (
        AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract
    )
    review_input_store_record_contract_index: int
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
    record_contract_required: bool = True
    record_contract_available: bool = False
    record_schema_available: bool = False
    append_only_log_available: bool = False
    idempotency_key_bound: bool = False
    payload_schema_validated: bool = False
    replay_protected: bool = False
    store_available: bool = False
    writer_available: bool = False
    writer_allowed: bool = False
    write_allowed: bool = False
    record_present: bool = False
    record_accepted: bool = False
    record_validated: bool = False
    validation_configured: bool = False
    replay_protection_configured: bool = False
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
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .command
        )

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .field
        )

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .blocker
        )

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .semantic_artifact
        )

    @property
    def resolution_plan_step_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStep:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .resolution_plan_step_kind
        )

    @property
    def resolution_plan_step_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .resolution_plan_step_index
        )

    @property
    def review_input_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInput:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .review_input_kind
        )

    @property
    def review_input_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .review_input_index
        )

    @property
    def review_input_store_requirement_kind(
        self,
    ) -> AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRequirement:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .review_input_store_requirement_kind
        )

    @property
    def review_input_store_requirement_index(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .review_input_store_requirement_index
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .semantic_ref
        )

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_ref
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_contract_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_input_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_contract_ref(
        self,
    ) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_input_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_requirement_ref(
        self,
    ) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_input_store_requirement_ref
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref(
        self,
    ) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref
        )

    @property
    def ordered_resolution_step_ref(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .ordered_resolution_step_ref
        )

    @property
    def ordered_resolution_step_count(self) -> int:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
            .ordered_resolution_step_count
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref(
        self,
    ) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref}_"
            f"{self.review_input_store_record_contract_kind.value}"
        )

    @property
    def execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref(
        self,
    ) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_"
            f"{self.resolution_plan_step_kind.value}_{self.review_input_kind.value}_"
            f"{self.review_input_store_requirement_kind.value}_"
            f"{self.review_input_store_record_contract_kind.value}"
        )

    @property
    def required_record_schema_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref}_schema"
        )

    @property
    def required_append_only_log_ref(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref}_append_only_log"
        )

    @property
    def required_idempotency_key(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref}_idempotency_key"
        )

    @property
    def record_contract_gate(self) -> str:
        return (
            f"{self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref}_gate"
        )

    @property
    def required_payload_fields(self) -> tuple[str, ...]:
        return (
            self.field.value,
            self.blocker.value,
            self.semantic_artifact.value,
            self.resolution_plan_step_kind.value,
            self.review_input_kind.value,
            self.review_input_store_requirement_kind.value,
        )

    @property
    def required_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref
        )

    @property
    def missing_backend_contract(self) -> str:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref
        )

    @property
    def missing_reason(self) -> str:
        return (
            f"resolution-plan step review input store record contract "
            f"{self.review_input_store_record_contract_kind.value} is not "
            f"available for {self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} step {self.resolution_plan_step_kind.value} "
            f"input {self.review_input_kind.value} store requirement "
            f"{self.review_input_store_requirement_kind.value}"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(
                        self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
                        .forbidden_execution_claims
                    ),
                    "record_contract_available",
                    "record_schema_available",
                    "append_only_log_available",
                    "idempotency_key_bound",
                    "payload_schema_validated",
                    "replay_protected",
                    "store_available",
                    "writer_available",
                    "writer_allowed",
                    "write_allowed",
                    "record_present",
                    "record_accepted",
                    "record_validated",
                    "validation_configured",
                    "replay_protection_configured",
                )
            )
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            *(
                self.execution_eligibility_resolution_plan_step_review_input_store_requirement_contract
                .required_evidence_refs
            ),
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref,
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref,
            self.required_record_schema_ref,
            self.required_append_only_log_ref,
            self.required_idempotency_key,
            self.record_contract_gate,
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref,
            self.required_record_schema_ref,
            self.required_append_only_log_ref,
            self.required_idempotency_key,
            self.record_contract_gate,
            self.execution_eligibility_resolution_plan_step_review_input_store_requirement_ref,
            self.execution_eligibility_resolution_plan_step_review_input_ref,
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} requires disabled review-input store "
            f"record contract {self.review_input_store_record_contract_index + 1}: "
            f"{self.review_input_store_record_contract_kind.value} for store "
            f"requirement {self.review_input_store_requirement_index + 1}: "
            f"{self.review_input_store_requirement_kind.value}, review input "
            f"{self.review_input_index + 1}: {self.review_input_kind.value}, "
            f"and resolution-plan step {self.resolution_plan_step_index + 1}/"
            f"{self.ordered_resolution_step_count}: "
            f"{self.resolution_plan_step_kind.value}. The record contract, "
            "record schema, append-only log, idempotency key, payload "
            "validation, replay protection, writer, and write path are not "
            "available and do not make the input present, accepted, validated, "
            "or execution eligible."
        )


_REVIEW_INPUT_STORE_RECORD_CONTRACT_KINDS: tuple[
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract,
    ...,
] = (
    AdminFuturesCommandExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract.INPUT_EVIDENCE_RECORD_CONTRACT,
)


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract(
        execution_eligibility_resolution_plan_step_review_input_store_requirement_contract=contract,
        review_input_store_record_contract_kind=review_input_store_record_contract_kind,
        review_input_store_record_contract_index=review_input_store_record_contract_index,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_REQUIREMENT_CONTRACTS
    )
    for review_input_store_record_contract_index, review_input_store_record_contract_kind in enumerate(
        _REVIEW_INPUT_STORE_RECORD_CONTRACT_KINDS
    )
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanStepReviewInputStoreRecordContract
]:
    """Yield disabled execution-eligibility review-input store record contracts."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_STEP_REVIEW_INPUT_STORE_RECORD_CONTRACT_CONTRACTS
    ):
        if contract.command == command:
            yield contract
