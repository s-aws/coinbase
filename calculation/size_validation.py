"""Order-size validation: tick-align AND enforce exchange minimums.

Mirrors the price-quantize pattern in
``core/stealth_order_manager._quantize_reprice_price`` but for the size
field. Two responsibilities, intentionally combined because they share
the same product-metadata lookup and have identical failure modes (an
order rejected at the exchange):

1. **Quantize to ``base_increment``** \u2014 snap the size to the product's
   tick-aligned base step (e.g. ``0.001 BTC``, ``1 contract``). Direction
   is configurable; default is ``"down"`` so we never silently inflate
   an operator's intended size.
2. **Validate against ``base_min_size`` and ``quote_min_size``** \u2014 reject
   sizes the exchange will reject. Done in one place so every order
   creation path (``create_stealth_order``, ``create_limit_order_span``,
   bridge follow-ups, etc.) gets the same guard.

Why combine quantize + validate
-------------------------------
A naive split (\"caller quantizes, validator only checks\") leaks the
boundary: a size of 0.0009 BTC quantized down to 0.000 would pass a
naive \"is positive\" check while violating min-size. Combining the
operations means the value the caller submits is *exactly* what the
validator approved.

Honest scope notes
------------------
* ``base_min_size`` and ``quote_min_size`` come from
  ``products.json::metadata`` which is populated by
  ``dashboard_server.update_products_json_from_api``. If the dashboard
  has never updated products (fresh checkout, mock environment), the
  metadata strings are empty and validation degrades to *quantize-only*
  with a warning hook. This matches the existing price-quantize
  behavior \u2014 missing metadata means no enforcement, never a crash.
* ``quote_min_size`` is checked by ``validate_and_quantize_size`` when a price
  is supplied. Quote-sized market BUYs call ``validate_quote_size`` because
  their quote notional is known even though base size is not.
* This module never silently changes prices or sides. It is purely
  a size-side guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from calculation.formatter import quantize_to_increment
from configuration import PRODUCT_METADATA, get_trading_product_id
from core.enums import RoundingDirection


@dataclass(frozen=True)
class SizeValidationResult:
    """Outcome of ``validate_and_quantize_size``.

    Either ``ok`` is True and ``size`` is the value to submit, or
    ``ok`` is False and ``reason`` explains why. ``size`` is always
    populated (carries the post-quantize value even on failure so
    callers can log it for debugging).
    """
    ok: bool
    size: float
    reason: str = ""

    def __bool__(self) -> bool:  # convenience for ``if result: ...``
        return self.ok


def _to_decimal(value, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Best-effort string\u2192Decimal conversion. Returns ``default`` on failure."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _product_metadata(product_id: str) -> dict:
    """Look up product metadata, with the same fallback the manager uses."""
    if not product_id:
        return {}
    trading_product_id = get_trading_product_id(str(product_id))
    return (
        PRODUCT_METADATA.get(product_id)
        or PRODUCT_METADATA.get(trading_product_id)
        or {}
    )


def validate_and_quantize_size(
    size: float,
    *,
    product_id: str,
    price: Optional[float] = None,
    direction: str = RoundingDirection.DOWN.value,
) -> SizeValidationResult:
    """Snap ``size`` to ``base_increment`` and validate against minimums.

    Args:
        size: The desired order size, in base units (BTC, contracts, etc.).
        product_id: Trading product id (e.g. ``"BTC-USDC"`` or
            ``"BIT-29MAY26-CDE"``). Used to look up
            ``base_increment`` / ``base_min_size`` / ``quote_min_size``
            from ``products.json``.
        price: Optional limit price. When supplied, the implied notional
            (``size * price``) is checked against ``quote_min_size``.
            Pass ``None`` for market orders.
        direction: How to quantize. Default ``"down"`` so we never
            silently inflate an operator's typed size. ``"up"`` is
            available for callers that would rather over-fill than
            reject a too-small order. ``"nearest"`` for repricing.

    Returns:
        ``SizeValidationResult``. Truthy on success.

    Failure cases (``ok=False``):
        * Non-positive size after quantize (e.g. ``size < base_increment``)
        * Below ``base_min_size``
        * Implied notional below ``quote_min_size`` (only when ``price``
          is given)
        * Bad inputs (None, NaN, etc.)
    """
    # --- input sanitation --------------------------------------------------
    if size is None:
        return SizeValidationResult(False, 0.0, "size is None")
    try:
        size_f = float(size)
    except (TypeError, ValueError):
        return SizeValidationResult(False, 0.0, f"size not numeric: {size!r}")
    if size_f != size_f:  # NaN check
        return SizeValidationResult(False, 0.0, "size is NaN")
    if size_f <= 0:
        return SizeValidationResult(False, size_f, f"size must be > 0, got {size_f}")

    metadata = _product_metadata(product_id)
    base_increment = metadata.get("base_increment")

    # --- quantize ----------------------------------------------------------
    if base_increment:
        try:
            size_f = float(
                quantize_to_increment(size_f, str(base_increment), direction=direction)
            )
        except (ValueError, ArithmeticError) as e:
            return SizeValidationResult(
                False, size_f, f"quantize_to_increment failed: {e}"
            )
        # Quantize down can drive sub-increment sizes to zero.
        if size_f <= 0:
            return SizeValidationResult(
                False, size_f,
                f"size {size!r} below base_increment {base_increment!r}"
            )

    # --- base_min_size -----------------------------------------------------
    base_min = _to_decimal(metadata.get("base_min_size"))
    if base_min is not None and base_min > 0:
        if Decimal(str(size_f)) < base_min:
            return SizeValidationResult(
                False, size_f,
                f"size {size_f} below base_min_size {base_min} for {product_id}"
            )

    # --- quote_min_size (only meaningful with a price) ---------------------
    if price is not None:
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            price_f = 0.0
        quote_min = _to_decimal(metadata.get("quote_min_size"))
        if price_f > 0 and quote_min is not None and quote_min > 0:
            notional = Decimal(str(size_f)) * Decimal(str(price_f))
            if notional < quote_min:
                return SizeValidationResult(
                    False, size_f,
                    f"notional {notional} (size {size_f} \u00d7 price {price_f}) "
                    f"below quote_min_size {quote_min} for {product_id}"
                )

    return SizeValidationResult(True, size_f, "")


def validate_quote_size(
    quote_size: float,
    *,
    product_id: str,
    direction: str = RoundingDirection.DOWN.value,
) -> SizeValidationResult:
    """Snap quote size to ``quote_increment`` and validate quote minimums.

    Coinbase market BUYs may specify ``quote_size`` instead of ``base_size``.
    In that shape there is no known base quantity to quantize, but the quote
    notional is known and must still be positive, increment-aligned, and above
    ``quote_min_size`` when product metadata supplies one.
    """
    if quote_size is None:
        return SizeValidationResult(False, 0.0, "quote_size is None")
    try:
        quote_f = float(quote_size)
    except (TypeError, ValueError):
        return SizeValidationResult(False, 0.0, f"quote_size not numeric: {quote_size!r}")
    if quote_f != quote_f:
        return SizeValidationResult(False, 0.0, "quote_size is NaN")
    if quote_f <= 0:
        return SizeValidationResult(
            False,
            quote_f,
            f"quote_size must be > 0, got {quote_f}",
        )

    metadata = _product_metadata(product_id)
    quote_increment = metadata.get("quote_increment")
    if quote_increment:
        try:
            quote_f = float(
                quantize_to_increment(
                    quote_f,
                    str(quote_increment),
                    direction=direction,
                )
            )
        except (ValueError, ArithmeticError) as e:
            return SizeValidationResult(
                False,
                quote_f,
                f"quote_size quantize_to_increment failed: {e}",
            )
        if quote_f <= 0:
            return SizeValidationResult(
                False,
                quote_f,
                f"quote_size {quote_size!r} below quote_increment {quote_increment!r}",
            )

    quote_min = _to_decimal(metadata.get("quote_min_size"))
    if quote_min is not None and quote_min > 0:
        if Decimal(str(quote_f)) < quote_min:
            return SizeValidationResult(
                False,
                quote_f,
                f"quote_size {quote_f} below quote_min_size {quote_min} for {product_id}",
            )

    return SizeValidationResult(True, quote_f, "")
