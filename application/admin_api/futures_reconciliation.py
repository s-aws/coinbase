"""Disabled futures/perpetual reconciliation contract.

This module defines the backend-owned reconciliation boundary for future
futures/perpetual admin commands. It intentionally does not execute
reconciliation, call Coinbase, accept proof records, or mutate trading state.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import AdminFuturesCommandAction


class FuturesReconciliationDisabledError(RuntimeError):
    """Raised if disabled futures reconciliation methods are invoked."""


@dataclass(frozen=True)
class FuturesReconciliationContract:
    """One disabled backend method contract for futures reconciliation."""

    method_name: str
    contract_ref: str
    commands: tuple[AdminFuturesCommandAction, ...]
    route_registered: bool = False
    reconciliation_execution_enabled: bool = False
    proof_acceptance_enabled: bool = False
    state_mutation_allowed: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False


FUTURES_RECONCILIATION_CONTRACT = FuturesReconciliationContract(
    method_name="record_futures_reconciliation_plan",
    contract_ref=(
        "application/admin_api/futures_reconciliation.py::"
        "record_futures_reconciliation_plan"
    ),
    commands=(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    ),
)


class AdminApiFuturesReconciliation:
    """Disabled backend reconciliation boundary for futures/perpetual commands."""

    def record_futures_reconciliation_plan(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        """Disabled futures reconciliation-plan record boundary."""

        raise FuturesReconciliationDisabledError(
            f"{FUTURES_RECONCILIATION_CONTRACT.contract_ref} is "
            "contract-defined but not executable; futures/perpetual "
            "reconciliation execution, proof acceptance, command routes, "
            "drafts, live adapters, Coinbase calls, and state mutation remain "
            "disabled."
        )
