"""Disabled futures/perpetual validation-record margin semantics registry.

These rows consume the existing semantic artifact runtime-evidence acceptance
chain and expose the next futures-specific semantic contract gap: margin
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
class FuturesRequestPayloadValidationRecordMarginSemanticContract:
    """One disabled margin-semantics row for a futures validation record."""

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
    margin_semantics_contract_available: bool = False
    margin_semantics_contract_ready: bool = False
    margin_account_bound: bool = False
    margin_requirement_bound: bool = False
    margin_mode_bound: bool = False
    margin_buffer_bound: bool = False
    runtime_margin_evidence_observed: bool = False
    runtime_evidence_satisfies_margin_semantics: bool = False
    semantic_artifact_runtime_evidence_acceptance_available: bool = False
    semantic_artifact_runtime_evidence_acceptance_accepted: bool = False
    validation_record_margin_semantics_ready: bool = False
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
    def margin_semantics_ref(self) -> str:
        return self.semantic_ref

    @property
    def margin_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_margin_semantics.py::"
            f"{self.command.value}_{self.field.value}_margin_semantics_contract"
        )

    @property
    def evidence_routes(self) -> tuple[AdminFuturesCommandEvidenceRoute, ...]:
        return (
            AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT,
            AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS,
        )

    @property
    def required_backend_contract(self) -> str:
        return self.margin_semantics_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.margin_semantics_ref

    @property
    def missing_reason(self) -> str:
        return (
            "backend-owned futures/perpetual margin semantics contract is "
            "missing or unavailable"
        )

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
            "margin_semantics_contract_available",
            "margin_semantics_contract_ready",
            "margin_account_bound",
            "margin_requirement_bound",
            "margin_mode_bound",
            "margin_buffer_bound",
            "runtime_margin_evidence_observed",
            "runtime_evidence_satisfies_margin_semantics",
            "semantic_artifact_runtime_evidence_acceptance_available",
            "semantic_artifact_runtime_evidence_acceptance_accepted",
            "validation_record_margin_semantics_ready",
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
                    self.margin_semantics_ref,
                    self.margin_semantics_contract_ref,
                    f"{self.margin_semantics_contract_ref}.account_equity",
                    f"{self.margin_semantics_contract_ref}.available_collateral",
                    f"{self.margin_semantics_contract_ref}.initial_margin",
                    f"{self.margin_semantics_contract_ref}.maintenance_margin",
                    f"{self.margin_semantics_contract_ref}.margin_mode",
                    AdminFuturesCommandEvidenceRoute.FUTURES_ACCOUNT.value,
                    AdminFuturesCommandEvidenceRoute.FUTURES_RISK_PROOFS.value,
                    f"{self.margin_semantics_contract_ref}_contextless_review",
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
            "margin semantics for futures/perpetual validation records. The "
            "contract must bind account equity, available collateral, initial "
            "margin, maintenance margin, margin mode, and risk-proof evidence "
            "before margin semantics can satisfy execution eligibility. This "
            "row is not a validator, command admission, Coinbase call, "
            "reconciliation execution, state mutation, browser authority, or "
            "BFF execution authority."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordMarginSemanticContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordMarginSemanticContract(
        semantic_artifact_runtime_evidence_acceptance_contract=contract,
    )
    for contract in (
        FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS
    )
    if contract.semantic_artifact == AdminFuturesCommandSemanticArtifact.MARGIN_SEMANTICS
)


def iter_futures_request_payload_validation_record_margin_semantics(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordMarginSemanticContract]:
    """Yield disabled margin-semantics contracts for one futures command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS:
        if contract.command == command:
            yield contract
