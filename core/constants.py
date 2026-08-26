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

# Fee Constants — Coinbase Derivatives (CDE) fixed per-contract cost
#
# Sources:
#   * Coinbase Fee Schedule effective March 2, 2026
#     https://assets.ctfassets.net/o10es7wu5gm1/6LbrWZkWY1BUS67poRlVe/
#     10ca89e22a46b899389678b8f3352c10/Fee_Schedule_3.2.2026.pdf
#   * Daily statement reconciliation (Aug-25-2026): the settled BIP/default
#     fixed cost is $0.12 per contract side.
#
# The settled default-tier total decomposes as:
#   * Venue commission:          $0.10/contract/side
#   * Clearing:                  $0.01/contract/side
#   * One regulatory/NFA charge: $0.01/contract/side
#                                 -------------------
#   * All-in fixed cost:         $0.12/contract/side
#
# Per the schedule (verbatim):
#   "Fees are charged per side (both the buy and the sell side) per contract"
#
# The BIP/default reconciliation does not establish a replacement all-in
# value for full-size BTI/ETI/SLC/XRL. Their existing $0.27 all-in behavior
# is therefore preserved explicitly below as an out-of-scope legacy value.
# Do not derive it from the reconciled default-tier component total.
#
# IMPORTANT: ``get_derivatives_per_side_fee`` returns the all-in fixed
# per-side cost. Callers computing round-trip fees must multiply by 2.
DERIVATIVES_VENUE_FEE_DEFAULT = 0.10
DERIVATIVES_VENUE_FEE_BY_SYMBOL = {
    "BTI": 0.20,  # Legacy full-size assumption; not changed by BIP reconciliation
    "ETI": 0.20,  # Legacy full-size assumption; not changed by BIP reconciliation
    "SLC": 0.20,  # Legacy full-size assumption; not changed by BIP reconciliation
    "XRL": 0.20,  # Legacy full-size assumption; not changed by BIP reconciliation
}

# Default-tier non-venue charges reconciled from settlement. The statement
# supports one combined regulatory/NFA charge; do not split it into multiple
# modeled fees without additional settlement evidence.
DERIVATIVES_CLEARING_FEE_PER_SIDE = 0.01
DERIVATIVES_REGULATORY_NFA_FEE_PER_SIDE = 0.01

DERIVATIVES_NON_VENUE_FEES_PER_SIDE = (
    DERIVATIVES_CLEARING_FEE_PER_SIDE
    + DERIVATIVES_REGULATORY_NFA_FEE_PER_SIDE
)

# Back-compat alias: resolves to the settlement-reconciled default all-in
# fixed cost and matches what get_derivatives_per_side_fee() returns for an
# unknown symbol. Do NOT use this for full-size contracts; call the function.
DERIVATIVES_PER_SIDE_FEE_DEFAULT = (
    DERIVATIVES_VENUE_FEE_DEFAULT + DERIVATIVES_NON_VENUE_FEES_PER_SIDE
)

# Explicit all-in values preserve the existing full-size behavior. Keeping
# these separate from the default-tier component sum prevents a BIP/default
# correction from silently changing full-size pricing and profitability.
DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL = {
    "BTI": 0.27,
    "ETI": 0.27,
    "SLC": 0.27,
    "XRL": 0.27,
}


def get_derivatives_per_side_fee(product_id: str) -> float:
    """Return the all-in per-side per-contract cost for a CDE product.

    The default tier is the settlement-reconciled $0.12 all-in fixed cost.
    Full-size symbols retain their explicit legacy $0.27 all-in value until
    that tier is independently reconciled and approved.

    Args:
        product_id: Coinbase Derivatives product id, e.g. ``"BIP-20DEC30-CDE"``.
            The leading symbol prefix (text before the first ``-``) is used
            to look up the venue tier.

    Returns:
        All-in fixed per-side cost in USD per contract.
        Defaults to the nano/perp-style tier when the symbol is unknown.
    """
    if not product_id:
        return DERIVATIVES_PER_SIDE_FEE_DEFAULT
    symbol = product_id.split("-", 1)[0].upper()
    return DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL.get(
        symbol,
        DERIVATIVES_PER_SIDE_FEE_DEFAULT,
    )

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


# ============================================================================
# HOTPOINT AUTO-REPLICATE
# ============================================================================
# Runtime kill switch. Operator-flippable without restart via
# OrderEngine.set_hotpoint_auto_place_enabled(bool). Defaults TRUE per spec
# (live from day one). Flip to FALSE to halt all auto-placement immediately;
# detector + decay continue running, only the placer gates on this flag.
HOTPOINT_AUTO_PLACE_ENABLED = True

# Bucket width as % of price. Buckets are log-spaced and deterministic:
#   bucket_id = floor(log(price) / log(1 + HOTPOINT_WIDTH_PCT))
# At 0.5%, BTC ~$100k buckets are ~$500 wide; ETH ~$3k buckets are ~$15 wide.
HOTPOINT_WIDTH_PCT = 0.005

# Trigger: at least N qualifying fills inside the bucket within T seconds
# (same product, same side, opted-in parents only).
HOTPOINT_TRIGGER_N = 3
HOTPOINT_TRIGGER_WINDOW_SECONDS = 60

# Rate limit: at most N auto-placements per (product, side, bucket) per T seconds.
# Restart-rebuilt from order_parent rows (auto_placed_by_hotpoint=TRUE within T).
HOTPOINT_RATE_LIMIT_N = 5
HOTPOINT_RATE_LIMIT_WINDOW_SECONDS = 300

# Decay sweeper: how often to scan for resting auto-placed orders whose bucket
# has gone cold (zero qualifying fills in the trigger window) and cancel them.
HOTPOINT_DECAY_SWEEP_INTERVAL_SECONDS = 30

# Default placement-price policy. See HotpointPlacementPolicy enum.
HOTPOINT_DEFAULT_POLICY = "WINDOW_CENTER"
