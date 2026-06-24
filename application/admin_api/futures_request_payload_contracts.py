"""Disabled futures/perpetual request payload contract registry.

The contracts in this module are backend-owned evidence for future command
payload validation. They intentionally do not validate browser payloads, accept
command drafts, call Coinbase, execute reconciliation, or mutate
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


@dataclass(frozen=True)
class FuturesRequestPayloadFieldContract:
    """One disabled futures command request payload-field contract."""

    command: AdminFuturesCommandAction
    field: AdminFuturesCommandRequestField
    detail: str
    identity_field: bool = False
    risk_field: bool = False
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.BACKEND_CONTRACT
    required: bool = True
    payload_field: bool = True
    backend_owned: bool = True
    spot_rule_authority: bool = False
    command_route_registered: bool = True
    command_draft_allowed: bool = True
    execution_allowed: bool = False
    validation_registered: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"

    @property
    def contract_ref(self) -> str:
        """Return the backend-owned registry ref for this disabled contract."""

        return (
            "application/admin_api/futures_request_payload_contracts.py::"
            f"{self.command.value}_{self.field.value}_request_payload_contract"
        )

    @property
    def validation_evidence_ref(self) -> str:
        """Return the missing future validation evidence ref for this field."""

        return f"{self.command.value}_{self.field.value}_request_payload_validated"

    @property
    def validation_gate_ref(self) -> str:
        """Return the disabled validation gate ref for this field."""

        return (
            "application/admin_api/futures_request_payload_contracts.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validation_gate"
        )

    @property
    def validator_contract_ref(self) -> str:
        """Return the missing future validator contract ref for this field."""

        return (
            "application/admin_api/futures_request_payload_validators.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validator_contract"
        )

    @property
    def validator_registration_ref(self) -> str:
        """Return the missing future validator registration ref for this field."""

        return (
            "application/admin_api/futures_request_payload_validators.py::"
            f"{self.command.value}_{self.field.value}_request_payload_validator_registration"
        )


def _contract(
    command: AdminFuturesCommandAction,
    field: AdminFuturesCommandRequestField,
    detail: str,
    *,
    identity_field: bool = False,
    risk_field: bool = False,
) -> FuturesRequestPayloadFieldContract:
    return FuturesRequestPayloadFieldContract(
        command=command,
        field=field,
        detail=detail,
        identity_field=identity_field,
        risk_field=risk_field,
    )


FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS: tuple[
    FuturesRequestPayloadFieldContract,
    ...,
] = (
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.PRODUCT_ID,
        "Futures placement product scope must come from backend futures product metadata, not spot USDC product assumptions.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.ORDER_SIDE,
        "Futures placement side requires a futures-specific backend contract before browser drafts can exist.",
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.ORDER_TYPE,
        "Futures placement order type must be validated by the backend command service contract.",
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.SIZE,
        "Futures placement size semantics must be validated against margin, collateral, liquidation, and product contract rules.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.LIMIT_PRICE,
        "Limit price semantics require futures-specific tick, liquidation, and cap/guard checks in the backend.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.TIME_IN_FORCE,
        "Time-in-force options require a backend futures command contract before any route accepts them.",
    ),
    _contract(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandRequestField.CLIENT_ORDER_ID,
        "Internal tracking must use client_order_id generated and audited by the backend command path.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.POSITION_KEY,
        "Close/reduce identity is the backend-derived position_key, not spot wallet inventory or average-cost evidence.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.PRODUCT_ID,
        "Product identity must be resolved from the backend position record before close/reduce commands exist.",
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.ORDER_SIDE,
        "Close/reduce side must be backend-derived from observed position side and reduce-only/close-only policy.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.SIZE,
        "Close/reduce size must be bounded by backend position evidence and futures risk contracts.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.REDUCE_ONLY,
        "Reduce-only intent is required and must be enforced in the backend command contract.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.CLOSE_ONLY,
        "Close-only intent requires backend position and reduce-only/close-only evidence before execution.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandRequestField.CLIENT_ORDER_ID,
        "Any future close/reduce placement must be tracked by backend-owned client_order_id evidence.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandRequestField.CLIENT_ORDER_ID,
        "Futures cancel must call the project wrapper with client_order_id; exchange order_id is exchange evidence only.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandRequestField.PRODUCT_ID,
        "Optional product context must be backend-owned evidence, not browser-side product inference.",
    ),
    _contract(
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandRequestField.OPERATOR_NOTES,
        "Operator notes are audit context only and cannot authorize futures cancellation.",
    ),
    _contract(
        AdminFuturesCommandAction.RECONCILE,
        AdminFuturesCommandRequestField.POSITION_KEY,
        "Reconciliation identity is the backend-derived position_key.",
        identity_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.RECONCILE,
        AdminFuturesCommandRequestField.PRODUCT_ID,
        "Product scope must be resolved from futures position evidence.",
    ),
    _contract(
        AdminFuturesCommandAction.RECONCILE,
        AdminFuturesCommandRequestField.EXPECTED_POSITION_STATE,
        "Expected position state must be compared against backend futures position, margin, collateral, funding, and liquidation evidence.",
        risk_field=True,
    ),
    _contract(
        AdminFuturesCommandAction.RECONCILE,
        AdminFuturesCommandRequestField.RECONCILIATION_REASON,
        "Reconciliation reason is append-only audit context and cannot execute reconciliation by itself.",
    ),
    _contract(
        AdminFuturesCommandAction.RECONCILE,
        AdminFuturesCommandRequestField.OPERATOR_NOTES,
        "Operator notes remain local audit context and do not grant browser or BFF execution authority.",
    ),
)


def iter_futures_request_payload_contracts(
    command: AdminFuturesCommandAction,
) -> Iterator[FuturesRequestPayloadFieldContract]:
    """Yield disabled request payload contracts for one futures command."""

    for contract in FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS:
        if contract.command == command:
            yield contract
