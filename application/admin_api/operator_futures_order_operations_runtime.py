"""Canonical exact-order Futures cancellation adapter for Goal 2."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
from typing import Any, Literal

from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
    canonical_coinbase_execution_scope,
)


@dataclass(frozen=True, slots=True)
class FuturesOrderCancelExecution:
    outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"]
    diagnostic_code: str
    exchange_order_id_sha256: str
    call_boundary_entered: bool
    public_evidence: dict[str, Any]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shallow_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    attributes = getattr(value, "__dict__", None)
    return dict(attributes) if isinstance(attributes, Mapping) else None


class AdminApiFuturesOrderOperationsExchangeExecutor:
    """Cancel one freshly reconciled exact Futures order with no fallback."""

    def __init__(self, *, rest_client: Any) -> None:
        self.rest_client = rest_client

    def cancel(
        self,
        *,
        client_order_id: str,
        private_exchange_order_id: str,
        expected_exchange_order_id_sha256: str,
        before_call: Callable[[], None],
    ) -> FuturesOrderCancelExecution:
        exact_client_order_id = str(client_order_id or "").strip()
        exchange_order_id = str(private_exchange_order_id or "").strip()
        exchange_hash = _sha256_text(exchange_order_id) if exchange_order_id else ""
        call_boundary_entered = False

        def enter_call_boundary() -> None:
            nonlocal call_boundary_entered
            before_call()
            call_boundary_entered = True

        public = {
            "client_order_id": exact_client_order_id or None,
            "exchange_order_id_sha256": exchange_hash or None,
            "call_boundary_entered": False,
            "raw_response_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        try:
            if (
                not exact_client_order_id
                or not exchange_order_id
                or exchange_hash != expected_exchange_order_id_sha256
            ):
                raise ValueError("operator_futures_order_cancel_binding_invalid")
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL
            ):
                raw = self.rest_client.cancel_futures_order(
                    exchange_order_id=exchange_order_id,
                    before_sdk_call=enter_call_boundary,
                )
            public["call_boundary_entered"] = call_boundary_entered
            response = _shallow_mapping(raw)
            results = response.get("results") if response is not None else None
            if type(results) is not list or len(results) != 1:
                raise ValueError(
                    "operator_futures_order_cancel_response_invalid"
                )
            result = _shallow_mapping(results[0])
            if result is None or result.get("order_id") != exchange_order_id:
                raise ValueError(
                    "operator_futures_order_cancel_identity_invalid"
                )
            if result.get("success") is False:
                return FuturesOrderCancelExecution(
                    outcome="REJECTED",
                    diagnostic_code=(
                        "operator_futures_order_cancel_exchange_rejected"
                    ),
                    exchange_order_id_sha256=exchange_hash,
                    call_boundary_entered=call_boundary_entered,
                    public_evidence=public,
                )
            if result.get("success") is not True:
                raise ValueError(
                    "operator_futures_order_cancel_response_invalid"
                )
            return FuturesOrderCancelExecution(
                outcome="ACCEPTED",
                diagnostic_code="operator_futures_order_cancel_accepted",
                exchange_order_id_sha256=exchange_hash,
                call_boundary_entered=call_boundary_entered,
                public_evidence=public,
            )
        except Exception:
            public["call_boundary_entered"] = call_boundary_entered
            return FuturesOrderCancelExecution(
                outcome="UNKNOWN",
                diagnostic_code="operator_futures_order_cancel_outcome_unknown",
                exchange_order_id_sha256=exchange_hash,
                call_boundary_entered=call_boundary_entered,
                public_evidence=public,
            )


__all__ = [
    "AdminApiFuturesOrderOperationsExchangeExecutor",
    "FuturesOrderCancelExecution",
]
