"""Default-profile Futures order catalog and exact-order policy primitives.

The catalog reader performs only explicitly claimed, no-retry Coinbase reads.
It returns sanitized projections keyed by ``client_order_id`` and keeps raw
exchange identifiers in a repr-hidden, process-local mapping for an immediate
exact reconciliation or cancellation decision.  No raw response, cursor, or
exchange identifier belongs in durable or public evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Literal

from requests.exceptions import (
    ConnectTimeout,
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ProxyError,
    ReadTimeout,
    SSLError,
    Timeout,
)

from .futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)


FUTURES_ORDER_OPERATIONS_GOAL_ID = (
    "operator_futures_order_inventory_detail_cancel_reconcile_v1"
)
FUTURES_ORDER_OPERATIONS_MAX_CYCLES = 10
FUTURES_ORDER_OPERATIONS_PAGE_LIMIT = 100
FUTURES_ORDER_OPERATIONS_MAX_PAGES_PER_CYCLE = 100
FUTURES_ORDER_OPERATIONS_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "futures_order_catalog",
)
FUTURES_ORDER_TERMINAL_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)
FUTURES_ORDER_NONTERMINAL_STATUSES = frozenset(
    {"PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"}
)
FUTURES_ORDER_STATUSES = (
    FUTURES_ORDER_TERMINAL_STATUSES
    | FUTURES_ORDER_NONTERMINAL_STATUSES
    | {"UNKNOWN_ORDER_STATUS"}
)
FUTURES_ORDER_TYPES = frozenset(
    {
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "BRACKET",
        "TWAP",
        "ROLL_OPEN",
        "ROLL_CLOSE",
        "LIQUIDATION",
        "SCALED",
        "UNKNOWN_ORDER_TYPE",
    }
)
FUTURES_TIME_IN_FORCES = frozenset(
    {
        "GOOD_UNTIL_DATE_TIME",
        "GOOD_UNTIL_CANCELLED",
        "IMMEDIATE_OR_CANCEL",
        "FILL_OR_KILL",
        "UNKNOWN_TIME_IN_FORCE",
    }
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _sdk_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        try:
            converted = converter()
        except Exception:
            return None
        return dict(converted) if isinstance(converted, Mapping) else None
    attributes = getattr(value, "__dict__", None)
    return dict(attributes) if isinstance(attributes, Mapping) else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _iso_timestamp(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number, "f")


def _order_configuration_values(order: Mapping[str, Any]) -> tuple[str | None, str | None]:
    configuration = order.get("order_configuration")
    if not isinstance(configuration, Mapping) or len(configuration) != 1:
        return None, None
    body = next(iter(configuration.values()))
    if not isinstance(body, Mapping):
        return None, None
    size = _decimal_text(body.get("base_size") or body.get("quote_size"))
    price = _decimal_text(body.get("limit_price"))
    return size, price


@dataclass(frozen=True, slots=True)
class FuturesOrderObservation:
    client_order_id: str
    product_id: str
    side: Literal["BUY", "SELL"]
    status: str
    order_type: str
    time_in_force: str
    size: str | None
    limit_price: str | None
    filled_size: str | None
    created_at: str | None
    updated_at: str | None
    exchange_order_id_sha256: str
    authoritatively_nonterminal: bool
    cancel_eligible: bool

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "product_id": self.product_id,
            "side": self.side,
            "status": self.status,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "size": self.size,
            "limit_price": self.limit_price,
            "filled_size": self.filled_size,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "exchange_order_id_sha256": self.exchange_order_id_sha256,
            "authoritatively_nonterminal": self.authoritatively_nonterminal,
            "cancel_eligible": self.cancel_eligible,
        }


@dataclass(frozen=True, slots=True)
class FuturesOrderCatalogResult:
    outcome: Literal["SUCCEEDED", "INELIGIBLE", "UNKNOWN"]
    diagnostic_code: str
    category_attempts: dict[str, int]
    page_count: int
    orders: tuple[FuturesOrderObservation, ...]
    credential_can_trade: bool
    portfolio_id_sha256: str | None
    evidence_sha256: str
    public_evidence: dict[str, Any]
    private_exchange_order_ids: dict[str, str] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )


class _CatalogReadError(RuntimeError):
    def __init__(self, diagnostic_code: str) -> None:
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code)


def _catalog_schema_error(boundary: str) -> _CatalogReadError:
    return _CatalogReadError(
        "operator_futures_orders_futures_order_catalog_" + boundary
    )


def _read_diagnostic(category: str, exc: Exception) -> str:
    prefix = f"operator_futures_orders_{category}"
    if isinstance(exc, HTTPError):
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 401:
            suffix = "http_unauthorized"
        elif status_code == 403:
            suffix = "http_forbidden"
        elif status_code == 404:
            suffix = "http_not_found"
        elif status_code == 429:
            suffix = "http_rate_limited"
        elif isinstance(status_code, int) and 400 <= status_code < 500:
            suffix = "http_client_error"
        elif isinstance(status_code, int) and 500 <= status_code < 600:
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


def _blocked_result(
    *,
    outcome: Literal["INELIGIBLE", "UNKNOWN"],
    diagnostic_code: str,
    attempts: Mapping[str, int],
    page_count: int,
) -> FuturesOrderCatalogResult:
    public = {
        "goal_id": FUTURES_ORDER_OPERATIONS_GOAL_ID,
        "profile_alias": "Default",
        "portfolio_type": "DEFAULT",
        "product_type": "FUTURE",
        "outcome": outcome,
        "diagnostic_code": diagnostic_code,
        "category_attempts": dict(attempts),
        "page_count": page_count,
        "order_count": 0,
        "orders": [],
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    return FuturesOrderCatalogResult(
        outcome=outcome,
        diagnostic_code=diagnostic_code,
        category_attempts=dict(attempts),
        page_count=page_count,
        orders=(),
        credential_can_trade=False,
        portfolio_id_sha256=None,
        evidence_sha256=_canonical_sha256(public),
        public_evidence=public,
    )


def _normalize_order(value: Any) -> tuple[FuturesOrderObservation, str]:
    order = _sdk_mapping(value)
    if order is None:
        raise _catalog_schema_error("order_mapping_invalid")
    exchange_order_id = _text(order.get("order_id"))
    client_order_id = _text(order.get("client_order_id"))
    product_id = _text(order.get("product_id"))
    side = _text(order.get("side")).upper()
    status = _text(order.get("status")).upper()
    order_type = _text(order.get("order_type")).upper() or "UNKNOWN_ORDER_TYPE"
    time_in_force = (
        _text(order.get("time_in_force")).upper() or "UNKNOWN_TIME_IN_FORCE"
    )
    if not exchange_order_id:
        raise _catalog_schema_error("exchange_identity_missing")
    if not client_order_id:
        raise _catalog_schema_error("client_identity_missing")
    if len(client_order_id) > 128:
        raise _catalog_schema_error("client_identity_too_long")
    if not product_id:
        raise _catalog_schema_error("product_identity_missing")
    if len(product_id) > 128:
        raise _catalog_schema_error("product_identity_too_long")
    if side not in {"BUY", "SELL"}:
        raise _catalog_schema_error("side_invalid")
    if status not in FUTURES_ORDER_STATUSES:
        raise _catalog_schema_error("status_invalid")
    if order_type not in FUTURES_ORDER_TYPES:
        raise _catalog_schema_error("order_type_invalid")
    if time_in_force not in FUTURES_TIME_IN_FORCES:
        raise _catalog_schema_error("time_in_force_invalid")
    size, limit_price = _order_configuration_values(order)
    size = size or _decimal_text(order.get("base_size") or order.get("size"))
    limit_price = limit_price or _decimal_text(
        order.get("limit_price") or order.get("price")
    )
    created_at = _iso_timestamp(order.get("created_time") or order.get("created_at"))
    updated_at = _iso_timestamp(
        order.get("last_update_time") or order.get("updated_at")
    )
    exchange_hash = _sha256_text(exchange_order_id)
    return (
        FuturesOrderObservation(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,  # type: ignore[arg-type]
            status=status,
            order_type=order_type,
            time_in_force=time_in_force,
            size=size,
            limit_price=limit_price,
            filled_size=_decimal_text(order.get("filled_size")),
            created_at=created_at,
            updated_at=updated_at,
            exchange_order_id_sha256=exchange_hash,
            authoritatively_nonterminal=(
                status in FUTURES_ORDER_NONTERMINAL_STATUSES
            ),
            cancel_eligible=(status == "OPEN"),
        ),
        exchange_order_id,
    )


class FuturesOrderCatalogReader:
    """Run one claimed Default-profile logical Futures order catalog read."""

    def __init__(
        self,
        *,
        rest_client: Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        before_category: Callable[[str], None],
        before_page: Callable[[int, str | None], None],
        after_page: Callable[[int], None] | None = None,
    ) -> FuturesOrderCatalogResult:
        attempts = {
            category: 0 for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
        }
        page_count = 0

        def read(category: str, call: Callable[[], Any]) -> Any:
            if attempts[category] != 0:
                raise _CatalogReadError(
                    "operator_futures_orders_duplicate_category_read"
                )
            try:
                before_category(category)
                attempts[category] = 1
                return call()
            except Exception as exc:
                raise _CatalogReadError(
                    _read_diagnostic(category, exc)
                ) from None

        try:
            permissions = read(
                "api_key_permissions",
                self.rest_client.get_api_key_permissions,
            )
            portfolios = read(
                "portfolio_catalog",
                self.rest_client.get_futures_preview_eligibility_portfolios,
            )
        except _CatalogReadError as exc:
            return _blocked_result(
                outcome="UNKNOWN",
                diagnostic_code=exc.diagnostic_code,
                attempts=attempts,
                page_count=page_count,
            )

        observed_at = self.now()
        try:
            binding = evaluate_futures_default_portfolio_binding(
                permissions=permissions,
                portfolios=portfolios,
                observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                permissions_read=True,
                portfolio_catalog_read=True,
            )
            if (
                not binding.read_ready
                or binding.can_view is not True
                or not binding.observed_portfolio_id
            ):
                raise ValueError("default_profile_ineligible")
        except Exception:
            return _blocked_result(
                outcome="INELIGIBLE",
                diagnostic_code=(
                    "operator_futures_orders_default_profile_ineligible"
                ),
                attempts=attempts,
                page_count=page_count,
            )

        try:
            before_category("futures_order_catalog")
            attempts["futures_order_catalog"] = 1
            cursor: str | None = None
            seen_cursor_hashes: set[str] = set()
            seen_orders: dict[str, FuturesOrderObservation] = {}
            private_ids: dict[str, str] = {}
            while True:
                if page_count >= FUTURES_ORDER_OPERATIONS_MAX_PAGES_PER_CYCLE:
                    raise _catalog_schema_error("page_limit_exceeded")
                page_count += 1
                cursor_hash = _sha256_text(cursor) if cursor else None
                if cursor_hash and cursor_hash in seen_cursor_hashes:
                    raise _catalog_schema_error("pagination_cursor_loop")
                if cursor_hash:
                    seen_cursor_hashes.add(cursor_hash)
                response = self.rest_client.list_orders(
                    product_type="FUTURE",
                    limit=FUTURES_ORDER_OPERATIONS_PAGE_LIMIT,
                    cursor=cursor,
                    retail_portfolio_id=None,
                    before_sdk_call=lambda ordinal=page_count, hashed=cursor_hash: (
                        before_page(ordinal, hashed)
                    ),
                )
                if after_page is not None:
                    after_page(page_count)
                page = _sdk_mapping(response)
                if page is None:
                    raise _catalog_schema_error("response_envelope_invalid")
                raw_orders = page.get("orders")
                if not isinstance(raw_orders, Sequence) or isinstance(
                    raw_orders, (str, bytes, bytearray)
                ):
                    raise _catalog_schema_error("orders_collection_invalid")
                for raw_order in raw_orders:
                    observation, exchange_order_id = _normalize_order(raw_order)
                    if binding.can_trade is not True:
                        observation = replace(
                            observation,
                            cancel_eligible=False,
                        )
                    previous = seen_orders.get(observation.client_order_id)
                    if (
                        previous is not None
                        and (
                            previous != observation
                            or private_ids.get(observation.client_order_id)
                            != exchange_order_id
                        )
                    ):
                        raise _CatalogReadError(
                            "operator_futures_orders_catalog_identity_ambiguous"
                        )
                    seen_orders[observation.client_order_id] = observation
                    private_ids[observation.client_order_id] = exchange_order_id
                has_next = page.get("has_next")
                if has_next is False:
                    break
                if has_next is not True:
                    raise _catalog_schema_error(
                        "pagination_has_next_invalid"
                    )
                next_cursor = _text(page.get("cursor"))
                if not next_cursor:
                    raise _catalog_schema_error(
                        "pagination_cursor_missing"
                    )
                cursor = next_cursor
        except _CatalogReadError as exc:
            return _blocked_result(
                outcome="UNKNOWN",
                diagnostic_code=exc.diagnostic_code,
                attempts=attempts,
                page_count=page_count,
            )
        except Exception as exc:
            return _blocked_result(
                outcome="UNKNOWN",
                diagnostic_code=_read_diagnostic(
                    "futures_order_catalog", exc
                ),
                attempts=attempts,
                page_count=page_count,
            )

        ordered = tuple(
            sorted(
                seen_orders.values(),
                key=lambda item: (
                    item.updated_at or "",
                    item.created_at or "",
                    item.client_order_id,
                ),
                reverse=True,
            )
        )
        portfolio_hash = _sha256_text(binding.observed_portfolio_id)
        public = {
            "goal_id": FUTURES_ORDER_OPERATIONS_GOAL_ID,
            "profile_alias": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id_sha256": portfolio_hash,
            "credential_can_view": True,
            "credential_can_trade": binding.can_trade is True,
            "selection_authority": "cdp_api_key_permissioned_portfolio",
            "product_type": "FUTURE",
            "outcome": "SUCCEEDED",
            "diagnostic_code": "operator_futures_orders_catalog_refreshed",
            "category_attempts": dict(attempts),
            "page_count": page_count,
            "order_count": len(ordered),
            "orders": [order.to_public_dict() for order in ordered],
            "observed_at": observed_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesOrderCatalogResult(
            outcome="SUCCEEDED",
            diagnostic_code="operator_futures_orders_catalog_refreshed",
            category_attempts=dict(attempts),
            page_count=page_count,
            orders=ordered,
            credential_can_trade=(binding.can_trade is True),
            portfolio_id_sha256=portfolio_hash,
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
            private_exchange_order_ids=private_ids,
        )


__all__ = [
    "FUTURES_ORDER_NONTERMINAL_STATUSES",
    "FUTURES_ORDER_OPERATIONS_CATEGORIES",
    "FUTURES_ORDER_OPERATIONS_GOAL_ID",
    "FUTURES_ORDER_OPERATIONS_MAX_CYCLES",
    "FUTURES_ORDER_TERMINAL_STATUSES",
    "FuturesOrderCatalogReader",
    "FuturesOrderCatalogResult",
    "FuturesOrderObservation",
]
