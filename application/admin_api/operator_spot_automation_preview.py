"""Value-blind classification for the Spot Automation Preview boundary.

Only shallow attributes documented by Coinbase and materialized by
``coinbase-advanced-py==1.8.4`` are inspected.  The SDK converter is never
called and raw response values are never retained in the classification.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import re
from typing import Any

from coinbase.rest.types.orders_types import PreviewOrderResponse


_DOCUMENTED_ERROR_PATTERN = re.compile(
    r"^(?:UNKNOWN_PREVIEW_FAILURE_REASON|PREVIEW_[A-Z0-9_]+)$"
)
_DOCUMENTED_WARNINGS = frozenset(
    {
        "UNKNOWN",
        "BIG_ORDER",
        "SMALL_ORDER",
        "DURATION_EXTENDED_BY_MARKET_CLOSE",
        "OPEN_ORDERS_EXCEED_COMPLIANCE_PURCHASE_LIMIT_MAY_CANCEL",
    }
)


class SpotAutomationPreviewOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SpotAutomationPreviewFailureClass(str, Enum):
    NONE = "NONE"
    DOCUMENTED_REJECTION = "DOCUMENTED_REJECTION"
    UNCLASSIFIED_REJECTION = "UNCLASSIFIED_REJECTION"
    RESPONSE_SCHEMA_INVALID = "RESPONSE_SCHEMA_INVALID"
    TRANSPORT_UNKNOWN = "TRANSPORT_UNKNOWN"


@dataclass(frozen=True)
class SpotAutomationPreviewClassification:
    outcome: SpotAutomationPreviewOutcome
    failure_class: SpotAutomationPreviewFailureClass
    warning_present: bool
    preview_id_sha256: str | None
    preview_call_count: int | None = 1
    preview_call_count_exact: bool = True


def unknown_spot_automation_preview_classification(
    *,
    transport_unknown: bool,
) -> SpotAutomationPreviewClassification:
    """Return the only value-blind unknown shapes allowed after a claim."""

    return SpotAutomationPreviewClassification(
        outcome=SpotAutomationPreviewOutcome.UNKNOWN,
        failure_class=(
            SpotAutomationPreviewFailureClass.TRANSPORT_UNKNOWN
            if transport_unknown
            else SpotAutomationPreviewFailureClass.RESPONSE_SCHEMA_INVALID
        ),
        warning_present=False,
        preview_id_sha256=None,
        preview_call_count=None if transport_unknown else 1,
        preview_call_count_exact=not transport_unknown,
    )


def _decimal(value: Any, *, positive: bool) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (parsed <= 0 if positive else parsed < 0):
        return None
    return parsed


def classify_spot_automation_preview_response(
    response: Any,
    *,
    expected_base_size: str,
    expected_quote_size: str,
) -> SpotAutomationPreviewClassification:
    """Classify one SDK response without conversion or raw-value retention."""

    invalid = unknown_spot_automation_preview_classification(
        transport_unknown=False
    )
    if (
        isinstance(response, Mapping)
        or not isinstance(response, PreviewOrderResponse)
        or not hasattr(response, "__dict__")
    ):
        return invalid
    required = (
        "order_total",
        "commission_total",
        "errs",
        "warning",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "is_max",
    )
    if any(not hasattr(response, name) for name in required):
        return invalid

    errs = getattr(response, "errs")
    warnings = getattr(response, "warning")
    if (
        type(errs) is not list
        or type(warnings) is not list
        or any(type(item) is not str or not item for item in errs)
        or any(type(item) is not str or item not in _DOCUMENTED_WARNINGS for item in warnings)
        or type(getattr(response, "is_max")) is not bool
    ):
        return invalid

    numeric = {
        "order_total": _decimal(getattr(response, "order_total"), positive=False),
        "commission_total": _decimal(
            getattr(response, "commission_total"), positive=False
        ),
        "quote_size": _decimal(getattr(response, "quote_size"), positive=True),
        "base_size": _decimal(getattr(response, "base_size"), positive=True),
        "best_bid": _decimal(getattr(response, "best_bid"), positive=True),
        "best_ask": _decimal(getattr(response, "best_ask"), positive=True),
    }
    expected = _decimal(expected_base_size, positive=True)
    expected_quote = _decimal(expected_quote_size, positive=True)
    if (
        expected is None
        or expected_quote is None
        or any(value is None for value in numeric.values())
        or numeric["base_size"] != expected
        or numeric["quote_size"] != expected_quote
        or numeric["order_total"]
        != numeric["quote_size"] + numeric["commission_total"]
        or numeric["best_bid"] > numeric["best_ask"]
        or getattr(response, "is_max") is not False
    ):
        return invalid

    raw_preview_id = getattr(response, "preview_id", None)
    if raw_preview_id is not None and (
        type(raw_preview_id) is not str
        or not raw_preview_id
        or len(raw_preview_id) > 1024
    ):
        return invalid

    if errs:
        documented = all(
            _DOCUMENTED_ERROR_PATTERN.fullmatch(item) is not None
            for item in errs
        )
        return SpotAutomationPreviewClassification(
            outcome=SpotAutomationPreviewOutcome.REJECTED,
            failure_class=(
                SpotAutomationPreviewFailureClass.DOCUMENTED_REJECTION
                if documented
                else SpotAutomationPreviewFailureClass.UNCLASSIFIED_REJECTION
            ),
            warning_present=bool(warnings),
            preview_id_sha256=None,
        )

    preview_id_sha256 = (
        hashlib.sha256(raw_preview_id.encode("utf-8")).hexdigest()
        if raw_preview_id is not None
        else None
    )
    return SpotAutomationPreviewClassification(
        outcome=SpotAutomationPreviewOutcome.ACCEPTED,
        failure_class=SpotAutomationPreviewFailureClass.NONE,
        warning_present=bool(warnings),
        preview_id_sha256=preview_id_sha256,
    )


__all__ = [
    "SpotAutomationPreviewClassification",
    "SpotAutomationPreviewFailureClass",
    "SpotAutomationPreviewOutcome",
    "classify_spot_automation_preview_response",
    "unknown_spot_automation_preview_classification",
]
