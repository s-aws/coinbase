"""Backend-owned Futures product-policy ticket eligibility.

The policy selection is PostgreSQL-owned and the browser cannot supply order
terms.  One refresh reads the six established Default-profile CFM categories
at most once and derives the exact one-contract candidate from documented
product, market, position, and margin evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

from requests.exceptions import (
    ConnectTimeout,
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ProxyError,
    ReadTimeout,
    SSLError,
    Timeout,
)

from core.enums import (
    AdminFuturesManualEligibilityOutcome,
)

from .futures_order_preview_r12 import (
    validate_r12_margin_collateral_evidence,
)
from .futures_order_preview import (
    slice2_preview_margin_windows_pair_policy_context,
)
from .futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)
from .operator_futures_manual_lifecycle import (
    FuturesManualEligibilityResult,
)


FUTURES_PRODUCT_TICKET_GOAL_ID = (
    "operator_futures_product_policy_and_ticket_expansion_v1"
)
FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS = (
    "AVP-20DEC30-CDE",
    "BIP-20DEC30-CDE",
)
FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "product",
    "best_bid_ask",
    "futures_positions",
    "futures_margin_collateral",
)
FUTURES_PRODUCT_TICKET_CONTRACT_COUNT = Decimal("1")
FUTURES_PRODUCT_TICKET_OPENING_CAP_USDC = Decimal("100")
FUTURES_PRODUCT_TICKET_EXPOSURE_CAP_USDC = Decimal("150")
FUTURES_PRODUCT_TICKET_TURNOVER_CAP_USDC = Decimal("300")
FUTURES_PRODUCT_TICKET_CLOSE_BUFFER = Decimal("1.20")
FUTURES_PRODUCT_TICKET_MAX_MARKET_AGE_SECONDS = 30

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENABLED = "ENABLED"
_MARGIN_VALIDATION_DIAGNOSTIC_CODES = {
    "futures_preview_margin_setting_not_exact_v3": (
        "operator_futures_product_ticket_margin_setting_not_exact_v3"
    ),
    "futures_preview_available_margin_not_positive": (
        "operator_futures_product_ticket_available_margin_not_positive"
    ),
    "futures_preview_margin_killswitch_enabled": (
        "operator_futures_product_ticket_margin_killswitch_enabled"
    ),
}
_MARGIN_VALIDATION_SCHEMA_CODES = {
    "futures_preview_margin_collateral_ambiguous": (
        "operator_futures_product_ticket_margin_envelope_schema_ambiguous"
    ),
    "futures_preview_margin_sweeps_not_authorized": (
        "operator_futures_product_ticket_margin_scope_ambiguous"
    ),
    "futures_preview_margin_source_reads_ambiguous": (
        "operator_futures_product_ticket_margin_read_accounting_ambiguous"
    ),
    "futures_preview_available_margin_currency_invalid": (
        "operator_futures_product_ticket_available_margin_schema_ambiguous"
    ),
    "futures_preview_available_margin_invalid": (
        "operator_futures_product_ticket_available_margin_schema_ambiguous"
    ),
    "futures_preview_total_usd_balance_currency_invalid": (
        "operator_futures_product_ticket_total_balance_schema_ambiguous"
    ),
    "futures_preview_total_usd_balance_invalid": (
        "operator_futures_product_ticket_total_balance_schema_ambiguous"
    ),
    "futures_preview_cfm_usd_balance_currency_invalid": (
        "operator_futures_product_ticket_cfm_balance_schema_ambiguous"
    ),
    "futures_preview_cfm_usd_balance_invalid": (
        "operator_futures_product_ticket_cfm_balance_schema_ambiguous"
    ),
    "futures_preview_futures_buying_power_currency_invalid": (
        "operator_futures_product_ticket_buying_power_schema_ambiguous"
    ),
    "futures_preview_futures_buying_power_invalid": (
        "operator_futures_product_ticket_buying_power_schema_ambiguous"
    ),
    "futures_preview_initial_margin_currency_invalid": (
        "operator_futures_product_ticket_initial_margin_schema_ambiguous"
    ),
    "futures_preview_initial_margin_invalid": (
        "operator_futures_product_ticket_initial_margin_schema_ambiguous"
    ),
    "futures_preview_liquidation_threshold_currency_invalid": (
        "operator_futures_product_ticket_liquidation_threshold_schema_ambiguous"
    ),
    "futures_preview_liquidation_threshold_invalid": (
        "operator_futures_product_ticket_liquidation_threshold_schema_ambiguous"
    ),
    "futures_preview_margin_window_measure_ambiguous": (
        "operator_futures_product_ticket_margin_window_measure_schema_ambiguous"
    ),
    "futures_preview_margin_maintenance_margin_invalid": (
        "operator_futures_product_ticket_margin_window_measure_schema_ambiguous"
    ),
    "futures_preview_margin_liquidation_buffer_invalid": (
        "operator_futures_product_ticket_margin_window_measure_schema_ambiguous"
    ),
    "futures_preview_margin_setting_ambiguous": (
        "operator_futures_product_ticket_margin_setting_schema_ambiguous"
    ),
    "futures_preview_margin_windows_ambiguous": (
        "operator_futures_product_ticket_margin_windows_schema_ambiguous"
    ),
    "futures_preview_margin_killswitch_ambiguous": (
        "operator_futures_product_ticket_margin_killswitch_schema_ambiguous"
    ),
}


@dataclass(frozen=True, slots=True)
class FuturesProductPolicySelection:
    """Exact enabled policy revision selected by the backend."""

    product_id: str
    policy_revision: int
    policy_sha256: str
    lifecycle: str


class _EligibilityReadError(Exception):
    def __init__(self, diagnostic_code: str) -> None:
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return dict(attributes)
    return {}


def _positive_decimal(value: Any, code: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(code) from None
    if not result.is_finite() or result <= 0:
        raise ValueError(code)
    return result


def _nonnegative_decimal(value: Any, code: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(code) from None
    if not result.is_finite() or result < 0:
        raise ValueError(code)
    return result


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _parse_timestamp(value: Any, code: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(code)
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _empty_attempts() -> dict[str, int]:
    return {
        category: 0
        for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES
    }


def _top_of_book(
    *,
    book: Mapping[str, Any],
    product_id: str,
    observed_at: datetime,
) -> tuple[Decimal, Decimal]:
    pricebooks = book.get("pricebooks")
    if not isinstance(pricebooks, list) or len(pricebooks) != 1:
        raise ValueError("operator_futures_product_ticket_book_invalid")
    row = _mapping(pricebooks[0])
    if row.get("product_id") != product_id:
        raise ValueError(
            "operator_futures_product_ticket_book_identity_invalid"
        )
    market_time = _parse_timestamp(
        row.get("time"),
        "operator_futures_product_ticket_market_time_invalid",
    )
    age = (
        observed_at.astimezone(timezone.utc) - market_time
    ).total_seconds()
    if (
        age < 0
        or age > FUTURES_PRODUCT_TICKET_MAX_MARKET_AGE_SECONDS
    ):
        raise ValueError("operator_futures_product_ticket_market_stale")

    def top(side: str) -> Decimal:
        levels = row.get(side)
        if not isinstance(levels, list) or not levels:
            raise ValueError(
                "operator_futures_product_ticket_book_invalid"
            )
        level = _mapping(levels[0])
        return _positive_decimal(
            level.get("price"),
            "operator_futures_product_ticket_book_invalid",
        )

    return top("bids"), top("asks")


def _position_contracts(positions: Any, product_id: str) -> Decimal:
    rows: list[Any]
    if isinstance(positions, Mapping):
        if product_id in positions:
            rows = [positions[product_id]]
        elif "positions" in positions:
            value = positions.get("positions")
            rows = list(value) if isinstance(value, list) else []
        else:
            rows = list(positions.values())
    elif isinstance(positions, Sequence) and not isinstance(
        positions,
        (str, bytes, bytearray),
    ):
        rows = list(positions)
    else:
        rows = []
    total = Decimal("0")
    for raw in rows:
        row = _mapping(raw)
        observed_product = str(
            row.get("product_id")
            or getattr(raw, "product_id", "")
            or ""
        )
        if observed_product != product_id:
            continue
        raw_count = (
            row.get("number_of_contracts")
            if "number_of_contracts" in row
            else getattr(raw, "number_of_contracts", None)
        )
        total += _nonnegative_decimal(
            raw_count,
            "operator_futures_product_ticket_position_invalid",
        )
    return total


def _margin_rate(
    details: Mapping[str, Any],
    *,
    field: str,
) -> Decimal:
    rate = _mapping(details.get(field))
    long_rate = _positive_decimal(
        rate.get("long_margin_rate"),
        "operator_futures_product_ticket_margin_rate_invalid",
    )
    short_rate = _positive_decimal(
        rate.get("short_margin_rate"),
        "operator_futures_product_ticket_margin_rate_invalid",
    )
    if long_rate > 1 or short_rate > 1:
        raise ValueError(
            "operator_futures_product_ticket_margin_rate_invalid"
        )
    return long_rate


def build_futures_product_ticket_candidate(
    *,
    selection: FuturesProductPolicySelection,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    available_margin_usdc: Any,
    observed_at: datetime,
) -> dict[str, str]:
    """Derive one immutable one-contract BUY candidate from current evidence."""

    if (
        selection.lifecycle != _ENABLED
        or selection.product_id
        not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
        or selection.policy_revision < 1
        or _SHA256_RE.fullmatch(selection.policy_sha256) is None
    ):
        raise ValueError(
            "operator_futures_product_ticket_selection_not_enabled"
        )
    product_id = selection.product_id
    if (
        str(product.get("product_id") or "") != product_id
        or str(product.get("product_type") or "").upper() != "FUTURE"
        or str(product.get("status") or "").upper()
        not in {"", "ONLINE"}
        or any(
            product.get(field) is not False
            for field in ("trading_disabled", "view_only", "cancel_only")
        )
    ):
        raise ValueError(
            "operator_futures_product_ticket_product_untradable"
        )
    session = _mapping(product.get("fcm_trading_session_details"))
    if (
        session.get("is_session_open") is not True
        or session.get("after_hours_order_entry_disabled")
        not in {True, False}
    ):
        raise ValueError(
            "operator_futures_product_ticket_session_ineligible"
        )
    details = _mapping(product.get("future_product_details"))
    contract_code = str(details.get("contract_code") or "").strip().upper()
    if (
        contract_code != product_id.split("-", 1)[0]
        or str(details.get("venue") or "").strip().lower() != "cde"
        or str(details.get("risk_managed_by") or "").strip().upper()
        != "MANAGED_BY_FCM"
    ):
        raise ValueError(
            "operator_futures_product_ticket_cfm_identity_invalid"
        )
    expiry = _parse_timestamp(
        details.get("contract_expiry"),
        "operator_futures_product_ticket_expiry_invalid",
    )
    if expiry <= observed_at.astimezone(timezone.utc):
        raise ValueError(
            "operator_futures_product_ticket_contract_expired"
        )
    expiry_type = str(
        details.get("contract_expiry_type") or ""
    ).strip().upper()
    if expiry_type not in {"EXPIRING", "PERPETUAL"}:
        raise ValueError(
            "operator_futures_product_ticket_expiry_type_invalid"
        )

    contract_size = _positive_decimal(
        details.get("contract_size"),
        "operator_futures_product_ticket_contract_size_invalid",
    )
    product_price = _positive_decimal(
        product.get("price"),
        "operator_futures_product_ticket_product_price_invalid",
    )
    price_increment = _positive_decimal(
        product.get("price_increment"),
        "operator_futures_product_ticket_price_increment_invalid",
    )
    base_increment = _positive_decimal(
        product.get("base_increment"),
        "operator_futures_product_ticket_base_increment_invalid",
    )
    base_min_size = _nonnegative_decimal(
        product.get("base_min_size"),
        "operator_futures_product_ticket_base_minimum_invalid",
    )
    if (
        FUTURES_PRODUCT_TICKET_CONTRACT_COUNT < base_min_size
        or FUTURES_PRODUCT_TICKET_CONTRACT_COUNT % base_increment != 0
    ):
        raise ValueError(
            "operator_futures_product_ticket_one_contract_invalid"
        )
    intraday_rate = _margin_rate(
        details,
        field="intraday_margin_rate",
    )
    overnight_rate = _margin_rate(
        details,
        field="overnight_margin_rate",
    )
    worst_case_margin_rate = max(intraday_rate, overnight_rate)

    best_bid, best_ask = _top_of_book(
        book=book,
        product_id=product_id,
        observed_at=observed_at,
    )
    if best_bid >= best_ask or best_bid % price_increment != 0:
        raise ValueError(
            "operator_futures_product_ticket_book_invalid"
        )
    limit_price = best_bid - price_increment
    if limit_price <= 0 or limit_price % price_increment != 0:
        raise ValueError(
            "operator_futures_product_ticket_limit_price_invalid"
        )
    if _position_contracts(positions, product_id) != 0:
        raise ValueError(
            "operator_futures_product_ticket_existing_exposure"
        )

    reference_price = max(product_price, best_ask)
    opening = (
        reference_price
        * contract_size
        * FUTURES_PRODUCT_TICKET_CONTRACT_COUNT
    )
    exposure = opening
    buffered_close = exposure * FUTURES_PRODUCT_TICKET_CLOSE_BUFFER
    turnover = opening + buffered_close
    required_margin = opening * worst_case_margin_rate
    available_margin = _positive_decimal(
        available_margin_usdc,
        "operator_futures_product_ticket_available_margin_invalid",
    )
    if (
        opening >= FUTURES_PRODUCT_TICKET_OPENING_CAP_USDC
        or exposure >= FUTURES_PRODUCT_TICKET_EXPOSURE_CAP_USDC
        or buffered_close >= FUTURES_PRODUCT_TICKET_EXPOSURE_CAP_USDC
        or turnover >= FUTURES_PRODUCT_TICKET_TURNOVER_CAP_USDC
    ):
        raise ValueError("operator_futures_product_ticket_cap_ineligible")
    if available_margin < required_margin:
        raise ValueError(
            "operator_futures_product_ticket_margin_insufficient"
        )

    return {
        "product_id": product_id,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "contract_code": contract_code,
        "contract_size": _decimal_text(contract_size),
        "contract_expiry": _timestamp(expiry),
        "contract_expiry_type": expiry_type,
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "product_price": _decimal_text(product_price),
        "reference_price": _decimal_text(reference_price),
        "reference_price_source": (
            "max_product_price_and_fresh_best_ask"
        ),
        "price_increment": _decimal_text(price_increment),
        "base_increment": _decimal_text(base_increment),
        "base_min_size": _decimal_text(base_min_size),
        "best_bid": _decimal_text(best_bid),
        "best_ask": _decimal_text(best_ask),
        "limit_price": _decimal_text(limit_price),
        "intraday_margin_rate": _decimal_text(intraday_rate),
        "overnight_margin_rate": _decimal_text(overnight_rate),
        "worst_case_margin_rate": _decimal_text(
            worst_case_margin_rate
        ),
        "required_margin_reference_usdc": _money_text(
            required_margin
        ),
        "opening_reference_notional_usdc": _money_text(opening),
        "maximum_exposure_reference_notional_usdc": _money_text(
            exposure
        ),
        "buffered_close_reference_notional_usdc": _money_text(
            buffered_close
        ),
        "branch_turnover_reference_notional_usdc": _money_text(turnover),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "product_policy_revision": str(selection.policy_revision),
        "product_policy_sha256": selection.policy_sha256,
        "observed_at": _timestamp(observed_at),
    }


def _read_diagnostic(category: str, exc: Exception) -> str:
    prefix = f"operator_futures_product_ticket_{category}"
    if isinstance(exc, HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 401:
            suffix = "http_unauthorized"
        elif status_code == 403:
            suffix = "http_forbidden"
        elif status_code == 404:
            suffix = "http_not_found"
        elif status_code == 429:
            suffix = "http_rate_limited"
        elif (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 400 <= status_code < 500
        ):
            suffix = "http_client_error"
        elif (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 500 <= status_code < 600
        ):
            suffix = "http_server_error"
        else:
            suffix = "http_unclassified"
    elif isinstance(exc, ConnectTimeout):
        suffix = "connect_timeout"
    elif isinstance(exc, ReadTimeout):
        suffix = "read_timeout"
    elif isinstance(exc, SSLError):
        suffix = "tls_failure"
    elif isinstance(exc, ProxyError):
        suffix = "proxy_failure"
    elif isinstance(exc, RequestsConnectionError):
        suffix = "connection_failure"
    elif isinstance(exc, Timeout):
        suffix = "timeout"
    elif isinstance(exc, (KeyError, TypeError, ValueError)):
        suffix = "schema_invalid"
    else:
        suffix = "read_unknown"
    return f"{prefix}_{suffix}"


def _margin_window_policy_diagnostic(value: Any) -> str:
    try:
        context = slice2_preview_margin_windows_pair_policy_context(
            value
        )
        evidence = _mapping(
            context.get("margin_windows_policy_evidence")
        )
    except Exception:
        return (
            "operator_futures_product_ticket_"
            "margin_windows_schema_ambiguous"
        )
    classification = evidence.get("classification")
    if (
        classification
        == "margin_window_type_documented_but_operator_rejected"
    ):
        return (
            "operator_futures_product_ticket_"
            "margin_window_documented_but_v3_ineligible"
        )
    return (
        "operator_futures_product_ticket_"
        "margin_windows_schema_ambiguous"
    )


def _margin_validation_diagnostic(
    exc: Exception,
    value: Any,
) -> str:
    """Return only allowlisted, value-blind margin boundary evidence."""

    code = (
        str(exc.args[0])
        if isinstance(exc, ValueError)
        and len(exc.args) == 1
        and isinstance(exc.args[0], str)
        else ""
    )
    if code in _MARGIN_VALIDATION_DIAGNOSTIC_CODES:
        return _MARGIN_VALIDATION_DIAGNOSTIC_CODES[code]
    if code == "futures_preview_margin_windows_ambiguous":
        return _margin_window_policy_diagnostic(value)
    if code in _MARGIN_VALIDATION_SCHEMA_CODES:
        return _MARGIN_VALIDATION_SCHEMA_CODES[code]
    return "operator_futures_product_ticket_margin_ineligible"


def _blocked_result(
    *,
    selection: FuturesProductPolicySelection | None,
    outcome: AdminFuturesManualEligibilityOutcome,
    diagnostic_code: str,
    attempts: Mapping[str, int],
) -> FuturesManualEligibilityResult:
    public = {
        "goal_id": FUTURES_PRODUCT_TICKET_GOAL_ID,
        "profile_alias": "Default",
        "product_id": (
            selection.product_id if selection is not None else None
        ),
        "contract_count": "1",
        "product_policy_revision": (
            selection.policy_revision if selection is not None else None
        ),
        "product_policy_sha256": (
            selection.policy_sha256 if selection is not None else None
        ),
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "exact_v3_eligible": False,
        "diagnostic_code": diagnostic_code,
        "category_attempts": dict(attempts),
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    return FuturesManualEligibilityResult(
        outcome=outcome,
        diagnostic_code=diagnostic_code,
        category_attempts=dict(attempts),
        candidate=None,
        portfolio_id_sha256=None,
        evidence_sha256=_canonical_sha256(public),
        public_evidence=public,
    )


class FuturesProductTicketEligibilityReader:
    """Read exactly one selected enabled product through the Default profile."""

    def __init__(
        self,
        *,
        rest_client: Any,
        selection_reader: Callable[[], FuturesProductPolicySelection],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.selection_reader = selection_reader
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        before_category: Callable[[str], None],
    ) -> FuturesManualEligibilityResult:
        attempts = _empty_attempts()
        try:
            selection = self.selection_reader()
        except Exception:
            return _blocked_result(
                selection=None,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_product_ticket_selection_unavailable"
                ),
                attempts=attempts,
            )
        if (
            selection.lifecycle != _ENABLED
            or selection.product_id
            not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
            or selection.policy_revision < 1
            or _SHA256_RE.fullmatch(selection.policy_sha256) is None
        ):
            return _blocked_result(
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_product_ticket_selection_not_enabled"
                ),
                attempts=attempts,
            )

        def read(category: str, call: Callable[[], Any]) -> Any:
            if attempts[category] != 0:
                raise RuntimeError(
                    "operator_futures_product_ticket_duplicate_category_read"
                )
            try:
                before_category(category)
                attempts[category] = 1
                return call()
            except Exception as exc:
                raise _EligibilityReadError(
                    _read_diagnostic(category, exc)
                ) from None

        try:
            permissions = read(
                "api_key_permissions",
                self.rest_client.get_api_key_permissions,
            )
            portfolios = read(
                "portfolio_catalog",
                self.rest_client
                .get_futures_preview_eligibility_portfolios,
            )
            product = read(
                "product",
                lambda: self.rest_client
                .get_futures_manual_eligibility_product(
                    selection.product_id
                ),
            )
            book = read(
                "best_bid_ask",
                lambda: self.rest_client.get_best_bid_ask(
                    product_ids=[selection.product_id]
                ),
            )
            observed_at = self.now()
            positions = read(
                "futures_positions",
                self.rest_client.get_futures_positions,
            )
            margin = read(
                "futures_margin_collateral",
                self.rest_client
                .get_futures_manual_eligibility_margin_collateral_snapshot,
            )
        except _EligibilityReadError as exc:
            return _blocked_result(
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
                diagnostic_code=exc.diagnostic_code,
                attempts=attempts,
            )

        try:
            binding = evaluate_futures_default_portfolio_binding(
                permissions=permissions,
                portfolios=portfolios,
                observed_at=_timestamp(observed_at),
                permissions_read=True,
                portfolio_catalog_read=True,
            )
            if (
                not binding.read_ready
                or binding.can_view is not True
                or binding.can_trade is not True
                or not binding.observed_portfolio_id
            ):
                raise ValueError("portfolio_ineligible")
        except Exception:
            return _blocked_result(
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_product_ticket_portfolio_ineligible"
                ),
                attempts=attempts,
            )
        try:
            available_margin = validate_r12_margin_collateral_evidence(
                margin
            )
        except Exception as exc:
            return _blocked_result(
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=_margin_validation_diagnostic(
                    exc,
                    margin,
                ),
                attempts=attempts,
            )
        try:
            candidate = build_futures_product_ticket_candidate(
                selection=selection,
                product=product if isinstance(product, Mapping) else {},
                book=book if isinstance(book, Mapping) else {},
                positions=positions,
                available_margin_usdc=available_margin,
                observed_at=observed_at,
            )
        except ValueError as exc:
            code = str(exc.args[0]) if len(exc.args) == 1 else ""
            if not code.startswith("operator_futures_product_ticket_"):
                code = (
                    "operator_futures_product_ticket_product_or_market_"
                    "ineligible"
                )
            return _blocked_result(
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=code,
                attempts=attempts,
            )

        portfolio_hash = _sha256_text(binding.observed_portfolio_id)
        public = {
            "goal_id": FUTURES_PRODUCT_TICKET_GOAL_ID,
            "profile_alias": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id_sha256": portfolio_hash,
            "credential_can_view": True,
            "credential_can_trade": True,
            "selection_authority": (
                "backend_enabled_futures_product_policy"
            ),
            "product_id": selection.product_id,
            "contract_count": "1",
            "product_policy_revision": selection.policy_revision,
            "product_policy_sha256": selection.policy_sha256,
            "caps": {
                "opening_usdc": "100",
                "exposure_usdc": "150",
                "turnover_usdc": "300",
                "comparison": "strictly_less_than",
            },
            "candidate": dict(candidate),
            "exact_v3_eligible": True,
            "diagnostic_code": (
                "operator_futures_product_ticket_eligible"
            ),
            "category_attempts": dict(attempts),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesManualEligibilityResult(
            outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
            diagnostic_code=(
                "operator_futures_product_ticket_eligible"
            ),
            category_attempts=dict(attempts),
            candidate=dict(candidate),
            portfolio_id_sha256=portfolio_hash,
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
        )


def validate_futures_product_ticket_eligibility_evidence(
    result: FuturesManualEligibilityResult,
) -> None:
    """Validate the Goal 3 eligible result before durable persistence."""

    public = result.public_evidence
    candidate = result.candidate
    if result.outcome is not AdminFuturesManualEligibilityOutcome.ELIGIBLE:
        return
    policy_revision = public.get("product_policy_revision")
    if (
        candidate is None
        or public.get("goal_id") != FUTURES_PRODUCT_TICKET_GOAL_ID
        or public.get("profile_alias") != "Default"
        or public.get("portfolio_type") != "DEFAULT"
        or public.get("portfolio_id_sha256")
        != result.portfolio_id_sha256
        or public.get("credential_can_view") is not True
        or public.get("credential_can_trade") is not True
        or public.get("selection_authority")
        != "backend_enabled_futures_product_policy"
        or public.get("product_id")
        not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
        or public.get("contract_count") != "1"
        or not isinstance(policy_revision, int)
        or isinstance(policy_revision, bool)
        or policy_revision < 1
        or _SHA256_RE.fullmatch(
            str(public.get("product_policy_sha256") or "")
        )
        is None
        or public.get("caps")
        != {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        }
        or public.get("exact_v3_eligible") is not True
        or public.get("diagnostic_code")
        != "operator_futures_product_ticket_eligible"
        or public.get("candidate") != candidate
        or candidate.get("product_id") != public.get("product_id")
        or candidate.get("contract_count") != "1"
        or candidate.get("product_policy_revision")
        != str(policy_revision)
        or candidate.get("product_policy_sha256")
        != public.get("product_policy_sha256")
    ):
        raise ValueError(
            "operator_futures_product_ticket_eligible_evidence_invalid"
        )


__all__ = [
    "FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS",
    "FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES",
    "FUTURES_PRODUCT_TICKET_GOAL_ID",
    "FuturesProductPolicySelection",
    "FuturesProductTicketEligibilityReader",
    "build_futures_product_ticket_candidate",
    "validate_futures_product_ticket_eligibility_evidence",
]
