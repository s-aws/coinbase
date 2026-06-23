"""Shared futures/perpetual risk-proof contract keys.

This module is metadata only. It does not register HTTP routes, write proof
records, call Coinbase, execute reconciliation, or mutate trading state.
"""

from __future__ import annotations

from collections.abc import Iterator

from core.enums import (
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
)


FUTURES_RISK_PROOF_KINDS_BY_COMMAND: dict[
    AdminFuturesCommandAction,
    tuple[AdminFuturesCommandRiskProofKind, ...],
] = {
    AdminFuturesCommandAction.PLACE: (
        AdminFuturesCommandRiskProofKind.PRODUCT_SCOPE,
        AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        AdminFuturesCommandRiskProofKind.LIQUIDATION_BUFFER,
        AdminFuturesCommandRiskProofKind.FUNDING_FEE,
        AdminFuturesCommandRiskProofKind.CAP_GUARD,
        AdminFuturesCommandRiskProofKind.RECONCILIATION_PLAN,
    ),
    AdminFuturesCommandAction.CLOSE_REDUCE: (
        AdminFuturesCommandRiskProofKind.POSITION_SCOPE,
        AdminFuturesCommandRiskProofKind.REDUCE_ONLY,
        AdminFuturesCommandRiskProofKind.CLOSE_ONLY,
        AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        AdminFuturesCommandRiskProofKind.LIQUIDATION_BUFFER,
        AdminFuturesCommandRiskProofKind.CAP_GUARD,
        AdminFuturesCommandRiskProofKind.RECONCILIATION_PLAN,
    ),
    AdminFuturesCommandAction.CANCEL: (
        AdminFuturesCommandRiskProofKind.PRODUCT_SCOPE,
        AdminFuturesCommandRiskProofKind.RECONCILIATION_PLAN,
    ),
    AdminFuturesCommandAction.RECONCILE: (
        AdminFuturesCommandRiskProofKind.POSITION_SCOPE,
        AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        AdminFuturesCommandRiskProofKind.LIQUIDATION_BUFFER,
        AdminFuturesCommandRiskProofKind.FUNDING_FEE,
        AdminFuturesCommandRiskProofKind.RECONCILIATION_PLAN,
    ),
}


def iter_futures_risk_proof_contract_keys() -> Iterator[
    tuple[AdminFuturesCommandAction, AdminFuturesCommandRiskProofKind]
]:
    """Yield exact command/proof-kind pairs used by M57 readiness evidence."""

    for command, proof_kinds in FUTURES_RISK_PROOF_KINDS_BY_COMMAND.items():
        for proof_kind in proof_kinds:
            yield command, proof_kind
