"""Disabled futures/perpetual semantic definition review-input registry.

These rows name the backend-owned input evidence required before a contextless
semantic definition review can be attempted. They are evidence only and do not
validate payloads, admit commands, call Coinbase, execute reconciliation, or
mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityBlocker,
    AdminFuturesCommandRequestField,
    AdminFuturesCommandSemanticArtifact,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_semantic_artifact_definition_reviews import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS,
    FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewInputContract:
    """One missing input-evidence row for a futures semantic definition review."""

    semantic_artifact_definition_review_contract: (
        FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewContract
    )
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    contextless_review_required: bool = True
    spot_rule_authority: bool = False
    semantic_artifact_definition_available: bool = False
    semantic_artifact_definition_review_available: bool = False
    semantic_artifact_definition_review_input_available: bool = False
    semantic_artifact_definition_review_input_accepted: bool = False
    semantic_artifact_definition_reviewed: bool = False
    semantic_artifact_definition_review_passed: bool = False
    semantic_artifact_runtime_evidence_bound: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_semantic_artifact_definition: bool = False
    semantic_artifact_defined: bool = False
    semantic_artifact_reviewed: bool = False
    execution_eligibility_blocker_resolved: bool = False
    validation_record_execution_eligible: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.semantic_artifact_definition_review_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.semantic_artifact_definition_review_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.semantic_artifact_definition_review_contract.blocker

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return self.semantic_artifact_definition_review_contract.semantic_artifact

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return self.semantic_artifact_definition_review_contract.semantic_ref

    @property
    def semantic_artifact_ref(self) -> str:
        return self.semantic_artifact_definition_review_contract.semantic_artifact_ref

    @property
    def semantic_artifact_contract_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_contract_ref
        )

    @property
    def semantic_artifact_definition_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_ref
        )

    @property
    def semantic_artifact_definition_contract_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_contract_ref
        )

    @property
    def semantic_artifact_definition_review_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_review_ref
        )

    @property
    def semantic_artifact_definition_review_contract_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_review_contract_ref
        )

    @property
    def semantic_artifact_definition_review_input_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_review_input_ref
        )

    @property
    def semantic_artifact_definition_review_input_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifact_definition_review_inputs.py::"
            f"{self.command.value}_{self.field.value}_{self.semantic_artifact.value}_definition_review_input"
        )

    @property
    def semantic_artifact_definition_review_output_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_definition_review_output_ref
        )

    @property
    def semantic_artifact_runtime_evidence_ref(self) -> str:
        return (
            self.semantic_artifact_definition_review_contract
            .semantic_artifact_runtime_evidence_ref
        )

    @property
    def required_backend_contract(self) -> str:
        return self.semantic_artifact_definition_review_input_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.semantic_artifact_definition_review_input_ref

    @property
    def missing_reason(self) -> str:
        return self.semantic_artifact_definition_review_contract.missing_reason

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
            "semantic_artifact_definition_available",
            "semantic_artifact_definition_review_available",
            "semantic_artifact_definition_review_input_available",
            "semantic_artifact_definition_review_input_accepted",
            "semantic_artifact_definition_reviewed",
            "semantic_artifact_definition_review_passed",
            "semantic_artifact_runtime_evidence_bound",
            "semantic_artifact_defined",
            "semantic_artifact_reviewed",
            "execution_eligibility_blocker_resolved",
            "validation_record_execution_eligible",
            "command_execution_allowed",
            "live_coinbase_orders_ran",
            "browser_execution_authority",
            "bff_execution_authority",
            "spot_rule_authority",
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.semantic_artifact_definition_review_contract.required_evidence_refs,
                    self.semantic_artifact_definition_review_input_ref,
                    self.semantic_artifact_definition_review_input_contract_ref,
                )
            )
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value}: missing backend-owned "
            f"input evidence for contextless {self.semantic_artifact.value} "
            "definition review; no validation, admission, Coinbase, "
            "reconciliation, state, browser, or BFF authority."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewInputContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewInputContract(
        semantic_artifact_definition_review_contract=contract,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS
    )
)


def iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordSemanticArtifactDefinitionReviewInputContract
]:
    """Yield disabled semantic definition review-input rows for one command."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS
    ):
        if contract.command == command:
            yield contract
