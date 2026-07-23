"""Operator-safe Product Catalog administration contracts.

Only allowlisted, documented, non-volatile product metadata crosses this
boundary. Raw Coinbase responses, pagination cursors, portfolio identifiers,
prices, response bodies, and exception text are never persisted or returned.
Catalog lifecycle is administrative evidence only and never grants trading
authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MAX_PRODUCT_CATALOG_PAGES = 100
PRODUCT_CATALOG_PAGE_LIMIT = 100
_PRODUCT_ID = re.compile(r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$")
_CURRENCY = re.compile(r"^[A-Z0-9]{1,32}$")
_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9 ._:/+-]{1,128}$")
_SAFE_STATUS = frozenset({"ONLINE", "OFFLINE", "DELISTED", "UNKNOWN"})


class ProductCatalogLifecycle(str, Enum):
    PENDING = "PENDING"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class OperatorProductCatalogError(ValueError):
    """Fixed-code catalog failure with no value-bearing text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProductCatalogNormalizedItem(BaseModel):
    """Allowlisted stable product metadata plus local lifecycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    product_type: Literal["SPOT", "FUTURE"]
    base_currency: str
    quote_currency: str
    base_increment: str
    quote_increment: str
    price_increment: str
    base_min_size: str
    base_max_size: str
    quote_min_size: str
    quote_max_size: str
    display_name: str
    exchange_status: Literal["ONLINE", "OFFLINE", "DELISTED", "UNKNOWN"]
    exchange_disabled: bool
    cancel_only: bool
    limit_only: bool
    post_only: bool
    view_only: bool
    lifecycle: ProductCatalogLifecycle = ProductCatalogLifecycle.PENDING


class ProductCatalogReadResult(BaseModel):
    """One complete logical no-retry catalog read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    products: list[ProductCatalogNormalizedItem]
    page_count: int = Field(ge=1, le=MAX_PRODUCT_CATALOG_PAGES)
    pagination_complete: bool


