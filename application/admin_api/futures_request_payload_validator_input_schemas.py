"""Disabled futures/perpetual request payload validator input-schema registry.

These rows are backend-owned evidence for future validator input schemas. They
do not register schemas, validate command payloads, call Coinbase, execute
reconciliation, or mutate futures/order/exchange state.
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

from .futures_request_payload_validators import (
    FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS,
    FuturesRequestPayloadValidatorContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidatorInputSchemaContract:
    """One disabled input-schema row for a futures payload validator."""

    validator_contract: FuturesRequestPayloadValidatorContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    input_schema_registered: bool = False
    validator_contract_registered: bool = False
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
        return self.validator_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.validator_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.validator_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.validator_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.validator_contract.validation_evidence_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.validator_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.validator_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.validator_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return self.validator_contract.validator_registration_ref

    @property
    def input_schema_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validator_input_schema_ref}.request_payload_contract_ref",
            f"{self.validator_input_schema_ref}.validation_gate_ref",
            f"{self.validator_input_schema_ref}.validation_evidence_ref",
            f"{self.validator_input_schema_ref}.validator_contract_ref",
            f"{self.validator_input_schema_ref}.runtime_evidence_snapshot",
        )

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            f"backend-owned validator input schema {self.validator_input_schema_ref} "
            "before any payload validator can be registered or run. The schema "
            "row is blocked display evidence only."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS: tuple[
    FuturesRequestPayloadValidatorInputSchemaContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidatorInputSchemaContract(validator_contract=contract)
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS
)


def iter_futures_request_payload_validator_input_schemas(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidatorInputSchemaContract]:
    """Yield disabled request-payload validator input schemas for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS:
        if contract.command == command:
            yield contract
