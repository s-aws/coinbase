"""Pure classification of Coinbase order-placement responses.

Coinbase's Advanced Trade create-order endpoint reports both HTTP/SDK return
and exchange acceptance in one response.  A call returning without raising is
therefore not proof that an order was accepted.  This module provides the one
shared, side-effect-free boundary for interpreting that response.

The classifier is intentionally fail-closed:

* only the literal boolean ``success=True`` can be accepted;
* acceptance also requires a nonblank nested
  ``success_response.order_id``;
* when Coinbase returns ``success_response.client_order_id``, it must match
  the client order id sent by the caller;
* literal ``success=False`` is a definitive rejection; and
* exceptions and every ambiguous/malformed shape are indeterminate.

No database, logging, retry, or lifecycle behavior belongs here.  Callers own
those effects after examining :class:`PlacementClassification`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from core.enums import OrderPlacementOutcome


_MAX_FAILURE_REASON_LENGTH = 512


@dataclass(frozen=True)
class PlacementClassification:
    """Normalized, immutable result of a placement attempt."""

    outcome: OrderPlacementOutcome
    exchange_order_id: Optional[str] = None
    returned_client_order_id: Optional[str] = None
    failure_reason: Optional[str] = None

    @property
    def accepted(self) -> bool:
        """Return whether exchange acceptance was positively established."""

        return self.outcome is OrderPlacementOutcome.ACCEPTED


def _safe_text(value: Any) -> Optional[str]:
    """Return a bounded single-line scalar string, or ``None``.

    Exchange error envelopes occasionally contain nested structures.  Those
    structures are deliberately not stringified because doing so can persist
    an entire response (including unrelated or sensitive fields) as a failure
    reason.  Known scalar values are whitespace-normalized and bounded to the
    database column's current 512-character limit.
    """

    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    if not isinstance(value, (str, int, float, bool)):
        return None

    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:_MAX_FAILURE_REASON_LENGTH]


def _nonblank_identifier(value: Any) -> Optional[str]:
    """Return a stripped identifier only when Coinbase supplied a string."""

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _failure_reason(response: Mapping[str, Any]) -> Optional[str]:
    """Extract a safe Coinbase failure reason in deterministic priority order."""

    candidates = [response.get("failure_reason")]
    error_response = response.get("error_response")
    if isinstance(error_response, Mapping):
        candidates.extend(
            (
                error_response.get("error"),
                error_response.get("preview_failure_reason"),
                error_response.get("message"),
            )
        )
    else:
        candidates.append(error_response)
    candidates.append(response.get("message"))

    for candidate in candidates:
        reason = _safe_text(candidate)
        if reason is not None:
            return reason
    return None


def _indeterminate(
    reason: str,
    *,
    exchange_order_id: Optional[str] = None,
    returned_client_order_id: Optional[str] = None,
) -> PlacementClassification:
    return PlacementClassification(
        outcome=OrderPlacementOutcome.INDETERMINATE,
        exchange_order_id=exchange_order_id,
        returned_client_order_id=returned_client_order_id,
        failure_reason=_safe_text(reason),
    )


def classify_placement_response(
    response: Any = None,
    *,
    expected_client_order_id: str,
    exception: Optional[BaseException] = None,
) -> PlacementClassification:
    """Classify one Coinbase ``place_limit_order`` attempt.

    Args:
        response: Raw SDK response mapping returned by ``place_limit_order``.
        expected_client_order_id: The internal id supplied with the request.
        exception: The exception caught around the REST call, when it raised.
            Pass ``response=None`` in that path.  Any exception is
            indeterminate because the exchange may have accepted the request
            before the client lost the response.

    Returns:
        A :class:`PlacementClassification`.  This function never raises for a
        malformed exchange response.
    """

    if exception is not None:
        exception_message = _safe_text(str(exception))
        exception_type = type(exception).__name__
        reason = f"{exception_type}: {exception_message}" if exception_message else exception_type
        return _indeterminate(reason)

    if not isinstance(response, Mapping):
        to_dict = getattr(response, "to_dict", None)
        if not callable(to_dict):
            return _indeterminate("placement response is not a mapping")
        try:
            response = to_dict()
        except Exception as conversion_error:
            return _indeterminate(
                "placement response to_dict failed: "
                f"{type(conversion_error).__name__}"
            )
        if not isinstance(response, Mapping):
            return _indeterminate("placement response to_dict did not return a mapping")

    success = response.get("success")
    if success is False:
        return PlacementClassification(
            outcome=OrderPlacementOutcome.REJECTED,
            failure_reason=(
                _failure_reason(response)
                or "exchange rejected placement without a failure reason"
            ),
        )

    if success is not True:
        return _indeterminate("placement response missing explicit boolean success")

    success_response = response.get("success_response")
    if not isinstance(success_response, Mapping):
        return _indeterminate("successful placement response missing success_response mapping")

    exchange_order_id = _nonblank_identifier(success_response.get("order_id"))
    if exchange_order_id is None:
        return _indeterminate(
            "successful placement response missing success_response.order_id"
        )

    expected_id = _nonblank_identifier(expected_client_order_id)
    if expected_id is None:
        return _indeterminate(
            "expected_client_order_id must be a nonblank scalar",
            exchange_order_id=exchange_order_id,
        )

    returned_client_order_id: Optional[str] = None
    if "client_order_id" in success_response:
        returned_client_order_id = _nonblank_identifier(
            success_response.get("client_order_id")
        )
        if returned_client_order_id is None:
            return _indeterminate(
                "successful placement response contains a blank client_order_id",
                exchange_order_id=exchange_order_id,
            )
        if returned_client_order_id != expected_id:
            return _indeterminate(
                "successful placement response client_order_id does not match request",
                exchange_order_id=exchange_order_id,
                returned_client_order_id=returned_client_order_id,
            )

    return PlacementClassification(
        outcome=OrderPlacementOutcome.ACCEPTED,
        exchange_order_id=exchange_order_id,
        returned_client_order_id=returned_client_order_id,
    )
