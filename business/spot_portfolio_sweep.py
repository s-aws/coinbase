"""USDC spot portfolio sweep planning, execution, status, and P/L snapshots.

The module keeps one code path for dry-run planning and live sweep execution.
Live placement must pass the same product, wallet, safety, and action-condition
checks used by planning before any Coinbase order is submitted.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from core.coinbase_execution_authority import require_coinbase_execution_authority
from core.enums import (
    ActionGuardPhase,
    EventSourceChannel,
    EventStreamType,
    InventoryAuthorityStatus,
    InventoryCostBasisStatus,
    InventoryLotSource,
    OrderStatus,
    OrderSide,
    ProductType,
    SpotAuditRecordType,
    SpotCostBasisSource,
    SpotCostBasisStatus,
    SpotInventoryBaselineFreshness,
    SpotInventoryCoverageStatus,
    SpotPortfolioPnlScope,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepItemStatus,
    SpotPortfolioSweepOrderType,
    SpotPortfolioSweepReconciliationStatus,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
    SpotPortfolioSweepSkipReason,
    SpotSweepFillLedgerMatchStatus,
    SpotSweepRecoveryGateStatus,
)


QUOTE_CURRENCY = "USDC"
DEFAULT_INVENTORY_BASELINE_MAX_AGE_SECONDS = 24 * 60 * 60
DEFAULT_COINBASE_AVERAGE_COST_AUTHORITY_MAX_AGE_SECONDS = 5 * 60
BASELINE_FRESHNESS_TIMESTAMP_FIELDS = (
    "source_updated_at",
    "updated_at",
    "generated_at",
    "observed_at",
    "as_of",
    "snapshot_at",
    "refreshed_at",
)
DISQUALIFYING_PRODUCT_FLAGS = (
    "trading_disabled",
    "is_disabled",
    "cancel_only",
    "limit_only",
    "post_only",
    "view_only",
    "auction_mode",
)
_EXCHANGE_ORDER_STATUSES = {
    "CANCELLED",
    "CANCEL_QUEUED",
    "EXPIRED",
    "FAILED",
    "FILLED",
    "OPEN",
    "PENDING",
    "REJECTED",
}


def _value_blind_exception_detail(exc: BaseException) -> str:
    """Classify an exception without returning exception-carried values."""

    return f"exception_class:{type(exc).__name__}"


def _sanitized_exchange_status(value: Any) -> str | None:
    status = str(value or "").strip().upper()
    if not status:
        return None
    if status in _EXCHANGE_ORDER_STATUSES:
        return status
    return "UNKNOWN"


def _sanitized_action_guard_failure(
    failure: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(failure, Mapping):
        return None
    evidence = dict(failure)
    reason = str(evidence.get("reason") or "").strip()
    if " failed:" in reason or "exception_class:" in reason:
        category = str(
            evidence.get("block_category")
            or evidence.get("condition")
            or "action_condition"
        ).strip()
        evidence["reason"] = f"{category}_check_failed"
    return evidence


def _get_value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _text(value: Any) -> str:
    value = _enum_value(value)
    if value is None:
        return ""
    return str(value).strip()


def _decimal(value: Any, default: str = "0") -> Decimal:
    value = _enum_value(value)
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        return str(value)
    if value == 0:
        return "0"
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def _quantize_up(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    rounded_down = _quantize_down(value, increment)
    if rounded_down == value:
        return value
    return rounded_down + increment


def _is_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _product_id(product: Any) -> str:
    return _text(_get_value(product, "product_id"))


def _base_currency(product: Any) -> str:
    base = _text(_get_value(product, "base_currency_id", "base_currency"))
    if base:
        return base.upper()
    product_id = _product_id(product)
    if "-" in product_id:
        return product_id.rsplit("-", 1)[0].upper()
    return ""


def _quote_currency(product: Any) -> str:
    quote = _text(_get_value(product, "quote_currency_id", "quote_currency"))
    if quote:
        return quote.upper()
    product_id = _product_id(product)
    if "-" in product_id:
        return product_id.rsplit("-", 1)[1].upper()
    return ""


def _wallet_available(wallets: Mapping[str, Any] | None, currency: str) -> Decimal:
    if not wallets:
        return Decimal("0")
    wallet = wallets.get(currency) or wallets.get(currency.upper())
    if wallet is None:
        return Decimal("0")
    balance = _get_value(wallet, "available_balance", default=wallet)
    return _decimal(balance)


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _timestamp_key(value: Any) -> float:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        if not text:
            return 0.0
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def is_usdc_spot_product_eligible(product: Any) -> bool:
    """Return True when product metadata is eligible for a USDC spot sweep."""
    product_id = _product_id(product)
    if not product_id:
        return False
    product_type = _text(_get_value(product, "product_type", "type")).upper()
    if product_type != ProductType.SPOT.value:
        return False
    base_currency = _base_currency(product)
    quote_currency = _quote_currency(product)
    if quote_currency != QUOTE_CURRENCY or not base_currency:
        return False
    if base_currency == quote_currency:
        return False

    status = _text(_get_value(product, "status")).lower()
    if status and status not in {"online", "open"}:
        return False
    for flag in DISQUALIFYING_PRODUCT_FLAGS:
        if _is_truthy_flag(_get_value(product, flag)):
            return False

    price = _decimal(_get_value(product, "price"))
    quote_min = _decimal(_get_value(product, "quote_min_size"))
    base_increment = _decimal(_get_value(product, "base_increment"))
    quote_increment = _decimal(_get_value(product, "quote_increment"))
    price_increment = _decimal(_get_value(product, "price_increment"))
    return (
        price > 0
        and quote_min > 0
        and base_increment > 0
        and quote_increment > 0
        and price_increment > 0
    )


def _product_filter_set(values: Iterable[Any] | None) -> set[str]:
    if not values:
        return set()
    if isinstance(values, str):
        values = [values]
    return {
        _text(value).upper()
        for value in values
        if _text(value)
    }


def filter_usdc_spot_products(
    products: Iterable[Any],
    *,
    allow_products: Iterable[Any] | None = None,
    deny_products: Iterable[Any] | None = None,
) -> list[Any]:
    """Return eligible USDC-quoted spot products sorted deterministically."""
    allowed = _product_filter_set(allow_products)
    denied = _product_filter_set(deny_products)
    return sorted(
        [
            product
            for product in products
            if is_usdc_spot_product_eligible(product)
            and (not allowed or _product_id(product).upper() in allowed)
            and _product_id(product).upper() not in denied
        ],
        key=lambda product: _product_id(product),
    )


@dataclass(frozen=True)
class SpotPortfolioSweepPlanItem:
    product_id: str
    base_currency: str
    quote_currency: str
    side: str
    status: str
    skip_reason: str
    requested_quote_notional: str
    estimated_price: str
    estimated_quote_notional: str
    planned_quote_size: str | None
    planned_base_size: str | None
    balance_currency: str
    available_balance: str
    quote_min_size: str
    base_min_size: str
    quote_increment: str
    base_increment: str
    price_increment: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "side": self.side,
            "status": self.status,
            "skip_reason": self.skip_reason,
            "requested_quote_notional": self.requested_quote_notional,
            "estimated_price": self.estimated_price,
            "estimated_quote_notional": self.estimated_quote_notional,
            "planned_quote_size": self.planned_quote_size,
            "planned_base_size": self.planned_base_size,
            "balance_currency": self.balance_currency,
            "available_balance": self.available_balance,
            "quote_min_size": self.quote_min_size,
            "base_min_size": self.base_min_size,
            "quote_increment": self.quote_increment,
            "base_increment": self.base_increment,
            "price_increment": self.price_increment,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SpotPortfolioSweepPlan:
    generated_at: str
    side: str
    quote_currency: str
    requested_quote_notional: str
    available_quote_balance: str
    eligible_product_count: int
    selected_product_count: int
    max_products: int | None
    wallet_check_enabled: bool
    items: tuple[SpotPortfolioSweepPlanItem, ...]

    @property
    def planned_items(self) -> tuple[SpotPortfolioSweepPlanItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.status == SpotPortfolioSweepItemStatus.PLANNED.value
        )

    @property
    def skipped_items(self) -> tuple[SpotPortfolioSweepPlanItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.status == SpotPortfolioSweepItemStatus.SKIPPED.value
        )

    def to_dict(self) -> dict[str, Any]:
        estimated_total = sum(
            (
                _decimal(item.estimated_quote_notional)
                for item in self.planned_items
            ),
            Decimal("0"),
        )
        skip_counts: dict[str, int] = {}
        for item in self.skipped_items:
            skip_counts[item.skip_reason] = skip_counts.get(item.skip_reason, 0) + 1
        return {
            "generated_at": self.generated_at,
            "side": self.side,
            "quote_currency": self.quote_currency,
            "requested_quote_notional": self.requested_quote_notional,
            "available_quote_balance": self.available_quote_balance,
            "eligible_product_count": self.eligible_product_count,
            "selected_product_count": self.selected_product_count,
            "max_products": self.max_products,
            "wallet_check_enabled": self.wallet_check_enabled,
            "planned_count": len(self.planned_items),
            "skipped_count": len(self.skipped_items),
            "estimated_planned_quote_notional": _format_decimal(estimated_total),
            "skip_counts": skip_counts,
            "items": [item.to_dict() for item in self.items],
        }


def _planned_item(
    *,
    product: Any,
    side: str,
    requested_quote_notional: Decimal,
    estimated_quote_notional: Decimal,
    planned_quote_size: Decimal | None,
    planned_base_size: Decimal | None,
    balance_currency: str,
    available_balance: Decimal,
    reason: str,
) -> SpotPortfolioSweepPlanItem:
    return SpotPortfolioSweepPlanItem(
        product_id=_product_id(product),
        base_currency=_base_currency(product),
        quote_currency=_quote_currency(product),
        side=side,
        status=SpotPortfolioSweepItemStatus.PLANNED.value,
        skip_reason=SpotPortfolioSweepSkipReason.NONE.value,
        requested_quote_notional=_format_decimal(requested_quote_notional) or "0",
        estimated_price=_format_decimal(_decimal(_get_value(product, "price"))) or "0",
        estimated_quote_notional=_format_decimal(estimated_quote_notional) or "0",
        planned_quote_size=_format_decimal(planned_quote_size),
        planned_base_size=_format_decimal(planned_base_size),
        balance_currency=balance_currency,
        available_balance=_format_decimal(available_balance) or "0",
        quote_min_size=_format_decimal(_decimal(_get_value(product, "quote_min_size"))) or "0",
        base_min_size=_format_decimal(_decimal(_get_value(product, "base_min_size"))) or "0",
        quote_increment=_format_decimal(_decimal(_get_value(product, "quote_increment"))) or "0",
        base_increment=_format_decimal(_decimal(_get_value(product, "base_increment"))) or "0",
        price_increment=_format_decimal(_decimal(_get_value(product, "price_increment"))) or "0",
        reason=reason,
    )


def _skipped_item(
    *,
    product: Any,
    side: str,
    requested_quote_notional: Decimal,
    estimated_quote_notional: Decimal = Decimal("0"),
    planned_quote_size: Decimal | None = None,
    planned_base_size: Decimal | None = None,
    balance_currency: str,
    available_balance: Decimal,
    skip_reason: SpotPortfolioSweepSkipReason,
    reason: str,
) -> SpotPortfolioSweepPlanItem:
    return SpotPortfolioSweepPlanItem(
        product_id=_product_id(product),
        base_currency=_base_currency(product),
        quote_currency=_quote_currency(product),
        side=side,
        status=SpotPortfolioSweepItemStatus.SKIPPED.value,
        skip_reason=skip_reason.value,
        requested_quote_notional=_format_decimal(requested_quote_notional) or "0",
        estimated_price=_format_decimal(_decimal(_get_value(product, "price"))) or "0",
        estimated_quote_notional=_format_decimal(estimated_quote_notional) or "0",
        planned_quote_size=_format_decimal(planned_quote_size),
        planned_base_size=_format_decimal(planned_base_size),
        balance_currency=balance_currency,
        available_balance=_format_decimal(available_balance) or "0",
        quote_min_size=_format_decimal(_decimal(_get_value(product, "quote_min_size"))) or "0",
        base_min_size=_format_decimal(_decimal(_get_value(product, "base_min_size"))) or "0",
        quote_increment=_format_decimal(_decimal(_get_value(product, "quote_increment"))) or "0",
        base_increment=_format_decimal(_decimal(_get_value(product, "base_increment"))) or "0",
        price_increment=_format_decimal(_decimal(_get_value(product, "price_increment"))) or "0",
        reason=reason,
    )


def build_usdc_portfolio_sweep_plan(
    *,
    side: str | OrderSide,
    quote_notional: Any,
    products: Iterable[Any],
    wallets: Mapping[str, Any] | None,
    max_products: int | None = None,
    allow_products: Iterable[Any] | None = None,
    deny_products: Iterable[Any] | None = None,
    generated_at: datetime | None = None,
) -> SpotPortfolioSweepPlan:
    """Build a wallet-aware dry-run plan for USDC spot BUY or SELL sweeps."""
    try:
        side_value = OrderSide(_text(side).upper()).value
    except ValueError:
        side_value = _text(side).upper()

    requested_quote_notional = _decimal(quote_notional)
    if requested_quote_notional <= 0:
        raise ValueError("quote_notional must be greater than 0")
    if max_products is not None and max_products <= 0:
        raise ValueError("max_products must be greater than 0 when provided")

    all_eligible_products = filter_usdc_spot_products(products)
    eligible_products = filter_usdc_spot_products(
        products,
        allow_products=allow_products,
        deny_products=deny_products,
    )
    selected_products = (
        eligible_products[:max_products] if max_products else eligible_products
    )
    available_quote_balance = _wallet_available(wallets, QUOTE_CURRENCY)
    remaining_quote_balance = available_quote_balance
    items: list[SpotPortfolioSweepPlanItem] = []

    for product in selected_products:
        price = _decimal(_get_value(product, "price"))
        quote_min_size = _decimal(_get_value(product, "quote_min_size"))
        base_min_size = _decimal(_get_value(product, "base_min_size"))
        base_increment = _decimal(_get_value(product, "base_increment"))
        quote_increment = _decimal(_get_value(product, "quote_increment"))
        base_currency = _base_currency(product)

        if side_value not in {OrderSide.BUY.value, OrderSide.SELL.value}:
            items.append(
                _skipped_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    balance_currency=QUOTE_CURRENCY,
                    available_balance=available_quote_balance,
                    skip_reason=SpotPortfolioSweepSkipReason.UNSUPPORTED_SIDE,
                    reason="side must be BUY or SELL",
                )
            )
            continue
        if price <= 0:
            balance_currency = (
                QUOTE_CURRENCY if side_value == OrderSide.BUY.value else base_currency
            )
            items.append(
                _skipped_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    balance_currency=balance_currency,
                    available_balance=_wallet_available(wallets, balance_currency),
                    skip_reason=SpotPortfolioSweepSkipReason.INVALID_PRICE,
                    reason="positive product price is required",
                )
            )
            continue

        if side_value == OrderSide.BUY.value:
            planned_quote_size = _quantize_down(
                requested_quote_notional,
                quote_increment,
            )
            if planned_quote_size <= 0 or planned_quote_size < quote_min_size:
                items.append(
                    _skipped_item(
                        product=product,
                        side=side_value,
                        requested_quote_notional=requested_quote_notional,
                        planned_quote_size=planned_quote_size,
                        balance_currency=QUOTE_CURRENCY,
                        available_balance=remaining_quote_balance,
                        skip_reason=SpotPortfolioSweepSkipReason.BELOW_QUOTE_MIN,
                        reason=(
                            "requested notional rounds below the product "
                            "quote_min_size"
                        ),
                    )
                )
                continue
            if remaining_quote_balance < planned_quote_size:
                items.append(
                    _skipped_item(
                        product=product,
                        side=side_value,
                        requested_quote_notional=requested_quote_notional,
                        planned_quote_size=planned_quote_size,
                        balance_currency=QUOTE_CURRENCY,
                        available_balance=remaining_quote_balance,
                        skip_reason=(
                            SpotPortfolioSweepSkipReason.INSUFFICIENT_QUOTE_BALANCE
                        ),
                        reason="available USDC balance is insufficient",
                    )
                )
                continue
            estimated_base_size = _quantize_down(
                planned_quote_size / price,
                base_increment,
            )
            remaining_quote_balance -= planned_quote_size
            items.append(
                _planned_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    estimated_quote_notional=planned_quote_size,
                    planned_quote_size=planned_quote_size,
                    planned_base_size=estimated_base_size,
                    balance_currency=QUOTE_CURRENCY,
                    available_balance=remaining_quote_balance,
                    reason="wallet balance covers requested USDC buy notional",
                )
            )
            continue

        requested_base_size = requested_quote_notional / price
        planned_base_size = _quantize_down(requested_base_size, base_increment)
        estimated_quote_notional = planned_base_size * price
        available_base_balance = _wallet_available(wallets, base_currency)
        if planned_base_size <= 0 or (
            base_min_size > 0 and planned_base_size < base_min_size
        ):
            items.append(
                _skipped_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    estimated_quote_notional=estimated_quote_notional,
                    planned_base_size=planned_base_size,
                    balance_currency=base_currency,
                    available_balance=available_base_balance,
                    skip_reason=SpotPortfolioSweepSkipReason.BELOW_BASE_MIN,
                    reason="requested notional rounds below base_min_size",
                )
            )
            continue
        if estimated_quote_notional < quote_min_size:
            items.append(
                _skipped_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    estimated_quote_notional=estimated_quote_notional,
                    planned_base_size=planned_base_size,
                    balance_currency=base_currency,
                    available_balance=available_base_balance,
                    skip_reason=SpotPortfolioSweepSkipReason.BELOW_QUOTE_MIN,
                    reason="rounded sell size is below quote_min_size",
                )
            )
            continue
        if available_base_balance < planned_base_size:
            items.append(
                _skipped_item(
                    product=product,
                    side=side_value,
                    requested_quote_notional=requested_quote_notional,
                    estimated_quote_notional=estimated_quote_notional,
                    planned_base_size=planned_base_size,
                    balance_currency=base_currency,
                    available_balance=available_base_balance,
                    skip_reason=(
                        SpotPortfolioSweepSkipReason.INSUFFICIENT_BASE_BALANCE
                    ),
                    reason=f"available {base_currency} balance is insufficient",
                )
            )
            continue
        items.append(
            _planned_item(
                product=product,
                side=side_value,
                requested_quote_notional=requested_quote_notional,
                estimated_quote_notional=estimated_quote_notional,
                planned_quote_size=None,
                planned_base_size=planned_base_size,
                balance_currency=base_currency,
                available_balance=available_base_balance,
                reason="wallet balance covers estimated USDC sell notional",
            )
        )

    timestamp = generated_at or datetime.now(timezone.utc)
    return SpotPortfolioSweepPlan(
        generated_at=timestamp.isoformat(),
        side=side_value,
        quote_currency=QUOTE_CURRENCY,
        requested_quote_notional=_format_decimal(requested_quote_notional) or "0",
        available_quote_balance=_format_decimal(available_quote_balance) or "0",
        eligible_product_count=len(all_eligible_products),
        selected_product_count=len(selected_products),
        max_products=max_products,
        wallet_check_enabled=wallets is not None,
        items=tuple(items),
    )


def build_sweep_product_metadata(products: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Build product metadata suitable for ActionConditionGuard injection."""
    metadata: dict[str, dict[str, Any]] = {}
    for product in products:
        product_id = _product_id(product)
        if not product_id:
            continue
        metadata[product_id] = {
            "product_id": product_id,
            "product_type": ProductType.SPOT.value,
            "base_currency": _base_currency(product),
            "quote_currency": _quote_currency(product),
            "base_increment": _text(_get_value(product, "base_increment")),
            "quote_increment": _text(_get_value(product, "quote_increment")),
            "price_increment": _text(_get_value(product, "price_increment")),
            "base_min_size": _text(_get_value(product, "base_min_size")),
            "quote_min_size": _text(_get_value(product, "quote_min_size")),
        }
    return metadata


