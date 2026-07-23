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
import socket
from typing import Any

from coinbase.rest.types.orders_types import PreviewOrderResponse
from requests.exceptions import (
    ConnectTimeout,
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    ContentDecodingError,
    HTTPError,
    InvalidHeader,
    InvalidProxyURL,
    InvalidSchema,
    InvalidURL,
    JSONDecodeError as RequestsJSONDecodeError,
    MissingSchema,
    ProxyError,
    ReadTimeout,
    SSLError,
    Timeout,
    TooManyRedirects,
    URLRequired,
)


# Exact allowlist from Coinbase's Preview Order ``errs`` response schema.
# Do not replace this with a prefix/shape check: a future or private-looking
# ``PREVIEW_*`` value is not documented evidence until this list is reviewed.
_DOCUMENTED_ERRORS = frozenset(
    {
        "UNKNOWN_PREVIEW_FAILURE_REASON",
        "PREVIEW_ASSET_BALANCE_INCREASE_REJECT",
        "PREVIEW_ATTACHED_ORDERS_ONLY_ALLOWED_ON_MARKET_LIMIT",
        "PREVIEW_ATTACHED_ORDER_MUST_HAVE_POSITIVE_PRICES",
        "PREVIEW_ATTACHED_ORDER_SIZE_MUST_BE_NIL",
        "PREVIEW_ATTACHED_STOP_LOSS_PRICE_TOO_HIGH",
        "PREVIEW_ATTACHED_STOP_LOSS_PRICE_TOO_LOW",
        "PREVIEW_ATTACHED_TAKE_PROFIT_PRICE_TOO_HIGH",
        "PREVIEW_ATTACHED_TAKE_PROFIT_PRICE_TOO_LOW",
        "PREVIEW_BELOW_MIN_SIZE_FOR_DURATION",
        "PREVIEW_BRACKET_LIMIT_PRICE_OUT_OF_BOUNDS",
        "PREVIEW_BRACKET_ORDER_NOT_SUPPORTED",
        "PREVIEW_BRACKET_ORDER_SIZE_EXCEEDS_POSITION",
        "PREVIEW_BREACHED_ACCOUNT_POSITION_LIMIT",
        "PREVIEW_BREACHED_COMPANY_POSITION_LIMIT",
        "PREVIEW_BREACHED_OPEN_INTEREST_LIMIT",
        "PREVIEW_BREACHED_PRICE_LIMIT",
        "PREVIEW_BREACHED_RISK_LIMIT",
        "PREVIEW_BUCKET_SIZE_SMALLER_THAN_BASE_MIN",
        "PREVIEW_BUCKET_SIZE_SMALLER_THAN_QUOTE_MIN",
        "PREVIEW_CLOSE_ONLY_FAILURE",
        "PREVIEW_COMPLIANCE_PURCHASE_LIMIT_EXCEEDED",
        "PREVIEW_DURATION_TOO_LARGE",
        "PREVIEW_DURATION_TOO_SMALL",
        "PREVIEW_ECOSYSTEM_LEVERAGE_UTILIZATION_BREACHED",
        "PREVIEW_END_TIME_AFTER_CONTRACT_EXPIRATION",
        "PREVIEW_END_TIME_IS_IN_THE_PAST",
        "PREVIEW_END_TIME_TOO_FAR_IN_FUTURE",
        "PREVIEW_FOK_DISABLED",
        "PREVIEW_FOK_ONLY_ALLOWED_ON_LIMIT_ORDERS",
        "PREVIEW_FRACTIONAL_ORDERS_NOT_ALLOWED_FOR_PRODUCT",
        "PREVIEW_FUTURES_AFTER_HOUR_INVALID_ORDER_TYPE",
        "PREVIEW_FUTURES_AFTER_HOUR_INVALID_TIME_IN_FORCE",
        "PREVIEW_GEOFENCING_RESTRICTION",
        "PREVIEW_GTD_ORDERS_MUST_HAVE_END_TIME",
        "PREVIEW_ICEBERG_ORDERS_NOT_SUPPORTED",
        "PREVIEW_INSUFFICIENT_FUND",
        "PREVIEW_INSUFFICIENT_FUNDS_FOR_FUTURES",
        "PREVIEW_INSUFFICIENT_LEDGER_BALANCE",
        "PREVIEW_INTX_FOK_ONLY_ALLOWED_ON_LIMIT_AND_MARKET_ORDERS",
        "PREVIEW_INVALID_ATTACHED_STOP_LOSS_PRICE",
        "PREVIEW_INVALID_ATTACHED_STOP_LOSS_PRICE_OUT_OF_BOUNDS",
        "PREVIEW_INVALID_ATTACHED_STOP_LOSS_PRICE_OUT_OF_BOUNDS_ON_AGGRESSIVE_ORDER",
        "PREVIEW_INVALID_ATTACHED_STOP_LOSS_PRICE_PRECISION",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_PRICE",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_PRICE_EXCEEDS_MAX_DISTANCE_FROM_ORIGINATING_PRICE",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_PRICE_OUT_OF_BOUNDS",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_PRICE_OUT_OF_BOUNDS_ON_AGGRESSIVE_ORDER",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_PRICE_PRECISION",
        "PREVIEW_INVALID_ATTACHED_TAKE_PROFIT_SIZE_BELOW_MIN",
        "PREVIEW_INVALID_BASE_SIZE_TOO_LARGE",
        "PREVIEW_INVALID_BASE_SIZE_TOO_SMALL",
        "PREVIEW_INVALID_BRACKET_LIMIT_PRICE",
        "PREVIEW_INVALID_BRACKET_LIMIT_PRICE_PRECISION",
        "PREVIEW_INVALID_BRACKET_ORDER_SIDE",
        "PREVIEW_INVALID_BRACKET_PRICES",
        "PREVIEW_INVALID_BRACKET_STOP_TRIGGER_PRICE",
        "PREVIEW_INVALID_COMMISSION_CONFIGURATION",
        "PREVIEW_INVALID_END_TIME",
        "PREVIEW_INVALID_EQUITY_TRADING_SESSION",
        "PREVIEW_INVALID_FCM_TRADING_SESSION",
        "PREVIEW_INVALID_INTX_CLIENT_ORDER_ID",
        "PREVIEW_INVALID_LEDGER_BALANCE",
        "PREVIEW_INVALID_LEVERAGE",
        "PREVIEW_INVALID_LIMIT_PRICE",
        "PREVIEW_INVALID_LIMIT_PRICE_POST_ONLY",
        "PREVIEW_INVALID_LIMIT_PRICE_PRECISION",
        "PREVIEW_INVALID_MARGIN_HEALTH",
        "PREVIEW_INVALID_MARGIN_TYPE",
        "PREVIEW_INVALID_NBBO_ASK_PRICE",
        "PREVIEW_INVALID_NBBO_BID_PRICE",
        "PREVIEW_INVALID_NO_LIQUIDITY",
        "PREVIEW_INVALID_ORDER_CONFIG",
        "PREVIEW_INVALID_ORDER_SIDE_FOR_ATTACHED_TPSL",
        "PREVIEW_INVALID_ORDER_TYPE_FOR_ATTACHED",
        "PREVIEW_INVALID_PEG_OFFSET",
        "PREVIEW_INVALID_PEG_VENUE_OPTIONS",
        "PREVIEW_INVALID_PEG_WIG_LEVEL",
        "PREVIEW_INVALID_PRICE_PRECISION",
        "PREVIEW_INVALID_PRICE_TOO_LARGE",
        "PREVIEW_INVALID_PRODUCT_ID",
        "PREVIEW_INVALID_QUOTE_SIZE_PRECISION",
        "PREVIEW_INVALID_QUOTE_SIZE_TOO_LARGE",
        "PREVIEW_INVALID_QUOTE_SIZE_TOO_SMALL",
        "PREVIEW_INVALID_RFQ_BASE_SIZE_TOO_LARGE",
        "PREVIEW_INVALID_RFQ_BASE_SIZE_TOO_SMALL",
        "PREVIEW_INVALID_RFQ_QUOTE_SIZE_TOO_LARGE",
        "PREVIEW_INVALID_RFQ_QUOTE_SIZE_TOO_SMALL",
        "PREVIEW_INVALID_SETTLEMENT_CURRENCY",
        "PREVIEW_INVALID_SIDE",
        "PREVIEW_INVALID_SIZE_PRECISION",
        "PREVIEW_INVALID_STOP_PRICE",
        "PREVIEW_INVALID_STOP_PRICE_PRECISION",
        "PREVIEW_INVALID_STOP_TRIGGER_PRICE_PRECISION",
        "PREVIEW_IN_LIQUIDATION",
        "PREVIEW_LIMIT_ORDER_PRICE_EXCEEDS_PRICE_BAND_ON_BUY",
        "PREVIEW_LIMIT_ORDER_PRICE_EXCEEDS_PRICE_BAND_ON_SELL",
        "PREVIEW_LIMIT_PRICE_TOO_FAR_FROM_MARKET",
        "PREVIEW_MARKET_ORDERS_PROHIBITED_DURING_NON_CORE_SESSION",
        "PREVIEW_MAX_DAILY_VOLUME_NOTIONAL_BREACHED",
        "PREVIEW_MAX_NOTIONAL_PER_ORDER_BREACHED_15C35_CHECK",
        "PREVIEW_MAX_SHARES_PER_ORDER_BREACHED_15C35_CHECK",
        "PREVIEW_MISSING_COMMISSION_RATE",
        "PREVIEW_MISSING_MARKET_TRADE_DATA",
        "PREVIEW_MISSING_PRODUCT_PRICE_BOOK",
        "PREVIEW_NBBO_NOT_PROVIDED",
        "PREVIEW_NON_NUMERIC_ORDER_SIZE",
        "PREVIEW_NOTIONAL_ORDERS_PROHIBITED_DURING_NON_CORE_SESSION",
        "PREVIEW_NOTIONAL_SIZE_BREACHES_FRACTIONAL_MINIMUM",
        "PREVIEW_NOT_ALLOWED_BY_MARKET_STATE",
        "PREVIEW_OPPOSITE_MARGIN_TYPE_EXISTS",
        "PREVIEW_ORDER_IS_PENDING_CANCEL",
        "PREVIEW_ORDER_SIZE_EXCEEDS_BRACKETED_POSITION",
        "PREVIEW_PEG_INVALID_ORDER_TYPE",
        "PREVIEW_POSITION_SIZE_INCREASE_REJECT",
        "PREVIEW_POST_ONLY_NOT_ALLOWED_WITH_FOK",
        "PREVIEW_POST_ONLY_NOT_ALLOWED_WITH_PEG",
        "PREVIEW_PREDICTIONS_HIGH_PRICE_CONTRACTS_BLOCKED",
        "PREVIEW_PREDICTIONS_QUOTE_SIZE_BELOW_MIN_CONTRACT_PRICE",
        "PREVIEW_PRICE_NOT_ALLOWED_FOR_MARKET_ORDERS",
        "PREVIEW_PRODUCT_TRADING_HALTED",
        "PREVIEW_QUOTE_ORDERS_NOT_ALLOWED_FOR_PRODUCT",
        "PREVIEW_QUOTE_SIZE_NOT_ALLOWED_FOR_BRACKET",
        "PREVIEW_REDUCE_ONLY_INCREASED_POSITION_SIZE",
        "PREVIEW_REDUCE_ONLY_NOT_ALLOWED_ON_SPOT_PRODUCTS",
        "PREVIEW_REDUCE_ONLY_NOT_ALLOWED_ON_VENUE",
        "PREVIEW_REPLACE_NOT_SUPPORTED",
        "PREVIEW_RISK_PROXY_FAILURE",
        "PREVIEW_SCALED_MAX_ORDER_VIOLATION",
        "PREVIEW_SCALED_MIN_ORDER_VIOLATION",
        "PREVIEW_SCALED_PARAM_DISCREPANCY",
        "PREVIEW_SCALED_PARAM_INFEASIBLE",
        "PREVIEW_SINGLE_LEGGED_TPSL_NOT_ALLOWED",
        "PREVIEW_START_TIME_MUST_BE_SPECIFIED",
        "PREVIEW_STOP_LOSS_PRICE_TOO_HIGH",
        "PREVIEW_STOP_LOSS_PRICE_TOO_LOW",
        "PREVIEW_STOP_PRICE_ABOVE_LAST_TRADE_PRICE",
        "PREVIEW_STOP_PRICE_ABOVE_LIMIT_PRICE",
        "PREVIEW_STOP_PRICE_BELOW_LAST_TRADE_PRICE",
        "PREVIEW_STOP_PRICE_BELOW_LIMIT_PRICE",
        "PREVIEW_STOP_TRIGGERED",
        "PREVIEW_STOP_TRIGGER_PRICE_OUT_OF_BOUNDS",
        "PREVIEW_TAKE_PROFIT_PRICE_TOO_HIGH",
        "PREVIEW_TAKE_PROFIT_PRICE_TOO_LOW",
        "PREVIEW_TOO_MANY_PENDING_REPLACES",
        "PREVIEW_TRADING_DISABLED",
        "PREVIEW_UBO_HIGH_LEVERAGE_NOTIONAL_BREACHED",
        "PREVIEW_UBO_HIGH_LEVERAGE_QUANTITY_BREACHED",
        "PREVIEW_UNTRADABLE_FCM_ACCOUNT_STATUS",
        "PREVIEW_UNTRADABLE_PRODUCT",
    }
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
    HTTP_CLIENT_RESPONSE = "HTTP_CLIENT_RESPONSE"
    HTTP_SERVER_RESPONSE = "HTTP_SERVER_RESPONSE"
    HTTP_REDIRECT_RESPONSE = "HTTP_REDIRECT_RESPONSE"
    HTTP_RESPONSE_INVALID = "HTTP_RESPONSE_INVALID"
    REQUEST_COMPOSITION_FAILURE = "REQUEST_COMPOSITION_FAILURE"
    SDK_INVOCATION_UNKNOWN = "SDK_INVOCATION_UNKNOWN"
    DNS_RESOLUTION_FAILURE = "DNS_RESOLUTION_FAILURE"
    TCP_CONNECTION_FAILURE = "TCP_CONNECTION_FAILURE"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    TLS_OR_CERTIFICATE_FAILURE = "TLS_OR_CERTIFICATE_FAILURE"
    PROXY_FAILURE = "PROXY_FAILURE"
    READ_TIMEOUT = "READ_TIMEOUT"
    CONNECTION_RESET = "CONNECTION_RESET"
    RESPONSE_DECODING_FAILURE = "RESPONSE_DECODING_FAILURE"
    TRANSPORT_UNKNOWN = "TRANSPORT_UNKNOWN"


class SpotAutomationPreviewInvocationStage(str, Enum):
    """Fixed caller-owned boundary; never derived from exception text."""

    REQUEST_COMPOSITION = "REQUEST_COMPOSITION"
    SDK_INVOCATION = "SDK_INVOCATION"


class SpotAutomationPreviewRejectionCode(str, Enum):
    """Fixed value-blind category derived from one documented ``errs`` value."""

    UNKNOWN_DOCUMENTED = "UNKNOWN_DOCUMENTED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    SIZE_PRECISION = "SIZE_PRECISION"
    PRICE_PRECISION = "PRICE_PRECISION"
    BASE_SIZE_TOO_LARGE = "BASE_SIZE_TOO_LARGE"
    BASE_SIZE_TOO_SMALL = "BASE_SIZE_TOO_SMALL"
    QUOTE_SIZE_PRECISION = "QUOTE_SIZE_PRECISION"
    QUOTE_SIZE_TOO_LARGE = "QUOTE_SIZE_TOO_LARGE"
    QUOTE_SIZE_TOO_SMALL = "QUOTE_SIZE_TOO_SMALL"
    PRICE_TOO_LARGE = "PRICE_TOO_LARGE"
    POST_ONLY_LIMIT_PRICE = "POST_ONLY_LIMIT_PRICE"
    LIMIT_PRICE = "LIMIT_PRICE"
    NO_LIQUIDITY = "NO_LIQUIDITY"
    PRODUCT_PRICE_BOOK_MISSING = "PRODUCT_PRICE_BOOK_MISSING"
    MARKET_TRADE_DATA_MISSING = "MARKET_TRADE_DATA_MISSING"
    PRODUCT_INVALID = "PRODUCT_INVALID"
    PRODUCT_UNTRADABLE = "PRODUCT_UNTRADABLE"
    MARKET_STATE = "MARKET_STATE"
    ORDER_CONFIGURATION = "ORDER_CONFIGURATION"
    POLICY = "POLICY"
    OTHER_DOCUMENTED = "OTHER_DOCUMENTED"
    MULTIPLE_DOCUMENTED = "MULTIPLE_DOCUMENTED"


_REJECTION_CODE_BY_ERROR = {
    "UNKNOWN_PREVIEW_FAILURE_REASON": (
        SpotAutomationPreviewRejectionCode.UNKNOWN_DOCUMENTED
    ),
    "PREVIEW_INSUFFICIENT_FUND": (
        SpotAutomationPreviewRejectionCode.INSUFFICIENT_FUNDS
    ),
    "PREVIEW_INSUFFICIENT_LEDGER_BALANCE": (
        SpotAutomationPreviewRejectionCode.INSUFFICIENT_FUNDS
    ),
    "PREVIEW_INVALID_LEDGER_BALANCE": (
        SpotAutomationPreviewRejectionCode.INSUFFICIENT_FUNDS
    ),
    "PREVIEW_INVALID_SIZE_PRECISION": (
        SpotAutomationPreviewRejectionCode.SIZE_PRECISION
    ),
    "PREVIEW_INVALID_PRICE_PRECISION": (
        SpotAutomationPreviewRejectionCode.PRICE_PRECISION
    ),
    "PREVIEW_INVALID_LIMIT_PRICE_PRECISION": (
        SpotAutomationPreviewRejectionCode.PRICE_PRECISION
    ),
    "PREVIEW_INVALID_BASE_SIZE_TOO_LARGE": (
        SpotAutomationPreviewRejectionCode.BASE_SIZE_TOO_LARGE
    ),
    "PREVIEW_INVALID_BASE_SIZE_TOO_SMALL": (
        SpotAutomationPreviewRejectionCode.BASE_SIZE_TOO_SMALL
    ),
    "PREVIEW_INVALID_QUOTE_SIZE_PRECISION": (
        SpotAutomationPreviewRejectionCode.QUOTE_SIZE_PRECISION
    ),
    "PREVIEW_INVALID_QUOTE_SIZE_TOO_LARGE": (
        SpotAutomationPreviewRejectionCode.QUOTE_SIZE_TOO_LARGE
    ),
    "PREVIEW_INVALID_QUOTE_SIZE_TOO_SMALL": (
        SpotAutomationPreviewRejectionCode.QUOTE_SIZE_TOO_SMALL
    ),
    "PREVIEW_INVALID_PRICE_TOO_LARGE": (
        SpotAutomationPreviewRejectionCode.PRICE_TOO_LARGE
    ),
    "PREVIEW_INVALID_LIMIT_PRICE_POST_ONLY": (
        SpotAutomationPreviewRejectionCode.POST_ONLY_LIMIT_PRICE
    ),
    "PREVIEW_INVALID_LIMIT_PRICE": SpotAutomationPreviewRejectionCode.LIMIT_PRICE,
    "PREVIEW_LIMIT_PRICE_TOO_FAR_FROM_MARKET": (
        SpotAutomationPreviewRejectionCode.LIMIT_PRICE
    ),
    "PREVIEW_LIMIT_ORDER_PRICE_EXCEEDS_PRICE_BAND_ON_BUY": (
        SpotAutomationPreviewRejectionCode.LIMIT_PRICE
    ),
    "PREVIEW_LIMIT_ORDER_PRICE_EXCEEDS_PRICE_BAND_ON_SELL": (
        SpotAutomationPreviewRejectionCode.LIMIT_PRICE
    ),
    "PREVIEW_BREACHED_PRICE_LIMIT": SpotAutomationPreviewRejectionCode.LIMIT_PRICE,
    "PREVIEW_INVALID_NO_LIQUIDITY": SpotAutomationPreviewRejectionCode.NO_LIQUIDITY,
    "PREVIEW_MISSING_PRODUCT_PRICE_BOOK": (
        SpotAutomationPreviewRejectionCode.PRODUCT_PRICE_BOOK_MISSING
    ),
    "PREVIEW_MISSING_MARKET_TRADE_DATA": (
        SpotAutomationPreviewRejectionCode.MARKET_TRADE_DATA_MISSING
    ),
    "PREVIEW_INVALID_PRODUCT_ID": (
        SpotAutomationPreviewRejectionCode.PRODUCT_INVALID
    ),
    "PREVIEW_UNTRADABLE_PRODUCT": (
        SpotAutomationPreviewRejectionCode.PRODUCT_UNTRADABLE
    ),
    "PREVIEW_PRODUCT_TRADING_HALTED": (
        SpotAutomationPreviewRejectionCode.PRODUCT_UNTRADABLE
    ),
    "PREVIEW_TRADING_DISABLED": (
        SpotAutomationPreviewRejectionCode.PRODUCT_UNTRADABLE
    ),
    "PREVIEW_NOT_ALLOWED_BY_MARKET_STATE": (
        SpotAutomationPreviewRejectionCode.MARKET_STATE
    ),
    "PREVIEW_INVALID_ORDER_CONFIG": (
        SpotAutomationPreviewRejectionCode.ORDER_CONFIGURATION
    ),
    "PREVIEW_COMPLIANCE_PURCHASE_LIMIT_EXCEEDED": (
        SpotAutomationPreviewRejectionCode.POLICY
    ),
    "PREVIEW_GEOFENCING_RESTRICTION": SpotAutomationPreviewRejectionCode.POLICY,
}


@dataclass(frozen=True)
class SpotAutomationPreviewClassification:
    outcome: SpotAutomationPreviewOutcome
    failure_class: SpotAutomationPreviewFailureClass
    warning_present: bool
    rejection_code: SpotAutomationPreviewRejectionCode | None
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
        rejection_code=None,
        preview_id_sha256=None,
        preview_call_count=None if transport_unknown else 1,
        preview_call_count_exact=not transport_unknown,
    )


