"""Enums for trading engine - Order states, product types, conditions, etc.

This module defines all fixed enumeration types used throughout the trading system,
derived from Coinbase API responses and WebSocket messages. Using enums improves:
- Type safety and IDE autocomplete
- Code readability and maintainability
- Consistency across the codebase
"""

from enum import Enum


# ============================================================================
# ORDER ATTRIBUTES
# ============================================================================

class OrderSide(str, Enum):
    """Direction of an order - BUY or SELL."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Status of an order throughout its lifecycle.
    
    From Coinbase API: PENDING, OPEN, FILLED, CANCELLED, EXPIRED, FAILED
    """
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCEL_QUEUED = "CANCEL_QUEUED"


class StealthOrderStatus(str, Enum):
    """Status of a stealth order throughout its internal lifecycle.
    
    Distinct from OrderStatus (which tracks API-visible states like OPEN, FILLED).
    StealthOrderStatus tracks the internal reveal and execution lifecycle of stealth orders.
    
    - HIDDEN: Order created, not yet revealed to exchange
    - PENDING: Reveal condition partially met, watching for full trigger
    - TRIGGERED: Reveal condition fully met, pending placement on exchange
    - REVEALED: Order partially or fully revealed to exchange
    - EXECUTED: Order fully executed
    - CANCELLED: Order cancelled before execution
    """
    HIDDEN = "HIDDEN"
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    REVEALED = "REVEALED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    """Type of order - how it executes.
    
    From Coinbase API: LIMIT, MARKET, STOP_LIMIT
    """
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    """How long an order remains valid.
    
    - GTC (GOOD_UNTIL_CANCELLED): Order stays until filled or manually cancelled
    - IOC (IMMEDIATE_OR_CANCEL): Fill entire order immediately or cancel
    - FOK (FILL_OR_KILL): Fill entire order immediately or cancel (no partial)
    - GTD (GOOD_UNTIL_DATE_TIME): Order expires at specified end_time
    """
    GOOD_UNTIL_CANCELLED = "GOOD_UNTIL_CANCELLED"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"
    GOOD_UNTIL_DATE_TIME = "GOOD_UNTIL_DATE_TIME"

    # Aliases for convenience
    GTC = "GOOD_UNTIL_CANCELLED"
    IOC = "IMMEDIATE_OR_CANCEL"
    FOK = "FILL_OR_KILL"
    GTD = "GOOD_UNTIL_DATE_TIME"


class TriggerStatus(str, Enum):
    """Status of trigger/stop order.
    
    From Coinbase API: UNKNOWN_TRIGGER_STATUS, INVALID_ORDER_TYPE, STOP_PENDING, STOP_TRIGGERED
    """
    UNKNOWN_TRIGGER_STATUS = "UNKNOWN_TRIGGER_STATUS"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"
    STOP_PENDING = "STOP_PENDING"
    STOP_TRIGGERED = "STOP_TRIGGERED"


# ============================================================================
# PRODUCT & MARKET ATTRIBUTES
# ============================================================================

class ProductType(str, Enum):
    """Type of trading product."""
    SPOT = "SPOT"
    FUTURE = "FUTURE"


class ProductStatus(str, Enum):
    """Status of a trading product from Coinbase.
    
    - OPEN: Product is trading normally
    - CLOSED: Product is not available for trading
    - POST_ONLY: Only maker orders (post-only) are accepted
    - LIMIT_ONLY: Only limit orders are accepted
    """
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    POST_ONLY = "POST_ONLY"
    LIMIT_ONLY = "LIMIT_ONLY"


class ContractExpiryType(str, Enum):
    """Type of futures contract expiration.
    
    From Coinbase API: PERPETUAL, EXPIRING, UNKNOWN_CONTRACT_EXPIRY_TYPE
    """
    PERPETUAL = "PERPETUAL"
    EXPIRING = "EXPIRING"
    UNKNOWN_CONTRACT_EXPIRY_TYPE = "UNKNOWN_CONTRACT_EXPIRY_TYPE"


class Direction(str, Enum):
    """Directional threshold comparisons for conditions.
    
    Used in price threshold and ratio evaluators.
    """
    ABOVE = "above"
    BELOW = "below"


class RoundingDirection(str, Enum):
    """Rounding direction for quantization operations.
    
    Used in price/size quantization to determine rounding strategy.
    """
    UP = "up"
    DOWN = "down"
    NEAREST = "nearest"


class FollowUpRevealDirection(str, Enum):
    """Direction strategy for follow-up orders after stealth order reveals/fills.
    
    Used to determine how follow-up stealth orders should be configured when
    a previous order transitions to the exchange or fills.
    
    - SAME: Create follow-up order with same side (BUY stays BUY, SELL stays SELL)
    - OPPOSITE: Flip the side (BUY becomes SELL, SELL becomes BUY)
    """
    SAME = "same"
    OPPOSITE = "opposite"


# ============================================================================
# STEALTH ORDER CONDITIONS
# ============================================================================

class RevealConditionType(str, Enum):
    """Type of condition that triggers stealth order reveal.
    
    - PRICE_THRESHOLD: Reveal when price crosses threshold
    - CUMULATIVE_VOLUME: Reveal when cumulative volume at price level reached
    - TIME_DELAY: Reveal after time delay (with optional jitter)
    - SPREAD: Reveal when bid-ask spread narrows below threshold
    - PRODUCT_RATIO: Reveal when ratio between two products meets threshold
    - COMPOSITE: Reveal when multiple conditions meet (AND/OR logic)
    """
    PRICE_THRESHOLD = "price"
    CUMULATIVE_VOLUME = "cumulative_volume"
    TIME_DELAY = "time_delay"
    SPREAD = "spread"
    PRODUCT_RATIO = "product_ratio"
    COMPOSITE = "composite"


# ============================================================================
# WEBSOCKET & EVENT TYPES
# ============================================================================

class WebSocketEventType(str, Enum):
    """Type of WebSocket event from message.
    
    - SNAPSHOT: Initial state of orders/positions
    - UPDATE: Incremental update to existing state
    - PATCH: Update (used in user channel)
    """
    SNAPSHOT = "snapshot"
    UPDATE = "update"
    PATCH = "patch"


class ChannelType(str, Enum):
    """WebSocket channel subscription types.
    
    Public channels (no auth):
    - TICKER: Real-time price updates
    - LEVEL2: Order book updates
    - MARKET_TRADES: Trade execution data
    - CANDLES: OHLCV candle data
    - HEARTBEATS: Server heartbeat
    - STATUS: System status
    - TICKER_BATCH: Batched ticker updates
    
    Authenticated channels:
    - USER: Order and position updates
    - FUTURES_BALANCE_SUMMARY: Futures account balance
    
    Control messages:
    - SUBSCRIPTIONS: Subscription acknowledgment/change notification
    """
    # Public channels
    TICKER = "ticker"
    LEVEL2 = "level2"
    MARKET_TRADES = "market_trades"
    CANDLES = "candles"
    HEARTBEATS = "heartbeats"
    STATUS = "status"
    TICKER_BATCH = "ticker_batch"
    
    # Authenticated channels
    USER = "user"
    FUTURES_BALANCE_SUMMARY = "futures_balance_summary"
    
    # Control messages
    SUBSCRIPTIONS = "subscriptions"


class RiskManagementType(str, Enum):
    """Type of risk management for futures orders.
    
    From Coinbase API:
    - MANAGED_BY_FCM: Risk managed by FCM (broker)
    - MANAGED_BY_VENUE: Risk managed by exchange
    - UNKNOWN_RISK_MANAGEMENT_TYPE: Unknown management type
    """
    MANAGED_BY_FCM = "MANAGED_BY_FCM"
    MANAGED_BY_VENUE = "MANAGED_BY_VENUE"
    UNKNOWN_RISK_MANAGEMENT_TYPE = "UNKNOWN_RISK_MANAGEMENT_TYPE"


# ============================================================================
# ORDER PROFIT TARGETS
# ============================================================================

class TargetMovementType(str, Enum):
    """How profit target is specified.
    
    - PERCENTAGE: As percentage (e.g., 0.004 = 0.4%)
    - ABSOLUTE: As absolute amount (e.g., $500)
    """
    PERCENTAGE = "P"       # As percentage (e.g., 0.004 = 0.4%)
    ABSOLUTE = "A"         # As absolute amount (e.g., $500)