def build_usdc_spot_mark_prices(products: Iterable[Any]) -> dict[str, str]:
    """Return mark prices for eligible USDC spot products from product data."""
    mark_prices: dict[str, str] = {}
    for product in filter_usdc_spot_products(products):
        product_id = _product_id(product)
        price = _decimal(_get_value(product, "price"))
        if product_id and price > 0:
            mark_prices[product_id] = _format_decimal(price) or "0"
    return mark_prices


def _coerce_sweep_order_type(order_type: str | SpotPortfolioSweepOrderType) -> str:
    try:
        return SpotPortfolioSweepOrderType(_text(order_type)).value
    except ValueError as exc:
        supported = ", ".join(item.value for item in SpotPortfolioSweepOrderType)
        raise ValueError(f"order_type must be one of: {supported}") from exc


def _sweep_client_order_id() -> str:
    return str(uuid.uuid4())


def _limit_price_for_plan_item(
    item: SpotPortfolioSweepPlanItem,
    *,
    limit_price_offset_bps: Any,
) -> Decimal:
    estimated_price = _decimal(item.estimated_price)
    price_increment = _decimal(item.price_increment)
    offset = _decimal(limit_price_offset_bps) / Decimal("10000")
    if offset < 0:
        raise ValueError("limit_price_offset_bps must be greater than or equal to 0")

    if item.side == OrderSide.BUY.value:
        raw_price = estimated_price * (Decimal("1") + offset)
        return _quantize_up(raw_price, price_increment)
    raw_price = estimated_price * (Decimal("1") - offset)
    if raw_price <= 0:
        raise ValueError("sell limit price offset would make limit_price non-positive")
    return _quantize_down(raw_price, price_increment)


@dataclass(frozen=True)
class SpotPortfolioSweepOrderSubmission:
    order_type: str
    order_configuration: dict[str, Any]
    submitted_notional_usdc: str
    guard_size: Decimal
    guard_limit_price: Decimal
    guard_quote_size: Decimal | None
    limit_price: str | None = None


def build_sweep_order_submission(
    item: SpotPortfolioSweepPlanItem,
    *,
    order_type: str | SpotPortfolioSweepOrderType = (
        SpotPortfolioSweepOrderType.MARKET_IOC
    ),
    limit_price_offset_bps: Any = 0,
) -> SpotPortfolioSweepOrderSubmission:
    """Build the Coinbase order payload and guard inputs for one plan item."""
    order_type_value = _coerce_sweep_order_type(order_type)
    planned_base_size = _decimal(item.planned_base_size)

    if order_type_value == SpotPortfolioSweepOrderType.MARKET_IOC.value:
        if item.side == OrderSide.BUY.value:
            return SpotPortfolioSweepOrderSubmission(
                order_type=order_type_value,
                order_configuration={
                    "market_market_ioc": {
                        "quote_size": item.planned_quote_size,
                    },
                },
                submitted_notional_usdc=item.planned_quote_size or "0",
                guard_size=planned_base_size,
                guard_limit_price=_decimal(item.estimated_price),
                guard_quote_size=_decimal(item.planned_quote_size),
            )
        return SpotPortfolioSweepOrderSubmission(
            order_type=order_type_value,
            order_configuration={
                "market_market_ioc": {
                    "base_size": item.planned_base_size,
                },
            },
            submitted_notional_usdc=item.estimated_quote_notional,
            guard_size=planned_base_size,
            guard_limit_price=_decimal(item.estimated_price),
            guard_quote_size=None,
        )

    if planned_base_size <= 0:
        raise ValueError("planned_base_size is required for limit sweep orders")
    limit_price = _limit_price_for_plan_item(
        item,
        limit_price_offset_bps=limit_price_offset_bps,
    )
    submitted_notional = planned_base_size * limit_price
    return SpotPortfolioSweepOrderSubmission(
        order_type=order_type_value,
        order_configuration={
            "limit_limit_gtc": {
                "base_size": item.planned_base_size,
                "limit_price": _format_decimal(limit_price) or "0",
                "post_only": (
                    order_type_value
                    == SpotPortfolioSweepOrderType.LIMIT_GTC_POST_ONLY.value
                ),
            },
        },
        submitted_notional_usdc=_format_decimal(submitted_notional) or "0",
        guard_size=planned_base_size,
        guard_limit_price=limit_price,
        guard_quote_size=None,
        limit_price=_format_decimal(limit_price) or "0",
    )


def _extract_order_id(response: Mapping[str, Any] | None) -> str | None:
    response = response or {}
    success = response.get("success_response") or {}
    if isinstance(success, Mapping):
        return success.get("order_id") or response.get("order_id")
    return response.get("order_id")


def _response_success(response: Mapping[str, Any] | None) -> bool | None:
    response = response or {}
    success = response.get("success")
    if isinstance(success, bool):
        return success
    return None


def _create_response_failure_code(response_success: bool | None) -> str:
    if response_success is False:
        return "coinbase_create_explicitly_rejected"
    return "coinbase_create_acceptance_unknown"


def _dict_response(response: Any) -> Any:
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def _extract_order_payload(response: Any) -> dict[str, Any]:
    data = _dict_response(response) or {}
    if isinstance(data, Mapping) and isinstance(data.get("order"), Mapping):
        return dict(data["order"])
    return dict(data) if isinstance(data, Mapping) else {}


def _publish_sweep_order_submission_event(
    *,
    event_publisher: Any,
    client_order_id: str,
    order_id: str | None,
    item: SpotPortfolioSweepPlanItem,
    submission: SpotPortfolioSweepOrderSubmission,
) -> bool:
    """Publish durable owned-submission evidence for a live sweep placement."""
    if event_publisher is None or not getattr(event_publisher, "enabled", False):
        return False

    inner_key = next(iter(submission.order_configuration), None)
    inner = (
        submission.order_configuration.get(inner_key, {})
        if inner_key
        else {}
    )
    payload = {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "product_id": item.product_id,
        "side": item.side,
        "order_type": submission.order_type,
        "order_configuration_type": inner_key,
        "order_configuration": submission.order_configuration,
        "base_size": inner.get("base_size"),
        "quote_size": inner.get("quote_size"),
        "limit_price": inner.get("limit_price"),
        "post_only": inner.get("post_only"),
        "submitted_notional_usdc": submission.submitted_notional_usdc,
        "planned_quote_size": item.planned_quote_size,
        "planned_base_size": item.planned_base_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"spot_sweep_submit:{client_order_id}:{order_id or ''}"
    try:
        return bool(
            event_publisher.publish_event(
                event_type=EventStreamType.ORDER_SUBMITTED.value,
                source_channel=EventSourceChannel.REST_SUBMIT.value,
                payload=payload,
                idempotency_key=key,
                status_to=OrderStatus.PENDING.value,
            )
        )
    except Exception:
        return False


def _get_order(rest_client: Any, order_id: str) -> dict[str, Any]:
    getter = getattr(rest_client, "get_order", None)
    if callable(getter):
        return _extract_order_payload(getter(order_id))
    sdk_getter = getattr(getattr(rest_client, "get_sdk_client", lambda: None)(), "get_order", None)
    if callable(sdk_getter):
        return _extract_order_payload(sdk_getter(order_id))
    return {}


def poll_sweep_order(
    rest_client: Any,
    order_id: str,
    *,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 0.5,
) -> dict[str, Any]:
    """Poll a Coinbase order until terminal or timeout."""
    deadline = time.time() + max(0.0, timeout_seconds)
    last: dict[str, Any] = {}
    while time.time() <= deadline:
        last = _get_order(rest_client, order_id)
        status = str(last.get("status") or "").upper()
        if status in {"FILLED", "CANCELLED", "EXPIRED", "FAILED", "REJECTED"}:
            return last
        time.sleep(max(0.0, poll_interval_seconds))
    return last


def fetch_sweep_order_fills_notional_and_size(
    rest_client: Any,
    *,
    order_id: str,
    product_id: str | None = None,
) -> tuple[Decimal, Decimal]:
    """Return filled base size and quote notional for one exchange order."""
    lister = getattr(rest_client, "list_fills", None)
    if callable(lister):
        fills_response = lister(order_id=order_id, limit=100)
    else:
        getter = getattr(rest_client, "get_fills", None)
        if callable(getter):
            fills_response = getter(order_ids=[order_id], limit=100)
        else:
            fills_response = {}
    fills = (_dict_response(fills_response) or {}).get("fills") or []
    total_size = Decimal("0")
    total_notional = Decimal("0")
    for fill in fills:
        size = _decimal(_get_value(fill, "size", "base_size"))
        price = _decimal(_get_value(fill, "price"))
        if bool(_get_value(fill, "size_in_quote")):
            total_notional += size
            if price > 0:
                total_size += size / price
            continue
        total_size += size
        total_notional += size * price
    return total_size, total_notional


def fetch_sweep_order_executed_notional(
    rest_client: Any,
    *,
    order_id: str | None,
    product_id: str,
    fallback_order: Mapping[str, Any] | None = None,
) -> tuple[Decimal, Decimal]:
    if not order_id:
        return Decimal("0"), Decimal("0")
    fill_size, fill_notional = fetch_sweep_order_fills_notional_and_size(
        rest_client,
        order_id=order_id,
        product_id=product_id,
    )
    if fill_notional > 0:
        return fill_size, fill_notional
    order = fallback_order or _get_order(rest_client, order_id)
    size = _decimal(
        _get_value(
            order,
            "filled_size",
            "filled_value",
            "cumulative_quantity",
        )
    )
    average_price = _decimal(_get_value(order, "average_filled_price"))
    return size, size * average_price


@dataclass(frozen=True)
class SpotPortfolioSweepLiveOrderReport:
    product_id: str
    side: str
    status: str
    order_type: str
    client_order_id: str | None
    exchange_order_id: str | None
    submitted_notional_usdc: str
    executed_notional_usdc: str
    planned_quote_size: str | None
    planned_base_size: str | None
    limit_price: str | None = None
    exchange_status: str | None = None
    response_success: bool | None = None
    submission_attempted: bool = False
    submission_event_recorded: bool | None = None
    guard_failure: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "side": self.side,
            "status": self.status,
            "order_type": self.order_type,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "submitted_notional_usdc": self.submitted_notional_usdc,
            "executed_notional_usdc": self.executed_notional_usdc,
            "planned_quote_size": self.planned_quote_size,
            "planned_base_size": self.planned_base_size,
            "limit_price": self.limit_price,
            "exchange_status": self.exchange_status,
            "response_success": self.response_success,
            "submission_attempted": self.submission_attempted,
            "submission_event_recorded": self.submission_event_recorded,
            "guard_failure": self.guard_failure,
            "error": self.error,
        }


