"""Canonical exchange adapter for the single-use Goal 11 position action."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any

from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
    COINBASE_EXECUTION_SCOPE_FUTURES_CLOSE_POSITION,
    canonical_coinbase_execution_scope,
)
from core.enums import AdminFuturesPositionCallOutcome

from .operator_futures_position_lifecycle import (
    FuturesPositionExecutionPlan,
)


_TERMINAL_ORDER_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)
_NONTERMINAL_ORDER_STATUSES = frozenset(
    {"PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"}
)


@dataclass(frozen=True, slots=True)
class FuturesPositionActionExecution:
    outcome: AdminFuturesPositionCallOutcome
    diagnostic_code: str
    exchange_order_id_sha256: str | None
    public_evidence: dict[str, Any]
    private_exchange_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class FuturesPositionOrderReconciliationExecution:
    outcome: AdminFuturesPositionCallOutcome
    diagnostic_code: str
    exchange_order_id_sha256: str
    order_status: str | None
    authoritatively_nonterminal: bool
    public_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesPositionPositionReconciliationExecution:
    outcome: AdminFuturesPositionCallOutcome
    diagnostic_code: str
    remaining_contracts: str | None
    public_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesPositionCancelExecution:
    outcome: AdminFuturesPositionCallOutcome
    diagnostic_code: str
    exchange_order_id_sha256: str
    public_evidence: dict[str, Any]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shallow_mapping(value: Any) -> dict[str, Any] | None:
    try:
        if isinstance(value, Mapping):
            return dict(value)
        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, Mapping):
            return dict(attributes)
    except Exception:
        return None
    return None


def _public_boundary() -> dict[str, bool]:
    return {
        "raw_response_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }


def _unknown_action() -> FuturesPositionActionExecution:
    return FuturesPositionActionExecution(
        outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
        diagnostic_code="operator_futures_position_action_outcome_unknown",
        exchange_order_id_sha256=None,
        public_evidence=_public_boundary(),
    )


class AdminApiFuturesPositionExchangeExecutor:
    """Invoke exactly one Close/Reduce, two reads, and conditional Cancel."""

    def __init__(self, *, rest_client: Any) -> None:
        self.rest_client = rest_client

    def close_or_reduce(
        self,
        *,
        plan: FuturesPositionExecutionPlan,
        before_call: Callable[[], None],
    ) -> FuturesPositionActionExecution:
        try:
            if (
                plan.mode not in {"CLOSE_FULL", "REDUCE_ONE_CONTRACT"}
                or not plan.client_order_id
                or not plan.product_id
                or plan.close_side not in {"BUY", "SELL"}
                or len(plan.portfolio_id_sha256) != 64
                or (
                    plan.mode == "CLOSE_FULL"
                    and plan.action_size is not None
                )
                or (
                    plan.mode == "REDUCE_ONE_CONTRACT"
                    and plan.action_size != "1"
                )
            ):
                raise ValueError("futures_position_execution_plan_invalid")
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_CLOSE_POSITION
            ):
                raw = self.rest_client.close_operator_futures_position(
                    client_order_id=plan.client_order_id,
                    product_id=plan.product_id,
                    size=plan.action_size,
                    before_sdk_call=before_call,
                )
            response = _shallow_mapping(raw)
            success = (
                _shallow_mapping(response.get("success_response"))
                if response is not None
                else None
            )
            exchange_id = (
                str(success.get("order_id") or "").strip()
                if success is not None
                else ""
            )
            if (
                response is None
                or response.get("success") is not True
                or success is None
                or not exchange_id
            ):
                if response is not None and response.get("success") is False:
                    return FuturesPositionActionExecution(
                        outcome=AdminFuturesPositionCallOutcome.REJECTED,
                        diagnostic_code=(
                            "operator_futures_position_action_exchange_rejected"
                        ),
                        exchange_order_id_sha256=None,
                        public_evidence=_public_boundary(),
                    )
                raise ValueError("futures_position_action_response_invalid")
            exchange_hash = _sha256(exchange_id)
            return FuturesPositionActionExecution(
                outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_position_action_accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "client_order_id": plan.client_order_id,
                    "position_key": plan.position_key,
                    "product_id": plan.product_id,
                    "mode": plan.mode,
                    "exchange_order_id_sha256": exchange_hash,
                    **_public_boundary(),
                },
                private_exchange_order_id=exchange_id,
            )
        except Exception:
            return _unknown_action()

    def reconcile_order(
        self,
        *,
        plan: FuturesPositionExecutionPlan,
        private_exchange_order_id: str,
        before_call: Callable[[], None],
    ) -> FuturesPositionOrderReconciliationExecution:
        exchange_id = str(private_exchange_order_id or "").strip()
        exchange_hash = _sha256(exchange_id) if exchange_id else ""
        try:
            if not exchange_id:
                raise ValueError("futures_position_order_binding_invalid")
            raw = self.rest_client.get_order(
                exchange_id,
                before_sdk_call=before_call,
            )
            response = _shallow_mapping(raw)
            order = (
                _shallow_mapping(response.get("order"))
                if response is not None
                else None
            )
            if (
                order is None
                or order.get("order_id") != exchange_id
                or order.get("client_order_id") != plan.client_order_id
                or order.get("product_id") != plan.product_id
                or order.get("side") != plan.close_side
            ):
                raise ValueError("futures_position_order_identity_invalid")
            status = str(order.get("status") or "").upper()
            if status not in (
                _TERMINAL_ORDER_STATUSES | _NONTERMINAL_ORDER_STATUSES
            ):
                raise ValueError("futures_position_order_status_invalid")
            return FuturesPositionOrderReconciliationExecution(
                outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_position_order_reconciliation_accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                order_status=status,
                authoritatively_nonterminal=(
                    status in _NONTERMINAL_ORDER_STATUSES
                ),
                public_evidence={
                    "client_order_id": plan.client_order_id,
                    "position_key": plan.position_key,
                    "product_id": plan.product_id,
                    "status": status,
                    "exchange_order_id_sha256": exchange_hash,
                    **_public_boundary(),
                },
            )
        except Exception:
            return FuturesPositionOrderReconciliationExecution(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_order_reconciliation_unknown"
                ),
                exchange_order_id_sha256=exchange_hash,
                order_status=None,
                authoritatively_nonterminal=False,
                public_evidence={
                    "exchange_order_id_sha256": exchange_hash or None,
                    **_public_boundary(),
                },
            )

    def reconcile_position(
        self,
        *,
        plan: FuturesPositionExecutionPlan,
        before_call: Callable[[], None],
    ) -> FuturesPositionPositionReconciliationExecution:
        try:
            raw = self.rest_client.get_operator_futures_position(
                product_id=plan.product_id,
                before_sdk_call=before_call,
            )
            response = _shallow_mapping(raw)
            nested_position = (
                _shallow_mapping(response.get("position"))
                if response is not None
                else None
            )
            position = (
                nested_position
                if nested_position is not None
                else response
                if response is not None and "product_id" in response
                else None
            )
            if position is None:
                raise ValueError(
                    "futures_position_reconciliation_absence_unproven"
                )
            if position.get("product_id") != plan.product_id:
                raise ValueError(
                    "futures_position_reconciliation_identity_invalid"
                )
            expected_side = (
                "LONG" if plan.close_side == "SELL" else "SHORT"
            )
            if str(position.get("side") or "").upper() != expected_side:
                raise ValueError(
                    "futures_position_reconciliation_side_invalid"
                )
            raw_portfolio = str(
                position.get("portfolio_uuid")
                or position.get("portfolio_id")
                or position.get("retail_portfolio_id")
                or ""
            ).strip()
            if (
                raw_portfolio
                and _sha256(raw_portfolio) != plan.portfolio_id_sha256
            ):
                raise ValueError(
                    "futures_position_reconciliation_portfolio_invalid"
                )
            raw_contracts = position.get("number_of_contracts")
            if raw_contracts is None:
                raw_contracts = position.get("net_size")
            contracts = abs(Decimal(str(raw_contracts)))
            if (
                not contracts.is_finite()
                or contracts < 0
                or contracts != contracts.to_integral()
            ):
                raise ValueError(
                    "futures_position_reconciliation_contracts_invalid"
                )
            remaining = format(contracts, "f")
            return FuturesPositionPositionReconciliationExecution(
                outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_position_position_reconciliation_accepted"
                ),
                remaining_contracts=remaining,
                public_evidence={
                    "position_key": plan.position_key,
                    "product_id": plan.product_id,
                    "remaining_contracts": remaining,
                    **_public_boundary(),
                },
            )
        except (Exception, InvalidOperation):
            return FuturesPositionPositionReconciliationExecution(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_position_reconciliation_unknown"
                ),
                remaining_contracts=None,
                public_evidence=_public_boundary(),
            )

    def cancel(
        self,
        *,
        plan: FuturesPositionExecutionPlan,
        private_exchange_order_id: str,
        before_call: Callable[[], None],
    ) -> FuturesPositionCancelExecution:
        exchange_id = str(private_exchange_order_id or "").strip()
        exchange_hash = _sha256(exchange_id) if exchange_id else ""
        try:
            if not exchange_id:
                raise ValueError("futures_position_cancel_binding_invalid")
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL
            ):
                raw = self.rest_client.cancel_operator_futures_position_order(
                    exchange_order_id=exchange_id,
                    before_sdk_call=before_call,
                )
            response = _shallow_mapping(raw)
            results = response.get("results") if response is not None else None
            if type(results) is not list or len(results) != 1:
                raise ValueError("futures_position_cancel_response_invalid")
            result = _shallow_mapping(results[0])
            if result is None or result.get("order_id") != exchange_id:
                raise ValueError("futures_position_cancel_identity_invalid")
            outcome = (
                AdminFuturesPositionCallOutcome.ACCEPTED
                if result.get("success") is True
                else AdminFuturesPositionCallOutcome.REJECTED
                if result.get("success") is False
                else AdminFuturesPositionCallOutcome.UNKNOWN
            )
            diagnostic = {
                AdminFuturesPositionCallOutcome.ACCEPTED: (
                    "operator_futures_position_cancel_accepted"
                ),
                AdminFuturesPositionCallOutcome.REJECTED: (
                    "operator_futures_position_cancel_exchange_rejected"
                ),
                AdminFuturesPositionCallOutcome.UNKNOWN: (
                    "operator_futures_position_cancel_outcome_unknown"
                ),
            }[outcome]
            return FuturesPositionCancelExecution(
                outcome=outcome,
                diagnostic_code=diagnostic,
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "client_order_id": plan.client_order_id,
                    "position_key": plan.position_key,
                    "exchange_order_id_sha256": exchange_hash,
                    **_public_boundary(),
                },
            )
        except Exception:
            return FuturesPositionCancelExecution(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_cancel_outcome_unknown"
                ),
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "exchange_order_id_sha256": exchange_hash or None,
                    **_public_boundary(),
                },
            )


__all__ = [
    "AdminApiFuturesPositionExchangeExecutor",
    "FuturesPositionActionExecution",
    "FuturesPositionCancelExecution",
    "FuturesPositionOrderReconciliationExecution",
    "FuturesPositionPositionReconciliationExecution",
]