class ProductCatalogDiff(BaseModel):
    """Sanitized immutable metadata diff used to build a proposed revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: list[ProductCatalogNormalizedItem]
    added_product_ids: list[str]
    changed_product_ids: list[str]
    removed_product_ids: list[str]
    unchanged_count: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def normalize_product_catalog_item(
    raw: Mapping[str, Any],
) -> ProductCatalogNormalizedItem:
    """Reduce one documented Coinbase product to the fixed safe contract."""

    product_id = _required_text(raw, "product_id")
    if _PRODUCT_ID.fullmatch(product_id) is None:
        raise OperatorProductCatalogError(
            "product_catalog_product_id_invalid"
        )
    product_type = _required_text(raw, "product_type").upper()
    if product_type not in {"SPOT", "FUTURE"}:
        raise OperatorProductCatalogError(
            "product_catalog_product_type_invalid"
        )
    base_currency = _currency(
        raw.get("base_currency_id", raw.get("base_currency"))
    )
    quote_currency = _currency(
        raw.get("quote_currency_id", raw.get("quote_currency"))
    )
    display_name = _required_text(raw, "display_name")
    if _DISPLAY_NAME.fullmatch(display_name) is None:
        raise OperatorProductCatalogError(
            "product_catalog_display_name_invalid"
        )

    exchange_status = str(raw.get("status") or "UNKNOWN").strip().upper()
    if exchange_status not in _SAFE_STATUS:
        exchange_status = "UNKNOWN"
    is_disabled = _strict_bool(raw, "is_disabled", default=False)
    trading_disabled = _strict_bool(
        raw,
        "trading_disabled",
        default=False,
    )
    return ProductCatalogNormalizedItem(
        product_id=product_id,
        product_type=product_type,
        base_currency=base_currency,
        quote_currency=quote_currency,
        base_increment=_positive_decimal(raw, "base_increment"),
        quote_increment=_positive_decimal(raw, "quote_increment"),
        price_increment=_positive_decimal(raw, "price_increment"),
        base_min_size=_nonnegative_decimal(raw, "base_min_size"),
        base_max_size=_positive_decimal(raw, "base_max_size"),
        quote_min_size=_nonnegative_decimal(raw, "quote_min_size"),
        quote_max_size=_positive_decimal(raw, "quote_max_size"),
        display_name=display_name,
        exchange_status=exchange_status,
        exchange_disabled=is_disabled or trading_disabled,
        cancel_only=_strict_bool(raw, "cancel_only", default=False),
        limit_only=_strict_bool(raw, "limit_only", default=False),
        post_only=_strict_bool(raw, "post_only", default=False),
        view_only=_strict_bool(raw, "view_only", default=False),
    )


def build_product_catalog_diff(
    *,
    current: list[ProductCatalogNormalizedItem],
    refreshed: list[ProductCatalogNormalizedItem],
) -> ProductCatalogDiff:
    """Build a deterministic snapshot while preserving reviewed lifecycle."""

    current_by_id = _unique_products(current)
    refreshed_by_id = _unique_products(refreshed)
    snapshot: list[ProductCatalogNormalizedItem] = []
    added: list[str] = []
    changed: list[str] = []
    removed: list[str] = []
    unchanged = 0
    for product_id in sorted(refreshed_by_id):
        row = refreshed_by_id[product_id]
        previous = current_by_id.get(product_id)
        if previous is None:
            added.append(product_id)
        else:
            row = row.model_copy(update={"lifecycle": previous.lifecycle})
            if _metadata_payload(row) == _metadata_payload(previous):
                unchanged += 1
            else:
                changed.append(product_id)
        snapshot.append(row)
    for product_id in sorted(set(current_by_id) - set(refreshed_by_id)):
        removed.append(product_id)
        snapshot.append(
            current_by_id[product_id].model_copy(
                update={"lifecycle": ProductCatalogLifecycle.RETIRED}
            )
        )
    snapshot.sort(key=lambda item: item.product_id)
    snapshot_payload = [
        item.model_dump(mode="json") for item in snapshot
    ]
    diff_payload = {
        "added_product_ids": added,
        "changed_product_ids": changed,
        "removed_product_ids": removed,
        "unchanged_count": unchanged,
    }
    return ProductCatalogDiff(
        snapshot=snapshot,
        added_product_ids=added,
        changed_product_ids=changed,
        removed_product_ids=removed,
        unchanged_count=unchanged,
        snapshot_sha256=_hash_json(snapshot_payload),
        diff_sha256=_hash_json(diff_payload),
    )


def read_operator_product_catalog(
    rest_client: Any,
    *,
    on_page_call: Callable[[int, str | None], None] | None = None,
    on_page_returned: Callable[[int], None] | None = None,
) -> ProductCatalogReadResult:
    """Read each documented List Products page exactly once."""

    method = getattr(rest_client, "get_product_catalog_page", None)
    if not callable(method):
        raise OperatorProductCatalogError(
            "product_catalog_reader_unavailable"
        )
    products: dict[str, ProductCatalogNormalizedItem] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    page_count = 0
    while True:
        if page_count >= MAX_PRODUCT_CATALOG_PAGES:
            raise OperatorProductCatalogError(
                "product_catalog_page_limit_exceeded"
            )
        ordinal = page_count + 1
        cursor_sha256 = _sha256(cursor) if cursor is not None else None
        if on_page_call is not None:
            on_page_call(ordinal, cursor_sha256)
        kwargs: dict[str, Any] = {
            "limit": PRODUCT_CATALOG_PAGE_LIMIT,
            "get_tradability_status": True,
        }
        if cursor is not None:
            kwargs["cursor"] = cursor
        try:
            raw_response = method(**kwargs)
        except Exception as exc:
            raise OperatorProductCatalogError(
                "product_catalog_read_failed"
            ) from exc
        page_count += 1
        if on_page_returned is not None:
            on_page_returned(ordinal)
        response = _plain_mapping(raw_response)
        raw_rows = response.get("products")
        if not isinstance(raw_rows, list):
            raise OperatorProductCatalogError(
                "product_catalog_response_invalid"
            )
        for raw_row in raw_rows:
            row_mapping = _plain_mapping(raw_row)
            item = normalize_product_catalog_item(row_mapping)
            if item.product_id in products:
                raise OperatorProductCatalogError(
                    "product_catalog_product_duplicate"
                )
            products[item.product_id] = item
        pagination = response.get("pagination")
        if pagination is None:
            pagination_map: Mapping[str, Any] = response
        elif isinstance(pagination, Mapping):
            pagination_map = pagination
        else:
            raise OperatorProductCatalogError(
                "product_catalog_pagination_invalid"
            )
        has_next = pagination_map.get("has_next", False)
        if type(has_next) is not bool:
            raise OperatorProductCatalogError(
                "product_catalog_pagination_invalid"
            )
        if not has_next:
            break
        next_cursor = pagination_map.get(
            "next_cursor",
            pagination_map.get("cursor"),
        )
        if not isinstance(next_cursor, str) or not next_cursor:
            raise OperatorProductCatalogError(
                "product_catalog_cursor_missing"
            )
        if next_cursor in seen_cursors:
            raise OperatorProductCatalogError(
                "product_catalog_cursor_repeated"
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return ProductCatalogReadResult(
        products=[products[key] for key in sorted(products)],
        page_count=page_count,
        pagination_complete=True,
    )


def _unique_products(
    products: list[ProductCatalogNormalizedItem],
) -> dict[str, ProductCatalogNormalizedItem]:
    result: dict[str, ProductCatalogNormalizedItem] = {}
    for item in products:
        if item.product_id in result:
            raise OperatorProductCatalogError(
                "product_catalog_product_duplicate"
            )
        result[item.product_id] = item
    return result


def _metadata_payload(item: ProductCatalogNormalizedItem) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    payload.pop("lifecycle", None)
    return payload


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    raise OperatorProductCatalogError(
        "product_catalog_response_invalid"
    )


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperatorProductCatalogError(
            "product_catalog_schema_invalid"
        )
    return value.strip()


def _currency(value: Any) -> str:
    if not isinstance(value, str):
        raise OperatorProductCatalogError(
            "product_catalog_currency_invalid"
        )
    normalized = value.strip().upper()
    if _CURRENCY.fullmatch(normalized) is None:
        raise OperatorProductCatalogError(
            "product_catalog_currency_invalid"
        )
    return normalized


def _strict_bool(
    raw: Mapping[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    value = raw.get(key, default)
    if type(value) is not bool:
        raise OperatorProductCatalogError(
            "product_catalog_boolean_invalid"
        )
    return value


def _positive_decimal(raw: Mapping[str, Any], key: str) -> str:
    value = _decimal(raw.get(key))
    if value <= 0:
        raise OperatorProductCatalogError(
            "product_catalog_increment_invalid"
        )
    return _decimal_text(value)


def _nonnegative_decimal(raw: Mapping[str, Any], key: str) -> str:
    value = _decimal(raw.get(key))
    if value < 0:
        raise OperatorProductCatalogError(
            "product_catalog_decimal_invalid"
        )
    return _decimal_text(value)


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, (str, int)):
        raise OperatorProductCatalogError(
            "product_catalog_decimal_invalid"
        )
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OperatorProductCatalogError(
            "product_catalog_decimal_invalid"
        ) from exc
    if not parsed.is_finite():
        raise OperatorProductCatalogError(
            "product_catalog_decimal_invalid"
        )
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
