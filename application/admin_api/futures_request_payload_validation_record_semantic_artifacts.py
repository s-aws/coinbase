"""Disabled futures/perpetual semantic artifact registry.

These rows expose the backend semantic artifacts required to resolve
validation-record execution-eligibility blockers. They are evidence only and
do not validate futures payloads, admit commands, call Coinbase, execute
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

from .futures_request_payload_validation_record_execution_eligibility_blockers import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract,
)


_BLOCKER_TO_ARTIFACT = {
    AdminFuturesCommandExecutionEligibilityBlocker.POSITION_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.POSITION_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.MARGIN_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.MARGIN_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.COLLATERAL_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.COLLATERAL_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.LIQUIDATION_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.LIQUIDATION_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.REDUCE_ONLY_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.REDUCE_ONLY_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.CLOSE_ONLY_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.CLOSE_ONLY_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.FUNDING_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.FUNDING_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.ORDER_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.ORDER_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.CANCEL_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.CANCEL_SEMANTICS
    ),
    AdminFuturesCommandExecutionEligibilityBlocker.RECONCILIATION_SEMANTICS_MISSING: (
        AdminFuturesCommandSemanticArtifact.RECONCILIATION_SEMANTICS
    ),
}


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordSemanticArtifactContract:
    """One missing backend semantic artifact for a futures validation record."""

    execution_eligibility_blocker_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract
    )
    semantic_artifact: AdminFuturesCommandSemanticArtifact
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    semantic_artifact_defined: bool = False
    semantic_artifact_reviewed: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_semantic_artifact: bool = False
    execution_eligibility_blocker_resolved: bool = False
    validation_record_execution_eligible: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.execution_eligibility_blocker_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.execution_eligibility_blocker_contract.field

    @property
    def blocker(self) -> AdminFuturesCommandExecutionEligibilityBlocker:
        return self.execution_eligibility_blocker_contract.blocker

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.execution_eligibility_blocker_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            self.execution_eligibility_blocker_contract
            .validation_record_execution_eligibility_blocker_ref
        )

    @property
    def semantic_ref(self) -> str:
        return self.execution_eligibility_blocker_contract.semantic_ref

    @property
    def semantic_artifact_ref(self) -> str:
        return self.execution_eligibility_blocker_contract.required_backend_artifact_ref

    @property
    def semantic_artifact_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_semantic_artifacts.py::"
            f"{self.command.value}_{self.field.value}_{self.semantic_artifact.value}"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.semantic_artifact_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.semantic_artifact_ref

    @property
    def missing_reason(self) -> str:
        return self.execution_eligibility_blocker_contract.missing_reason

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
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
        return (
            self.validation_record_execution_eligibility_contract_ref,
            self.validation_record_execution_eligibility_blocker_ref,
            self.semantic_ref,
            self.semantic_artifact_ref,
            self.semantic_artifact_contract_ref,
            f"{self.semantic_artifact_contract_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            f"backend-owned {self.semantic_artifact.value} before blocker "
            f"{self.blocker.value} can be resolved. This row is not a "
            "validator, command admission, Coinbase call, reconciliation "
            "execution, state mutation, browser authority, or BFF execution "
            "authority."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordSemanticArtifactContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordSemanticArtifactContract(
        execution_eligibility_blocker_contract=contract,
        semantic_artifact=_BLOCKER_TO_ARTIFACT[contract.blocker],
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS
)


def iter_futures_request_payload_validation_record_semantic_artifacts(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordSemanticArtifactContract]:
    """Yield disabled semantic artifact rows for one futures command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS:
        if contract.command == command:
            yield contract
