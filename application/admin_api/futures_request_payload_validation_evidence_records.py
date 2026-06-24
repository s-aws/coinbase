"""Disabled futures/perpetual request payload validation record registry.

These rows are backend-owned evidence for the future append-only record that
will persist request-payload validation results. They do not validate payloads,
write validation records, call Coinbase, execute reconciliation, or mutate
futures/order/exchange state.
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

from .futures_request_payload_validation_evidence import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS,
    FuturesRequestPayloadValidationEvidenceContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationEvidenceRecordContract:
    """One disabled validation-evidence record row for a futures payload field."""

    validation_evidence_contract: FuturesRequestPayloadValidationEvidenceContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_validation_record: bool = False
    validation_record_contract_ready: bool = False
    validation_record_store_ready: bool = False
    validation_record_writer_enabled: bool = False
    validation_record_replay_guard_ready: bool = False
    validation_evidence_ready: bool = False
    validation_evidence_recorded: bool = False
    validation_recorded: bool = False
    append_only_validation_record: bool = False
    validation_record_idempotency_bound: bool = False
    request_payload_validated: bool = False
    validator_registered: bool = False
    command_route_registered: bool = True
    command_draft_allowed: bool = True
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def command(self) -> AdminFuturesCommandAction:
        return self.validation_evidence_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.validation_evidence_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.validation_evidence_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.validation_evidence_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.validation_evidence_contract.validation_evidence_ref

    @property
    def validation_evidence_contract_ref(self) -> str:
        return self.validation_evidence_contract.validation_evidence_contract_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.validation_evidence_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.validation_evidence_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.validation_evidence_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return self.validation_evidence_contract.validator_registration_ref

    @property
    def validation_record_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_evidence_records.py::"
            f"{self.command.value}_{self.field.value}_"
            "request_payload_validation_evidence_record"
        )

    @property
    def validation_record_store_ref(self) -> str:
        return f"{self.validation_record_contract_ref}_store"

    @property
    def validation_record_writer_ref(self) -> str:
        return f"{self.validation_record_contract_ref}_writer"

    @property
    def validation_record_replay_guard_ref(self) -> str:
        return f"{self.validation_record_contract_ref}_replay_guard"

    @property
    def required_backend_contract(self) -> str:
        return self.validation_record_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.validation_record_contract_ref

    @property
    def validation_record_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validation_record_contract_ref}.validation_evidence_contract_ref",
            f"{self.validation_record_contract_ref}.validation_record_store_ref",
            f"{self.validation_record_contract_ref}.validation_record_writer_ref",
            f"{self.validation_record_contract_ref}.validation_record_replay_guard_ref",
            f"{self.validation_record_contract_ref}.payload_hash_ref",
            f"{self.validation_record_contract_ref}.operator_intent_ref",
            f"{self.validation_record_contract_ref}.idempotency_key_ref",
            f"{self.validation_record_contract_ref}.authority_flags",
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
            self.validation_record_contract_ref,
            self.validation_record_store_ref,
            self.validation_record_writer_ref,
            self.validation_record_replay_guard_ref,
            f"{self.validation_record_contract_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            "an append-only backend validation-evidence record after validation "
            "evidence is ready. Runtime reads, browser display, and BFF "
            "forwarding cannot persist validation records, satisfy idempotent "
            "payload binding, or make the command executable."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS: tuple[
    FuturesRequestPayloadValidationEvidenceRecordContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationEvidenceRecordContract(
        validation_evidence_contract=contract,
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS
)


def iter_futures_request_payload_validation_evidence_records(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationEvidenceRecordContract]:
    """Yield disabled validation-evidence record contracts for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS:
        if contract.command == command:
            yield contract
