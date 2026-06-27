"""Disabled futures/perpetual risk-guard contract.

This module defines the backend-owned risk-guard boundary for future
futures/perpetual admin commands. It intentionally does not validate margin,
collateral, liquidation, or funding as execution-ready checks, call Coinbase,
execute reconciliation, or mutate trading state.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import AdminFuturesCommandAction


class FuturesRiskGuardDisabledError(RuntimeError):
    """Raised if disabled futures risk-guard methods are invoked."""


@dataclass(frozen=True)
class FuturesRiskGuardContract:
    """One disabled backend method contract for futures risk evaluation."""

    method_name: str
    contract_ref: str
    commands: tuple[AdminFuturesCommandAction, ...]
    route_registered: bool = False
    proof_writer_enabled: bool = False
    risk_accepted: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False


FUTURES_RISK_GUARD_CONTRACT = FuturesRiskGuardContract(
    method_name="evaluate_futures_margin_collateral_liquidation",
    contract_ref=(
        "application/admin_api/futures_risk_guard.py::"
        "evaluate_futures_margin_collateral_liquidation"
    ),
    commands=(
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.RECONCILE,
    ),
)


class AdminApiFuturesRiskGuard:
    """Disabled backend risk guard for futures/perpetual admin commands."""

    def evaluate_futures_margin_collateral_liquidation(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        """Disabled margin/collateral/liquidation evaluation boundary."""

        raise FuturesRiskGuardDisabledError(
            f"{FUTURES_RISK_GUARD_CONTRACT.contract_ref} is contract-defined "
            "but not executable; futures/perpetual risk proof acceptance, "
            "command routes, drafts, live adapters, Coinbase calls, "
            "reconciliation execution, and state mutation remain disabled."
        )
