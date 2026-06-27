"""Disabled futures/perpetual risk-proof payload field contract registry.

The contracts in this module are backend-owned evidence for future proof
payload validation. They intentionally do not validate submitted payloads,
write proof records, accept proof records as command readiness, call Coinbase,
execute reconciliation, or mutate futures/order/exchange state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.enums import (
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
    AdminFuturesCommandRiskProofPayloadField,
)


@dataclass(frozen=True)
class FuturesProofPayloadFieldContract:
    """One disabled payload-field validation contract."""

    field: AdminFuturesCommandRiskProofPayloadField
    payload_path: str
    validation_rule_template: str
    payload_field_present: bool = False
    validation_registered: bool = False
    command_route_registered: bool = False
    command_draft_allowed: bool = False
    execution_allowed: bool = False
    proof_route_registered: bool = False
    proof_writer_enabled: bool = False
    live_coinbase_orders_ran: bool = False

    def validation_rule(
        self,
        *,
        command: AdminFuturesCommandAction,
        proof_kind: AdminFuturesCommandRiskProofKind,
        identity_key: str,
    ) -> str:
        """Return the display-only validation rule for this payload field."""

        return self.validation_rule_template.format(
            command=command.value,
            proof_kind=proof_kind.value,
            identity_key=identity_key,
        )

    def required_evidence_ref(
        self,
        *,
        command: AdminFuturesCommandAction,
        proof_kind: AdminFuturesCommandRiskProofKind,
    ) -> str:
        """Return the missing validation evidence ref for this payload field."""

        return f"{command.value}_{proof_kind.value}_payload_{self.field.value}_validated"


FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS: tuple[
    FuturesProofPayloadFieldContract,
    ...,
] = (
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.COMMAND,
        payload_path="proof_payload.command",
        validation_rule_template="Must equal {command}.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.PROOF_KIND,
        payload_path="proof_payload.proof_kind",
        validation_rule_template="Must equal {proof_kind}.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.IDENTITY_KEY,
        payload_path="proof_payload.identity.key",
        validation_rule_template="Must equal {identity_key}.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.IDENTITY_VALUE,
        payload_path="proof_payload.identity.value",
        validation_rule_template="Must bind the backend-owned {identity_key} value.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.REQUIRED_EVIDENCE_REFS,
        payload_path="proof_payload.required_evidence_refs",
        validation_rule_template=(
            "Must contain every required evidence ref for this proof."
        ),
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.SOURCE_SNAPSHOT_REF,
        payload_path="proof_payload.source_snapshot_ref",
        validation_rule_template=(
            "Must reference the backend source snapshot used to build proof evidence."
        ),
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.VALIDATION_STATUS,
        payload_path="proof_payload.validation.status",
        validation_rule_template="Must be accepted only by backend proof validation.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.IDEMPOTENCY_KEY,
        payload_path="proof_payload.idempotency_key",
        validation_rule_template="Must bind the backend idempotency key for replay safety.",
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.CORRELATION_ID,
        payload_path="proof_payload.correlation_id",
        validation_rule_template=(
            "Must bind the backend correlation id used for audit traceability."
        ),
    ),
    FuturesProofPayloadFieldContract(
        field=AdminFuturesCommandRiskProofPayloadField.AUDIT_ID,
        payload_path="proof_payload.audit_id",
        validation_rule_template="Must bind the backend audit id for durable proof readback.",
    ),
)


def iter_futures_proof_payload_field_contracts(
    *,
    command: AdminFuturesCommandAction,
    proof_kind: AdminFuturesCommandRiskProofKind,
    identity_key: str,
) -> Iterator[tuple[FuturesProofPayloadFieldContract, str, str]]:
    """Yield payload contracts with resolved rule and evidence refs."""

    for contract in FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS:
        yield (
            contract,
            contract.validation_rule(
                command=command,
                proof_kind=proof_kind,
                identity_key=identity_key,
            ),
            contract.required_evidence_ref(command=command, proof_kind=proof_kind),
        )
