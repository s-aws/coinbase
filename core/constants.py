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

# Fee Constants
DERIVATIVES_MANDATORY_FEE_PER_CONTRACT = 0.15  # Base fee per contract
DEFAULT_MAX_ORDER_REPLACEMENT = 1               # Max follow-up orders per parent

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