def classify_spot_automation_preview_exception(
    exception: Exception,
    *,
    stage: SpotAutomationPreviewInvocationStage = (
        SpotAutomationPreviewInvocationStage.SDK_INVOCATION
    ),
) -> SpotAutomationPreviewClassification:
    """Classify an invocation failure without reading its message or body.

    The caller supplies the stage; neither messages nor nested causes are read.
    The pinned SDK has one Requests call with zero configured retries and zero
    followed redirects.  Only exception types that prove a boundary receive a
    narrower fixed class.  Generic Requests connection failures remain
    transport-unknown because Requests collapses DNS/TCP/TLS causes.
    """

    if stage is SpotAutomationPreviewInvocationStage.REQUEST_COMPOSITION:
        return SpotAutomationPreviewClassification(
            outcome=SpotAutomationPreviewOutcome.UNKNOWN,
            failure_class=(
                SpotAutomationPreviewFailureClass.REQUEST_COMPOSITION_FAILURE
            ),
            warning_present=False,
            rejection_code=None,
            preview_id_sha256=None,
            preview_call_count=0,
            preview_call_count_exact=True,
        )

    def classified(
        failure_class: SpotAutomationPreviewFailureClass,
        *,
        count: int | None,
        exact: bool,
    ) -> SpotAutomationPreviewClassification:
        return SpotAutomationPreviewClassification(
            outcome=SpotAutomationPreviewOutcome.UNKNOWN,
            failure_class=failure_class,
            warning_present=False,
            rejection_code=None,
            preview_id_sha256=None,
            preview_call_count=count,
            preview_call_count_exact=exact,
        )

    if isinstance(
        exception,
        (RequestsJSONDecodeError, ContentDecodingError, ChunkedEncodingError),
    ):
        return classified(
            SpotAutomationPreviewFailureClass.RESPONSE_DECODING_FAILURE,
            count=1,
            exact=True,
        )
    if isinstance(exception, ConnectTimeout):
        return classified(
            SpotAutomationPreviewFailureClass.CONNECT_TIMEOUT,
            count=0,
            exact=True,
        )
    if isinstance(exception, ReadTimeout):
        return classified(
            SpotAutomationPreviewFailureClass.READ_TIMEOUT,
            count=1,
            exact=True,
        )
    if isinstance(exception, ProxyError):
        return classified(
            SpotAutomationPreviewFailureClass.PROXY_FAILURE,
            count=0,
            exact=True,
        )
    if isinstance(exception, SSLError):
        return classified(
            SpotAutomationPreviewFailureClass.TLS_OR_CERTIFICATE_FAILURE,
            count=None,
            exact=False,
        )
    if isinstance(exception, socket.gaierror):
        return classified(
            SpotAutomationPreviewFailureClass.DNS_RESOLUTION_FAILURE,
            count=0,
            exact=True,
        )
    if isinstance(exception, ConnectionResetError):
        return classified(
            SpotAutomationPreviewFailureClass.CONNECTION_RESET,
            count=None,
            exact=False,
        )
    if isinstance(exception, ConnectionRefusedError):
        return classified(
            SpotAutomationPreviewFailureClass.TCP_CONNECTION_FAILURE,
            count=0,
            exact=True,
        )
    if isinstance(
        exception,
        (
            URLRequired,
            MissingSchema,
            InvalidSchema,
            InvalidURL,
            InvalidHeader,
            InvalidProxyURL,
        ),
    ):
        return classified(
            SpotAutomationPreviewFailureClass.REQUEST_COMPOSITION_FAILURE,
            count=0,
            exact=True,
        )
    if not isinstance(exception, (HTTPError, TooManyRedirects)):
        if isinstance(exception, (RequestsConnectionError, Timeout)):
            return unknown_spot_automation_preview_classification(
                transport_unknown=True
            )
        return classified(
            SpotAutomationPreviewFailureClass.SDK_INVOCATION_UNKNOWN,
            count=None,
            exact=False,
        )
    response = getattr(exception, "response", None)
    status_code = getattr(response, "status_code", None)
    if type(status_code) is int:
        if 300 <= status_code < 400:
            failure_class = (
                SpotAutomationPreviewFailureClass.HTTP_REDIRECT_RESPONSE
            )
        elif 400 <= status_code < 500:
            failure_class = (
                SpotAutomationPreviewFailureClass.HTTP_CLIENT_RESPONSE
            )
        elif 500 <= status_code < 600:
            failure_class = (
                SpotAutomationPreviewFailureClass.HTTP_SERVER_RESPONSE
            )
        else:
            failure_class = (
                SpotAutomationPreviewFailureClass.HTTP_RESPONSE_INVALID
            )
        return SpotAutomationPreviewClassification(
            outcome=SpotAutomationPreviewOutcome.UNKNOWN,
            failure_class=failure_class,
            warning_present=False,
            rejection_code=None,
            preview_id_sha256=None,
            preview_call_count=1,
            preview_call_count_exact=True,
        )
    return unknown_spot_automation_preview_classification(
        transport_unknown=True
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
        documented = all(item in _DOCUMENTED_ERRORS for item in errs)
        unique_errors = frozenset(errs)
        rejection_code = (
            SpotAutomationPreviewRejectionCode.MULTIPLE_DOCUMENTED
            if documented and len(unique_errors) > 1
            else _REJECTION_CODE_BY_ERROR.get(
                next(iter(unique_errors)),
                SpotAutomationPreviewRejectionCode.OTHER_DOCUMENTED,
            )
            if documented
            else None
        )
        return SpotAutomationPreviewClassification(
            outcome=SpotAutomationPreviewOutcome.REJECTED,
            failure_class=(
                SpotAutomationPreviewFailureClass.DOCUMENTED_REJECTION
                if documented
                else SpotAutomationPreviewFailureClass.UNCLASSIFIED_REJECTION
            ),
            warning_present=bool(warnings),
            rejection_code=rejection_code,
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
        rejection_code=None,
        preview_id_sha256=preview_id_sha256,
    )


__all__ = [
    "SpotAutomationPreviewClassification",
    "SpotAutomationPreviewFailureClass",
    "SpotAutomationPreviewInvocationStage",
    "SpotAutomationPreviewOutcome",
    "SpotAutomationPreviewRejectionCode",
    "classify_spot_automation_preview_exception",
    "classify_spot_automation_preview_response",
    "unknown_spot_automation_preview_classification",
]
