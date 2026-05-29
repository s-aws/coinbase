"""Data models - Core dataclasses for orders, positions, products."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, TypedDict
from datetime import datetime

from core.enums import (
    OrderSide,
    OrderStatus,
    ProductType,
    RepricingDistanceType,
    RepricingReferenceSource,
    RepricingUpdateMode,
)


class MarketData(TypedDict, total=False):
    """Snapshot of recent market data for a single product.

    Populated by ``StealthOrderBridge`` from the engine's market-data feed
    and consumed throughout the stealth path (condition evaluation,
    repricing reference resolution, reveal pricing, audit logging).

    All fields are optional (``total=False``) because the cache may hold
    a placeholder when no feed event has arrived yet — see
    ``StealthOrderManager._get_current_market_data``. Use ``safe_float``
    or explicit ``.get(..., default)`` at every read site; do not assume a
    field is present.

    Field semantics:
        product_id:    Coinbase product symbol (e.g. ``BTC-USDC``).
        price:         Last trade price.
        bid / ask:     Best bid / ask from the order book or ticker.
        volume_1m:     Trade volume in the last 60 seconds (used by the
                       repricing volume guardrail).
        market_spread: Pre-computed ``ask - bid`` when available.
        time:          Timestamp of the snapshot (engine-local datetime).
        source:        Provenance/control tag -- one of ``ticker``,
                       ``snapshot``, ``unavailable``,
                       ``synthetic_follow_up_seed``. Live-ticker-only
                       paths require ``ticker``; other values block those
                       paths and are also persisted/logged for audit.
    """
    product_id: str
    price: float
    bid: float
    ask: float
    volume_1m: float
    market_spread: float
    time: datetime
    source: str


class RepricingState(TypedDict, total=False):
    """Per-stealth-order anchor-repricing runtime state.

    Persisted as ``stealth_orders.anchor_repricing_state_json`` (JSONB).
    Holds the in-flight placement context plus the scheduling fields the
    repricing loop needs to decide *when* to act next.

    Pairs with :class:`RepricingPolicy`: the policy is the immutable
    config, the state is the mutable per-order ledger. Both are stored
    side-by-side on the stealth order row.

    All fields are optional (``total=False``) because state is built
    incrementally — a brand-new order has only ``reprice_history=[]``
    until the first reprice or placement event populates the rest.

    Field semantics:
        active_placement_client_order_id:
            Client order ID of the order currently resting on the exchange.
            Cleared when the order is cancelled or fills.
        active_exchange_order_id:
            Exchange order ID of the order currently resting on the exchange.
            Cleared when the order is cancelled or fills.
        active_exchange_price:
            Limit price actually submitted to the exchange (may differ from the
            logical target if clamped).
        current_logical_limit_price:
            The unclamped target price the policy resolved for this round.
        last_reprice_at:
            ISO-8601 string (JSONB-safe) of the last reprice timestamp.
            Used for rate limiting and analytics.
        next_reprice_at:
            ISO-8601 string (JSONB-safe) of the scheduling deadline.
            The repricing loop checks this on every tick to determine when to reprice.
        reprice_reason:
            Tag for the most recent reprice (``adaptive``, ``slide_step``,
            ``blocked_unprofitable``, ...). Used for analytics and debugging.
        reprice_history:
            Append-only list of ISO timestamps, one per successful reprice.
            Used by slide-calibration analytics — see
            ``database/slide_calibration_helpers.py``.
        last_profitability_block_reason:
            Set when the reveal-time profitability gate blocks a reprice.
            Cleared on the next successful reprice.
        reveal_condition_price_offsets:
            Offsets captured the first time we reprice an order, so the
            reveal-condition price thresholds can be moved in lock-step
            with the limit price. See
            ``_apply_reveal_condition_price_tracking``.
        post_fill_retreat_offset:
            Cumulative absolute price offset from same-side post-fill retreat.
            Future anchor repricing adds this offset to target bands so the retreat
            is not erased on the next tick.
        post_fill_retreat_count:
            Cumulative count of same-side post-fill retreats. Used for tracking
            and analytics.
    """
    active_placement_client_order_id: Optional[str]
    active_exchange_order_id: Optional[str]
    active_exchange_price: Optional[float]
    current_logical_limit_price: Optional[float]
    last_reprice_at: str
    next_reprice_at: str
    reprice_reason: str
    reprice_history: List[str]
    last_profitability_block_reason: str
    reveal_condition_price_offsets: Dict[str, float]
    post_fill_retreat_offset: float
    post_fill_retreat_count: int


def _required_str(data: Dict[str, Any], key: str, owner: str) -> str:
    """Boundary validator: pull a required string from an API/DB payload.

    Pre-strict-mode, missing keys silently became ``None`` and bound to a
    non-Optional ``str`` field, deferring the failure to the first attribute
    access. Strict typing surfaces this as a real risk; this helper turns it
    into an explicit error at the boundary so the offending payload is in
    the traceback.
    """
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{owner}.from_dict: missing required string field {key!r} "
            f"(got {value!r})"
        )
    return value


@dataclass
class Product:
    """Trading product metadata.

    Represents a trading product (spot or futures) with its market characteristics.
    This class is used to store and manage product information retrieved from
    Coinbase's API, including pricing increments, minimum sizes, and trading status.

    Attributes:
        product_id: Coinbase product symbol (e.g. ``BTC-USDC``).
        product_type: Type of product (SPOT or FUTURE).
        base_increment: Minimum increment for base currency (e.g. '0.001' for BTC).
        quote_increment: Minimum increment for quote currency (e.g. '0.01' for USDC).
        price_increment: Minimum price increment (e.g. '0.01' for USDC).
        base_min_size: Minimum order size in base currency (e.g. '0.001' for BTC).
        trading_disabled: Boolean indicating if trading is disabled for this product.

    Example:
        >>> product = Product(
        ...     product_id="BTC-USDC",
        ...     product_type=ProductType.SPOT,
        ...     base_increment="0.001",
        ...     quote_increment="0.01",
        ...     price_increment="0.01",
        ...     base_min_size="0.001",
        ...     trading_disabled=False
        ... )
    """
    product_id: str
    product_type: ProductType
    base_increment: str
    quote_increment: str
    price_increment: str
    base_min_size: str = "0"
    trading_disabled: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Product':
        """Create Product from API response dict.

        This method is used to construct a Product instance from a dictionary
        typically received from Coinbase's API. It handles type conversion and
        default values for missing fields.

        Args:
            data: Dictionary containing product information from Coinbase API.

        Returns:
            Product: A new Product instance populated with data from the dict.

        Example:
            >>> api_data = {
            ...     'product_id': 'BTC-USDC',
            ...     'product_type': 'SPOT',
            ...     'base_increment': '0.001',
            ...     'quote_increment': '0.01',
            ...     'price_increment': '0.01'
            ... }
            >>> product = Product.from_dict(api_data)
        """
        return cls(
            product_id=_required_str(data, 'product_id', 'Product'),
            product_type=ProductType(str(data.get('product_type', 'SPOT')).upper()),
            base_increment=str(data.get('base_increment', '0')),
            quote_increment=str(data.get('quote_increment', '0')),
            price_increment=str(data.get('price_increment', '0')),
            base_min_size=str(data.get('base_min_size', '0')),
            trading_disabled=bool(data.get('trading_disabled', False)),
        )


@dataclass
class Position:
    """Futures position - contract holdings.

    Represents a futures position with its current holdings and pricing information.
    This class is used to track position details for futures contracts.

    Attributes:
        product_id: Coinbase product symbol (e.g. ``BTC-USDC``).
        side: Position side ('LONG' or 'SHORT').
        number_of_contracts: Number of contracts in the position.
        current_price: Current market price of the position (optional).
        entry_price: Entry price of the position (optional).

    Example:
        >>> position = Position(
        ...     product_id="BTC-USDC",
        ...     side="LONG",
        ...     number_of_contracts="10",
        ...     current_price="40000.00",
        ...     entry_price="38000.00"
        ... )
    """
    product_id: str
    side: str  # 'LONG' or 'SHORT'
    number_of_contracts: str
    current_price: Optional[str] = None
    entry_price: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """Create Position from API response dict.

        This method is used to construct a Position instance from a dictionary
        typically received from Coinbase's API. It handles type conversion and
        default values for missing fields.

        Args:
            data: Dictionary containing position information from Coinbase API.

        Returns:
            Position: A new Position instance populated with data from the dict.

        Example:
            >>> api_data = {
            ...     'product_id': 'BTC-USDC',
            ...     'side': 'LONG',
            ...     'number_of_contracts': '10',
            ...     'current_price': '40000.00',
            ...     'entry_price': '38000.00'
            ... }
            >>> position = Position.from_dict(api_data)
        """
        return cls(
            product_id=_required_str(data, 'product_id', 'Position'),
            side=_required_str(data, 'side', 'Position'),
            number_of_contracts=str(data.get('number_of_contracts', '0')),
            current_price=data.get('current_price'),
            entry_price=data.get('entry_price'),
        )


@dataclass
class Wallet:
    """Account wallet - currency balance.

    Represents a wallet with currency balance information for a Coinbase account.
    This class is used to track wallet details including available and total balances.

    Attributes:
        currency: Currency code (e.g. ``BTC``, ``USDC``).
        available_balance: Available balance for trading (excluding reserved amounts).
        total_balance: Total balance including reserved amounts.
        created_at: ISO timestamp when the wallet was created (optional).
        updated_at: ISO timestamp when the wallet was last updated (optional).
        deleted_at: ISO timestamp when the wallet was deleted (optional).

    Example:
        >>> wallet = Wallet(
        ...     currency="BTC",
        ...     available_balance="1.5",
        ...     total_balance="2.0",
        ...     created_at="2026-05-01T10:00:00Z",
        ...     updated_at="2026-05-01T12:00:00Z"
        ... )
    """
    currency: str
    available_balance: str
    total_balance: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Wallet':
        """Create Wallet from API response dict.

        This method is used to construct a Wallet instance from a dictionary
        typically received from Coinbase's API. It handles type conversion and
        default values for missing fields.

        Args:
            data: Dictionary containing wallet information from Coinbase API.

        Returns:
            Wallet: A new Wallet instance populated with data from the dict.

        Example:
            >>> api_data = {
            ...     'currency': 'BTC',
            ...     'available_balance': '1.5',
            ...     'total_balance': '2.0',
            ...     'created_at': '2026-05-01T10:00:00Z'
            ... }
            >>> wallet = Wallet.from_dict(api_data)
        """
        return cls(
            currency=_required_str(data, 'currency', 'Wallet'),
            available_balance=str(data.get('available_balance', '0')),
            total_balance=str(data.get('total_balance', '0')),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            deleted_at=data.get('deleted_at'),
        )


@dataclass
class Order:
    """Trading order - spot or futures.

    Represents a trading order with all relevant information for spot and futures trading.
    This class is used to track order details including status, pricing, and execution information.

    Attributes:
        client_order_id: Internal client order ID for tracking (UUID).
        product_id: Coinbase product symbol (e.g. ``BTC-USDC``).
        order_side: Direction of the order (BUY or SELL).
        status: Current status of the order (OPEN, FILLED, CANCELLED, etc.).
        size: Total order size in base currency.
        price: Order price (for market orders).
        filled_size: Size that has been filled.
        limit_price: Limit price for limit orders (optional).
        avg_price: Average price at which the order was filled (optional).
        order_id: Exchange order ID (only for exchange-facing operations).
        product_type: Type of product (SPOT or FUTURE).
        created_at: ISO timestamp when the order was created.
        custom_metadata: Additional metadata for custom tracking.

    Example:
        >>> order = Order(
        ...     client_order_id="uuid-12345",
        ...     product_id="BTC-USDC",
        ...     order_side=OrderSide.BUY,
        ...     status=OrderStatus.OPEN,
        ...     size=0.5,
        ...     price=40000.0,
        ...     filled_size=0.0,
        ...     limit_price=40000.0,
        ...     avg_price=None,
        ...     order_id="exchange-12345",
        ...     product_type=ProductType.SPOT,
        ...     created_at=datetime.utcnow()
        ... )
    """
    client_order_id: str
    product_id: str
    order_side: OrderSide
    status: OrderStatus
    size: float = 0.0
    price: float = 0.0
    filled_size: float = 0.0
    limit_price: Optional[float] = None
    avg_price: Optional[float] = None
    order_id: Optional[str] = None
    product_type: ProductType = ProductType.SPOT
    created_at: Optional[datetime] = None
    custom_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Order':
        """Create Order from API response dict.

        This method is used to construct an Order instance from a dictionary
        typically received from Coinbase's API. It handles type conversion,
        default values, and validation for missing fields.

        Args:
            data: Dictionary containing order information from Coinbase API.

        Returns:
            Order: A new Order instance populated with data from the dict.

        Example:
            >>> api_data = {
            ...     'client_order_id': 'uuid-12345',
            ...     'product_id': 'BTC-USDC',
            ...     'order_side': 'BUY',
            ...     'status': 'OPEN',
            ...     'size': '0.5',
            ...     'price': '40000.0',
            ...     'filled_size': '0.0',
            ...     'limit_price': '40000.0',
            ...     'avg_price': None,
            ...     'order_id': 'exchange-12345',
            ...     'product_type': 'SPOT'
            ... }
            >>> order = Order.from_dict(api_data)
        """
        from calculation.resolver import safe_float, normalize_product_type

        side_raw = data.get('order_side') or data.get('side')
        if isinstance(side_raw, OrderSide):
            order_side = side_raw
        elif isinstance(side_raw, str):
            order_side = OrderSide(side_raw)
        else:
            raise ValueError(
                f"Order.from_dict: missing or invalid 'order_side'/'side' "
                f"(got {side_raw!r})"
            )
        status_str = str(data.get('status', 'OPEN')).upper()

        return cls(
            client_order_id=_required_str(data, 'client_order_id', 'Order'),
            product_id=_required_str(data, 'product_id', 'Order'),
            order_side=order_side,
            status=OrderStatus(status_str) if status_str in [e.value for e in OrderStatus] else OrderStatus.OPEN,
            size=safe_float(data.get('size'), 0.0),
            price=safe_float(data.get('price'), 0.0),
            filled_size=safe_float(data.get('filled_size'), 0.0),
            limit_price=safe_float(data.get('limit_price'), default=None),
            avg_price=safe_float(data.get('avg_price'), default=None),
            order_id=data.get('order_id'),
            product_type=ProductType(normalize_product_type(data)),
            created_at=data.get('created_at'),
            custom_metadata=data,
        )


@dataclass
class FollowUpOrderTemplate:
    """Template for creating a follow-up order after fill/cancellation."""
    product_id: str
    side: OrderSide
    order_base_size: str
    start_price: str
    order_price_difference: str
    profit_move_pct: float
    mandatory_fee: float = 0.0
    current_contract_count: str = "N/A"
    position_update: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API placement."""
        return {
            'product_id': self.product_id,
            'side': self.side.value,
            'order_base_size': self.order_base_size,
            'start_price': self.start_price,
            'order_price_difference': self.order_price_difference,
            'profit_move_pct': self.profit_move_pct,
            'mandatory_fee': self.mandatory_fee,
            'current_contract_count': self.current_contract_count,
            'position_update': self.position_update,
        }


