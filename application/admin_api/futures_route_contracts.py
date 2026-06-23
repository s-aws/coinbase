"""Disabled futures/perpetual route-registration contract metadata.

This module is the single source for futures/perpetual command route contract
refs. The FastAPI route module re-exports these constants under the documented
``api/v1/routes/futures.py::*_route_contract`` names, while the read service
uses this module directly to avoid a route/read-service import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import AdminFuturesCommandAction

from .live_execution import (
    FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS,
    FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS,
)


@dataclass(frozen=True)
class FuturesRouteContract:
    """One disabled route-registration contract for a futures command."""

    command: AdminFuturesCommandAction
    contract_name: str
    contract_ref: str
    route_registered: bool = False
    command_draft_allowed: bool = False
    live_adapter_bound: bool = False
    execution_allowed: bool = False
    reconciliation_execution_enabled: bool = False
    state_mutation_allowed: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


def _route_contract(
    command: AdminFuturesCommandAction,
    contract_name: str,
) -> FuturesRouteContract:
    return FuturesRouteContract(
        command=command,
        contract_name=contract_name,
        contract_ref=f"api/v1/routes/futures.py::{contract_name}",
    )


FUTURES_PLACE_ROUTE_CONTRACT = _route_contract(
    AdminFuturesCommandAction.PLACE,
    "futures_place_route_contract",
)
FUTURES_CLOSE_REDUCE_ROUTE_CONTRACT = _route_contract(
    AdminFuturesCommandAction.CLOSE_REDUCE,
    "futures_close_reduce_route_contract",
)
FUTURES_CANCEL_ROUTE_CONTRACT = _route_contract(
    AdminFuturesCommandAction.CANCEL,
    "futures_cancel_route_contract",
)
FUTURES_RECONCILE_ROUTE_CONTRACT = _route_contract(
    AdminFuturesCommandAction.RECONCILE,
    "futures_reconcile_route_contract",
)

FUTURES_ROUTE_CONTRACTS: dict[AdminFuturesCommandAction, FuturesRouteContract] = {
    FUTURES_PLACE_ROUTE_CONTRACT.command: FUTURES_PLACE_ROUTE_CONTRACT,
    FUTURES_CLOSE_REDUCE_ROUTE_CONTRACT.command: FUTURES_CLOSE_REDUCE_ROUTE_CONTRACT,
    FUTURES_CANCEL_ROUTE_CONTRACT.command: FUTURES_CANCEL_ROUTE_CONTRACT,
    FUTURES_RECONCILE_ROUTE_CONTRACT.command: FUTURES_RECONCILE_ROUTE_CONTRACT,
}


def futures_live_adapter_contract_ref(command: AdminFuturesCommandAction) -> str:
    """Return the disabled live-adapter contract ref for a futures command."""

    return FUTURES_LIVE_ADAPTER_CONTRACTS[command].contract_ref


def futures_live_adapter_construction_contract_ref(
    command: AdminFuturesCommandAction,
) -> str:
    """Return the disabled construction contract ref for a futures adapter."""

    return FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS[command].contract_ref


def futures_live_adapter_decision_contract_ref(
    command: AdminFuturesCommandAction,
) -> str:
    """Return the disabled decision contract ref for a futures adapter."""

    return FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS[command].contract_ref


def futures_live_adapter_decision_record_contract_ref(
    command: AdminFuturesCommandAction,
) -> str:
    """Return the disabled decision-record contract ref for a futures adapter."""

    return FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS[command].contract_ref


def futures_live_adapter_invocation_contract_ref(
    command: AdminFuturesCommandAction,
) -> str:
    """Return the disabled invocation contract ref for a futures adapter."""

    return FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS[command].contract_ref


def futures_live_adapter_execution_contract_ref(
    command: AdminFuturesCommandAction,
) -> str:
    """Return the missing execution contract ref for a futures adapter."""

    return FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS[command].execution_contract_ref