def _order_record_value(order: Any, key: str) -> Any:
    if isinstance(order, Mapping):
        return order.get(key)
    return getattr(order, key, None)


def _is_sweep_execution_failure(order: Any) -> bool:
    status = _text(_order_record_value(order, "status"))
    has_error = bool(_text(_order_record_value(order, "error")))
    if status in {
        SpotPortfolioSweepExecutionStatus.ERROR.value,
        SpotPortfolioSweepExecutionStatus.BLOCKED.value,
    }:
        return True
    if status == SpotPortfolioSweepExecutionStatus.SKIPPED.value:
        return False
    return has_error


def summarize_sweep_order_statuses(
    orders: Iterable[Any],
) -> dict[str, Any]:
    """Summarize execution outcome statuses without counting plan skips as errors."""
    orders = list(orders)
    submitted = [
        order
        for order in orders
        if _text(_order_record_value(order, "status"))
        == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
    ]
    skipped = [
        order
        for order in orders
        if _text(_order_record_value(order, "status"))
        == SpotPortfolioSweepExecutionStatus.SKIPPED.value
    ]
    attempted = [
        order
        for order in orders
        if _text(_order_record_value(order, "status"))
        == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
        or bool(_order_record_value(order, "submission_attempted"))
    ]
    failures = [order for order in orders if _is_sweep_execution_failure(order)]
    if submitted and failures:
        run_status = SpotPortfolioSweepRunStatus.PARTIAL.value
    elif submitted:
        run_status = SpotPortfolioSweepRunStatus.COMPLETED.value
    elif failures:
        run_status = SpotPortfolioSweepRunStatus.FAILED.value
    else:
        run_status = SpotPortfolioSweepRunStatus.SKIPPED.value
    return {
        "run_status": run_status,
        "live_coinbase_orders_ran": bool(attempted),
        "submission_attempted_count": len(attempted),
        "submitted_order_count": len(submitted),
        "blocked_or_error_count": len(failures),
        "skipped_order_count": len(skipped),
    }


def execute_usdc_portfolio_sweep_plan(
    *,
    plan: SpotPortfolioSweepPlan,
    rest_client: Any,
    wallet_fetcher: Callable[[], Mapping[str, Any]],
    product_metadata: Mapping[str, Mapping[str, Any]],
    order_type: str | SpotPortfolioSweepOrderType = (
        SpotPortfolioSweepOrderType.MARKET_IOC
    ),
    limit_price_offset_bps: Any = 0,
    poll_timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 0.5,
    client_order_id_factory: Callable[[], str] | None = None,
    order_event_publisher: Any | None = None,
) -> list[SpotPortfolioSweepLiveOrderReport]:
    """Submit live orders for planned sweep items after guard checks."""
    from core.action_condition_guard import ActionConditionGuard

    order_type_value = _coerce_sweep_order_type(order_type)
    client_order_id_factory = client_order_id_factory or _sweep_client_order_id
    spot_product_ids = list(product_metadata)
    reports: list[SpotPortfolioSweepLiveOrderReport] = []
    for item in plan.items:
        if item.status != SpotPortfolioSweepItemStatus.PLANNED.value:
            reports.append(
                SpotPortfolioSweepLiveOrderReport(
                    product_id=item.product_id,
                    side=item.side,
                    status=SpotPortfolioSweepExecutionStatus.SKIPPED.value,
                    order_type=order_type_value,
                    client_order_id=None,
                    exchange_order_id=None,
                    submitted_notional_usdc="0",
                    executed_notional_usdc="0",
                    planned_quote_size=item.planned_quote_size,
                    planned_base_size=item.planned_base_size,
                    error=item.reason,
                )
            )
            continue

        client_order_id = client_order_id_factory()
        try:
            submission = build_sweep_order_submission(
                item,
                order_type=order_type_value,
                limit_price_offset_bps=limit_price_offset_bps,
            )
        except Exception as exc:
            reports.append(
                SpotPortfolioSweepLiveOrderReport(
                    product_id=item.product_id,
                    side=item.side,
                    status=SpotPortfolioSweepExecutionStatus.ERROR.value,
                    order_type=order_type_value,
                    client_order_id=client_order_id,
                    exchange_order_id=None,
                    submitted_notional_usdc="0",
                    executed_notional_usdc="0",
                    planned_quote_size=item.planned_quote_size,
                    planned_base_size=item.planned_base_size,
                    error=_value_blind_exception_detail(exc),
                )
            )
            continue

        guard_ok, guard_failure = ActionConditionGuard(
            wallet_fetcher=wallet_fetcher,
            credentials_configured=lambda: True,
            product_metadata=dict(product_metadata),
            spot_product_ids=spot_product_ids,
        ).evaluate(
            phase=ActionGuardPhase.PLANNING,
            product_id=item.product_id,
            side=item.side,
            size=submission.guard_size,
            limit_price=submission.guard_limit_price,
            quote_size=submission.guard_quote_size,
            client_order_id=client_order_id,
        )
        if not guard_ok:
            guard_failure_evidence = _sanitized_action_guard_failure(guard_failure)
            reports.append(
                SpotPortfolioSweepLiveOrderReport(
                    product_id=item.product_id,
                    side=item.side,
                    status=SpotPortfolioSweepExecutionStatus.BLOCKED.value,
                    order_type=order_type_value,
                    client_order_id=client_order_id,
                    exchange_order_id=None,
                    submitted_notional_usdc="0",
                    executed_notional_usdc="0",
                    planned_quote_size=item.planned_quote_size,
                    planned_base_size=item.planned_base_size,
                    limit_price=submission.limit_price,
                    guard_failure=guard_failure_evidence,
                    error=(guard_failure_evidence or {}).get(
                        "reason",
                        "guard blocked",
                    ),
                )
            )
            continue

        order_id: str | None = None
        exchange_status: str | None = None
        submission_attempted = False
        submission_event_recorded = False
        try:
            submission_attempted = True
            require_coinbase_execution_authority()
            response = _dict_response(
                rest_client.create_order(
                    client_order_id=client_order_id,
                    product_id=item.product_id,
                    side=item.side,
                    order_configuration=submission.order_configuration,
                )
            )
            if not isinstance(response, Mapping):
                response = {}
            order_id = _extract_order_id(response)
            response_success = _response_success(response)
            if response_success is not True:
                reports.append(
                    SpotPortfolioSweepLiveOrderReport(
                        product_id=item.product_id,
                        side=item.side,
                        status=SpotPortfolioSweepExecutionStatus.ERROR.value,
                        order_type=order_type_value,
                        client_order_id=client_order_id,
                        exchange_order_id=order_id,
                        submitted_notional_usdc=(
                            submission.submitted_notional_usdc
                        ),
                        executed_notional_usdc="0",
                        planned_quote_size=item.planned_quote_size,
                        planned_base_size=item.planned_base_size,
                        limit_price=submission.limit_price,
                        response_success=response_success,
                        submission_attempted=True,
                        submission_event_recorded=False,
                        error=_create_response_failure_code(response_success),
                    )
                )
                continue
            if not order_id:
                reports.append(
                    SpotPortfolioSweepLiveOrderReport(
                        product_id=item.product_id,
                        side=item.side,
                        status=SpotPortfolioSweepExecutionStatus.ERROR.value,
                        order_type=order_type_value,
                        client_order_id=client_order_id,
                        exchange_order_id=None,
                        submitted_notional_usdc=(
                            submission.submitted_notional_usdc
                        ),
                        executed_notional_usdc="0",
                        planned_quote_size=item.planned_quote_size,
                        planned_base_size=item.planned_base_size,
                        limit_price=submission.limit_price,
                        response_success=True,
                        submission_attempted=True,
                        submission_event_recorded=False,
                        error="coinbase_create_order_id_missing",
                    )
                )
                continue
            submission_event_recorded = _publish_sweep_order_submission_event(
                event_publisher=order_event_publisher,
                client_order_id=client_order_id,
                order_id=order_id,
                item=item,
                submission=submission,
            )
            order = (
                poll_sweep_order(
                    rest_client,
                    order_id,
                    timeout_seconds=poll_timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
                if order_id
                else {}
            )
            exchange_status = _sanitized_exchange_status(order.get("status"))
            _, executed_notional = fetch_sweep_order_executed_notional(
                rest_client,
                order_id=order_id,
                product_id=item.product_id,
                fallback_order=order,
            )
            reports.append(
                SpotPortfolioSweepLiveOrderReport(
                    product_id=item.product_id,
                    side=item.side,
                    status=SpotPortfolioSweepExecutionStatus.SUBMITTED.value,
                    order_type=order_type_value,
                    client_order_id=client_order_id,
                    exchange_order_id=order_id,
                    submitted_notional_usdc=submission.submitted_notional_usdc,
                    executed_notional_usdc=_format_decimal(executed_notional) or "0",
                    planned_quote_size=item.planned_quote_size,
                    planned_base_size=item.planned_base_size,
                    limit_price=submission.limit_price,
                    exchange_status=exchange_status,
                    response_success=True,
                    submission_attempted=True,
                    submission_event_recorded=submission_event_recorded,
                )
            )
        except Exception as exc:
            reports.append(
                SpotPortfolioSweepLiveOrderReport(
                    product_id=item.product_id,
                    side=item.side,
                    status=(
                        SpotPortfolioSweepExecutionStatus.SUBMITTED.value
                        if order_id
                        else SpotPortfolioSweepExecutionStatus.ERROR.value
                    ),
                    order_type=order_type_value,
                    client_order_id=client_order_id,
                    exchange_order_id=order_id,
                    submitted_notional_usdc=(
                        submission.submitted_notional_usdc
                        if submission_attempted
                        else "0"
                    ),
                    executed_notional_usdc="0",
                    planned_quote_size=item.planned_quote_size,
                    planned_base_size=item.planned_base_size,
                    limit_price=submission.limit_price,
                    exchange_status=exchange_status,
                    submission_attempted=submission_attempted,
                    submission_event_recorded=submission_event_recorded,
                    error=_value_blind_exception_detail(exc),
                )
            )
    return reports


def summarize_sweep_execution(
    *,
    reports: Iterable[SpotPortfolioSweepLiveOrderReport],
) -> dict[str, Any]:
    reports = list(reports)
    status_summary = summarize_sweep_order_statuses(reports)
    total_submitted = sum(
        (_decimal(report.submitted_notional_usdc) for report in reports),
        Decimal("0"),
    )
    total_executed = sum(
        (_decimal(report.executed_notional_usdc) for report in reports),
        Decimal("0"),
    )
    return {
        **status_summary,
        "total_submitted_notional_usdc": _format_decimal(total_submitted) or "0",
        "total_executed_notional_usdc": _format_decimal(total_executed) or "0",
        "orders": [report.to_dict() for report in reports],
    }


@dataclass(frozen=True)
class SpotPortfolioSweepSafetyPolicy:
    """Artificial account/run limits applied before live sweep execution."""

    enabled: bool = True
    require_wallet_check: bool = True
    require_known_profitable_inventory: bool = False
    allow_coinbase_average_cost_basis: bool = False
    coinbase_average_cost_profit_buffer_pct: str = "0.5"
    max_total_notional_per_run: str | None = None
    max_notional_per_order: str | None = None
    max_planned_orders: int | None = None
    max_skipped_orders: int | None = None
    allow_products: tuple[str, ...] = ()
    deny_products: tuple[str, ...] = ()

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None,
    ) -> "SpotPortfolioSweepSafetyPolicy":
        if config is None:
            return cls()
        raw_allow_products = config.get("allow_products") or []
        raw_deny_products = config.get("deny_products") or []
        if isinstance(raw_allow_products, str):
            raw_allow_products = [raw_allow_products]
        if isinstance(raw_deny_products, str):
            raw_deny_products = [raw_deny_products]
        allow_products = tuple(
            sorted(
                str(product_id).upper()
                for product_id in raw_allow_products
                if str(product_id).strip()
            )
        )
        deny_products = tuple(
            sorted(
                str(product_id).upper()
                for product_id in raw_deny_products
                if str(product_id).strip()
            )
        )
        return cls(
            enabled=bool(config.get("enabled", True)),
            require_wallet_check=bool(config.get("require_wallet_check", True)),
            require_known_profitable_inventory=bool(
                config.get("require_known_profitable_inventory", False)
            ),
            allow_coinbase_average_cost_basis=bool(
                config.get("allow_coinbase_average_cost_basis", False)
            ),
            coinbase_average_cost_profit_buffer_pct=(
                _format_decimal(
                    _decimal(
                        config.get(
                            "coinbase_average_cost_profit_buffer_pct",
                            "0.5",
                        )
                    )
                )
                or "0.5"
            ),
            max_total_notional_per_run=(
                _format_decimal(_decimal(config.get("max_total_notional_per_run")))
                if config.get("max_total_notional_per_run") is not None
                else None
            ),
            max_notional_per_order=(
                _format_decimal(_decimal(config.get("max_notional_per_order")))
                if config.get("max_notional_per_order") is not None
                else None
            ),
            max_planned_orders=(
                int(config["max_planned_orders"])
                if config.get("max_planned_orders") is not None
                else None
            ),
            max_skipped_orders=(
                int(config["max_skipped_orders"])
                if config.get("max_skipped_orders") is not None
                else None
            ),
            allow_products=allow_products,
            deny_products=deny_products,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "require_wallet_check": self.require_wallet_check,
            "require_known_profitable_inventory": (
                self.require_known_profitable_inventory
            ),
            "allow_coinbase_average_cost_basis": (
                self.allow_coinbase_average_cost_basis
            ),
            "coinbase_average_cost_profit_buffer_pct": (
                self.coinbase_average_cost_profit_buffer_pct
            ),
            "max_total_notional_per_run": self.max_total_notional_per_run,
            "max_notional_per_order": self.max_notional_per_order,
            "max_planned_orders": self.max_planned_orders,
            "max_skipped_orders": self.max_skipped_orders,
            "allow_products": list(self.allow_products),
            "deny_products": list(self.deny_products),
        }