@dataclass
class RevealExecutionPlan:
    """Plan for revealing a stealth order - captures pricing intent and market context.

    Encapsulates all information needed to execute a stealth order reveal, including
    what price to submit, why that price was chosen, and current market context.
    Used for:
    - Pre-reveal planning and validation
    - Reveal-time price resolution
    - Post-reveal profitability revalidation
    - Audit trail of reveal decisions

    Attributes:
        configured_limit_price: Original limit price from stealth order creation.
        submitted_limit_price: Actual limit price that will be submitted to exchange.
        reveal_pricing_policy: Policy that determined the price (RevealPricingPolicy enum value as string).
        reveal_price_source: How the price was sourced (RevealPriceSource enum value, e.g. ticker_best_ask).
        fallback_used: Whether configured limit was used as fallback (market data unavailable).
        market_source: Source of market data (ticker, snapshot, unavailable).
        market_bid: Best bid price at reveal time.
        market_ask: Best ask price at reveal time.
        target_movement: Profit target (decimal, e.g. 0.003 for 0.3%) resolved
            from the canonical ``order_parent`` row. Used by the reveal-time
            profitability gate. ``None`` when no target is configured.
        target_movement_type: ``'P'`` (percentage) or ``'A'`` (absolute);
            paired with ``target_movement``. ``None`` when target is missing.
        target_movement_source: Where ``target_movement`` was resolved from
            (e.g. ``'order_parent'``, ``'stealth_order'``, ``'unavailable'``).
            Recorded for audit so silent skips of the profitability gate are
            traceable.
        post_only: Whether the placement must submit with ``post_only=True``.
            Derived from the reveal policy (see
            :meth:`core.enums.RevealPricingPolicy.implies_post_only`):
            ``CONFIGURED_LIMIT`` → ``False`` (taker), ``TOP_OF_BOOK`` and
            ``MIDPOINT`` → ``True`` (maker). Drives both the fee tier used
            in profitability validation (maker vs taker) and the actual
            ``post_only`` flag passed to ``REST_CLIENT.place_limit_order``.

    Example:
        >>> plan = RevealExecutionPlan(
        ...     configured_limit_price=40000.0,
        ...     submitted_limit_price=40005.0,
        ...     reveal_pricing_policy="top_of_book",
        ...     reveal_price_source="ticker_best_ask",
        ...     fallback_used=False,
        ...     market_source="ticker",
        ...     market_bid=39995.0,
        ...     market_ask=40005.0,
        ...     target_movement=0.003,
        ...     target_movement_type="P",
        ...     target_movement_source="order_parent",
        ...     post_only=True
        ... )
    """
    configured_limit_price: float
    submitted_limit_price: float
    reveal_pricing_policy: str  # RevealPricingPolicy enum value as string
    reveal_price_source: str  # RevealPriceSource enum value as string
    fallback_used: bool
    market_source: Optional[str] = None
    market_bid: Optional[float] = None
    market_ask: Optional[float] = None
    target_movement: Optional[float] = None
    target_movement_type: Optional[str] = None
    target_movement_source: Optional[str] = None
    post_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for persistence/serialization.

        Returns:
            Dictionary representation of the RevealExecutionPlan for persistence.

        Example:
            >>> plan = RevealExecutionPlan(...)
            >>> plan_dict = plan.to_dict()
            >>> print(plan_dict['configured_limit_price'])
        """
        return {
            'configured_limit_price': self.configured_limit_price,
            'submitted_limit_price': self.submitted_limit_price,
            'reveal_pricing_policy': self.reveal_pricing_policy,
            'reveal_price_source': self.reveal_price_source,
            'fallback_used': self.fallback_used,
            'market_source': self.market_source,
            'market_bid': self.market_bid,
            'market_ask': self.market_ask,
            'target_movement': self.target_movement,
            'target_movement_type': self.target_movement_type,
            'target_movement_source': self.target_movement_source,
            'post_only': self.post_only,
        }


@dataclass
class StealthMovePlan:
    """Plan for "moving" a REVEALED stealth order — i.e. cancel-and-replace
    on the exchange while keeping the same internal ``stealth_order_id``.

    Coinbase exposes no order-edit endpoint, so a move is implemented as
    cancel + place. This dataclass captures every decision needed to
    execute the move atomically, in the same integrated-by-design shape
    as :class:`RevealExecutionPlan`:

    - **Single source of truth** — built once via
      ``StealthOrderManager.build_stealth_move_plan(...)``.
    - **Composes RevealExecutionPlan** — pricing/policy/market context for
      the *new* placement is delegated to the existing reveal path so
      there is one canonical pricing decision in the system.
    - **Audit-friendly** — every field is persisted alongside the move
      audit row.

    Current move scope (pinned by ``tests/regression/test_stealth_move_revealed.py``):
    - Order must be ``REVEALED`` with ``executed_size == 0`` (no partial
      fills); reject at build time otherwise.
    - Move always resets per-order anchor repricing state and
      ``revealed_orders[]`` history; the new placement starts fresh.
    - Flat hierarchy preserved: ``root_parent_client_order_id`` is
      resolved via :func:`resolve_stealth_chain_root` and reused for the
      new placement's parent linkage.

    Attributes:
        stealth_order_id: Internal id of the stealth order being moved.
            Persisted across the move; the new exchange placement is
            recorded against the same stealth order.
        root_parent_client_order_id: Original parent client_order_id
            (flat hierarchy: never re-parented to a child).
        old_exchange_order_id: Coinbase order id of the placement being
            cancelled. Required for the cancel call.
        old_submitted_price: Limit price of the placement being cancelled,
            captured for the audit snapshot.
        new_configured_limit_price: New target limit price the user is
            moving the order to. Becomes the order's persisted
            ``limit_price`` and the input to the new reveal plan.
        new_target_movement: Optional override of the parent's profit
            target. ``None`` means inherit unchanged.
        new_target_movement_type: ``'P'`` (percent) or ``'A'`` (absolute);
            paired with ``new_target_movement``. ``None`` when no override.
        reveal_plan: The composed :class:`RevealExecutionPlan` describing
            the *new* placement. Drives ``submitted_limit_price`` so we
            never duplicate pricing logic.
        reset_repricing_state: Always ``True`` in v1. Field exists so
            future variants (e.g. preserve-cooldown moves) are explicit.
        reset_reveal_counters: Always ``True`` in v1. Same rationale.
        reason: Why the move was triggered (audit field).
        notes: Optional human-readable note for the audit row.
        market_bid: Best bid at plan-build time (audit snapshot).
        market_ask: Best ask at plan-build time (audit snapshot.

    Example:
        >>> move_plan = StealthMovePlan(
        ...     stealth_order_id="stealth-12345",
        ...     root_parent_client_order_id="parent-12345",
        ...     old_exchange_order_id="exchange-12345",
        ...     old_submitted_price=40000.0,
        ...     new_configured_limit_price=40050.0,
        ...     reveal_plan=RevealExecutionPlan(...),
        ...     reason=StealthMoveReason.MANUAL_USER_MOVE,
        ...     market_bid=39995.0,
        ...     market_ask=40005.0
        ... )
    """

    stealth_order_id: str
    root_parent_client_order_id: str
    old_exchange_order_id: str
    old_submitted_price: float
    new_configured_limit_price: float
    reveal_plan: "RevealExecutionPlan"
    reason: "StealthMoveReason"
    new_target_movement: Optional[float] = None
    new_target_movement_type: Optional[str] = None
    reset_repricing_state: bool = True
    reset_reveal_counters: bool = True
    notes: Optional[str] = None
    market_bid: Optional[float] = None
    market_ask: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence in the move audit row.

        Returns:
            Dictionary representation of the StealthMovePlan for audit persistence.

        Example:
            >>> move_plan = StealthMovePlan(...)
            >>> move_dict = move_plan.to_dict()
            >>> print(move_dict['stealth_order_id'])
        """
        return {
            'stealth_order_id': self.stealth_order_id,
            'root_parent_client_order_id': self.root_parent_client_order_id,
            'old_exchange_order_id': self.old_exchange_order_id,
            'old_submitted_price': self.old_submitted_price,
            'new_configured_limit_price': self.new_configured_limit_price,
            'new_target_movement': self.new_target_movement,
            'new_target_movement_type': self.new_target_movement_type,
            'reveal_plan': self.reveal_plan.to_dict() if self.reveal_plan else None,
            'reset_repricing_state': self.reset_repricing_state,
            'reset_reveal_counters': self.reset_reveal_counters,
            'reason': self.reason.value if self.reason is not None else None,
            'notes': self.notes,
            'market_bid': self.market_bid,
            'market_ask': self.market_ask,
        }


@dataclass
class StealthMoveResult:
    """Outcome of a successful :meth:`StealthOrderManager.execute_stealth_move`.

    Both ids are returned — internal (``new_placement_client_order_id``)
    AND exchange (``new_exchange_order_id``) — because:

    - The internal id is what every downstream system uses to track the
      placement (per AGENTS.md: ``client_order_id`` for internal tracking).
    - The exchange id is what the operator types into the Coinbase UI to
      look up the live order, and what the WS payload surfaces inline so
      the dashboard doesn't need to round-trip through the audit table.

    Returning a structured result instead of a bare string also makes
    future additions (submitted_price, status snapshot, ...) backwards
    compatible without breaking call-site signatures.
    """

    new_placement_client_order_id: str
    new_exchange_order_id: Optional[str]
    new_submitted_price: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'new_placement_client_order_id': self.new_placement_client_order_id,
            'new_exchange_order_id': self.new_exchange_order_id,
            'new_submitted_price': self.new_submitted_price,
        }


