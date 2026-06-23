"""Disabled futures/perpetual risk-proof route contract registry.

The contracts in this module are backend-owned evidence for future proof routes.
They intentionally do not register FastAPI routes, accept proof payloads, call
Coinbase, execute reconciliation, or mutate futures/order/exchange state.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import (
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
)

from .futures_proof_contracts import iter_futures_risk_proof_contract_keys


@dataclass(frozen=True)
class FuturesProofRouteContract:
    """One disabled proof-route contract for a futures risk-proof requirement."""

    command: AdminFuturesCommandAction
    proof_kind: AdminFuturesCommandRiskProofKind
    method_name: str
    contract_ref: str
    route_path: str
    method: str = "POST"
    route_registered: bool = False
    proof_payloads_accepted: bool = False
    command_route_registered: bool = False
    command_draft_allowed: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False


def _build_route_contract(
    command: AdminFuturesCommandAction,
    proof_kind: AdminFuturesCommandRiskProofKind,
) -> FuturesProofRouteContract:
    method_name = f"post_{command.value}_{proof_kind.value}_proof"
    return FuturesProofRouteContract(
        command=command,
        proof_kind=proof_kind,
        method_name=method_name,
        contract_ref=f"application/admin_api/futures_proof_routes.py::{method_name}",
        route_path=f"/api/v1/futures/proofs/{command.value}/{proof_kind.value}",
    )


FUTURES_PROOF_ROUTE_CONTRACTS: dict[
    tuple[AdminFuturesCommandAction, AdminFuturesCommandRiskProofKind],
    FuturesProofRouteContract,
] = {
    (command, proof_kind): _build_route_contract(command, proof_kind)
    for command, proof_kind in iter_futures_risk_proof_contract_keys()
}


def get_futures_proof_route_contract(
    command: AdminFuturesCommandAction,
    proof_kind: AdminFuturesCommandRiskProofKind,
) -> FuturesProofRouteContract:
    """Return the disabled route contract for a command/proof-kind pair."""

    return FUTURES_PROOF_ROUTE_CONTRACTS[(command, proof_kind)]
