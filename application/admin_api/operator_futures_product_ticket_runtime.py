"""Canonical dynamic-product exchange adapter for Goal 3."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import re
from typing import Any

from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
    COINBASE_EXECUTION_SCOPE_FUTURES_PLACE,
    COINBASE_EXECUTION_SCOPE_FUTURES_PREVIEW,
    canonical_coinbase_execution_scope,
)
from core.enums import AdminFuturesManualCallOutcome

from .futures_order_preview import (
    classify_post_r10_preview_response_rejection,
    validate_post_r10_preview_response_acceptance,
    validate_preview_against_candidate,
)
from .operator_futures_manual_runtime import (
    FuturesManualCancelExecution,
    FuturesManualCreateExecution,
    FuturesManualPreviewExecution,
    FuturesManualReconciliationExecution,
)
from .operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_ORDER_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)
_NONTERMINAL_ORDER_STATUSES = frozenset(
    {"PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"}
)


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


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _validated_candidate(candidate: Mapping[str, Any]) -> dict[str, str]:
    normalized = {
        str(key): str(value)
        for key, value in dict(candidate).items()
    }
    opening = _positive_decimal(
        normalized.get("opening_reference_notional_usdc")
    )
    exposure = _positive_decimal(
        normalized.get("maximum_exposure_reference_notional_usdc")
    )
    buffered_close = _positive_decimal(
        normalized.get("buffered_close_reference_notional_usdc")
    )
    turnover = _positive_decimal(
        normalized.get("branch_turnover_reference_notional_usdc")
    )
    if (
        normalized.get("product_id")
        not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
        or normalized.get("side") not in {"BUY", "SELL"}
        or normalized.get("order_type") != "LIMIT_GTC"
        or normalized.get("post_only") != "true"
        or normalized.get("contract_count") != "1"
        or _positive_decimal(normalized.get("limit_price")) is None
        or _positive_decimal(normalized.get("contract_size")) is None
        or opening is None
        or exposure is None
        or buffered_close is None
        or turnover is None
        or opening >= Decimal("100")
        or exposure >= Decimal("150")
        or buffered_close >= Decimal("150")
        or turnover >= Decimal("300")
        or normalized.get("opening_cap_usdc") != "100"
        or normalized.get("exposure_cap_usdc") != "150"
        or normalized.get("turnover_cap_usdc") != "300"
        or not str(
            normalized.get("product_policy_revision") or ""
        ).isdigit()
        or int(normalized["product_policy_revision"]) < 1
        or _SHA256_RE.fullmatch(
            normalized.get("product_policy_sha256", "")
        )
        is None
    ):
        raise ValueError(
            "operator_futures_product_ticket_candidate_invalid"
        )
    follow_up_binding_fields = (
        "source_client_order_id",
        "root_client_order_id",
        "follow_up_intent_id",
        "trigger_evidence_sha256",
        "position_side",
        "position_contract_count",
    )
    is_follow_up = any(
        normalized.get(field) for field in follow_up_binding_fields
    )
    if normalized["side"] == "SELL" or is_follow_up:
        required_position_side = (
            "LONG" if normalized["side"] == "SELL" else "SHORT"
        )
        if (
            any(
                not normalized.get(field)
                for field in follow_up_binding_fields
            )
            or normalized["source_client_order_id"]
            != normalized["root_client_order_id"]
            or _SHA256_RE.fullmatch(
                normalized["trigger_evidence_sha256"]
            )
            is None
            or normalized["position_side"] != required_position_side
            or normalized["position_contract_count"] != "1"
        ):
            raise ValueError(
                "operator_futures_product_ticket_follow_up_binding_invalid"
            )
    return normalized


def _order_configuration(
    candidate: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "limit_limit_gtc": {
            "base_size": "1",
            "limit_price": candidate["limit_price"],
            "post_only": True,
        }
    }


def _unknown_preview(
    *,
    diagnostic_code: str = (
        "operator_futures_product_ticket_preview_outcome_unknown"
    ),
) -> FuturesManualPreviewExecution:
    return FuturesManualPreviewExecution(
        outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        diagnostic_code=diagnostic_code,
        preview_id_sha256=None,
        public_evidence={
            "raw_response_included": False,
            "private_identifiers_included": False,
        },
    )


def _unknown_create() -> FuturesManualCreateExecution:
    return FuturesManualCreateExecution(
        outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        diagnostic_code=(
            "operator_futures_product_ticket_create_outcome_unknown"
        ),
        exchange_order_id_sha256=None,
        public_evidence={
            "raw_response_included": False,
            "private_identifiers_included": False,
        },
    )


class AdminApiFuturesProductTicketExchangeExecutor:
    """Invoke one selected-product Preview/Create/read/Cancel sequence."""

    def __init__(self, *, rest_client: Any) -> None:
        self.rest_client = rest_client

    def preview(
        self,
        candidate: Mapping[str, Any],
        *,
        before_call: Callable[[], None],
    ) -> FuturesManualPreviewExecution:
        try:
            exact = _validated_candidate(candidate)
            product_id = exact["product_id"]
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_PREVIEW
            ):
                raw = self.rest_client.preview_futures_order(
                    product_id=product_id,
                    side=exact["side"],
                    order_configuration=_order_configuration(exact),
                    before_sdk_call=before_call,
                )
            normalized = validate_post_r10_preview_response_acceptance(raw)
            bound = validate_preview_against_candidate(
                normalized,
                exact,
            )
            preview_id = str(bound.pop("preview_id"))
            preview_hash = _sha256(preview_id)
            return FuturesManualPreviewExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_product_ticket_preview_accepted"
                ),
                preview_id_sha256=preview_hash,
                public_evidence={
                    **bound,
                    "product_id": product_id,
                    "preview_id_sha256": preview_hash,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
                private_preview_id=preview_id,
            )
        except ValueError as exc:
            fixed = classify_post_r10_preview_response_rejection(exc)
            if fixed in {
                "futures_preview_response_exchange_errors_present",
                "futures_preview_response_exchange_warnings_present",
            }:
                return FuturesManualPreviewExecution(
                    outcome=AdminFuturesManualCallOutcome.REJECTED,
                    diagnostic_code=(
                        "operator_futures_product_ticket_preview_"
                        "exchange_rejected"
                    ),
                    preview_id_sha256=None,
                    public_evidence={
                        "raw_response_included": False,
                        "private_identifiers_included": False,
                    },
                )
            if fixed == "futures_preview_response_economics_invalid":
                return _unknown_preview(
                    diagnostic_code=(
                        "operator_futures_product_ticket_preview_"
                        "economics_invalid"
                    )
                )
            if fixed is not None:
                return _unknown_preview(
                    diagnostic_code=(
                        "operator_futures_product_ticket_preview_"
                        "schema_invalid"
                    )
                )
            return _unknown_preview()
        except Exception:
            return _unknown_preview()

    def create(
        self,
        *,
        candidate: Mapping[str, Any],
        client_order_id: str,
        private_preview_id: str,
        before_call: Callable[[], None],
    ) -> FuturesManualCreateExecution:
        try:
            exact = _validated_candidate(candidate)
            product_id = exact["product_id"]
            exact_client_order_id = str(client_order_id or "").strip()
            exact_preview_id = str(private_preview_id or "").strip()
            if not exact_client_order_id or not exact_preview_id:
                raise ValueError(
                    "operator_futures_product_ticket_create_binding_invalid"
                )
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_PLACE
            ):
                raw = self.rest_client.create_futures_order(
                    client_order_id=exact_client_order_id,
                    product_id=product_id,
                    side=exact["side"],
                    order_configuration=_order_configuration(exact),
                    preview_id=exact_preview_id,
                    before_sdk_call=before_call,
                )
            response = _shallow_mapping(raw)
            if response is None:
                return _unknown_create()
            if response.get("success") is False:
                return FuturesManualCreateExecution(
                    outcome=AdminFuturesManualCallOutcome.REJECTED,
                    diagnostic_code=(
                        "operator_futures_product_ticket_create_"
                        "exchange_rejected"
                    ),
                    exchange_order_id_sha256=None,
                    public_evidence={
                        "raw_response_included": False,
                        "private_identifiers_included": False,
                    },
                )
            success = _shallow_mapping(response.get("success_response"))
            if response.get("success") is not True or success is None:
                return _unknown_create()
            exchange_order_id = str(
                success.get("order_id") or ""
            ).strip()
            if (
                not exchange_order_id
                or success.get("product_id") != product_id
                or success.get("side") != exact["side"]
                or success.get("client_order_id")
                != exact_client_order_id
            ):
                return _unknown_create()
            exchange_hash = _sha256(exchange_order_id)
            return FuturesManualCreateExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_product_ticket_create_accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "client_order_id": exact_client_order_id,
                    "product_id": product_id,
                    "side": exact["side"],
                    "exchange_order_id_sha256": exchange_hash,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
                private_exchange_order_id=exchange_order_id,
            )
        except Exception:
            return _unknown_create()

    def reconcile(
        self,
        *,
        candidate: Mapping[str, Any],
        client_order_id: str,
        private_exchange_order_id: str,
        before_call: Callable[[], None],
    ) -> FuturesManualReconciliationExecution:
        exchange_order_id = str(
            private_exchange_order_id or ""
        ).strip()
        exchange_hash = _sha256(exchange_order_id) if exchange_order_id else ""
        try:
            exact = _validated_candidate(candidate)
            product_id = exact["product_id"]
            exact_client_order_id = str(client_order_id or "").strip()
            if not exact_client_order_id or not exchange_order_id:
                raise ValueError(
                    "operator_futures_product_ticket_reconciliation_"
                    "binding_invalid"
                )
            raw = self.rest_client.get_order(
                exchange_order_id,
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
                or order.get("order_id") != exchange_order_id
                or order.get("client_order_id")
                != exact_client_order_id
                or order.get("product_id") != product_id
                or order.get("side") != exact["side"]
            ):
                raise ValueError(
                    "operator_futures_product_ticket_reconciliation_"
                    "identity_invalid"
                )
            order_status = str(order.get("status") or "").upper()
            if order_status not in (
                _TERMINAL_ORDER_STATUSES | _NONTERMINAL_ORDER_STATUSES
            ):
                raise ValueError(
                    "operator_futures_product_ticket_reconciliation_"
                    "status_invalid"
                )
            return FuturesManualReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_product_ticket_reconciliation_"
                    "accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                order_status=order_status,
                authoritatively_nonterminal=(
                    order_status in _NONTERMINAL_ORDER_STATUSES
                ),
                public_evidence={
                    "client_order_id": exact_client_order_id,
                    "product_id": product_id,
                    "side": exact["side"],
                    "status": order_status,
                    "exchange_order_id_sha256": exchange_hash,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
            )
        except Exception:
            return FuturesManualReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_reconciliation_"
                    "outcome_unknown"
                ),
                exchange_order_id_sha256=exchange_hash,
                order_status=None,
                authoritatively_nonterminal=False,
                public_evidence={
                    "exchange_order_id_sha256": exchange_hash or None,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
            )

    def cancel(
        self,
        *,
        candidate: Mapping[str, Any],
        client_order_id: str,
        private_exchange_order_id: str,
        before_call: Callable[[], None],
    ) -> FuturesManualCancelExecution:
        exchange_order_id = str(
            private_exchange_order_id or ""
        ).strip()
        exchange_hash = _sha256(exchange_order_id) if exchange_order_id else ""
        try:
            _validated_candidate(candidate)
            exact_client_order_id = str(client_order_id or "").strip()
            if not exact_client_order_id or not exchange_order_id:
                raise ValueError(
                    "operator_futures_product_ticket_cancel_binding_invalid"
                )
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL
            ):
                raw = self.rest_client.cancel_futures_order(
                    exchange_order_id=exchange_order_id,
                    before_sdk_call=before_call,
                )
            response = _shallow_mapping(raw)
            results = response.get("results") if response is not None else None
            if type(results) is not list or len(results) != 1:
                raise ValueError(
                    "operator_futures_product_ticket_cancel_response_invalid"
                )
            result = _shallow_mapping(results[0])
            if result is None or result.get("order_id") != exchange_order_id:
                raise ValueError(
                    "operator_futures_product_ticket_cancel_identity_invalid"
                )
            if result.get("success") is False:
                return FuturesManualCancelExecution(
                    outcome=AdminFuturesManualCallOutcome.REJECTED,
                    diagnostic_code=(
                        "operator_futures_product_ticket_cancel_"
                        "exchange_rejected"
                    ),
                    exchange_order_id_sha256=exchange_hash,
                    public_evidence={
                        "client_order_id": exact_client_order_id,
                        "exchange_order_id_sha256": exchange_hash,
                        "raw_response_included": False,
                        "private_identifiers_included": False,
                    },
                )
            if result.get("success") is not True:
                raise ValueError(
                    "operator_futures_product_ticket_cancel_response_invalid"
                )
            return FuturesManualCancelExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_product_ticket_cancel_accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "client_order_id": exact_client_order_id,
                    "exchange_order_id_sha256": exchange_hash,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
            )
        except Exception:
            return FuturesManualCancelExecution(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_cancel_outcome_unknown"
                ),
                exchange_order_id_sha256=exchange_hash,
                public_evidence={
                    "exchange_order_id_sha256": exchange_hash or None,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                },
            )


__all__ = [
    "AdminApiFuturesProductTicketExchangeExecutor",
]