@dataclass
class RepricingPolicy:
    """Anchor-repricing policy for a stealth order.

    Single source of truth for every field stored in
    ``stealth_orders.anchor_repricing_policy_json``. Built once via
    :meth:`from_dict` (the canonical normalizer) and consumed at every read
    site via attribute access — no more ``policy.get("x")`` magic-string
    duplication scattered across the manager and the dashboard.

    On-disk shape is preserved by :meth:`to_dict`: enum fields serialize as
    their string ``.value`` so existing JSONB rows load without migration.

    Build helpers:
    - ``from_dict(raw)`` — normalize a raw dict (clamps, default fill-in,
      enum coercion). Disabled policy returns a minimal ``enabled=False``
      instance.
    - ``coerce(policy_or_dict)`` — accept either a dict or an existing
      ``RepricingPolicy`` and return a ``RepricingPolicy``. Used by every
      internal helper so callers don't have to wrap.

    Behavior helpers (encapsulate per-site decisions so the rule lives
    here, not at every caller):
    - ``compute_distance_bands(side, reference_price)``
    - ``clamp_to_step(current_price, desired_price)``
    - ``should_reprice_revealed`` (property)
    - ``post_only`` (property)

    Defaults match the historical behavior of
    ``StealthOrderManager._normalize_anchor_repricing_policy`` and are
    pinned by tests in ``tests/integration/test_anchor_repricing_phase2.py``
    and ``tests/regression/test_repricing_policy.py``.

    Attributes:
        enabled: Whether anchor repricing is enabled for this stealth order.
        reference_price_source: Source of reference price for repricing (MIDPOINT, TOP_OF_BOOK, LAST_TRADE).
        distance_type: How target_distance and max_distance are interpreted (PERCENT or ABSOLUTE).
        target_distance: Target distance from reference price for repricing.
        max_distance: Maximum distance from reference price for repricing.
        update_mode: How often the repricing loop evaluates a new target (ADAPTIVE or FIXED).
        fixed_interval_seconds: Interval in seconds for FIXED update mode.
        allow_revealed_reprice: Whether repricing applies to already-revealed orders.
        min_price_change: Minimum price change required to trigger a reprice.
        hysteresis_bps: Hysteresis in basis points to prevent oscillation.
        min_reprice_interval_seconds: Minimum interval between reprices in seconds.
        max_reprices_per_hour: Maximum number of reprices allowed per hour.
        post_only_required: Whether repriced orders must submit with post_only=True.
        converge_to_target: Whether to converge toward the target price.
        inherit_to_follow_ups: Whether this policy is inherited by follow-up orders.
        slide_mode: Whether to use slide mode for repricing.
        max_step_per_reprice: Maximum price step per reprice in slide mode.
        volatility_sensitivity: Sensitivity to market volatility for guardrails.
        max_reprice_window_seconds: Maximum window for reprice rate limiting.
        require_minimum_volume: Minimum volume required for repricing.
        enable_spread_monitoring: Whether to monitor bid-ask spread.
        max_spread_bps: Maximum allowed spread in basis points.
        follow_up_retreat_distance: Distance for post-fill follow-up retreat (fingerprint-hiding).
        follow_up_retreat_jitter: Jitter for retreat distance (fingerprint-hiding).

    Example:
        >>> policy = RepricingPolicy(
        ...     enabled=True,
        ...     reference_price_source=RepricingReferenceSource.MIDPOINT,
        ...     distance_type=RepricingDistanceType.PERCENT,
        ...     target_distance=0.005,  # 0.5%
        ...     max_distance=0.01,      # 1%
        ...     update_mode=RepricingUpdateMode.ADAPTIVE,
        ...     allow_revealed_reprice=True,
        ...     min_price_change=0.01,
        ...     hysteresis_bps=5.0,
        ...     min_reprice_interval_seconds=30,
        ...     max_reprices_per_hour=20,
        ...     post_only_required=True,
        ...     converge_to_target=True,
        ...     inherit_to_follow_ups=True,
        ...     slide_mode=False,
        ...     max_step_per_reprice=0.0,
        ...     volatility_sensitivity=1.0,
        ...     max_reprice_window_seconds=600,
        ...     require_minimum_volume=0.0,
        ...     enable_spread_monitoring=False,
        ...     max_spread_bps=50.0,
        ...     follow_up_retreat_distance=0.0005,  # 5 bps
        ...     follow_up_retreat_jitter=0.5
        ... )
    """

    enabled: bool = False
    reference_price_source: RepricingReferenceSource = RepricingReferenceSource.MIDPOINT
    distance_type: RepricingDistanceType = RepricingDistanceType.PERCENT
    target_distance: float = 0.0
    max_distance: float = 0.0
    update_mode: RepricingUpdateMode = RepricingUpdateMode.ADAPTIVE
    fixed_interval_seconds: int = 60
    allow_revealed_reprice: bool = True
    min_price_change: float = 0.01
    hysteresis_bps: float = 5.0
    min_reprice_interval_seconds: int = 30
    max_reprices_per_hour: int = 20
    post_only_required: bool = True
    converge_to_target: bool = True
    inherit_to_follow_ups: bool = True
    slide_mode: bool = False
    max_step_per_reprice: float = 0.0
    # Phase 2 guardrails
    volatility_sensitivity: float = 1.0
    max_reprice_window_seconds: int = 600
    require_minimum_volume: float = 0.0
    enable_spread_monitoring: bool = False
    max_spread_bps: float = 50.0

    # ---- post-fill follow-up fingerprint-hiding ----
    # Always RETREAT direction (away from the price that just got hit /
    # away from the price the caller would otherwise post at). Always
    # PERCENT-based (scale-invariant fingerprint regardless of the
    # product's price magnitude).
    #
    # Defaults are non-zero (opt-OUT, not opt-in): every follow-up gets a
    # small retreat so the fill -> follow-up correlation isn't an exact
    # multiple of ``target_movement``. Set to 0.0 to disable.
    #
    # The goal is fingerprint-hiding (reaction-magnitude signal), NOT
    # inventory-hiding. The fact that a follow-up exists already discloses
    # inventory; this just blurs how predictable your post-fill price is.
    follow_up_retreat_distance: float = 0.0005  # 5 bps default
    follow_up_retreat_jitter:   float = 0.5     # +/-50% of distance

    # ---- builders ----

    @classmethod
    def disabled(cls) -> 'RepricingPolicy':
        """Canonical \"no repricing\" instance. Equivalent to ``{\"enabled\": False}``.

        Returns:
            RepricingPolicy: A disabled repricing policy instance.

        Example:
            >>> policy = RepricingPolicy.disabled()
            >>> print(policy.enabled)
            False
        """
        return cls(enabled=False)

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> 'RepricingPolicy':
        """Field-by-field normalizer for an arbitrary dict.

        Lenient: missing fields fall back to documented defaults; only the
        ``enabled`` flag short-circuits to a fully-disabled instance. The
        "meaningless config" gate (e.g. ``target_distance <= 0`` → disable)
        belongs to the *storage* path — see
        :meth:`StealthOrderManager._normalize_anchor_repricing_policy` —
        because consumers that read already-stored policies shouldn't have
        their config silently collapsed by a re-read.

        Args:
            raw: Dictionary containing policy configuration.

        Returns:
            RepricingPolicy: A normalized RepricingPolicy instance.

        Example:
            >>> policy_dict = {
            ...     'enabled': True,
            ...     'target_distance': 0.005,
            ...     'distance_type': 'P'
            ... }
            >>> policy = RepricingPolicy.from_dict(policy_dict)
        """
        # Local import keeps models.py free of calculation-layer cycles.
        from configuration import safe_float

        policy = dict(raw or {})
        if not bool(policy.get('enabled')):
            return cls.disabled()

        # Reference source (enum, fallback to MIDPOINT)
        ref_raw = str(
            policy.get('reference_price_source')
            or RepricingReferenceSource.MIDPOINT.value
        ).strip().lower()
        try:
            reference_price_source = RepricingReferenceSource(ref_raw)
        except ValueError:
            reference_price_source = RepricingReferenceSource.MIDPOINT

        # Distance type (enum, fallback to PERCENT)
        dist_raw = str(
            policy.get('distance_type') or RepricingDistanceType.PERCENT.value
        ).strip().upper()
        try:
            distance_type = RepricingDistanceType(dist_raw)
        except ValueError:
            distance_type = RepricingDistanceType.PERCENT

        # Distances. Note: ``target_distance`` may be 0 here — the gate that
        # collapses such a policy to ``disabled`` lives in the storage path,
        # not here, so consumers that pass partial dicts (e.g. tests
        # exercising a single guardrail) keep all the field overrides they
        # set.
        target_distance = max(safe_float(policy.get('target_distance'), default=0.0), 0.0)
        max_distance = safe_float(policy.get('max_distance'), default=target_distance)
        if max_distance < target_distance:
            max_distance = target_distance

        # Update mode (enum, fallback to ADAPTIVE)
        mode_raw = str(
            policy.get('update_mode') or RepricingUpdateMode.ADAPTIVE.value
        ).strip().lower()
        try:
            update_mode = RepricingUpdateMode(mode_raw)
        except ValueError:
            update_mode = RepricingUpdateMode.ADAPTIVE

        fixed_interval_seconds = int(
            safe_float(policy.get('fixed_interval_seconds'), default=60.0)
        )
        if fixed_interval_seconds <= 0:
            fixed_interval_seconds = 60

        min_price_change = max(
            safe_float(policy.get('min_price_change'), default=0.01), 0.0
        )
        hysteresis_bps = max(
            safe_float(policy.get('hysteresis_bps'), default=5.0), 0.0
        )

        # Slide-mode coupling: sub-tick gates would suppress slide steps,
        # so force them to zero when slide mode is active. Pacing is
        # controlled by the throttles instead.
        slide_mode = bool(policy.get('slide_mode', False))
        max_step_per_reprice = max(
            safe_float(policy.get('max_step_per_reprice'), default=0.0), 0.0
        )
        if slide_mode and max_step_per_reprice > 0:
            min_price_change = 0.0
            hysteresis_bps = 0.0

        min_reprice_interval_seconds = max(
            int(safe_float(policy.get('min_reprice_interval_seconds'), default=30.0)),
            0,
        )
        max_reprices_per_hour = max(
            int(safe_float(policy.get('max_reprices_per_hour'), default=20.0)),
            1,
        )

        # Phase 2 guardrails
        volatility_sensitivity = max(
            min(safe_float(policy.get('volatility_sensitivity'), default=1.0), 2.0),
            0.1,
        )
        max_reprice_window_seconds = max(
            int(safe_float(policy.get('max_reprice_window_seconds'), default=600.0)),
            min_reprice_interval_seconds,
        )
        require_minimum_volume = max(
            safe_float(policy.get('require_minimum_volume'), default=0.0), 0.0
        )
        enable_spread_monitoring = bool(policy.get('enable_spread_monitoring', False))
        max_spread_bps = max(
            safe_float(policy.get('max_spread_bps'), default=50.0), 0.0
        )

        # Follow-up retreat (fingerprint-hiding). Both clamped to >= 0;
        # jitter additionally clamped to <= 1.0 so the effective step
        # cannot flip sign and become a chase. Defaults match the
        # dataclass defaults (opt-out: 5bps / 0.5 jitter) so loading a
        # legacy policy that omits these fields gets the new behavior.
        follow_up_retreat_distance = max(
            safe_float(policy.get('follow_up_retreat_distance'), default=0.0005), 0.0
        )
        follow_up_retreat_jitter = max(
            min(safe_float(policy.get('follow_up_retreat_jitter'), default=0.5), 1.0),
            0.0,
        )

        return cls(
            enabled=True,
            reference_price_source=reference_price_source,
            distance_type=distance_type,
            target_distance=target_distance,
            max_distance=max_distance,
            update_mode=update_mode,
            fixed_interval_seconds=fixed_interval_seconds,
            allow_revealed_reprice=bool(policy.get('allow_revealed_reprice', True)),
            min_price_change=min_price_change,
            hysteresis_bps=hysteresis_bps,
            min_reprice_interval_seconds=min_reprice_interval_seconds,
            max_reprices_per_hour=max_reprices_per_hour,
            post_only_required=bool(policy.get('post_only_required', True)),
            converge_to_target=bool(policy.get('converge_to_target', True)),
            inherit_to_follow_ups=bool(policy.get('inherit_to_follow_ups', True)),
            slide_mode=slide_mode,
            max_step_per_reprice=max_step_per_reprice,
            volatility_sensitivity=volatility_sensitivity,
            max_reprice_window_seconds=max_reprice_window_seconds,
            require_minimum_volume=require_minimum_volume,
            enable_spread_monitoring=enable_spread_monitoring,
            max_spread_bps=max_spread_bps,
            follow_up_retreat_distance=follow_up_retreat_distance,
            follow_up_retreat_jitter=follow_up_retreat_jitter,
        )

    @classmethod
    def coerce(cls, value: Any) -> 'RepricingPolicy':
        """Accept a dict, ``None``, or an existing ``RepricingPolicy``.

        Lets internal helpers be called from both refactored sites and
        legacy dict callers (incl. tests) without forcing wrapping at every
        call site.

        Args:
            value: Either a dict, None, or an existing RepricingPolicy instance.

        Returns:
            RepricingPolicy: A RepricingPolicy instance.

        Example:
            >>> policy_dict = {'enabled': True, 'target_distance': 0.005}
            >>> policy = RepricingPolicy.coerce(policy_dict)
        """
        if isinstance(value, cls):
            return value
        return cls.from_dict(value if isinstance(value, dict) else None)

    # ---- serialization ----

    def to_dict(self) -> Dict[str, Any]:
        """JSONB-compatible dict; preserves the historical on-disk shape.

        Disabled policies serialize to ``{\"enabled\": False}`` only —
        matches what the previous normalizer wrote so persistence is a
        bit-for-bit no-op.

        Returns:
            Dict[str, Any]: Dictionary representation of the policy for persistence.

        Example:
            >>> policy = RepricingPolicy(...)
            >>> policy_dict = policy.to_dict()
            >>> print(policy_dict['enabled'])
        """
        if not self.enabled:
            return {'enabled': False}
        return {
            'enabled': True,
            'reference_price_source': self.reference_price_source.value,
            'distance_type': self.distance_type.value,
            'target_distance': self.target_distance,
            'max_distance': self.max_distance,
            'update_mode': self.update_mode.value,
            'fixed_interval_seconds': self.fixed_interval_seconds,
            'allow_revealed_reprice': self.allow_revealed_reprice,
            'min_price_change': self.min_price_change,
            'hysteresis_bps': self.hysteresis_bps,
            'min_reprice_interval_seconds': self.min_reprice_interval_seconds,
            'max_reprices_per_hour': self.max_reprices_per_hour,
            'post_only_required': self.post_only_required,
            'converge_to_target': self.converge_to_target,
            'inherit_to_follow_ups': self.inherit_to_follow_ups,
            'slide_mode': self.slide_mode,
            'max_step_per_reprice': self.max_step_per_reprice,
            'volatility_sensitivity': self.volatility_sensitivity,
            'max_reprice_window_seconds': self.max_reprice_window_seconds,
            'require_minimum_volume': self.require_minimum_volume,
            'enable_spread_monitoring': self.enable_spread_monitoring,
            'max_spread_bps': self.max_spread_bps,
            'follow_up_retreat_distance': self.follow_up_retreat_distance,
            'follow_up_retreat_jitter': self.follow_up_retreat_jitter,
        }

    # ---- behavior helpers ----

    def compute_distance_bands(
        self, side: str, reference_price: float
    ) -> Dict[str, float]:
        """Resolve target/max prices around ``reference_price`` for ``side``.

        Encapsulates the percent-vs-absolute branch so callers don't have
        to inspect ``distance_type`` themselves.

        Args:
            side: Order side ('BUY' or 'SELL').
            reference_price: Reference price for computing bands.

        Returns:
            Dict[str, float]: Dictionary with target_price, max_boundary_price,
            target_distance_amount, and max_distance_amount.

        Example:
            >>> policy = RepricingPolicy(target_distance=0.005, distance_type=RepricingDistanceType.PERCENT)
            >>> bands = policy.compute_distance_bands('BUY', 40000.0)
            >>> print(bands['target_price'])
        """
        if self.distance_type is RepricingDistanceType.ABSOLUTE:
            target = self.target_distance
            maximum = self.max_distance
        else:
            target = reference_price * self.target_distance
            maximum = reference_price * self.max_distance

        normalized_side = str(side or '').upper()
        if normalized_side == OrderSide.BUY.value:
            target_price = reference_price - target
            max_boundary_price = reference_price - maximum
        else:
            target_price = reference_price + target
            max_boundary_price = reference_price + maximum
        return {
            'target_price': float(target_price),
            'max_boundary_price': float(max_boundary_price),
            'target_distance_amount': float(target),
            'max_distance_amount': float(maximum),
        }

    def clamp_to_step(
        self, current_price: float, desired_price: float
    ) -> tuple[float, bool]:
        """Cap a reprice to ``max_step_per_reprice`` when slide mode is on.

        Returns ``(price, clamped)`` where ``clamped`` is True if the move
        was reduced. No-op when slide mode is off or step is non-positive.

        Args:
            current_price: Current price of the order.
            desired_price: Desired price to reprice to.

        Returns:
            Tuple[float, bool]: (clamped_price, is_clamped).

        Example:
            >>> policy = RepricingPolicy(slide_mode=True, max_step_per_reprice=10.0)
            >>> clamped_price, is_clamped = policy.clamp_to_step(40000.0, 40100.0)
        """
        if not self.slide_mode or self.max_step_per_reprice <= 0:
            return float(desired_price), False
        delta = float(desired_price) - float(current_price)
        if abs(delta) <= self.max_step_per_reprice:
            return float(desired_price), False
        direction = 1.0 if delta > 0 else -1.0
        return float(current_price) + direction * float(self.max_step_per_reprice), True

    def compute_follow_up_price(
        self,
        *,
        anchor_price: float,
        side: str,
        follow_up_client_order_id: str,
    ) -> float:
        """Resolve the price for a post-fill follow-up order.

        ``anchor_price`` is the price the caller would otherwise post at
        (typically already derived upstream from
        ``fill_price + target_movement``). RETREAT moves it slightly in
        the patient direction: BUY -> lower bid, SELL -> higher offer.
        The point is to break the exact-multiple-of-target_movement
        fingerprint that a counterparty could otherwise lock onto.

        Always percent-based (scale-invariant). Always retreat (never
        chase — chase is the loud option and is not configurable).

        Jitter is DETERMINISTIC from ``follow_up_client_order_id`` (sha256
        derived, same approach as ``calculation/price_camouflage.py``):
        replayable for audit, no float-RNG in money paths. Effective
        retreat lands in ``[d * (1 - jitter), d * (1 + jitter)]``.

        Returns ``anchor_price`` unchanged when
        ``follow_up_retreat_distance`` is 0 — the documented opt-out path.

        NOTE: this method does NOT tick-align the result. The caller
        (typically the follow-up creation path) must run the price
        through ``calculation.formatter.quantize_to_increment`` with the
        product's ``price_increment`` before placement.

        Args:
            anchor_price: The anchor price to retreat from.
            side: Order side ('BUY' or 'SELL').
            follow_up_client_order_id: Client order ID for deterministic jitter.

        Returns:
            float: The computed follow-up price.

        Example:
            >>> policy = RepricingPolicy(follow_up_retreat_distance=0.0005)
            >>> follow_up_price = policy.compute_follow_up_price(
            ...     anchor_price=40000.0,
            ...     side='BUY',
            ...     follow_up_client_order_id='follow-up-123'
            ... )
        """
        # A disabled policy is fully inert: no anchor repricing AND no
        # retreat. The defaults on the dataclass are the OPT-OUT values
        # that take effect once a policy is enabled and omits the retreat
        # fields; they are NOT meant to leak into a fully-disabled policy.
        if not self.enabled:
            return float(anchor_price)
        if self.follow_up_retreat_distance <= 0:
            return float(anchor_price)

        # Deterministic jitter in [-1, +1] from the follow-up's coid.
        # Keeps audit-replayable and never injects RNG into pricing.
        jitter_fraction = 0.0
        if self.follow_up_retreat_jitter > 0 and follow_up_client_order_id:
            import hashlib

            digest = hashlib.sha256(
                follow_up_client_order_id.encode('utf-8')
            ).digest()
            # Use 8 bytes -> uint64 -> [0, 1) -> [-1, +1)
            raw = int.from_bytes(digest[:8], 'big') / float(1 << 64)
            unit = (raw * 2.0) - 1.0
            jitter_fraction = unit * self.follow_up_retreat_jitter

        # Effective retreat fraction. Clamp >= 0 as a belt-and-suspenders
        # check so jitter can never flip retreat into chase even if
        # ``follow_up_retreat_jitter`` somehow exceeded 1.0 at runtime.
        effective_distance = max(
            self.follow_up_retreat_distance * (1.0 + jitter_fraction),
            0.0,
        )
        retreat_amount = float(anchor_price) * effective_distance

        normalized_side = str(side or '').upper()
        if normalized_side == OrderSide.BUY.value:
            # Buying: retreat means post LOWER than the anchor.
            return float(anchor_price) - retreat_amount
        # Selling (or unknown): retreat means post HIGHER than the anchor.
        return float(anchor_price) + retreat_amount

    @property
    def should_reprice_revealed(self) -> bool:
        """True iff repricing applies to already-revealed orders.

        Returns:
            bool: True if repricing applies to revealed orders.

        Example:
            >>> policy = RepricingPolicy(allow_revealed_reprice=True)
            >>> print(policy.should_reprice_revealed)
            True
        """
        return self.enabled and self.allow_revealed_reprice

    @property
    def is_fixed_interval(self) -> bool:
        """True iff update mode is FIXED.

        Returns:
            bool: True if update mode is FIXED.

        Example:
            >>> policy = RepricingPolicy(update_mode=RepricingUpdateMode.FIXED)
            >>> print(policy.is_fixed_interval)
            True
        """
        return self.update_mode is RepricingUpdateMode.FIXED
