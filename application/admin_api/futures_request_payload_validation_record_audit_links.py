"""Disabled futures/perpetual validation-record audit-link registry.

These rows are backend-owned evidence for the future actor, operator-intent,
correlation, and admission-audit binding required by request-payload
validation records. They do not validate payloads, write validation records,
append audit rows, call Coinbase, execute reconciliation, or mutate
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

from .futures_request_payload_validation_record_replay_guards import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS,
    FuturesRequestPayloadValidationRecordReplayGuardContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordAuditLinkContract:
    """One disabled audit/correlation binding row for a futures payload field."""

    validation_record_replay_guard_contract: FuturesRequestPayloadValidationRecordReplayGuardContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_validation_record_audit_link: bool = False
    validation_record_audit_link_contract_ready: bool = False
    validation_record_audit_link_ready: bool = False
    validation_record_actor_bound: bool = False
    validation_record_operator_intent_bound: bool = False
    validation_record_correlation_bound: bool = False
    validation_record_admission_audit_bound: bool = False
    validation_record_audit_recorded: bool = False
    validation_record_replay_guard_contract_ready: bool = False
    validation_record_replay_guard_ready: bool = False
    validation_record_idempotency_contract_ready: bool = False
    validation_record_idempotency_bound: bool = False
    validation_record_replay_protected: bool = False
    validation_record_schema_ready: bool = False
    validation_record_schema_registered: bool = False
    validation_record_append_only_log_ready: bool = False
    validation_record_contract_ready: bool = False
    validation_record_store_ready: bool = False
    validation_record_writer_enabled: bool = False
    validation_evidence_ready: bool = False
    validation_evidence_recorded: bool = False
    validation_recorded: bool = False
    append_only_validation_record: bool = False
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
        return self.validation_record_replay_guard_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.validation_record_replay_guard_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.validation_record_replay_guard_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_evidence_ref

    @property
    def validation_evidence_contract_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_evidence_contract_ref

    @property
    def validator_contract_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validator_registration_ref

    @property
    def validation_record_contract_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_contract_ref

    @property
    def validation_record_store_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_store_ref

    @property
    def validation_record_writer_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_writer_ref

    @property
    def validation_record_replay_guard_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_replay_guard_ref

    @property
    def validation_record_schema_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_schema_ref

    @property
    def validation_record_append_only_log_ref(self) -> str:
        return (
            self.validation_record_replay_guard_contract.validation_record_append_only_log_ref
        )

    @property
    def validation_record_replay_guard_contract_ref(self) -> str:
        return (
            self.validation_record_replay_guard_contract.validation_record_replay_guard_contract_ref
        )

    @property
    def validation_record_idempotency_contract_ref(self) -> str:
        return (
            self.validation_record_replay_guard_contract.validation_record_idempotency_contract_ref
        )

    @property
    def validation_record_replay_window_ref(self) -> str:
        return self.validation_record_replay_guard_contract.validation_record_replay_window_ref

    @property
    def validation_record_duplicate_policy_ref(self) -> str:
        return (
            self.validation_record_replay_guard_contract.validation_record_duplicate_policy_ref
        )

    @property
    def validation_record_audit_link_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_audit_links.py::"
            f"{self.command.value}_{self.field.value}_"
            "request_payload_validation_record_audit_link"
        )

    @property
    def validation_record_actor_ref(self) -> str:
        return f"{self.validation_record_audit_link_contract_ref}_actor"

    @property
    def validation_record_operator_intent_ref(self) -> str:
        return f"{self.validation_record_audit_link_contract_ref}_operator_intent"

    @property
    def validation_record_correlation_ref(self) -> str:
        return f"{self.validation_record_audit_link_contract_ref}_correlation"

    @property
    def validation_record_admission_audit_ref(self) -> str:
        return f"{self.validation_record_audit_link_contract_ref}_admission_audit"

    @property
    def validation_record_audit_record_ref(self) -> str:
        return f"{self.validation_record_audit_link_contract_ref}_audit_record"

    @property
    def required_backend_contract(self) -> str:
        return self.validation_record_audit_link_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.validation_record_audit_link_contract_ref

    @property
    def validation_record_audit_link_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validation_record_audit_link_contract_ref}.validation_record_schema_ref",
            f"{self.validation_record_audit_link_contract_ref}.validation_record_append_only_log_ref",
            f"{self.validation_record_audit_link_contract_ref}.validation_record_replay_guard_contract_ref",
            f"{self.validation_record_audit_link_contract_ref}.validation_record_idempotency_contract_ref",
            f"{self.validation_record_audit_link_contract_ref}.payload_hash_ref",
            f"{self.validation_record_audit_link_contract_ref}.actor_ref",
            f"{self.validation_record_audit_link_contract_ref}.operator_intent_ref",
            f"{self.validation_record_audit_link_contract_ref}.correlation_ref",
            f"{self.validation_record_audit_link_contract_ref}.admission_audit_ref",
            f"{self.validation_record_audit_link_contract_ref}.audit_record_ref",
            f"{self.validation_record_audit_link_contract_ref}.authority_flags",
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            self.validation_evidence_contract_ref,
            self.validation_record_contract_ref,
            self.validation_record_store_ref,
            self.validation_record_writer_ref,
            self.validation_record_replay_guard_ref,
            self.validation_record_schema_ref,
            self.validation_record_append_only_log_ref,
            self.validation_record_replay_guard_contract_ref,
            self.validation_record_idempotency_contract_ref,
            self.validation_record_audit_link_contract_ref,
            self.validation_record_actor_ref,
            self.validation_record_operator_intent_ref,
            self.validation_record_correlation_ref,
            self.validation_record_admission_audit_ref,
            self.validation_record_audit_record_ref,
            f"{self.validation_record_audit_link_contract_ref}_field_manifest",
            f"{self.validation_record_audit_link_contract_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            "backend-owned validation-record audit linkage before validation "
            "records can be trusted as command evidence. Runtime reads, "
            "browser display, and BFF forwarding cannot bind actor, operator "
            "intent, correlation, admission-audit, or append audit records."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordAuditLinkContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordAuditLinkContract(
        validation_record_replay_guard_contract=contract,
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS
)


def iter_futures_request_payload_validation_record_audit_links(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordAuditLinkContract]:
    """Yield disabled audit-link contracts for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS:
        if contract.command == command:
            yield contract