@dataclass(frozen=True)
class SpotPortfolioSweepSafetyEvaluation:
    decision: str
    violations: tuple[dict[str, Any], ...]
    policy: SpotPortfolioSweepSafetyPolicy
    planned_order_count: int
    skipped_order_count: int
    total_planned_notional_usdc: str

    @property
    def allowed(self) -> bool:
        return self.decision == SpotPortfolioSweepSafetyDecision.ALLOWED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "violations": list(self.violations),
            "policy": self.policy.to_dict(),
            "planned_order_count": self.planned_order_count,
            "skipped_order_count": self.skipped_order_count,
            "total_planned_notional_usdc": self.total_planned_notional_usdc,
        }


def _planned_item_notional(item: SpotPortfolioSweepPlanItem) -> Decimal:
    if item.side == OrderSide.BUY.value and item.planned_quote_size is not None:
        return _decimal(item.planned_quote_size)
    return _decimal(item.estimated_quote_notional)


def _planned_item_sell_authority_price(
    item: SpotPortfolioSweepPlanItem,
    *,
    order_type: str,
    limit_price_offset_bps: Any,
) -> Decimal:
    if order_type == SpotPortfolioSweepOrderType.MARKET_IOC.value:
        return _decimal(item.estimated_price)
    return _limit_price_for_plan_item(
        item,
        limit_price_offset_bps=limit_price_offset_bps,
    )


def _evaluate_sweep_sell_lot_authority(
    *,
    item: SpotPortfolioSweepPlanItem,
    fill_ledger_repo: Any,
    inventory_baselines: Any = None,
    coinbase_average_cost_baselines: Any = None,
    allow_coinbase_average_cost_basis: bool = False,
    coinbase_average_cost_profit_buffer_pct: Any = "0.5",
    profit_target_pct: Any = None,
    submitted_price: Decimal,
) -> dict[str, Any]:
    requested_size = _decimal(item.planned_base_size)
    if fill_ledger_repo is None:
        return {
            "allowed": False,
            "status": InventoryAuthorityStatus.UNAVAILABLE.value,
            "product_id": item.product_id,
            "requested_size": _format_decimal(requested_size) or "0",
            "limit_price": _format_decimal(submitted_price) or "0",
            "known_quantity": "0",
            "known_profitable_quantity": "0",
            "unknown_cost_basis_quantity": "0",
            "reason": "fill ledger repository is unavailable",
        }
    if requested_size <= 0 or submitted_price <= 0:
        return {
            "allowed": False,
            "status": InventoryAuthorityStatus.INSUFFICIENT_KNOWN_PROFITABLE.value,
            "product_id": item.product_id,
            "requested_size": _format_decimal(requested_size) or "0",
            "limit_price": _format_decimal(submitted_price) or "0",
            "known_quantity": "0",
            "known_profitable_quantity": "0",
            "unknown_cost_basis_quantity": "0",
            "reason": "positive planned_base_size and price are required",
        }

    from business.lot_builder import PositionLotBuilder
    from business.lot_config import get_profit_target_for_product

    target_pct = (
        float(_decimal(profit_target_pct))
        if profit_target_pct is not None
        else get_profit_target_for_product(item.product_id)
    )
    position = PositionLotBuilder(
        fill_ledger_repo,
        inventory_baselines=inventory_baselines,
    ).build_position_by_product(
        item.product_id,
        side=OrderSide.BUY,
        profit_target_pct=target_pct,
    )

    known_quantity = Decimal("0")
    known_profitable_quantity = Decimal("0")
    unknown_quantity = Decimal("0")
    price_float = float(submitted_price)
    for lot in position.get_unexited_lots():
        remaining = _decimal(_get_value(lot, "remaining_quantity"))
        if remaining <= 0:
            continue
        if _get_value(lot, "cost_basis_status") != InventoryCostBasisStatus.KNOWN:
            unknown_quantity += remaining
            continue
        known_quantity += remaining
        if lot.can_exit_profitably_at(price_float):
            known_profitable_quantity += remaining

    allowed = known_profitable_quantity >= requested_size
    if allowed:
        status = InventoryAuthorityStatus.KNOWN_PROFITABLE.value
        reason = "known profitable lots cover requested spot sweep sell size"
        coinbase_average_quantity = Decimal("0")
        coinbase_average_profitable_quantity = Decimal("0")
        coinbase_average_profit_target_pct = None
    else:
        coinbase_average_quantity = Decimal("0")
        coinbase_average_profitable_quantity = Decimal("0")
        coinbase_average_profit_target_pct = (
            target_pct + float(_decimal(coinbase_average_cost_profit_buffer_pct))
        )
        if allow_coinbase_average_cost_basis:
            average_position = PositionLotBuilder(
                fill_ledger_repo,
                inventory_baselines=coinbase_average_cost_baselines or [],
            ).build_position_by_product(
                item.product_id,
                side=OrderSide.BUY,
                profit_target_pct=coinbase_average_profit_target_pct,
            )
            for lot in average_position.get_unexited_lots():
                remaining = _decimal(_get_value(lot, "remaining_quantity"))
                if remaining <= 0:
                    continue
                if (
                    _enum_value(_get_value(lot, "lot_source"))
                    != InventoryLotSource.COINBASE_AVERAGE_COST.value
                ):
                    continue
                coinbase_average_quantity += remaining
                if lot.can_exit_profitably_at(price_float):
                    coinbase_average_profitable_quantity += remaining
        if coinbase_average_profitable_quantity >= requested_size:
            allowed = True
            status = InventoryAuthorityStatus.COINBASE_AVERAGE_PROFITABLE.value
            reason = (
                "Coinbase average cost basis covers requested spot sweep sell "
                "with the configured extra profit buffer"
            )
        elif known_quantity <= 0 and unknown_quantity <= 0 and coinbase_average_quantity <= 0:
            status = InventoryAuthorityStatus.NO_LOTS.value
            reason = "no known, imported, or Coinbase-average inventory covers this sweep sell"
        elif unknown_quantity > 0:
            status = InventoryAuthorityStatus.UNKNOWN_COST_BASIS.value
            reason = (
                "known profitable lots do not cover the sweep sell and remaining "
                "inventory has unknown cost basis"
            )
        else:
            status = InventoryAuthorityStatus.INSUFFICIENT_KNOWN_PROFITABLE.value
            reason = "known lots exist but are insufficient or not profitable"

    return {
        "allowed": allowed,
        "status": status,
        "product_id": item.product_id,
        "requested_size": _format_decimal(requested_size) or "0",
        "limit_price": _format_decimal(submitted_price) or "0",
        "known_quantity": _format_decimal(known_quantity) or "0",
        "known_profitable_quantity": (
            _format_decimal(known_profitable_quantity) or "0"
        ),
        "unknown_cost_basis_quantity": _format_decimal(unknown_quantity) or "0",
        "coinbase_average_cost_quantity": (
            _format_decimal(coinbase_average_quantity) or "0"
        ),
        "coinbase_average_profitable_quantity": (
            _format_decimal(coinbase_average_profitable_quantity) or "0"
        ),
        "coinbase_average_cost_profit_target_pct": (
            _format_decimal(_decimal(coinbase_average_profit_target_pct))
            if coinbase_average_profit_target_pct is not None
            else None
        ),
        "cost_basis_authority": (
            SpotCostBasisSource.COINBASE_AVERAGE_COST.value
            if status == InventoryAuthorityStatus.COINBASE_AVERAGE_PROFITABLE.value
            else SpotCostBasisSource.FILL_LEDGER.value
            if status == InventoryAuthorityStatus.KNOWN_PROFITABLE.value
            else SpotCostBasisSource.WALLET_ONLY.value
        ),
        "reason": reason,
    }


def evaluate_sweep_safety_policy(
    *,
    plan: SpotPortfolioSweepPlan,
    policy: Mapping[str, Any] | SpotPortfolioSweepSafetyPolicy | None = None,
    order_type: str | SpotPortfolioSweepOrderType = (
        SpotPortfolioSweepOrderType.MARKET_IOC
    ),
    limit_price_offset_bps: Any = 0,
    fill_ledger_repo: Any = None,
    inventory_baselines: Any = None,
    coinbase_average_cost_baselines: Any = None,
    profit_target_pct: Any = None,
) -> SpotPortfolioSweepSafetyEvaluation:
    """Evaluate artificial run limits before live sweep execution."""
    if isinstance(policy, SpotPortfolioSweepSafetyPolicy):
        safety_policy = policy
    else:
        safety_policy = SpotPortfolioSweepSafetyPolicy.from_config(policy)
    order_type_value = _coerce_sweep_order_type(order_type)

    planned_items = list(plan.planned_items)
    skipped_items = list(plan.skipped_items)
    total_notional = sum(
        (_planned_item_notional(item) for item in planned_items),
        Decimal("0"),
    )
    violations: list[dict[str, Any]] = []

    if safety_policy.enabled:
        if safety_policy.require_wallet_check and not plan.wallet_check_enabled:
            violations.append({
                "code": "wallet_check_required",
                "reason": "sweep plan must be built with wallet balances",
            })

        max_total = _decimal(safety_policy.max_total_notional_per_run)
        if max_total > 0 and total_notional > max_total:
            violations.append({
                "code": "max_total_notional_per_run",
                "configured": _format_decimal(max_total),
                "actual": _format_decimal(total_notional),
                "reason": "planned sweep notional exceeds configured run cap",
            })

        max_order = _decimal(safety_policy.max_notional_per_order)
        if max_order > 0:
            for item in planned_items:
                item_notional = _planned_item_notional(item)
                if item_notional > max_order:
                    violations.append({
                        "code": "max_notional_per_order",
                        "product_id": item.product_id,
                        "configured": _format_decimal(max_order),
                        "actual": _format_decimal(item_notional),
                        "reason": "planned product notional exceeds order cap",
                    })

        if (
            safety_policy.max_planned_orders is not None
            and len(planned_items) > safety_policy.max_planned_orders
        ):
            violations.append({
                "code": "max_planned_orders",
                "configured": safety_policy.max_planned_orders,
                "actual": len(planned_items),
                "reason": "planned product count exceeds configured cap",
            })

        if (
            safety_policy.max_skipped_orders is not None
            and len(skipped_items) > safety_policy.max_skipped_orders
        ):
            violations.append({
                "code": "max_skipped_orders",
                "configured": safety_policy.max_skipped_orders,
                "actual": len(skipped_items),
                "reason": "skipped product count exceeds configured cap",
            })

        allowed = set(safety_policy.allow_products)
        denied = set(safety_policy.deny_products)
        if allowed:
            outside_allowed = [
                item.product_id
                for item in planned_items
                if item.product_id.upper() not in allowed
            ]
            if outside_allowed:
                violations.append({
                    "code": "allow_products",
                    "product_ids": outside_allowed,
                    "reason": "planned products are outside allow_products",
                })
        if denied:
            denied_planned = [
                item.product_id
                for item in planned_items
                if item.product_id.upper() in denied
            ]
            if denied_planned:
                violations.append({
                    "code": "deny_products",
                    "product_ids": denied_planned,
                    "reason": "planned products are present in deny_products",
                })

        if (
            safety_policy.require_known_profitable_inventory
            and plan.side == OrderSide.SELL.value
        ):
            for item in planned_items:
                try:
                    authority_price = _planned_item_sell_authority_price(
                        item,
                        order_type=order_type_value,
                        limit_price_offset_bps=limit_price_offset_bps,
                    )
                    authority = _evaluate_sweep_sell_lot_authority(
                        item=item,
                        fill_ledger_repo=fill_ledger_repo,
                        inventory_baselines=inventory_baselines,
                        coinbase_average_cost_baselines=(
                            coinbase_average_cost_baselines
                        ),
                        allow_coinbase_average_cost_basis=(
                            safety_policy.allow_coinbase_average_cost_basis
                        ),
                        coinbase_average_cost_profit_buffer_pct=(
                            safety_policy.coinbase_average_cost_profit_buffer_pct
                        ),
                        profit_target_pct=profit_target_pct,
                        submitted_price=authority_price,
                    )
                except Exception as exc:
                    authority = {
                        "allowed": False,
                        "status": InventoryAuthorityStatus.UNAVAILABLE.value,
                        "product_id": item.product_id,
                        "reason": _value_blind_exception_detail(exc),
                    }
                if not authority.get("allowed"):
                    violations.append({
                        "code": "known_profitable_inventory",
                        "product_id": item.product_id,
                        "inventory_authority": authority,
                        "reason": authority.get(
                            "reason",
                            "known profitable inventory does not cover sell",
                        ),
                    })

    decision = (
        SpotPortfolioSweepSafetyDecision.BLOCKED.value
        if violations
        else SpotPortfolioSweepSafetyDecision.ALLOWED.value
    )
    return SpotPortfolioSweepSafetyEvaluation(
        decision=decision,
        violations=tuple(violations),
        policy=safety_policy,
        planned_order_count=len(planned_items),
        skipped_order_count=len(skipped_items),
        total_planned_notional_usdc=_format_decimal(total_notional) or "0",
    )


