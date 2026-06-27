"""Disabled futures/perpetual validation-record execution-eligibility registry.

These rows are backend-owned evidence that an admitted futures/perpetual
validation record still cannot make a command executable until futures-specific
position, margin, collateral, liquidation, reduce-only, close-only, funding,
order, cancel, and reconciliation semantics exist. They do not validate
payloads, admit commands, call Coinbase, execute reconciliation, or mutate
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

from .futures_request_payload_validation_record_admission_links import (
    FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS,
    FuturesRequestPayloadValidationRecordAdmissionLinkContract,
)


@dataclass(frozen=True)
class FuturesRequestPayloadValidationRecordExecutionEligibilityContract:
    """One disabled execution-eligibility row for a futures payload field."""

    validation_record_admission_link_contract: FuturesRequestPayloadValidationRecordAdmissionLinkContract
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    read_only: bool = True
    spot_rule_authority: bool = False
    runtime_evidence_observed: bool = False
    runtime_evidence_satisfies_validation_record_execution_eligibility: bool = False
    runtime_evidence_satisfies_validation_record_admission_link: bool = False
    validation_record_execution_eligibility_contract_ready: bool = False
    validation_record_execution_eligible: bool = False
    validation_record_position_semantics_ready: bool = False
    validation_record_margin_semantics_ready: bool = False
    validation_record_collateral_semantics_ready: bool = False
    validation_record_liquidation_semantics_ready: bool = False
    validation_record_reduce_only_semantics_ready: bool = False
    validation_record_close_only_semantics_ready: bool = False
    validation_record_funding_semantics_ready: bool = False
    validation_record_order_semantics_ready: bool = False
    validation_record_cancel_semantics_ready: bool = False
    validation_record_reconciliation_semantics_ready: bool = False
    validation_record_semantic_contracts_present: bool = True
    validation_record_semantic_contracts_ready: bool = False
    validation_record_admission_link_contract_ready: bool = False
    validation_record_admission_link_ready: bool = False
    validation_record_approval_snapshot_bound: bool = False
    validation_record_cap_guard_decision_bound: bool = False
    validation_record_reconciliation_plan_bound: bool = False
    validation_record_live_intent_bound: bool = False
    validation_record_command_admission_bound: bool = False
    validation_record_admitted: bool = False
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
        return self.validation_record_admission_link_contract.command

    @property
    def field(self) -> AdminFuturesCommandRequestField:
        return self.validation_record_admission_link_contract.field

    @property
    def request_payload_contract_ref(self) -> str:
        return self.validation_record_admission_link_contract.request_payload_contract_ref

    @property
    def validation_gate_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_gate_ref

    @property
    def validation_evidence_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_evidence_ref

    @property
    def validation_evidence_contract_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_evidence_contract_ref
        )

    @property
    def validator_contract_ref(self) -> str:
        return self.validation_record_admission_link_contract.validator_contract_ref

    @property
    def validator_input_schema_ref(self) -> str:
        return self.validation_record_admission_link_contract.validator_input_schema_ref

    @property
    def validator_output_schema_ref(self) -> str:
        return self.validation_record_admission_link_contract.validator_output_schema_ref

    @property
    def validator_registration_ref(self) -> str:
        return self.validation_record_admission_link_contract.validator_registration_ref

    @property
    def validation_record_contract_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_contract_ref

    @property
    def validation_record_store_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_store_ref

    @property
    def validation_record_writer_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_writer_ref

    @property
    def validation_record_replay_guard_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_replay_guard_ref
        )

    @property
    def validation_record_schema_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_schema_ref

    @property
    def validation_record_append_only_log_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_append_only_log_ref
        )

    @property
    def validation_record_replay_guard_contract_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_replay_guard_contract_ref
        )

    @property
    def validation_record_idempotency_contract_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_idempotency_contract_ref
        )

    @property
    def validation_record_replay_window_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_replay_window_ref
        )

    @property
    def validation_record_duplicate_policy_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_duplicate_policy_ref
        )

    @property
    def validation_record_audit_link_contract_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_audit_link_contract_ref
        )

    @property
    def validation_record_actor_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_actor_ref

    @property
    def validation_record_operator_intent_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_operator_intent_ref
        )

    @property
    def validation_record_correlation_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_correlation_ref
        )

    @property
    def validation_record_admission_audit_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_admission_audit_ref
        )

    @property
    def validation_record_audit_record_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_audit_record_ref
        )

    @property
    def validation_record_admission_link_contract_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_admission_link_contract_ref
        )

    @property
    def validation_record_approval_snapshot_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_approval_snapshot_ref
        )

    @property
    def validation_record_cap_guard_decision_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_cap_guard_decision_ref
        )

    @property
    def validation_record_reconciliation_plan_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_reconciliation_plan_ref
        )

    @property
    def validation_record_live_intent_ref(self) -> str:
        return self.validation_record_admission_link_contract.validation_record_live_intent_ref

    @property
    def validation_record_command_admission_ref(self) -> str:
        return (
            self.validation_record_admission_link_contract.validation_record_command_admission_ref
        )

    @property
    def validation_record_admission_link_field_refs(self) -> tuple[str, ...]:
        return (
            self.validation_record_admission_link_contract.validation_record_admission_link_field_refs
        )

    @property
    def validation_record_execution_eligibility_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_execution_eligibilities.py::"
            f"{self.command.value}_{self.field.value}_"
            "request_payload_validation_record_execution_eligibility"
        )

    @property
    def validation_record_position_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_position_semantics"

    @property
    def validation_record_position_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_position_semantics.py::"
            f"{self.command.value}_{self.field.value}_position_semantics_contract"
        )

    @property
    def validation_record_margin_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_margin_semantics"

    @property
    def validation_record_margin_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_margin_semantics.py::"
            f"{self.command.value}_{self.field.value}_margin_semantics_contract"
        )

    @property
    def validation_record_collateral_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_collateral_semantics"

    @property
    def validation_record_collateral_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_collateral_semantics.py::"
            f"{self.command.value}_{self.field.value}_collateral_semantics_contract"
        )

    @property
    def validation_record_liquidation_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_liquidation_semantics"

    @property
    def validation_record_liquidation_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_liquidation_semantics.py::"
            f"{self.command.value}_{self.field.value}_liquidation_semantics_contract"
        )

    @property
    def validation_record_reduce_only_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_reduce_only_semantics"

    @property
    def validation_record_reduce_only_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_reduce_only_semantics.py::"
            f"{self.command.value}_{self.field.value}_reduce_only_semantics_contract"
        )

    @property
    def validation_record_close_only_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_close_only_semantics"

    @property
    def validation_record_close_only_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_close_only_semantics.py::"
            f"{self.command.value}_{self.field.value}_close_only_semantics_contract"
        )

    @property
    def validation_record_funding_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_funding_semantics"

    @property
    def validation_record_funding_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_funding_semantics.py::"
            f"{self.command.value}_{self.field.value}_funding_semantics_contract"
        )

    @property
    def validation_record_order_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_order_semantics"

    @property
    def validation_record_order_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_order_semantics.py::"
            f"{self.command.value}_{self.field.value}_order_semantics_contract"
        )

    @property
    def validation_record_cancel_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_cancel_semantics"

    @property
    def validation_record_cancel_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_cancel_semantics.py::"
            f"{self.command.value}_{self.field.value}_cancel_semantics_contract"
        )

    @property
    def validation_record_reconciliation_semantics_ref(self) -> str:
        return f"{self.validation_record_execution_eligibility_contract_ref}_reconciliation_semantics"

    @property
    def validation_record_reconciliation_semantics_contract_ref(self) -> str:
        return (
            "application/admin_api/"
            "futures_request_payload_validation_record_reconciliation_semantics.py::"
            f"{self.command.value}_{self.field.value}_reconciliation_semantics_contract"
        )

    @property
    def validation_record_semantic_contract_refs(self) -> tuple[str, ...]:
        return (
            self.validation_record_position_semantics_contract_ref,
            self.validation_record_margin_semantics_contract_ref,
            self.validation_record_collateral_semantics_contract_ref,
            self.validation_record_liquidation_semantics_contract_ref,
            self.validation_record_reduce_only_semantics_contract_ref,
            self.validation_record_close_only_semantics_contract_ref,
            self.validation_record_funding_semantics_contract_ref,
            self.validation_record_order_semantics_contract_ref,
            self.validation_record_cancel_semantics_contract_ref,
            self.validation_record_reconciliation_semantics_contract_ref,
        )

    @property
    def required_backend_contract(self) -> str:
        return self.validation_record_execution_eligibility_contract_ref

    @property
    def missing_backend_contract(self) -> str:
        return self.validation_record_execution_eligibility_contract_ref

    @property
    def validation_record_execution_eligibility_field_refs(self) -> tuple[str, ...]:
        return (
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_admission_link_contract_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_position_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_margin_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_collateral_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_liquidation_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_reduce_only_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_close_only_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_funding_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_order_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_cancel_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_reconciliation_semantics_ref",
            f"{self.validation_record_execution_eligibility_contract_ref}.validation_record_semantic_contract_refs",
            f"{self.validation_record_execution_eligibility_contract_ref}.authority_flags",
        )

    @property
    def required_evidence_refs(self) -> tuple[str, ...]:
        return (
            *self.validation_record_admission_link_contract.required_evidence_refs,
            self.validation_record_execution_eligibility_contract_ref,
            self.validation_record_position_semantics_ref,
            self.validation_record_margin_semantics_ref,
            self.validation_record_collateral_semantics_ref,
            self.validation_record_liquidation_semantics_ref,
            self.validation_record_reduce_only_semantics_ref,
            self.validation_record_close_only_semantics_ref,
            self.validation_record_funding_semantics_ref,
            self.validation_record_order_semantics_ref,
            self.validation_record_cancel_semantics_ref,
            self.validation_record_reconciliation_semantics_ref,
            *self.validation_record_semantic_contract_refs,
            f"{self.validation_record_execution_eligibility_contract_ref}_field_manifest",
            f"{self.validation_record_execution_eligibility_contract_ref}_contextless_review",
        )

    @property
    def missing_evidence_refs(self) -> tuple[str, ...]:
        return self.required_evidence_refs

    @property
    def detail(self) -> str:
        return (
            f"{self.command.value} request field {self.field.value} requires "
            "backend-owned execution eligibility semantics before an admitted "
            "validation record can make a futures/perpetual command executable. "
            "Runtime reads, browser display, and BFF forwarding cannot supply "
            "position, margin, collateral, liquidation, reduce-only, close-only, "
            "funding, order, cancel, or reconciliation semantics. The semantic "
            "contract rows may be present as backend-owned disabled evidence, "
            "but none are ready or runtime-accepted."
        )


FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS: tuple[
    FuturesRequestPayloadValidationRecordExecutionEligibilityContract,
    ...,
] = tuple(
    FuturesRequestPayloadValidationRecordExecutionEligibilityContract(
        validation_record_admission_link_contract=contract,
    )
    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS
)


def iter_futures_request_payload_validation_record_execution_eligibilities(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadValidationRecordExecutionEligibilityContract]:
    """Yield disabled execution-eligibility contracts for one command."""

    for contract in FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS:
        if contract.command == command:
            yield contract
