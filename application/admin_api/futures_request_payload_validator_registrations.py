"""Disabled futures/perpetual request payload validator registration registry.

These rows are backend-owned evidence for future payload-validator
registration. They do not register validators, validate command payloads, call
Coinbase, execute reconciliation, or mutate futures/order/exchange state.
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

from .futures_request_payload_validator_output_schemas import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS,
    FuturesRequestPayloadValidatorOutputSchemaContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidatorRegistrationContract:
    """One disabled registration row for a futures payload validator."""

    output_schema_contract: FuturesRequestPayloadValidatorOutputSchemaContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_validator_registration: bool = False
    validator_contract_registered: bool = False
    input_schema_registered: bool = False
    output_schema_registered: bool = False
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
        return self.output_schema_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.output_schema_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.output_schema_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.output_schema_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.output_schema_contract.validation_evidence_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.output_schema_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.output_schema_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.output_schema_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return (
            "application/admin_api/futures_request_payload_validator_registrations.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validator_registration"
        )

    @property
    def required_backend_contract(self) -> str:
        return self.validator_registration_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.validator_registration_ref

    @property
    def validator_registration_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validator_registration_ref}.validator_contract_ref",
            f"{self.validator_registration_ref}.validator_input_schema_ref",
            f"{self.validator_registration_ref}.validator_output_schema_ref",
            f"{self.validator_registration_ref}.request_payload_contract_ref",
            f"{self.validator_registration_ref}.validation_gate_ref",
            f"{self.validator_registration_ref}.authority_flags",
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.validator_contract_ref,
            self.validator_input_schema_ref,
            self.validator_output_schema_ref,
            self.validator_registration_ref,
            f"{self.validator_registration_ref}_registry_record",
            f"{self.validator_registration_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            "a backend-owned validator registration record that binds the "
            "validator contract, input schema, output schema, request payload "
            "contract, validation gate, and authority flags before the "
            "validator can be registered or run. Runtime evidence, browser "
            "display, and BFF forwarding cannot satisfy registration or enable "
            "futures command execution."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS: tuple[
    FuturesRequestPayloadValidatorRegistrationContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidatorRegistrationContract(
        output_schema_contract=contract
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS
)


def iter_futures_request_payload_validator_registrations(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidatorRegistrationContract]:
    """Yield disabled request-payload validator registrations for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS:
        if contract.command == command:
            yield contract
