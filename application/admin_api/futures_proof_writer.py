"""Disabled futures/perpetual risk-proof writer contract registry.

The contracts in this module are backend-owned evidence for future proof
writers. They intentionally do not write proof records, accept proof records as
command readiness, call Coinbase, execute reconciliation, or mutate
futures/order/exchange state.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import (
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
)

from .futures_proof_contracts import iter_futures_risk_proof_contract_keys


@dataclass(frozen=True)
class FuturesProofWriterContract:
    """One disabled proof-writer contract for a futures risk-proof requirement."""

    command: AdminFuturesCommandAction
    proof_kind: AdminFuturesCommandRiskProofKind
    method_name: str
    contract_ref: str
    method: str = "LOCAL"
    writer_enabled: bool = False
    proof_records_accepted: bool = False
    proof_records_write_allowed: bool = False
    command_route_registered: bool = False
    command_draft_allowed: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False


def _build_writer_contract(
    command: AdminFuturesCommandAction,
    proof_kind: AdminFuturesCommandRiskProofKind,
) -> FuturesProofWriterContract:
    method_name = f"write_{command.value}_{proof_kind.value}_proof"
    return FuturesProofWriterContract(
        command=command,
        proof_kind=proof_kind,
        method_name=method_name,
        contract_ref=f"application/admin_api/futures_proof_writer.py::{method_name}",
    )


FUTURES_PROOF_WRITER_CONTRACTS: dict[
    tuple[AdminFuturesCommandAction, AdminFuturesCommandRiskProofKind],
    FuturesProofWriterContract,
] = {
    (command, proof_kind): _build_writer_contract(command, proof_kind)
    for command, proof_kind in iter_futures_risk_proof_contract_keys()
}


def get_futures_proof_writer_contract(
    command: AdminFuturesCommandAction,
    proof_kind: AdminFuturesCommandRiskProofKind,
) -> FuturesProofWriterContract:
    """Return the disabled writer contract for a command/proof-kind pair."""

    return FUTURES_PROOF_WRITER_CONTRACTS[(command, proof_kind)]
