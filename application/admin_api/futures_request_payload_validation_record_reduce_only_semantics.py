"""Disabled futures/perpetual validation-record reduce-only semantics registry.

These rows consume the existing semantic artifact runtime-evidence acceptance
chain and expose the next futures-specific semantic contract gap: reduce-only
semantics. They are evidence only and do not validate payloads, admit commands,
call Coinbase, execute reconciliation, or mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandEvidenceRoute,
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
class FuturesRequestPayloadValidationRecordReduceOnlySemanticContract:
    """One disabled reduce-only-semantics row for a futures validation record."""

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
    reduce_only_semantics_contract_available: bool = False
    reduce_only_semantics_contract_ready: bool = False
    reduce_only_flag_bound: bool = False
    reduce_only_position_side_bound: bool = False
    reduce_only_position_size_bound: bool = False
    reduce_only_order_side_bound: bool = False
    runtime_reduce_only_evidence_observed: bool = False
    runtime_evidence_satisfies_reduce_only_semantics: bool = False
    semantic_artifact_runtime_evidence_acceptance_available: bool = False
    semantic_artifact_runtime_evidence_acceptance_accepted: bool = False
    validation_record_reduce_only_semantics_ready: bool = False
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
    def semantic_artifact_definition_review_contract_ref(self) -> str:
        return (
            self.semantic_artifact_runtime_evidence_acceptance_contract
            .semantic_artifact_definition_review_contract_ref
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
    def reduce_only_semantics_ref(self) -> str:
        return self.semantic_ref

    @property
    def reduce_only_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_reduce_only_semantics.py::"
            f"{self.command.value}_{self.field.value}_reduce_only_semantics_contract"
        )

    @property
    def evidence_routes(self) -> tuple[AdminFuturesCommandEvidenceRoute, ...]:
        return (
            AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT,
            AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS,
        )

    @property
    def required_backend_contract(self) -> str:
        return self.reduce_only_semantics_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.reduce_only_semantics_ref

    @property
    def missing_reason(self) -> str:
        return (
            "backend-owned futures/perpetual reduce-only semantics contract is "
            "missing or unavailable"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
            "reduce_only_semantics_contract_available",
            "reduce_only_semantics_contract_ready",
            "reduce_only_flag_bound",
            "reduce_only_position_side_bound",
            "reduce_only_position_size_bound",
            "reduce_only_order_side_bound",
            "runtime_reduce_only_evidence_observed",
            "runtime_evidence_satisfies_reduce_only_semantics",
            "semantic_artifact_runtime_evidence_acceptance_available",
            "semantic_artifact_runtime_evidence_acceptance_accepted",
            "validation_record_reduce_only_semantics_ready",
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
                    *self.semantic_artifact_runtime_evidence_acceptance_contract.required_evidence_refs,
                    self.reduce_only_semantics_ref,
                    self.reduce_only_semantics_contract_ref,
                    f"{self.reduce_only_semantics_contract_ref}.reduce_only_flag",
                    f"{self.reduce_only_semantics_contract_ref}.position_side",
                    f"{self.reduce_only_semantics_contract_ref}.position_size",
                    f"{self.reduce_only_semantics_contract_ref}.order_side",
                    AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT.value,
                    AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS.value,
                    f"{self.reduce_only_semantics_contract_ref}_contextless_review",
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
            "reduce-only semantics for futures/perpetual validation records. "
            "The contract must bind the reduce-only flag, position side, "
            "position size, order side, and risk-proof evidence before "
            "reduce-only semantics can satisfy execution eligibility. This row "
            "is not a validator, command admission, Coinbase call, "
            "reconciliation execution, state mutation, browser authority, or "
            "BFF execution authority."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordReduceOnlySemanticContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordReduceOnlySemanticContract(
        semantic_artifact_runtime_evidence_acceptance_contract=contract,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
    )
    if contract.semantic_artifact == AdminFuturesCommandSemanticArtifact.REDUCE_ONLY_SEMANTICS
)


def iter_futures_request_payload_validation_record_reduce_only_semantics(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordReduceOnlySemanticContract]:
    """Yield disabled reduce-only-semantics contracts for one futures command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS:
        if contract.command == command:
            yield contract