def build_sweep_plan_explain(
    *,
    plan: SpotPortfolioSweepPlan,
    safety_evaluation: (
        SpotPortfolioSweepSafetyEvaluation | Mapping[str, Any] | None
    ) = None,
    order_type: str | SpotPortfolioSweepOrderType = (
        SpotPortfolioSweepOrderType.MARKET_IOC
    ),
    limit_price_offset_bps: Any = 0,
    fill_ledger_repo: Any = None,
    inventory_baselines: Any = None,
    coinbase_average_cost_baselines: Any = None,
    profit_target_pct: Any = None,
) -> dict[str, Any]:
    """Explain per-product planning, safety, and SELL lot authority details."""
    order_type_value = _coerce_sweep_order_type(order_type)
    if isinstance(safety_evaluation, SpotPortfolioSweepSafetyEvaluation):
        safety = safety_evaluation.to_dict()
    else:
        safety = dict(safety_evaluation or {})
    violations_by_product: dict[str, list[dict[str, Any]]] = {}
    for violation in safety.get("violations") or []:
        if not isinstance(violation, Mapping):
            continue
        product_id = _text(violation.get("product_id"))
        if product_id:
            violations_by_product.setdefault(product_id, []).append(dict(violation))

    items: list[dict[str, Any]] = []
    for item in plan.items:
        row = {
            "product_id": item.product_id,
            "side": item.side,
            "status": item.status,
            "skip_reason": item.skip_reason,
            "requested_quote_notional": item.requested_quote_notional,
            "estimated_price": item.estimated_price,
            "estimated_quote_notional": item.estimated_quote_notional,
            "planned_quote_size": item.planned_quote_size,
            "planned_base_size": item.planned_base_size,
            "balance_currency": item.balance_currency,
            "available_balance": item.available_balance,
            "reason": item.reason,
            "safety_violations": violations_by_product.get(item.product_id, []),
        }
        if (
            plan.side == OrderSide.SELL.value
            and item.status == SpotPortfolioSweepItemStatus.PLANNED.value
        ):
            try:
                authority_price = _planned_item_sell_authority_price(
                    item,
                    order_type=order_type_value,
                    limit_price_offset_bps=limit_price_offset_bps,
                )
                row["sell_authority"] = _evaluate_sweep_sell_lot_authority(
                    item=item,
                    fill_ledger_repo=fill_ledger_repo,
                    inventory_baselines=inventory_baselines,
                    coinbase_average_cost_baselines=(
                        coinbase_average_cost_baselines
                    ),
                    allow_coinbase_average_cost_basis=bool(
                        (safety.get("policy") or {}).get(
                            "allow_coinbase_average_cost_basis",
                            False,
                        )
                    ),
                    coinbase_average_cost_profit_buffer_pct=(
                        (safety.get("policy") or {}).get(
                            "coinbase_average_cost_profit_buffer_pct",
                            "0.5",
                        )
                    ),
                    profit_target_pct=profit_target_pct,
                    submitted_price=authority_price,
                )
            except Exception as exc:
                row["sell_authority"] = {
                    "allowed": False,
                    "status": InventoryAuthorityStatus.UNAVAILABLE.value,
                    "product_id": item.product_id,
                    "reason": _value_blind_exception_detail(exc),
                }
        items.append(row)

    return {
        "generated_at": plan.generated_at,
        "side": plan.side,
        "quote_currency": plan.quote_currency,
        "order_type": order_type_value,
        "limit_price_offset_bps": _format_decimal(
            _decimal(limit_price_offset_bps)
        ) or "0",
        "requested_quote_notional": plan.requested_quote_notional,
        "planned_count": len(plan.planned_items),
        "skipped_count": len(plan.skipped_items),
        "estimated_planned_quote_notional": (
            plan.to_dict().get("estimated_planned_quote_notional") or "0"
        ),
        "safety_decision": safety.get("decision"),
        "safety_violation_count": len(safety.get("violations") or []),
        "items": items,
    }


def _coinbase_average_cost_authority_products(
    plan_explain: Mapping[str, Any] | None,
) -> list[str]:
    product_ids: list[str] = []
    for item in (plan_explain or {}).get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if _text(item.get("status")) != SpotPortfolioSweepItemStatus.PLANNED.value:
            continue
        authority = item.get("sell_authority")
        if not isinstance(authority, Mapping):
            continue
        if authority.get("allowed") is not True:
            continue
        if (
            _text(authority.get("cost_basis_authority"))
            != SpotCostBasisSource.COINBASE_AVERAGE_COST.value
        ):
            continue
        product_id = _text(item.get("product_id")).upper()
        if product_id and product_id not in product_ids:
            product_ids.append(product_id)
    return product_ids


