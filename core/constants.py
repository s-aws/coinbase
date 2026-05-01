"""Constants for trading engine - Order mappings, product lists, fees."""

from datetime import datetime, timezone
from core.enums import OrderSide


def get_local_now() -> datetime:
    """Get current time with local timezone awareness.
    
    Returns timezone-aware datetime in local timezone.
    Replaces deprecated datetime.now() which returns naive datetime.
    """
    return datetime.now(timezone.utc).astimezone()

# Order Side Mapping
ORDER_SIDE_SWITCH = {
    OrderSide.BUY: OrderSide.SELL,
    OrderSide.SELL: OrderSide.BUY,
    "BUY": "SELL",
    "SELL": "BUY"
}

# Position Side Mapping
ORDER_POSITION_SIDE = {
    "SHORT": OrderSide.SELL,
    "LONG": OrderSide.BUY,
    "SELL": "SHORT",
    "BUY": "LONG",
}

# Order Direction (multiplier for price movement)
# SELL orders: price increases (1 = positive direction)
# BUY orders: price decreases (-1 = negative direction)
ORDER_DIRECTION = {
    OrderSide.SELL: 1,
    OrderSide.BUY: -1,
    "SELL": 1,
    "BUY": -1,
}

# Fee Constants — Coinbase Derivatives (CDE) per-contract commission
#
# Source: Fee Schedule effective March 2, 2026
#   https://assets.ctfassets.net/o10es7wu5gm1/6LbrWZkWY1BUS67poRlVe/
#   10ca89e22a46b899389678b8f3352c10/Fee_Schedule_3.2.2026.pdf
#
# Per the schedule (verbatim):
#   "Fees are charged per side (both the buy and the sell side) per contract"
#
# Two non-professional electronic tiers exist:
#   * Full-size contracts (BTI, ETI, SLC, XRL):       $0.20 per side
#   * Nano / Perp-Style and everything else:          $0.10 per side
#
# IMPORTANT: This is a PER-SIDE rate. A round-trip (open + close) charges
# the rate twice. Callers computing round-trip fees must multiply by 2.
# Pre-2026-03-02 the schedule was a flat $0.15 per contract (one charge for
# the round-trip); the constant was renamed when the model changed so any
# stale call site fails to import rather than silently miscompute.
DERIVATIVES_PER_SIDE_FEE_DEFAULT = 0.10
DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL = {
    "BTI": 0.20,  # Bitcoin Futures (full-size)
    "ETI": 0.20,  # Ether Futures (full-size)
    "SLC": 0.20,  # Solana Futures (full-size)
    "XRL": 0.20,  # XRP Futures (full-size)
}


def get_derivatives_per_side_fee(product_id: str) -> float:
    """Return the per-side per-contract commission for a CDE product.

    Args:
        product_id: Coinbase Derivatives product id, e.g. ``"BIP-20DEC30-CDE"``.
            The leading symbol prefix (text before the first ``-``) is used
            to look up the tier.

    Returns:
        Per-side fee in USD per contract. Defaults to
        ``DERIVATIVES_PER_SIDE_FEE_DEFAULT`` when the symbol is unknown
        (covers all nano/perp-style products and any new listings on the
        $0.10 tier).
    """
    if not product_id:
        return DERIVATIVES_PER_SIDE_FEE_DEFAULT
    symbol = product_id.split("-", 1)[0].upper()
    return DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL.get(symbol, DERIVATIVES_PER_SIDE_FEE_DEFAULT)

# Replacement Cap
# Default ``max_order_replacement`` per parent. ``1`` means "round-trip
# only" (open is free; one closing follow-up consumes the slot). To
# allow re-anchors, override per parent at order-creation time.
# Previously also lived in ``configuration.py`` with the desynced value
# 101 — 2026-04-30 audit consolidated here.
DEFAULT_MAX_ORDER_REPLACEMENT = 1

# Product Lists
SPOT_PRODUCT_IDS = [
    "DOT-BTC",
    "NCT-USDC",
    "BTC-USDC",
    "LTC-USDC",
    "ETH-USDC",
    "MON-USDC",
    "ZKP-USDC",
    "WET-USDC",
    "XPL-USDC",
    "DOGE-USDC",
    "SENT-USDC"
]

DERIVATIVES_PRODUCT_IDS = [
    "BIP-20DEC30-CDE",
    "ETP-20DEC30-CDE",
    "XPP-20DEC30-CDE",
    "SLP-20DEC30-CDE",
    "ADP-20DEC30-CDE",
    "DOP-20DEC30-CDE",
    "BCP-20DEC30-CDE",
    "SUP-20DEC30-CDE",
    "AVP-20DEC30-CDE",
    "XLP-20DEC30-CDE",
    "LNP-20DEC30-CDE",
    "LCP-20DEC30-CDE",
    "POP-20DEC30-CDE",
    "HEP-20DEC30-CDE",
    "PAU-20DEC30-CDE",
    "SLR-28APR26-CDE",
    "GOL-27MAR26-CDE",
    "NOL-19MAR26-CDE",
    "PT-27MAR26-CDE",
    "CU-28APR26-CDE",
    "BIT-24APR26-CDE"
]

# All Trading Pairs
ALL_PRODUCT_IDS = SPOT_PRODUCT_IDS + DERIVATIVES_PRODUCT_IDS
