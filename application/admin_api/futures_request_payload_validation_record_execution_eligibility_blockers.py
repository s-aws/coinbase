"""Disabled futures/perpetual execution-eligibility blocker registry.

These rows explain why a validation-record execution-eligibility row remains
blocked. They are backend-owned evidence only: they do not implement futures
semantic validators, call Coinbase, execute reconciliation, or mutate
futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandExecutionEligibilityBlocker,
    AdminFuturesCommandRequestField,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validation_record_execution_eligibilities import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS,
    FuturesRequestPayloadValidationRecordExecutionEligibilityContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract:
    """One missing semantic blocker for a validation-record eligibility row."""

    validation_record_execution_eligibility_contract: (
        FuturesRequestPayloadValidationRecordExecutionEligibilityContract
    )
    blocker: AdminFuturesCommandExecutionEligibilityBlocker
    semantic_ref: str
    semantic_contract_ref: str
    required_backend_artifact_ref: str
    missing_reason: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    semantic_contract_present: bool = True
    semantic_contract_ready: bool = False
    semantic_ready: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_execution_eligibility_blocker: bool = False
    blocker_resolved: bool = False
    validation_record_execution_eligible: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.validation_record_execution_eligibility_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.validation_record_execution_eligibility_contract.field

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            self.validation_record_execution_eligibility_contract
            .validation_record_execution_eligibility_contract_ref
        )

    @property
    def validation_record_execution_eligibility_blocker_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibility_blockers.py::"
            f"{self.command.value}_{self.field.value}_{self.blocker.value}"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.validation_record_execution_eligibility_blocker_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.required_backend_artifact_ref

    @property
    def forbidden_execution_claims(self) -> tuple[str, ...]:
        return (
            "validation_record_execution_eligible",
            "futures_semantic_ready",
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
            self.semantic_contract_ref,
            self.required_backend_artifact_ref,
            f"{self.validation_record_execution_eligibility_blocker_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} remains "
            f"execution-ineligible because {self.missing_reason}. The backend "
            "must satisfy the named futures/perpetual semantic contract before "
            "this validation record can participate in command execution. A "
            "present disabled contract row is not execution readiness."
        )


def _blocker_specs(
    contract: FuturesRequestPayloadValidationRecordExecutionEligibilityContract,
) -> tuple[
    tuple[
        AdminFuturesCommandExecutionEligibilityBlocker,
        str,
        str,
        str,
        str,
    ],
    ...,
]:
    return (
        (
            AdminFuturesCommandExecutionEligibilityBlocker.POSITION_SEMANTICS_MISSING,
            contract.validation_record_position_semantics_ref,
            contract.validation_record_position_semantics_contract_ref,
            f"{contract.validation_record_position_semantics_ref}_backend_contract",
            "position-scope semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.MARGIN_SEMANTICS_MISSING,
            contract.validation_record_margin_semantics_ref,
            contract.validation_record_margin_semantics_contract_ref,
            f"{contract.validation_record_margin_semantics_ref}_backend_contract",
            "margin semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.COLLATERAL_SEMANTICS_MISSING,
            contract.validation_record_collateral_semantics_ref,
            contract.validation_record_collateral_semantics_contract_ref,
            f"{contract.validation_record_collateral_semantics_ref}_backend_contract",
            "collateral semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.LIQUIDATION_SEMANTICS_MISSING,
            contract.validation_record_liquidation_semantics_ref,
            contract.validation_record_liquidation_semantics_contract_ref,
            f"{contract.validation_record_liquidation_semantics_ref}_backend_contract",
            "liquidation-buffer semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.REDUCE_ONLY_SEMANTICS_MISSING,
            contract.validation_record_reduce_only_semantics_ref,
            contract.validation_record_reduce_only_semantics_contract_ref,
            f"{contract.validation_record_reduce_only_semantics_ref}_backend_contract",
            "reduce-only semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.CLOSE_ONLY_SEMANTICS_MISSING,
            contract.validation_record_close_only_semantics_ref,
            contract.validation_record_close_only_semantics_contract_ref,
            f"{contract.validation_record_close_only_semantics_ref}_backend_contract",
            "close-only semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.FUNDING_SEMANTICS_MISSING,
            contract.validation_record_funding_semantics_ref,
            contract.validation_record_funding_semantics_contract_ref,
            f"{contract.validation_record_funding_semantics_ref}_backend_contract",
            "funding semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.ORDER_SEMANTICS_MISSING,
            contract.validation_record_order_semantics_ref,
            contract.validation_record_order_semantics_contract_ref,
            f"{contract.validation_record_order_semantics_ref}_backend_contract",
            "order semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.CANCEL_SEMANTICS_MISSING,
            contract.validation_record_cancel_semantics_ref,
            contract.validation_record_cancel_semantics_contract_ref,
            f"{contract.validation_record_cancel_semantics_ref}_backend_contract",
            "cancel semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
        (
            AdminFuturesCommandExecutionEligibilityBlocker.RECONCILIATION_SEMANTICS_MISSING,
            contract.validation_record_reconciliation_semantics_ref,
            contract.validation_record_reconciliation_semantics_contract_ref,
            f"{contract.validation_record_reconciliation_semantics_ref}_backend_contract",
            "reconciliation semantics are present only as disabled contract evidence and are not runtime-accepted",
        ),
    )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract(
        validation_record_execution_eligibility_contract=contract,
        blocker=blocker,
        semantic_ref=semantic_ref,
        semantic_contract_ref=semantic_contract_ref,
        required_backend_artifact_ref=required_backend_artifact_ref,
        missing_reason=missing_reason,
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS
    for (
        blocker,
        semantic_ref,
        semantic_contract_ref,
        required_backend_artifact_ref,
        missing_reason,
    ) in _blocker_specs(contract)
)


def iter_futures_request_payload_validation_record_execution_eligibility_blockers(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordExecutionEligibilityBlockerContract]:
    """Yield disabled execution-eligibility blockers for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS:
        if contract.command == command:
            yield contract
