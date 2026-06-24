"""Disabled futures/perpetual request payload validator contract registry.

This module records backend-owned validator contract evidence for futures
command request fields. It does not implement validators, accept payloads, call
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

from .futures_request_payload_contracts import (
    FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS,
    FuturesRequestPayloadFieldContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidatorContract:
    """One disabled validator contract for a futures request payload field."""

    field_contract: FuturesRequestPayloadFieldContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    spot_rule_authority: bool = False
    command_route_registered: bool = True
    command_draft_allowed: bool = True
    execution_allowed: bool = False
    validation_gate_ready: bool = False
    validation_gate_passed: bool = False
    validator_contract_registered: bool = False
    validator_input_schema_registered: bool = False
    validator_output_schema_registered: bool = False
    validator_registered: bool = False
    request_payload_validated: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.field_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.field_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.field_contract.contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.field_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.field_contract.validation_evidence_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.field_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return (
            "application/admin_api/futures_request_payload_validators.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validator_input_schema"
        )

    @property
    def validator_output_schema_ref(self) -> str:
        return (
            "application/admin_api/futures_request_payload_validators.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validator_output_schema"
        )

    @property
    def validator_registration_ref(self) -> str:
        return self.field_contract.validator_registration_ref

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} has a "
            "backend-owned disabled validator contract placeholder. The "
            "contract, input schema, output schema, registration, validation "
            "gate, and payload validation remain blocked evidence only."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS: tuple[
    FuturesRequestPayloadValidatorContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidatorContract(field_contract=contract)
    for contract in FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
)


def iter_futures_request_payload_validator_contracts(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidatorContract]:
    """Yield disabled request-payload validator contracts for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS:
        if contract.command == command:
            yield contract