def apply_coinbase_average_cost_authority_gate(
    *,
    safety: Mapping[str, Any],
    plan_explain: Mapping[str, Any] | None = None,
    coinbase_average_cost_records: Iterable[Mapping[str, Any]] | None = None,
    cost_basis_drift_audit: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    max_age_seconds: int = DEFAULT_COINBASE_AVERAGE_COST_AUTHORITY_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Block stale Coinbase average-cost rows when they provide SELL authority."""
    updated = dict(safety)
    updated["violations"] = [dict(item) for item in updated.get("violations") or []]
    policy = updated.get("policy") or {}
    if not bool(policy.get("allow_coinbase_average_cost_basis")):
        return updated

    timestamp = generated_at or datetime.now(timezone.utc)
    authority_products = _coinbase_average_cost_authority_products(plan_explain)
    records_by_product = {
        _text(record.get("product_id")).upper(): dict(record)
        for record in coinbase_average_cost_records or []
        if isinstance(record, Mapping) and _text(record.get("product_id"))
    }
    drift_by_product = {
        _text(row.get("product_id")).upper(): dict(row)
        for row in (cost_basis_drift_audit or {}).get("products") or []
        if isinstance(row, Mapping) and _text(row.get("product_id"))
    }

    gate_violations: list[dict[str, Any]] = []
    for product_id in authority_products:
        record = records_by_product.get(product_id)
        parsed_generated_at = (
            _parse_baseline_timestamp(record.get("generated_at"))
            if record
            else None
        )
        if not record:
            gate_violations.append({
                "code": "coinbase_average_cost_freshness",
                "product_id": product_id,
                "status": SpotCostBasisStatus.MISSING_POSITION.value,
                "reason": (
                    "Coinbase average cost authority is selected but no "
                    "average-cost record exists for this product"
                ),
            })
        elif parsed_generated_at is None:
            gate_violations.append({
                "code": "coinbase_average_cost_freshness",
                "product_id": product_id,
                "status": SpotCostBasisStatus.UNAVAILABLE.value,
                "generated_at": record.get("generated_at"),
                "reason": "Coinbase average cost record has invalid freshness metadata",
            })
        else:
            age_seconds = max(0, int((timestamp - parsed_generated_at).total_seconds()))
            if age_seconds > max_age_seconds:
                gate_violations.append({
                    "code": "coinbase_average_cost_freshness",
                    "product_id": product_id,
                    "status": SpotCostBasisStatus.STALE.value,
                    "generated_at": record.get("generated_at"),
                    "age_seconds": age_seconds,
                    "max_age_seconds": max_age_seconds,
                    "reason": (
                        "Coinbase average cost authority record is stale for "
                        "live SELL authorization"
                    ),
                })

        drift = drift_by_product.get(product_id)
        if drift and drift.get("status") == SpotCostBasisStatus.STALE.value:
            gate_violations.append({
                "code": "coinbase_average_cost_drift",
                "product_id": product_id,
                "status": SpotCostBasisStatus.STALE.value,
                "drift_pct": drift.get("drift_pct"),
                "warning_threshold_pct": drift.get("warning_threshold_pct"),
                "reason": (
                    "Coinbase average cost authority has stale drift against "
                    "local fill-ledger lots"
                ),
            })

    gate = {
        "required": True,
        "decision": (
            SpotPortfolioSweepSafetyDecision.BLOCKED.value
            if gate_violations
            else SpotPortfolioSweepSafetyDecision.ALLOWED.value
        ),
        "authority_product_count": len(authority_products),
        "authority_products": authority_products,
        "max_age_seconds": max_age_seconds,
        "violations": gate_violations,
    }
    updated["coinbase_average_cost_authority_gate"] = gate
    if gate_violations:
        updated["decision"] = SpotPortfolioSweepSafetyDecision.BLOCKED.value
        updated["violations"].extend(gate_violations)
    return updated


def build_sweep_config_id(
    *,
    side: str,
    quote_notional: Any,
    max_products: int | None,
    order_type: str | SpotPortfolioSweepOrderType = (
        SpotPortfolioSweepOrderType.MARKET_IOC
    ),
    limit_price_offset_bps: Any = 0,
    allow_products: Iterable[Any] | None = None,
    deny_products: Iterable[Any] | None = None,
) -> str:
    payload = {
        "side": _text(side).upper(),
        "quote_notional": _format_decimal(_decimal(quote_notional)),
        "max_products": max_products,
        "quote_currency": QUOTE_CURRENCY,
    }
    allowed = sorted(_product_filter_set(allow_products))
    denied = sorted(_product_filter_set(deny_products))
    if allowed:
        payload["allow_products"] = allowed
    if denied:
        payload["deny_products"] = denied
    order_type_value = _coerce_sweep_order_type(order_type)
    offset_text = _format_decimal(_decimal(limit_price_offset_bps)) or "0"
    if (
        order_type_value != SpotPortfolioSweepOrderType.MARKET_IOC.value
        or _decimal(offset_text) != 0
    ):
        payload["order_type"] = order_type_value
        payload["limit_price_offset_bps"] = offset_text
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"spot-sweep-{digest[:16]}"


def load_sweep_run_records(state_file: str | Path) -> list[dict[str, Any]]:
    path = Path(state_file)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def append_sweep_run_record(
    state_file: str | Path,
    record: Mapping[str, Any],
) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True))
        handle.write("\n")


def _record_config_id(record: Mapping[str, Any]) -> str:
    return str(record.get("config_id") or "")


def _record_started_at(record: Mapping[str, Any]) -> datetime | None:
    raw = record.get("started_at") or record.get("created_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_run_attempt(record: Mapping[str, Any]) -> bool:
    return record.get("record_type") == "sweep_run" and record.get("status") in {
        SpotPortfolioSweepRunStatus.COMPLETED.value,
        SpotPortfolioSweepRunStatus.PARTIAL.value,
        SpotPortfolioSweepRunStatus.FAILED.value,
    }


def evaluate_sweep_automation_due(
    *,
    config_id: str,
    repeat_every_hours: Any,
    max_runs: int,
    records: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether a recurring sweep config is due for one run."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    interval_hours = _decimal(repeat_every_hours)
    if interval_hours <= 0:
        raise ValueError("repeat_every_hours must be greater than 0")
    if max_runs <= 0:
        raise ValueError("max_runs must be greater than 0")

    matching = [
        record for record in records if _record_config_id(record) == config_id
    ]
    disabled_records = [
        record
        for record in matching
        if record.get("record_type") == "automation_disabled"
        or record.get("status") == SpotPortfolioSweepRunStatus.DISABLED.value
    ]
    disabled_times = [
        disabled_at
        for disabled_at in (_record_started_at(record) for record in disabled_records)
        if disabled_at is not None
    ]
    latest_disabled_at = max(disabled_times, default=None)
    attempts = [
        record
        for record in matching
        if _is_run_attempt(record)
        and (
            latest_disabled_at is None
            or (_record_started_at(record) or datetime.min.replace(tzinfo=timezone.utc))
            > latest_disabled_at
        )
    ]
    if latest_disabled_at is not None:
        return {
            "decision": SpotPortfolioSweepAutomationDecision.DISABLED.value,
            "reason": "automation disabled for this config_id",
            "attempt_count": len(attempts),
            "max_runs": max_runs,
            "next_run_at": None,
        }
    if len(attempts) >= max_runs:
        return {
            "decision": SpotPortfolioSweepAutomationDecision.MAX_RUNS_REACHED.value,
            "reason": "max_runs has already been reached",
            "attempt_count": len(attempts),
            "max_runs": max_runs,
            "next_run_at": None,
        }
    started_times = [
        started_at for started_at in (_record_started_at(record) for record in attempts)
        if started_at is not None
    ]
    if not started_times:
        return {
            "decision": SpotPortfolioSweepAutomationDecision.DUE.value,
            "reason": "no prior run attempt exists",
            "attempt_count": len(attempts),
            "max_runs": max_runs,
            "next_run_at": now.isoformat(),
        }
    last_started_at = max(started_times)
    next_run_at = last_started_at + timedelta(hours=float(interval_hours))
    if now >= next_run_at:
        return {
            "decision": SpotPortfolioSweepAutomationDecision.DUE.value,
            "reason": "repeat interval elapsed",
            "attempt_count": len(attempts),
            "max_runs": max_runs,
            "last_started_at": last_started_at.isoformat(),
            "next_run_at": now.isoformat(),
        }
    return {
        "decision": SpotPortfolioSweepAutomationDecision.NOT_DUE.value,
        "reason": "repeat interval has not elapsed",
        "attempt_count": len(attempts),
        "max_runs": max_runs,
        "last_started_at": last_started_at.isoformat(),
        "next_run_at": next_run_at.isoformat(),
    }


def build_sweep_run_record(
    *,
    config_id: str,
    run_id: str,
    status: str,
    started_at: datetime,
    completed_at: datetime,
    config: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
    execution: Mapping[str, Any] | None = None,
    automation_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "record_type": "sweep_run",
        "config_id": config_id,
        "run_id": run_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "config": dict(config),
        "plan": dict(plan or {}),
        "execution": dict(execution or {}),
        "automation_decision": dict(automation_decision or {}),
    }


def build_sweep_disabled_record(
    *,
    config_id: str,
    config: Mapping[str, Any],
    disabled_at: datetime | None = None,
) -> dict[str, Any]:
    disabled_at = disabled_at or datetime.now(timezone.utc)
    return {
        "record_type": "automation_disabled",
        "config_id": config_id,
        "status": SpotPortfolioSweepRunStatus.DISABLED.value,
        "started_at": disabled_at.isoformat(),
        "completed_at": disabled_at.isoformat(),
        "config": dict(config),
    }


def _fill_ledger_comparison_for_order(
    *,
    fill_ledger_repo: Any,
    client_order_id: str | None,
    rest_base_size: Decimal,
    rest_notional: Decimal,
) -> dict[str, Any]:
    if fill_ledger_repo is None:
        return {"status": SpotSweepFillLedgerMatchStatus.UNCHECKED.value}
    if not client_order_id:
        return {
            "status": SpotSweepFillLedgerMatchStatus.UNAVAILABLE.value,
            "reason": "client_order_id is required for fill-ledger comparison",
        }
    getter = getattr(fill_ledger_repo, "get_fills_by_order", None)
    if not callable(getter):
        return {
            "status": SpotSweepFillLedgerMatchStatus.UNAVAILABLE.value,
            "reason": "fill ledger repository does not expose get_fills_by_order",
        }
    fills = getter(client_order_id) or []
    local_base_size = sum(
        (_fill_quantity(fill) for fill in fills),
        Decimal("0"),
    )
    local_notional = sum(
        (_fill_quantity(fill) * _fill_price(fill) for fill in fills),
        Decimal("0"),
    )
    base_tolerance = Decimal("0.00000001")
    notional_tolerance = max(
        Decimal("0.00000001"),
        abs(rest_notional) * Decimal("0.0001"),
    )
    matched = (
        abs(local_base_size - rest_base_size) <= base_tolerance
        and abs(local_notional - rest_notional) <= notional_tolerance
    )
    return {
        "status": (
            SpotSweepFillLedgerMatchStatus.MATCHED.value
            if matched
            else SpotSweepFillLedgerMatchStatus.MISMATCH.value
        ),
        "local_fill_count": len(fills),
        "local_base_size": _format_decimal(local_base_size) or "0",
        "local_notional_usdc": _format_decimal(local_notional) or "0",
        "rest_base_size": _format_decimal(rest_base_size) or "0",
        "rest_notional_usdc": _format_decimal(rest_notional) or "0",
    }


def _unavailable_fill_ledger_match(reason: str) -> dict[str, Any]:
    return {
        "status": SpotSweepFillLedgerMatchStatus.UNAVAILABLE.value,
        "reason": reason,
    }


def reconcile_sweep_run_record(
    *,
    record: Mapping[str, Any],
    rest_client: Any,
    fill_ledger_repo: Any = None,
    reconciled_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable reconciliation record for one sweep run."""
    reconciled_at = reconciled_at or datetime.now(timezone.utc)
    execution = record.get("execution") if isinstance(record, Mapping) else {}
    orders = (
        execution.get("orders")
        if isinstance(execution, Mapping)
        else []
    ) or []
    reconciled_orders: list[dict[str, Any]] = []
    status_counts = {
        status.value: 0 for status in SpotPortfolioSweepReconciliationStatus
    }
    fill_ledger_status_counts = {
        status.value: 0 for status in SpotSweepFillLedgerMatchStatus
    }
    total_executed = Decimal("0")
    total_base_size = Decimal("0")

    for order_record in orders:
        if not isinstance(order_record, Mapping):
            continue
        product_id = _text(order_record.get("product_id"))
        client_order_id = _text(order_record.get("client_order_id")) or None
        exchange_order_id = _text(order_record.get("exchange_order_id")) or None
        base_result = {
            "product_id": product_id,
            "side": order_record.get("side"),
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "recorded_status": order_record.get("status"),
            "recorded_executed_notional_usdc": (
                order_record.get("executed_notional_usdc") or "0"
            ),
        }

        if not exchange_order_id:
            status = SpotPortfolioSweepReconciliationStatus.NOT_SUBMITTED.value
            status_counts[status] += 1
            fill_ledger_match = (
                {"status": SpotSweepFillLedgerMatchStatus.UNCHECKED.value}
                if fill_ledger_repo is None
                else _unavailable_fill_ledger_match(
                    "exchange_order_id is required for fill-ledger comparison"
                )
            )
            fill_ledger_status_counts[fill_ledger_match["status"]] += 1
            reconciled_orders.append({
                **base_result,
                "reconciliation_status": status,
                "client_order_id_match": None,
                "exchange_status": None,
                "reconciled_base_size": "0",
                "reconciled_executed_notional_usdc": "0",
                "fill_ledger_match": fill_ledger_match,
            })
            continue

        try:
            live_order = _get_order(rest_client, exchange_order_id)
            if not live_order:
                status = (
                    SpotPortfolioSweepReconciliationStatus
                    .MISSING_EXCHANGE_ORDER
                    .value
                )
                status_counts[status] += 1
                fill_ledger_match = (
                    {"status": SpotSweepFillLedgerMatchStatus.UNCHECKED.value}
                    if fill_ledger_repo is None
                    else _unavailable_fill_ledger_match(
                        "exchange order is missing from Coinbase"
                    )
                )
                fill_ledger_status_counts[fill_ledger_match["status"]] += 1
                reconciled_orders.append({
                    **base_result,
                    "reconciliation_status": status,
                    "client_order_id_match": False,
                    "exchange_status": None,
                    "reconciled_base_size": "0",
                    "reconciled_executed_notional_usdc": "0",
                    "fill_ledger_match": fill_ledger_match,
                })
                continue

            live_client_order_id = (
                _text(_get_value(live_order, "client_order_id"))
                or _text(
                    _get_value(
                        live_order.get("success_response", {})
                        if isinstance(live_order, Mapping)
                        else {},
                        "client_order_id",
                    )
                )
                or None
            )
            client_order_id_match = (
                None
                if not live_client_order_id or not client_order_id
                else live_client_order_id == client_order_id
            )
            fill_size, fill_notional = fetch_sweep_order_executed_notional(
                rest_client,
                order_id=exchange_order_id,
                product_id=product_id,
                fallback_order=live_order,
            )
            total_base_size += fill_size
            total_executed += fill_notional
            status = (
                SpotPortfolioSweepReconciliationStatus
                .CLIENT_ORDER_ID_MISMATCH
                .value
                if client_order_id_match is False
                else SpotPortfolioSweepReconciliationStatus.MATCHED.value
            )
            status_counts[status] += 1
            fill_ledger_match = _fill_ledger_comparison_for_order(
                fill_ledger_repo=fill_ledger_repo,
                client_order_id=client_order_id,
                rest_base_size=fill_size,
                rest_notional=fill_notional,
            )
            fill_ledger_status_counts[fill_ledger_match["status"]] += 1
            reconciled_orders.append({
                **base_result,
                "reconciliation_status": status,
                "client_order_id_match": client_order_id_match,
                "exchange_client_order_id": live_client_order_id,
                "exchange_status": _sanitized_exchange_status(
                    live_order.get("status")
                ),
                "reconciled_base_size": _format_decimal(fill_size) or "0",
                "reconciled_executed_notional_usdc": (
                    _format_decimal(fill_notional) or "0"
                ),
                "fill_ledger_match": fill_ledger_match,
            })
        except Exception as exc:
            status = SpotPortfolioSweepReconciliationStatus.FETCH_ERROR.value
            status_counts[status] += 1
            fill_ledger_match = (
                {"status": SpotSweepFillLedgerMatchStatus.UNCHECKED.value}
                if fill_ledger_repo is None
                else _unavailable_fill_ledger_match(
                    "Coinbase order/fill fetch failed before comparison"
                )
            )
            fill_ledger_status_counts[fill_ledger_match["status"]] += 1
            reconciled_orders.append({
                **base_result,
                "reconciliation_status": status,
                "client_order_id_match": None,
                "exchange_status": None,
                "reconciled_base_size": "0",
                "reconciled_executed_notional_usdc": "0",
                "fill_ledger_match": fill_ledger_match,
                "error": _value_blind_exception_detail(exc),
            })

    return {
        "record_type": "sweep_reconciliation",
        "config_id": record.get("config_id"),
        "run_id": record.get("run_id"),
        "status": (
            SpotPortfolioSweepRunStatus.COMPLETED.value
            if not status_counts[
                SpotPortfolioSweepReconciliationStatus.FETCH_ERROR.value
            ]
            and not status_counts[
                SpotPortfolioSweepReconciliationStatus.CLIENT_ORDER_ID_MISMATCH.value
            ]
            and not status_counts[
                SpotPortfolioSweepReconciliationStatus.MISSING_EXCHANGE_ORDER.value
            ]
            else SpotPortfolioSweepRunStatus.PARTIAL.value
        ),
        "created_at": reconciled_at.isoformat(),
        "summary": {
            "order_count": len(reconciled_orders),
            "status_counts": status_counts,
            "fill_ledger_status_counts": fill_ledger_status_counts,
            "total_reconciled_base_size": _format_decimal(total_base_size) or "0",
            "total_reconciled_executed_notional_usdc": (
                _format_decimal(total_executed) or "0"
            ),
        },
        "orders": reconciled_orders,
    }


def build_sweep_recovery_record(
    *,
    plan: Mapping[str, Any],
    status: str | SpotSweepRecoveryGateStatus,
    failures: Iterable[Any] | None = None,
    summary: Mapping[str, Any] | None = None,
    config_id: str | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable summary of a sweep recovery gate run."""
    created_at = created_at or datetime.now(timezone.utc)
    failures = [_text(failure) for failure in (failures or [])]
    status_value = _enum_value(status)
    return {
        "record_type": SpotAuditRecordType.SWEEP_RECOVERY.value,
        "config_id": config_id or plan.get("config_id"),
        "run_id": run_id or plan.get("run_id"),
        "status": status_value,
        "created_at": created_at.isoformat(),
        "summary": {
            "failure_count": len(failures),
            "planned_reconciliation_run_count": int(
                plan.get("planned_reconciliation_run_count") or 0
            ),
            "planned_backfill_order_count": int(
                plan.get("planned_backfill_order_count") or 0
            ),
            **dict(summary or {}),
        },
        "failures": failures,
        "plan": {
            key: plan.get(key)
            for key in (
                "state_file",
                "run_id",
                "config_id",
                "sweep_run_count",
                "runs_needing_reconciliation",
                "runs_needing_backfill",
                "planned_reconciliation_run_count",
                "candidate_backfill_order_count",
                "planned_backfill_order_count",
            )
        },
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_sweep_operator_status(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Summarize durable sweep ledger state for dashboard/operator surfaces."""
    generated_at = generated_at or datetime.now(timezone.utc)
    configs: dict[str, dict[str, Any]] = {}

    for record in records:
        config_id = _record_config_id(record)
        if not config_id:
            continue
        entry = configs.setdefault(
            config_id,
            {
                "config_id": config_id,
                "config": record.get("config") or {},
                "run_count": 0,
                "submitted_order_count": 0,
                "blocked_or_error_count": 0,
                "total_submitted_notional_usdc": Decimal("0"),
                "total_executed_notional_usdc": Decimal("0"),
                "disabled": False,
                "latest_run": None,
                "latest_reconciliation": None,
                "latest_recovery": None,
                "recent_runs": [],
            },
        )
        if record.get("config"):
            entry["config"] = record.get("config") or {}
        if (
            record.get("record_type") == "automation_disabled"
            or record.get("status") == SpotPortfolioSweepRunStatus.DISABLED.value
        ):
            entry["disabled"] = True
            entry["disabled_at"] = (
                record.get("started_at") or record.get("completed_at")
            )
            continue
        if record.get("record_type") == "sweep_reconciliation":
            latest = entry.get("latest_reconciliation")
            if latest is None or _timestamp_key(record.get("created_at")) >= (
                _timestamp_key(latest.get("created_at"))
            ):
                entry["latest_reconciliation"] = {
                    "created_at": record.get("created_at"),
                    "status": record.get("status"),
                    "summary": record.get("summary") or {},
                }
            continue
        if record.get("record_type") == SpotAuditRecordType.SWEEP_RECOVERY.value:
            latest = entry.get("latest_recovery")
            if latest is None or _timestamp_key(record.get("created_at")) >= (
                _timestamp_key(latest.get("created_at"))
            ):
                entry["latest_recovery"] = {
                    "created_at": record.get("created_at"),
                    "status": record.get("status"),
                    "summary": record.get("summary") or {},
                }
            continue
        if record.get("record_type") != "sweep_run":
            continue

        entry["run_count"] += 1
        execution = record.get("execution") or {}
        execution_orders = list(execution.get("orders") or [])
        effective_outcome = (
            summarize_sweep_order_statuses(execution_orders)
            if execution_orders
            else {}
        )
        effective_status = (
            effective_outcome.get("run_status") or record.get("status")
        )
        effective_submitted_count = int(
            effective_outcome.get("submitted_order_count")
            if effective_outcome
            else execution.get("submitted_order_count") or 0
        )
        effective_blocked_or_error_count = int(
            effective_outcome.get("blocked_or_error_count")
            if effective_outcome
            else execution.get("blocked_or_error_count") or 0
        )
        effective_skipped_count = int(
            effective_outcome.get("skipped_order_count")
            if effective_outcome
            else execution.get("skipped_order_count") or 0
        )
        entry["submitted_order_count"] += effective_submitted_count
        entry["blocked_or_error_count"] += effective_blocked_or_error_count
        entry["total_submitted_notional_usdc"] += _decimal(
            execution.get("total_submitted_notional_usdc")
        )
        entry["total_executed_notional_usdc"] += _decimal(
            execution.get("total_executed_notional_usdc")
        )
        entry["recent_runs"].append({
            "run_id": record.get("run_id"),
            "status": effective_status,
            "recorded_status": record.get("status"),
            "started_at": record.get("started_at"),
            "completed_at": record.get("completed_at"),
            "submitted_order_count": effective_submitted_count,
            "blocked_or_error_count": effective_blocked_or_error_count,
            "skipped_order_count": effective_skipped_count,
            "total_submitted_notional_usdc": (
                execution.get("total_submitted_notional_usdc")
            ),
            "total_executed_notional_usdc": (
                execution.get("total_executed_notional_usdc")
            ),
            "fill_backfill": execution.get("fill_backfill") or {},
            "orders": list(execution.get("orders") or [])[:10],
        })
        latest = entry.get("latest_run")
        if latest is None or _timestamp_key(record.get("started_at")) >= (
            _timestamp_key(latest.get("started_at"))
        ):
            entry["latest_run"] = {
                "run_id": record.get("run_id"),
                "status": effective_status,
                "recorded_status": record.get("status"),
                "started_at": record.get("started_at"),
                "completed_at": record.get("completed_at"),
                "automation_decision": record.get("automation_decision") or {},
                "plan": {
                    key: (record.get("plan") or {}).get(key)
                    for key in (
                        "planned_count",
                        "skipped_count",
                        "estimated_planned_quote_notional",
                    )
                },
                "execution": {
                    "submitted_order_count": effective_submitted_count,
                    "blocked_or_error_count": effective_blocked_or_error_count,
                    "skipped_order_count": effective_skipped_count,
                    "total_submitted_notional_usdc": (
                        execution.get("total_submitted_notional_usdc")
                    ),
                    "total_executed_notional_usdc": (
                        execution.get("total_executed_notional_usdc")
                    ),
                },
                "fill_backfill": execution.get("fill_backfill") or {},
                "orders": list(execution.get("orders") or [])[:10],
            }

    output_configs = []
    total_submitted = Decimal("0")
    total_executed = Decimal("0")
    for entry in sorted(configs.values(), key=lambda item: item["config_id"]):
        submitted = entry.pop("total_submitted_notional_usdc")
        executed = entry.pop("total_executed_notional_usdc")
        total_submitted += submitted
        total_executed += executed
        entry["total_submitted_notional_usdc"] = (
            _format_decimal(submitted) or "0"
        )
        entry["total_executed_notional_usdc"] = _format_decimal(executed) or "0"
        entry["recent_runs"] = sorted(
            entry.get("recent_runs") or [],
            key=lambda run: _timestamp_key(run.get("started_at")),
            reverse=True,
        )[:5]
        output_configs.append(entry)

    return {
        "generated_at": generated_at.isoformat(),
        "config_count": len(output_configs),
        "run_count": sum(config["run_count"] for config in output_configs),
        "submitted_order_count": sum(
            config["submitted_order_count"] for config in output_configs
        ),
        "blocked_or_error_count": sum(
            config["blocked_or_error_count"] for config in output_configs
        ),
        "total_submitted_notional_usdc": _format_decimal(total_submitted) or "0",
        "total_executed_notional_usdc": _format_decimal(total_executed) or "0",
        "configs": output_configs,
    }


def build_sweep_config_registry(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an operator-facing registry of configured sweep automations."""
    status = build_sweep_operator_status(records=records, generated_at=generated_at)
    configs = []
    for config in status.get("configs") or []:
        latest_run = config.get("latest_run") or {}
        latest_reconciliation = config.get("latest_reconciliation") or {}
        latest_recovery = config.get("latest_recovery") or {}
        configs.append({
            "config_id": config.get("config_id"),
            "disabled": bool(config.get("disabled")),
            "run_count": int(config.get("run_count") or 0),
            "submitted_order_count": int(config.get("submitted_order_count") or 0),
            "blocked_or_error_count": int(
                config.get("blocked_or_error_count") or 0
            ),
            "total_submitted_notional_usdc": (
                config.get("total_submitted_notional_usdc") or "0"
            ),
            "total_executed_notional_usdc": (
                config.get("total_executed_notional_usdc") or "0"
            ),
            "latest_run_id": latest_run.get("run_id"),
            "latest_run_status": latest_run.get("status"),
            "latest_started_at": latest_run.get("started_at"),
            "latest_reconciliation_status": latest_reconciliation.get("status"),
            "latest_reconciliation_at": latest_reconciliation.get("created_at"),
            "latest_recovery_status": latest_recovery.get("status"),
            "latest_recovery_at": latest_recovery.get("created_at"),
            "latest_fill_backfill": latest_run.get("fill_backfill") or {},
            "config": config.get("config") or {},
        })
    disabled_count = len([config for config in configs if config["disabled"]])
    return {
        "generated_at": status["generated_at"],
        "config_count": len(configs),
        "active_config_count": len(configs) - disabled_count,
        "disabled_config_count": disabled_count,
        "run_count": status["run_count"],
        "submitted_order_count": status["submitted_order_count"],
        "blocked_or_error_count": status["blocked_or_error_count"],
        "total_submitted_notional_usdc": status["total_submitted_notional_usdc"],
        "total_executed_notional_usdc": status["total_executed_notional_usdc"],
        "configs": configs,
    }


def _inventory_lot_quantities(
    *,
    fill_ledger_repo: Any,
    product_id: str,
    inventory_baselines: Any = None,
) -> dict[str, Any]:
    if fill_ledger_repo is None:
        return {
            "available": False,
            "known_quantity": Decimal("0"),
            "unknown_cost_basis_quantity": Decimal("0"),
            "error": "fill ledger repository is unavailable",
        }
    try:
        from business.lot_builder import PositionLotBuilder

        position = PositionLotBuilder(
            fill_ledger_repo,
            inventory_baselines=inventory_baselines,
        ).build_position_by_product(product_id, side=OrderSide.BUY)
    except Exception as exc:
        return {
            "available": False,
            "known_quantity": Decimal("0"),
            "unknown_cost_basis_quantity": Decimal("0"),
            "error": _value_blind_exception_detail(exc),
        }

    known = Decimal("0")
    unknown = Decimal("0")
    for lot in position.get_unexited_lots():
        remaining = _decimal(_get_value(lot, "remaining_quantity"))
        if remaining <= 0:
            continue
        cost_basis_status = _enum_value(_get_value(lot, "cost_basis_status"))
        if cost_basis_status == InventoryCostBasisStatus.KNOWN.value:
            known += remaining
        else:
            unknown += remaining
    return {
        "available": True,
        "known_quantity": known,
        "unknown_cost_basis_quantity": unknown,
        "error": None,
    }


def _inventory_baseline_entries(inventory_baselines: Any) -> list[dict[str, Any]]:
    raw = inventory_baselines or []
    if isinstance(raw, Mapping):
        nested = raw.get("lots") or raw.get("baselines")
        if isinstance(nested, list):
            raw = nested
        else:
            flattened: list[Any] = []
            for value in raw.values():
                if isinstance(value, list):
                    flattened.extend(value)
                elif isinstance(value, Mapping):
                    flattened.append(value)
            raw = flattened
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        return []

    entries: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            entries.append(dict(entry))
    return entries


def _baseline_freshness_timestamp(
    entry: Mapping[str, Any],
) -> tuple[str | None, Any]:
    for field_name in BASELINE_FRESHNESS_TIMESTAMP_FIELDS:
        value = entry.get(field_name)
        if _text(value):
            return field_name, value
    return None, None


def _parse_baseline_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_spot_inventory_baseline_freshness_audit(
    *,
    inventory_baselines: Any = None,
    generated_at: datetime | None = None,
    max_age_seconds: int = DEFAULT_INVENTORY_BASELINE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Report whether imported baseline inventory carries fresh source metadata."""
    timestamp = generated_at or datetime.now(timezone.utc)
    entries = _inventory_baseline_entries(inventory_baselines)
    status_counts = {
        status.value: 0 for status in SpotInventoryBaselineFreshness
    }
    rows: list[dict[str, Any]] = []

    for index, entry in enumerate(entries):
        timestamp_field, raw_timestamp = _baseline_freshness_timestamp(entry)
        parsed_timestamp = _parse_baseline_timestamp(raw_timestamp)
        if timestamp_field is None:
            status = SpotInventoryBaselineFreshness.MISSING_TIMESTAMP
            age_seconds = None
        elif parsed_timestamp is None:
            status = SpotInventoryBaselineFreshness.INVALID_TIMESTAMP
            age_seconds = None
        else:
            age_seconds = max(0, int((timestamp - parsed_timestamp).total_seconds()))
            status = (
                SpotInventoryBaselineFreshness.STALE
                if age_seconds > max_age_seconds
                else SpotInventoryBaselineFreshness.FRESH
            )

        status_counts[status.value] += 1
        source_id = entry.get("source_id") or entry.get("lot_id") or index
        product_id = _text(
            entry.get("product_id")
            or entry.get("instrument")
            or entry.get("symbol")
        ).upper()
        rows.append({
            "product_id": product_id,
            "source_id": _text(source_id),
            "lot_source": _text(
                entry.get("lot_source")
                or entry.get("source")
                or InventoryLotSource.IMPORTED_BASELINE.value
            ).lower(),
            "freshness_status": status.value,
            "timestamp_field": timestamp_field,
            "timestamp": _iso_timestamp(raw_timestamp),
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
            "remaining_quantity": _format_decimal(
                _decimal(entry.get("remaining_quantity", entry.get("quantity")))
            ) or "0",
            "cost_basis_status": _text(
                entry.get("cost_basis_status") or InventoryCostBasisStatus.UNKNOWN.value
            ).lower(),
        })

    if not rows:
        status = SpotInventoryBaselineFreshness.NOT_CONFIGURED
        status_counts[status.value] = 1
    elif status_counts[SpotInventoryBaselineFreshness.INVALID_TIMESTAMP.value]:
        status = SpotInventoryBaselineFreshness.INVALID_TIMESTAMP
    elif status_counts[SpotInventoryBaselineFreshness.MISSING_TIMESTAMP.value]:
        status = SpotInventoryBaselineFreshness.MISSING_TIMESTAMP
    elif status_counts[SpotInventoryBaselineFreshness.STALE.value]:
        status = SpotInventoryBaselineFreshness.STALE
    else:
        status = SpotInventoryBaselineFreshness.FRESH

    return {
        "generated_at": timestamp.isoformat(),
        "freshness_status": status.value,
        "max_age_seconds": max_age_seconds,
        "baseline_count": len(rows),
        "fresh_count": status_counts[SpotInventoryBaselineFreshness.FRESH.value],
        "stale_count": status_counts[SpotInventoryBaselineFreshness.STALE.value],
        "missing_timestamp_count": status_counts[
            SpotInventoryBaselineFreshness.MISSING_TIMESTAMP.value
        ],
        "invalid_timestamp_count": status_counts[
            SpotInventoryBaselineFreshness.INVALID_TIMESTAMP.value
        ],
        "status_counts": status_counts,
        "baselines": rows,
    }


def build_spot_inventory_coverage_report(
    *,
    fill_ledger_repo: Any,
    products: Iterable[Any],
    wallets: Mapping[str, Any] | None,
    inventory_baselines: Any = None,
    coinbase_average_costs: Iterable[Mapping[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare USDC spot wallet balances to local fill-ledger/baseline evidence."""
    from business.spot_cost_basis import average_cost_records_by_product

    timestamp = generated_at or datetime.now(timezone.utc)
    eligible_products = filter_usdc_spot_products(products)
    average_cost_by_product = average_cost_records_by_product(coinbase_average_costs)
    baseline_freshness_audit = build_spot_inventory_baseline_freshness_audit(
        inventory_baselines=inventory_baselines,
        generated_at=timestamp,
    )
    status_counts = {status.value: 0 for status in SpotInventoryCoverageStatus}
    rows: list[dict[str, Any]] = []
    wallet_balance_count = 0
    wallet_only_count = 0
    unknown_count = 0
    covered_count = 0
    coinbase_average_count = 0
    tolerance = Decimal("0.00000001")

    for product in eligible_products:
        product_id = _product_id(product)
        base_currency = _base_currency(product)
        wallet_available = _wallet_available(wallets, base_currency)
        if wallet_available > 0:
            wallet_balance_count += 1

        lot_quantities = _inventory_lot_quantities(
            fill_ledger_repo=fill_ledger_repo,
            product_id=product_id,
            inventory_baselines=inventory_baselines,
        )
        known_quantity = lot_quantities["known_quantity"]
        unknown_quantity = lot_quantities["unknown_cost_basis_quantity"]
        local_quantity = known_quantity + unknown_quantity
        average_cost_record = average_cost_by_product.get(product_id) or {}
        average_cost_quantity = _decimal(average_cost_record.get("quantity"))
        average_entry_price = _decimal(
            average_cost_record.get("average_entry_price")
        )
        uncovered_wallet_quantity = max(
            Decimal("0"),
            wallet_available - local_quantity,
        )
        local_excess_quantity = max(
            Decimal("0"),
            local_quantity - wallet_available,
        )

        if wallet_available <= 0:
            status = SpotInventoryCoverageStatus.NO_WALLET_BALANCE
            reason = "no wallet balance is available for this base currency"
            cost_basis_authority = SpotCostBasisSource.WALLET_ONLY.value
        elif not lot_quantities["available"]:
            status = SpotInventoryCoverageStatus.UNAVAILABLE
            reason = lot_quantities["error"]
            cost_basis_authority = SpotCostBasisSource.WALLET_ONLY.value
        elif known_quantity >= wallet_available - tolerance:
            status = SpotInventoryCoverageStatus.COVERED
            reason = "wallet balance is covered by known local inventory evidence"
            cost_basis_authority = SpotCostBasisSource.FILL_LEDGER.value
            covered_count += 1
        elif unknown_quantity > tolerance and local_quantity >= wallet_available - tolerance:
            status = SpotInventoryCoverageStatus.UNKNOWN_COST_BASIS
            reason = "wallet balance is covered only with unknown cost basis lots"
            cost_basis_authority = SpotCostBasisSource.IMPORTED_BASELINE.value
            unknown_count += 1
        elif (
            average_cost_record.get("status") == SpotCostBasisStatus.AVAILABLE.value
            and average_cost_quantity >= wallet_available - tolerance
            and average_entry_price > 0
        ):
            status = SpotInventoryCoverageStatus.COINBASE_AVERAGE_COST
            reason = (
                "wallet balance is covered by Coinbase average cost basis, "
                "not local lot evidence"
            )
            cost_basis_authority = SpotCostBasisSource.COINBASE_AVERAGE_COST.value
            coinbase_average_count += 1
        elif uncovered_wallet_quantity > tolerance:
            status = SpotInventoryCoverageStatus.WALLET_ONLY
            reason = (
                "wallet balance exceeds local fill-ledger and imported baseline "
                "inventory evidence"
            )
            cost_basis_authority = SpotCostBasisSource.WALLET_ONLY.value
            wallet_only_count += 1
        else:
            status = SpotInventoryCoverageStatus.COVERED
            reason = "wallet balance is covered by known local inventory evidence"
            cost_basis_authority = SpotCostBasisSource.FILL_LEDGER.value
            covered_count += 1

        status_counts[status.value] += 1
        rows.append({
            "product_id": product_id,
            "base_currency": base_currency,
            "quote_currency": QUOTE_CURRENCY,
            "coverage_status": status.value,
            "wallet_available": _format_decimal(wallet_available) or "0",
            "known_quantity": _format_decimal(known_quantity) or "0",
            "unknown_cost_basis_quantity": (
                _format_decimal(unknown_quantity) or "0"
            ),
            "coinbase_average_cost_quantity": (
                _format_decimal(average_cost_quantity) or "0"
            ),
            "coinbase_average_entry_price": (
                _format_decimal(average_entry_price) or "0"
            ),
            "local_evidence_quantity": _format_decimal(local_quantity) or "0",
            "uncovered_wallet_quantity": (
                _format_decimal(uncovered_wallet_quantity) or "0"
            ),
            "local_excess_quantity": _format_decimal(local_excess_quantity) or "0",
            "cost_basis_authority": cost_basis_authority,
            "reason": reason,
        })

    return {
        "generated_at": timestamp.isoformat(),
        "quote_currency": QUOTE_CURRENCY,
        "eligible_product_count": len(eligible_products),
        "wallet_balance_product_count": wallet_balance_count,
        "covered_product_count": covered_count,
        "coinbase_average_cost_product_count": coinbase_average_count,
        "unknown_cost_basis_product_count": unknown_count,
        "wallet_only_product_count": wallet_only_count,
        "status_counts": status_counts,
        "baseline_freshness_audit": baseline_freshness_audit,
        "products": rows,
    }


@dataclass(frozen=True)
class SpotPortfolioProductPnl:
    product_id: str
    buy_base_size: str
    sell_base_size: str
    net_base_size: str
    buy_notional: str
    sell_notional: str
    fees: str
    mark_price: str
    mark_price_available: bool
    mark_value: str
    cashflow: str
    total_pnl: str
    last_purchase_at: str | None
    since_last_purchase: dict[str, Any]
    realized_lot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "buy_base_size": self.buy_base_size,
            "sell_base_size": self.sell_base_size,
            "net_base_size": self.net_base_size,
            "buy_notional": self.buy_notional,
            "sell_notional": self.sell_notional,
            "fees": self.fees,
            "mark_price": self.mark_price,
            "mark_price_available": self.mark_price_available,
            "mark_value": self.mark_value,
            "cashflow": self.cashflow,
            "total_pnl": self.total_pnl,
            "last_purchase_at": self.last_purchase_at,
            "since_last_purchase": self.since_last_purchase,
            "realized_lot": self.realized_lot,
        }


@dataclass(frozen=True)
class SpotPortfolioPnlSnapshot:
    generated_at: str
    quote_currency: str
    scopes: tuple[str, ...]
    products: tuple[SpotPortfolioProductPnl, ...]

    def to_dict(self) -> dict[str, Any]:
        portfolio = {
            "scope": SpotPortfolioPnlScope.PORTFOLIO.value,
            "buy_notional": "0",
            "sell_notional": "0",
            "fees": "0",
            "mark_value": "0",
            "cashflow": "0",
            "total_pnl": "0",
        }
        totals = {key: Decimal("0") for key in portfolio if key != "scope"}
        realized_totals = {
            "matched_sell_base_size": Decimal("0"),
            "unmatched_sell_base_size": Decimal("0"),
            "open_base_size": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "realized_exit_count": 0,
        }
        for product in self.products:
            totals["buy_notional"] += _decimal(product.buy_notional)
            totals["sell_notional"] += _decimal(product.sell_notional)
            totals["fees"] += _decimal(product.fees)
            totals["mark_value"] += _decimal(product.mark_value)
            totals["cashflow"] += _decimal(product.cashflow)
            totals["total_pnl"] += _decimal(product.total_pnl)
            realized = product.realized_lot or {}
            realized_totals["matched_sell_base_size"] += _decimal(
                realized.get("matched_sell_base_size")
            )
            realized_totals["unmatched_sell_base_size"] += _decimal(
                realized.get("unmatched_sell_base_size")
            )
            realized_totals["open_base_size"] += _decimal(
                realized.get("open_base_size")
            )
            realized_totals["realized_pnl"] += _decimal(
                realized.get("realized_pnl")
            )
            realized_totals["realized_exit_count"] += int(
                realized.get("realized_exit_count") or 0
            )
        for key, value in totals.items():
            portfolio[key] = _format_decimal(value) or "0"
        portfolio["realized_lot"] = {
            "scope": SpotPortfolioPnlScope.REALIZED_LOT.value,
            "method": "fifo_known_cost_basis",
            "matched_sell_base_size": (
                _format_decimal(realized_totals["matched_sell_base_size"]) or "0"
            ),
            "unmatched_sell_base_size": (
                _format_decimal(realized_totals["unmatched_sell_base_size"]) or "0"
            ),
            "open_base_size": (
                _format_decimal(realized_totals["open_base_size"]) or "0"
            ),
            "realized_pnl": (
                _format_decimal(realized_totals["realized_pnl"]) or "0"
            ),
            "realized_exit_count": realized_totals["realized_exit_count"],
        }
        return {
            "generated_at": self.generated_at,
            "quote_currency": self.quote_currency,
            "scopes": list(self.scopes),
            "portfolio": portfolio,
            "products": [product.to_dict() for product in self.products],
        }


def _fill_product_id(fill: Any) -> str:
    return _text(_get_value(fill, "product_id")) or _text(
        _get_value(fill, "instrument")
    )


def _fill_side(fill: Any) -> str:
    return _text(_get_value(fill, "side")).upper()


def _fill_quantity(fill: Any) -> Decimal:
    return _decimal(_get_value(fill, "quantity", "size", "base_size"))


def _fill_price(fill: Any) -> Decimal:
    return _decimal(_get_value(fill, "average_price", "price"))


def _fill_fees(fill: Any) -> Decimal:
    return _decimal(_get_value(fill, "fees", "commission"))


def _fill_timestamp(fill: Any) -> Any:
    return _get_value(fill, "timestamp", "trade_time", "created_at")


def _build_realized_lot_pnl(*, fills: Iterable[Any]) -> dict[str, Any]:
    """Build FIFO realized P/L from known fill-ledger buys and sells."""
    open_lots: list[dict[str, Decimal]] = []
    matched_sell_base = Decimal("0")
    unmatched_sell_base = Decimal("0")
    realized_pnl = Decimal("0")
    realized_exit_count = 0

    for fill in sorted(fills, key=lambda item: _timestamp_key(_fill_timestamp(item))):
        side = _fill_side(fill)
        quantity = _fill_quantity(fill)
        price = _fill_price(fill)
        fee = _fill_fees(fill)
        if quantity <= 0 or price <= 0:
            continue
        if side == OrderSide.BUY.value:
            unit_cost = price + (fee / quantity if quantity > 0 else Decimal("0"))
            open_lots.append({"remaining": quantity, "unit_cost": unit_cost})
            continue
        if side != OrderSide.SELL.value:
            continue

        remaining_sell = quantity
        sell_fee_per_unit = fee / quantity if quantity > 0 else Decimal("0")
        while remaining_sell > 0 and open_lots:
            lot = open_lots[0]
            matched = min(remaining_sell, lot["remaining"])
            proceeds = matched * price
            cost_basis = matched * lot["unit_cost"]
            sell_fee = matched * sell_fee_per_unit
            realized_pnl += proceeds - cost_basis - sell_fee
            matched_sell_base += matched
            realized_exit_count += 1
            remaining_sell -= matched
            lot["remaining"] -= matched
            if lot["remaining"] <= 0:
                open_lots.pop(0)
        if remaining_sell > 0:
            unmatched_sell_base += remaining_sell

    open_base = sum((lot["remaining"] for lot in open_lots), Decimal("0"))
    return {
        "scope": SpotPortfolioPnlScope.REALIZED_LOT.value,
        "method": "fifo_known_cost_basis",
        "matched_sell_base_size": _format_decimal(matched_sell_base) or "0",
        "unmatched_sell_base_size": _format_decimal(unmatched_sell_base) or "0",
        "open_base_size": _format_decimal(open_base) or "0",
        "realized_pnl": _format_decimal(realized_pnl) or "0",
        "realized_exit_count": realized_exit_count,
    }


def _build_product_pnl(
    *,
    product_id: str,
    fills: Iterable[Any],
    mark_price: Decimal,
    mark_price_available: bool,
) -> SpotPortfolioProductPnl:
    ordered_fills = sorted(fills, key=lambda fill: _timestamp_key(_fill_timestamp(fill)))
    realized_lot = _build_realized_lot_pnl(fills=ordered_fills)
    buy_base = Decimal("0")
    sell_base = Decimal("0")
    buy_notional = Decimal("0")
    sell_notional = Decimal("0")
    fees = Decimal("0")
    cashflow = Decimal("0")
    last_buy_key = None
    last_buy_at = None

    for fill in ordered_fills:
        side = _fill_side(fill)
        quantity = _fill_quantity(fill)
        price = _fill_price(fill)
        fee = _fill_fees(fill)
        notional = quantity * price
        if side == OrderSide.BUY.value:
            buy_base += quantity
            buy_notional += notional
            cashflow -= notional
            last_buy_key = _timestamp_key(_fill_timestamp(fill))
            last_buy_at = _fill_timestamp(fill)
        elif side == OrderSide.SELL.value:
            sell_base += quantity
            sell_notional += notional
            cashflow += notional
        else:
            continue
        fees += fee
        cashflow -= fee

    net_base = buy_base - sell_base
    mark_value = net_base * mark_price
    total_pnl = cashflow + mark_value

    since_last_purchase = {
        "scope": SpotPortfolioPnlScope.SINCE_LAST_PURCHASE.value,
        "buy_notional": "0",
        "sell_notional": "0",
        "fees": "0",
        "net_base_size": "0",
        "mark_value": "0",
        "cashflow": "0",
        "total_pnl": "0",
    }
    if last_buy_key is not None:
        period_buy_base = Decimal("0")
        period_sell_base = Decimal("0")
        period_buy_notional = Decimal("0")
        period_sell_notional = Decimal("0")
        period_fees = Decimal("0")
        period_cashflow = Decimal("0")
        for fill in ordered_fills:
            if _timestamp_key(_fill_timestamp(fill)) < last_buy_key:
                continue
            side = _fill_side(fill)
            quantity = _fill_quantity(fill)
            price = _fill_price(fill)
            fee = _fill_fees(fill)
            notional = quantity * price
            if side == OrderSide.BUY.value:
                period_buy_base += quantity
                period_buy_notional += notional
                period_cashflow -= notional
            elif side == OrderSide.SELL.value:
                period_sell_base += quantity
                period_sell_notional += notional
                period_cashflow += notional
            else:
                continue
            period_fees += fee
            period_cashflow -= fee
        period_net_base = period_buy_base - period_sell_base
        period_mark_value = period_net_base * mark_price
        period_total_pnl = period_cashflow + period_mark_value
        since_last_purchase.update({
            "buy_notional": _format_decimal(period_buy_notional) or "0",
            "sell_notional": _format_decimal(period_sell_notional) or "0",
            "fees": _format_decimal(period_fees) or "0",
            "net_base_size": _format_decimal(period_net_base) or "0",
            "mark_value": _format_decimal(period_mark_value) or "0",
            "cashflow": _format_decimal(period_cashflow) or "0",
            "total_pnl": _format_decimal(period_total_pnl) or "0",
        })

    return SpotPortfolioProductPnl(
        product_id=product_id,
        buy_base_size=_format_decimal(buy_base) or "0",
        sell_base_size=_format_decimal(sell_base) or "0",
        net_base_size=_format_decimal(net_base) or "0",
        buy_notional=_format_decimal(buy_notional) or "0",
        sell_notional=_format_decimal(sell_notional) or "0",
        fees=_format_decimal(fees) or "0",
        mark_price=_format_decimal(mark_price) or "0",
        mark_price_available=mark_price_available,
        mark_value=_format_decimal(mark_value) or "0",
        cashflow=_format_decimal(cashflow) or "0",
        total_pnl=_format_decimal(total_pnl) or "0",
        last_purchase_at=_iso_timestamp(last_buy_at),
        since_last_purchase=since_last_purchase,
        realized_lot=realized_lot,
    )


def build_spot_portfolio_pnl_snapshot(
    *,
    fills: Iterable[Any],
    mark_prices: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> SpotPortfolioPnlSnapshot:
    """Build durable P/L views from persisted fill-ledger rows and mark prices.

    This includes cashflow plus mark-to-market reporting and a FIFO realized
    P/L view for known fill-ledger lots. It is not tax accounting and does not
    implement specific-identification or tax-lot election rules.
    """
    grouped: dict[str, list[Any]] = {}
    for fill in fills:
        product_id = _fill_product_id(fill)
        if not product_id.endswith(f"-{QUOTE_CURRENCY}"):
            continue
        grouped.setdefault(product_id, []).append(fill)

    products = []
    for product_id in sorted(grouped):
        mark_price_available = product_id in mark_prices
        mark_price = _decimal(mark_prices.get(product_id))
        products.append(
            _build_product_pnl(
                product_id=product_id,
                fills=grouped[product_id],
                mark_price=mark_price,
                mark_price_available=mark_price_available,
            )
        )

    timestamp = generated_at or datetime.now(timezone.utc)
    return SpotPortfolioPnlSnapshot(
        generated_at=timestamp.isoformat(),
        quote_currency=QUOTE_CURRENCY,
        scopes=(
            SpotPortfolioPnlScope.PRODUCT.value,
            SpotPortfolioPnlScope.PORTFOLIO.value,
            SpotPortfolioPnlScope.SINCE_LAST_PURCHASE.value,
            SpotPortfolioPnlScope.REALIZED_LOT.value,
        ),
        products=tuple(products),
    )


def build_spot_portfolio_pnl_snapshot_from_repo(
    *,
    fill_ledger_repo: Any,
    product_ids: Iterable[str],
    mark_prices: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> SpotPortfolioPnlSnapshot:
    """Build the spot P/L snapshot by reading fill-ledger rows per product."""
    fills: list[Any] = []
    for product_id in sorted({str(product_id) for product_id in product_ids}):
        getter = getattr(fill_ledger_repo, "get_fills_by_product", None)
        if callable(getter):
            fills.extend(getter(product_id) or [])
            continue
        instrument_getter = getattr(fill_ledger_repo, "get_fills_by_instrument", None)
        if callable(instrument_getter):
            fills.extend(instrument_getter(product_id) or [])
    return build_spot_portfolio_pnl_snapshot(
        fills=fills,
        mark_prices=mark_prices,
        generated_at=generated_at,
    )


def build_spot_portfolio_pnl_report(
    *,
    fill_ledger_repo: Any,
    products: Iterable[Any],
    product_ids: Iterable[str] | None = None,
    coinbase_average_costs: Iterable[Mapping[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable USDC spot P/L report from fill ledger and marks."""
    from business.spot_cost_basis import build_average_cost_pnl_report

    mark_prices = build_usdc_spot_mark_prices(products)
    selected_product_ids = sorted(mark_prices)
    if product_ids is not None:
        requested = {str(product_id).upper() for product_id in product_ids}
        selected_product_ids = [
            product_id
            for product_id in selected_product_ids
            if product_id.upper() in requested
        ]
    snapshot = build_spot_portfolio_pnl_snapshot_from_repo(
        fill_ledger_repo=fill_ledger_repo,
        product_ids=selected_product_ids,
        mark_prices=mark_prices,
        generated_at=generated_at,
    ).to_dict()
    report = {
        "generated_at": snapshot["generated_at"],
        "quote_currency": QUOTE_CURRENCY,
        "eligible_mark_product_count": len(mark_prices),
        "selected_product_count": len(selected_product_ids),
        "selected_product_ids": selected_product_ids,
        "mark_price_count": len(
            [
                product_id
                for product_id in selected_product_ids
                if product_id in mark_prices
            ]
        ),
        "snapshot": snapshot,
    }
    if coinbase_average_costs is not None:
        selected_average_records = [
            record for record in coinbase_average_costs
            if record.get("product_id") in set(selected_product_ids)
        ]
        report["average_cost_pnl"] = build_average_cost_pnl_report(
            average_cost_records=selected_average_records,
            mark_prices=mark_prices,
            generated_at=generated_at,
        )
    return report
