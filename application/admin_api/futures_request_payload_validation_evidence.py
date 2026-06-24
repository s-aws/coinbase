"""Disabled futures/perpetual request payload validation evidence registry.

These rows are backend-owned evidence for future command request-payload
validation results. They do not validate command payloads, record validation
evidence, call Coinbase, execute reconciliation, or mutate futures/order/
exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminApiGateStatus,
    AdminFuturesCommandAction,
    AdminFuturesCommandRequestField,
    AdminFuturesEvidenceSource,
)

from .futures_request_payload_validator_registrations import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS,
    FuturesRequestPayloadValidatorRegistrationContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationEvidenceContract:
    """One disabled validation-evidence row for a futures payload field."""

    registration_contract: FuturesRequestPayloadValidatorRegistrationContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_validation_evidence: bool = False
    validation_evidence_ready: bool = False
    validation_evidence_recorded: bool = False
    validation_gate_ready: bool = False
    validation_gate_passed: bool = False
    validator_registration_ready: bool = False
    validator_registered: bool = False
    request_payload_validated: bool = False
    command_route_registered: bool = True
    command_draft_allowed: bool = True
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.registration_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.registration_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.registration_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.registration_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.registration_contract.validation_evidence_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.registration_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.registration_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.registration_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return self.registration_contract.validator_registration_ref

    @property
    def validation_evidence_contract_ref(self) -> str:
        return (
            "application/admin_api/futures_request_payload_validation_evidence.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validation_evidence"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.validation_evidence_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.validation_evidence_contract_ref

    @property
    def validation_evidence_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validation_evidence_contract_ref}.validation_evidence_ref",
            f"{self.validation_evidence_contract_ref}.validation_gate_ref",
            f"{self.validation_evidence_contract_ref}.validator_registration_ref",
            f"{self.validation_evidence_contract_ref}.request_payload_contract_ref",
            f"{self.validation_evidence_contract_ref}.runtime_evidence_snapshot",
            f"{self.validation_evidence_contract_ref}.authority_flags",
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.request_payload_contract_ref,
            self.validation_gate_ref,
            self.validation_evidence_ref,
            self.validator_contract_ref,
            self.validator_registration_ref,
            self.validation_evidence_contract_ref,
            f"{self.validation_evidence_contract_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            "backend-owned request payload validation evidence after the "
            "validator registration, validation gate, and payload contract are "
            "ready. Runtime reads, browser display, and BFF forwarding cannot "
            "record validation evidence or make the command payload valid."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS: tuple[
    FuturesRequestPayloadValidationEvidenceContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationEvidenceContract(registration_contract=contract)
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS
)


def iter_futures_request_payload_validation_evidence(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationEvidenceContract]:
    """Yield disabled request-payload validation evidence for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS:
        if contract.command == command:
            yield contract
