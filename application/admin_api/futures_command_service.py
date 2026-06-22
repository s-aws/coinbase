"""Disabled futures/perpetual command service contract.

This module defines the backend-owned command-service boundary for future
futures/perpetual admin commands. It intentionally does not submit orders,
call Coinbase, reconcile exchange state, or mutate trading state.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import AdminFuturesCommandAction


class FuturesCommandServiceDisabledError(RuntimeError):
    """Raised if disabled futures command service methods are invoked."""


@dataclass(frozen=True)
class FuturesCommandServiceContract:
    """One disabled backend method contract for a futures command."""

    command: AdminFuturesCommandAction
    method_name: str
    contract_ref: str
    route_registered: bool = False
    command_draft_allowed: bool = False
    live_adapter_bound: bool = False
    execution_allowed: bool = False
    live_coinbase_orders_ran: bool = False


FUTURES_COMMAND_SERVICE_CONTRACTS: dict[
    AdminFuturesCommandAction,
    FuturesCommandServiceContract,
] = {
    AdminFuturesCommandAction.PLACE: FuturesCommandServiceContract(
        command=AdminFuturesCommandAction.PLACE,
        method_name="place_futures_order",
        contract_ref="application/admin_api/futures_command_service.py::place_futures_order",
    ),
    AdminFuturesCommandAction.CLOSE_REDUCE: FuturesCommandServiceContract(
        command=AdminFuturesCommandAction.CLOSE_REDUCE,
        method_name="close_or_reduce_futures_position",
        contract_ref=(
            "application/admin_api/futures_command_service.py::"
            "close_or_reduce_futures_position"
        ),
    ),
    AdminFuturesCommandAction.CANCEL: FuturesCommandServiceContract(
        command=AdminFuturesCommandAction.CANCEL,
        method_name="cancel_futures_order",
        contract_ref="application/admin_api/futures_command_service.py::cancel_futures_order",
    ),
}


class AdminApiFuturesCommandService:
    """Disabled backend command service for futures/perpetual admin commands."""

    def place_futures_order(self, *_args: object, **_kwargs: object) -> None:
        """Disabled futures placement boundary."""

        self._raise_disabled(AdminFuturesCommandAction.PLACE)

    def close_or_reduce_futures_position(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        """Disabled futures close/reduce boundary."""

        self._raise_disabled(AdminFuturesCommandAction.CLOSE_REDUCE)

    def cancel_futures_order(self, *_args: object, **_kwargs: object) -> None:
        """Disabled futures cancel boundary."""

        self._raise_disabled(AdminFuturesCommandAction.CANCEL)

    def _raise_disabled(self, command: AdminFuturesCommandAction) -> None:
        contract = FUTURES_COMMAND_SERVICE_CONTRACTS[command]
        raise FuturesCommandServiceDisabledError(
            f"{contract.contract_ref} is contract-defined but not executable; "
            "futures/perpetual command routes, drafts, live adapters, "
            "Coinbase calls, reconciliation execution, and state mutation "
            "remain disabled."
        )
