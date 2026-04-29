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

    Engine event statuses also routed through order processing:
    - UPDATE: Incremental websocket update for an existing order
    - SNAPSHOT: Initial websocket snapshot payload
    """
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCEL_QUEUED = "CANCEL_QUEUED"
    UPDATE = "UPDATE"
    SNAPSHOT = "SNAPSHOT"


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


class FollowUpKind(str, Enum):
    """Terminal-event kind for follow-up processing claims.

    The OrderEngine claims a per-order processing token before creating a
    follow-up so concurrent threads observing the same WS terminal event do
    not double-spawn. ``FILLED`` and ``CANCELLED`` use independent token
    namespaces — a filled-side claim does not block a cancelled-side claim.
    """

    FILLED = "filled"
    CANCELLED = "cancelled"


class RevealPricingPolicy(str, Enum):
    """Pricing policy for stealth order reveal.
    
    Determines what price to use when revealing a stealth order to the exchange.
    
    - CONFIGURED_LIMIT: Use the limit price specified at order creation
    - TOP_OF_BOOK: Use current best bid (SELL) or best ask (BUY) from ticker
    - MIDPOINT: Use midpoint between current bid and ask
    """
    CONFIGURED_LIMIT = "configured_limit"
    TOP_OF_BOOK = "top_of_book"
    MIDPOINT = "midpoint"


class RevealPriceSource(str, Enum):
    """Source of the price used when revealing a stealth order.
    
    Indicates how the submitted limit price was determined at reveal time.
    Used for audit trails and understanding reveal execution decisions.
    
    - CONFIGURED_LIMIT: Used original limit price from order creation (fallback or direct use)
    - TICKER_BEST_BID: Used best bid from ticker (SELL orders with TOP_OF_BOOK policy)
    - TICKER_BEST_ASK: Used best ask from ticker (BUY orders with TOP_OF_BOOK policy)
    - TICKER_MIDPOINT: Used midpoint between bid/ask (MIDPOINT policy)
    - UNAVAILABLE: Market data unavailable, fell back to configured limit
    """
    CONFIGURED_LIMIT = "configured_limit"
    TICKER_BEST_BID = "ticker_best_bid"
    TICKER_BEST_ASK = "ticker_best_ask"
    TICKER_MIDPOINT = "ticker_midpoint"
    UNAVAILABLE = "unavailable"


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
# ANCHOR REPRICING POLICY
# ============================================================================

class RepricingReferenceSource(str, Enum):
    """Market reference used by ``anchor_repricing_policy`` to compute the
    target price each tick.

    - LAST_TRADE: Use the most recent trade price from the ticker.
    - MIDPOINT: Use ``(bid + ask) / 2``.
    - TOP_OF_BOOK: Use best bid for BUY orders, best ask for SELL orders.

    Persisted as a string in
    ``stealth_orders.anchor_repricing_policy_json -> 'reference_price_source'``.
    """
    LAST_TRADE = "last_trade"
    MIDPOINT = "midpoint"
    TOP_OF_BOOK = "top_of_book"


class RepricingDistanceType(str, Enum):
    """How ``target_distance`` / ``max_distance`` are interpreted.

    - PERCENT (``"P"``): Distance is a percentage of the reference price.
    - ABSOLUTE (``"A"``): Distance is in absolute price units.

    Single-letter codes are preserved for on-disk compatibility with the
    existing dashboard payload.
    """
    PERCENT = "P"
    ABSOLUTE = "A"


class RepricingUpdateMode(str, Enum):
    """How often the repricing loop evaluates a new target.

    - ADAPTIVE: Re-evaluate when the market moves (rate-limited by the min
      interval / max-per-hour throttles).
    - FIXED: Re-evaluate on a fixed cadence (``fixed_interval_seconds``).
    """
    ADAPTIVE = "adaptive"
    FIXED = "fixed"


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


class EventTriggerType(str, Enum):
    """Trigger categories for audit/event-stream payloads."""
    STEALTH_CONDITION = "stealth_condition"
    FOLLOW_UP = "follow_up"


class EventSourceChannel(str, Enum):
    """Named source channels for order_event_stream rows."""
    PLACEMENT_PRE_HOOK      = "placement_pre_hook"
    WS_USER                 = "ws_user"
    FILL_HOOK               = "fill_hook"
    REST_SUBMIT             = "rest_submit"
    PLACEMENT_POST_HOOK     = "placement_post_hook"
    ORDER_STATE_HOOK        = "order_state_hook"
    STEALTH_LIFECYCLE_HOOK  = "stealth_lifecycle_hook"
    ORDER_ENGINE_OPEN       = "order_engine_open_handler"
    ORDER_ENGINE_TERMINAL   = "order_engine_terminal_handler"


class EventStreamType(str, Enum):
    """Static event_type values written to order_event_stream.

    Dynamic values (e.g. ``stealth_<lifecycle_event>`` and ``order_<status>``)
    are derived from existing enums at runtime and are NOT listed here.
    """
    STEALTH_CONDITION_MET         = "stealth_condition_met"
    FILL_RECORDED                 = "fill_recorded"
    ORDER_SUBMITTED               = "order_submitted"
    STEALTH_REVEALED              = "stealth_revealed"
    STEALTH_FOLLOW_UP_CREATED     = "stealth_follow_up_created"
    INVENTORY_OPENED              = "inventory_opened"
    INVENTORY_CLOSED              = "inventory_closed"
    PARTIAL_FILL_DETECTED         = "partial_fill_detected"
    PARTIAL_FILL_PROGRESS_UPDATED = "partial_fill_progress_updated"
    PARTIAL_FILL_FOLLOW_UP_QUEUED = "partial_fill_follow_up_queued"
    PARTIAL_FILL_BELOW_MIN        = "partial_fill_below_min_accumulated"
    PARTIAL_FILL_FINALIZED        = "partial_fill_finalized"


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
# ORDER INVENTORY & LIFECYCLE TRACKING
# ============================================================================

class OrderStateEvent(str, Enum):
    """Lifecycle event emitted when an exchange-visible order changes state.

    Used by OrderStateHookRegistry to notify subscribers (e.g. OrderInventory)
    of working-order transitions. These map directly to exchange-confirmed states.

    - OPENED:    Order is now working on the exchange (OPEN/PENDING from WebSocket)
    - FILLED:    Order fully filled on the exchange
    - CANCELLED: Order cancelled (user-initiated or exchange-expired)
    - EXPIRED:   Order expired (e.g. GTD time-in-force elapsed)

    Integration:
        Dispatched from StateManager AFTER its internal lock is released so that
        subscribers never hold StateManager._lock, preventing any lock-ordering
        deadlock. See data/order_inventory.py and integration/order_state_hooks.py.
    """
    OPENED    = "OPENED"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED   = "EXPIRED"


class StealthLifecycleEvent(str, Enum):
    """Fine-grained stealth order state-machine transition events.

    Provides a complete play-by-play audit trail of every stealth order from
    creation through final execution or failure. Stored in order_event_stream
    via StealthLifecycleHookRegistry → OrderEventStreamPublisher.

    State machine flow:
        CREATED
          └─► CONDITION_WATCHING  (condition partially met, watching for hold duration)
                └─► CONDITION_MET (condition fully confirmed, order TRIGGERED)
                      └─► REVEAL_ATTEMPTED
                            ├─► PLACEMENT_BLOCKED  (pre-submission hook raised)  [terminal/retriable]
                            ├─► REVEAL_FAILED      (REST exception / network error) [terminal/retriable]
                            └─► REVEAL_SUCCEEDED   (slice placed on exchange books)
                                  ├─► FILL_RECEIVED (fill event arrived from exchange)
                                  ├─► EXECUTED      (all size filled)               [terminal]
                                  └─► CANCELLED     (cancelled at any stage)        [terminal]

    Integration:
        Dispatched from StealthOrderManager at each transition point. Hooks are
        called OUTSIDE any internal locks where possible. Subscribers receive a
        context dict with product_id, side, product_type, size, limit_price, reason,
        failure_reason (if applicable), placed_order_id (if applicable).
        See integration/stealth_lifecycle_hooks.py and data/order_inventory.py.
    """
    CREATED            = "CREATED"             # create_stealth_order() persisted
    CONDITION_WATCHING = "CONDITION_WATCHING"  # condition first partially met → PENDING
    CONDITION_MET      = "CONDITION_MET"       # condition confirmed → TRIGGERED
    REVEAL_ATTEMPTED   = "REVEAL_ATTEMPTED"    # slice placement about to be sent
    PLACEMENT_BLOCKED  = "PLACEMENT_BLOCKED"   # pre-submission hook blocked placement
    REVEAL_FAILED      = "REVEAL_FAILED"       # REST/network exception during placement
    REVEAL_SUCCEEDED   = "REVEAL_SUCCEEDED"    # slice confirmed placed on exchange
    FILL_RECEIVED      = "FILL_RECEIVED"       # fill event received for revealed slice
    EXECUTED           = "EXECUTED"            # all size executed
    CANCELLED          = "CANCELLED"           # order cancelled at any stage


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


# ============================================================================
# RUNTIME LIFECYCLE
# ============================================================================

class EngineState(str, Enum):
    """Engine lifecycle states for graceful shutdown / pause / restart.

    State machine (industry-standard quiesce-drain-stop model):

        RUNNING  --request_pause()-->     PAUSING  --(drain)-->  PAUSED
        PAUSED   --resume()-->            RUNNING
        RUNNING  --request_shutdown()-->  DRAINING --(drain)-->  STOPPED
        PAUSED   --request_shutdown()-->  DRAINING --(drain)-->  STOPPED

    Admission rules (what is accepted at each state):

        | State    | New orders | Cancellations | Fill processing | DB writes |
        | RUNNING  |    yes     |     yes       |       yes       |    yes    |
        | PAUSING  |    no      |     yes       |       yes       |    yes    |
        | PAUSED   |    no      |     yes       |       yes       |    yes    |
        | DRAINING |    no      |     yes       |       yes       |    yes    |
        | STOPPED  |    no      |     no        |       no        |    no     |

    "Soft pause" — pause stops *originating* new orders but keeps WS, fills,
    and cancellations active so existing positions remain manageable.
    """
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
