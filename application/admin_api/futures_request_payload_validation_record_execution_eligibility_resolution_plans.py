"""Disabled futures/perpetual execution-eligibility resolution-plan registry.

These rows connect each execution-eligibility blocker to the ordered backend
evidence that must exist before the blocker can be cleared. They are evidence
only and do not validate payloads, admit commands, call Coinbase, execute
reconciliation, or mutate futures/order/exchange state.
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

from .futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS,
    FuturesRequestPayloadValidationRecordSemanticArtifactRuntimeEvidenceAcceptanceContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract:
    """One disabled resolution plan for a futures execution blocker."""

    semantic_artifact_runtime_evidence_acceptance_contract: (
        FuturesRequestPayloadValidationRecordSemanticArtifactRuntimeEvidenceAcceptanceContract
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
    resolution_plan_ready: bool = False
    resolution_plan_accepted: bool = False
    semantic_contract_present: bool = True
    semantic_contract_ready: bool = False
    semantic_artifact_definition_available: bool = False
    semantic_artifact_definition_review_passed: bool = False
    semantic_artifact_runtime_evidence_available: bool = False
    semantic_artifact_runtime_evidence_accepted: bool = False
    semantic_artifact_runtime_evidence_acceptance_available: bool = False
    semantic_artifact_runtime_evidence_acceptance_accepted: bool = False
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
        return self.semantic_artifact_runtime_evidence_acceptance_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.semantic_artifact_runtime_evidence_acceptance_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.semantic_artifact_runtime_evidence_acceptance_contract.blocker

    @property
    def semantic_artifact(self) -> AdminFuturesCommandSemanticArtifact:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return self.semantic_artifact_runtime_evidence_acceptance_contract.semantic_ref

    @property
    def semantic_artifact_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_ref
        )

    @property
    def semantic_artifact_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_contract_ref
        )

    @property
    def semantic_artifact_definition_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_definition_ref
        )

    @property
    def semantic_artifact_definition_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_definition_contract_ref
        )

    @property
    def semantic_artifact_definition_review_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_definition_review_ref
        )

    @property
    def semantic_artifact_runtime_evidence_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_runtime_evidence_ref
        )

    @property
    def semantic_artifact_runtime_evidence_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_runtime_evidence_contract_ref
        )

    @property
    def semantic_artifact_runtime_evidence_acceptance_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_runtime_evidence_acceptance_ref
        )

    @property
    def semantic_artifact_runtime_evidence_acceptance_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_runtime_evidence_acceptance_contract_ref
        )

    @property
    def execution_eligibility_resolution_plan_ref(self) -> str:
        return (
            f"{self.validation_record_execution_eligibility_blocker_ref}"
            "_resolution_plan"
        )

    @property
    def execution_eligibility_resolution_plan_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_resolution_plans.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}_resolution_plan"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.execution_eligibility_resolution_plan_ref

    @property
    def missing_reason(self) -> str:
        return (
            "execution-eligibility blocker has no accepted semantic runtime "
            "evidence, no accepted runtime-evidence readback, and no admitted "
            "validation record tied to futures/perpetual semantics"
        )

    @property
    def ordered_resolution_step_refs(self) -> tuple[str, ...]:
        return (
            self.semantic_artifact_contract_ref,
            self.semantic_artifact_definition_contract_ref,
            self.semantic_artifact_definition_review_ref,
            self.semantic_artifact_runtime_evidence_contract_ref,
            self.semantic_artifact_runtime_evidence_acceptance_contract_ref,
            f"{self.validation_record_execution_eligibility_blocker_ref}_runtime_readback",
            f"{self.validation_record_execution_eligibility_blocker_ref}_admission_link",
            f"{self.validation_record_execution_eligibility_blocker_ref}_contextless_review",
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
            "resolution_plan_ready",
            "resolution_plan_accepted",
            "semantic_contract_ready",
            "semantic_artifact_definition_available",
            "semantic_artifact_definition_review_passed",
            "semantic_artifact_runtime_evidence_available",
            "semantic_artifact_runtime_evidence_accepted",
            "semantic_artifact_runtime_evidence_acceptance_available",
            "semantic_artifact_runtime_evidence_acceptance_accepted",
            "runtime_evidence_satisfies_semantic_contract",
            "validation_record_admission_link_ready",
            "validation_record_admitted",
            "blocker_resolved",
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
                    *(
                        self.semantic_artifact_runtime_evidence_acceptance_contract
                        .required_evidence_refs
                    ),
                    self.execution_eligibility_resolution_plan_ref,
                    self.execution_eligibility_resolution_plan_contract_ref,
                    *self.ordered_resolution_step_refs,
                )
            )
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value}.{self.field.value} blocker "
            f"{self.blocker.value} remains unresolved. The resolution plan is "
            "present only as disabled backend evidence and requires accepted "
            "semantic artifact definition review, runtime evidence readback, "
            "runtime-evidence acceptance, validation-record admission, and "
            "contextless review before this blocker can be cleared."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract(
        semantic_artifact_runtime_evidence_acceptance_contract=contract,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
    )
)


def iter_futures_request_payload_validation_record_execution_eligibility_resolution_plans(
    command: AdminFuturesCommandAction,
) -> Iterator[
    FuturesRequestPayloadValidationRecordExecutionEligibilityResolutionPlanContract
]:
    """Yield disabled execution-eligibility resolution plans for one command."""

    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_RESOLUTION_PLAN_CONTRACTS
    ):
        if contract.command == command:
            yield contract
