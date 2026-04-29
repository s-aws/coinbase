"""Data models - Core dataclasses for orders, positions, products."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from core.enums import (
    OrderSide,
    OrderStatus,
    ProductType,
    RepricingDistanceType,
    RepricingReferenceSource,
    RepricingUpdateMode,
    RevealPricingPolicy,
    RevealPriceSource,
    TargetMovementType,
)


@dataclass
class Product:
    """Trading product metadata."""
    product_id: str
    product_type: ProductType
    base_increment: str
    quote_increment: str
    price_increment: str
    base_min_size: str = "0"
    trading_disabled: bool = False
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Product':
        """Create Product from API response dict."""
        return cls(
            product_id=data.get('product_id'),
            product_type=ProductType(data.get('product_type', 'SPOT').upper()),
            base_increment=data.get('base_increment', '0'),
            quote_increment=data.get('quote_increment', '0'),
            price_increment=data.get('price_increment', '0'),
            base_min_size=data.get('base_min_size', '0'),
            trading_disabled=data.get('trading_disabled', False),
        )


@dataclass
class Position:
    """Futures position - contract holdings."""
    product_id: str
    side: str  # 'LONG' or 'SHORT'
    number_of_contracts: str
    current_price: Optional[str] = None
    entry_price: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """Create Position from API response dict."""
        return cls(
            product_id=data.get('product_id'),
            side=data.get('side'),
            number_of_contracts=str(data.get('number_of_contracts', '0')),
            current_price=data.get('current_price'),
            entry_price=data.get('entry_price'),
        )


@dataclass
class Wallet:
    """Account wallet - currency balance."""
    currency: str
    available_balance: str
    total_balance: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Wallet':
        """Create Wallet from API response dict."""
        return cls(
            currency=data.get('currency'),
            available_balance=str(data.get('available_balance', '0')),
            total_balance=str(data.get('total_balance', '0')),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            deleted_at=data.get('deleted_at'),
        )


@dataclass
class Order:
    """Trading order - spot or futures."""
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
        """Create Order from API response dict."""
        from calculation.resolver import safe_float, normalize_product_type
        
        side = data.get('order_side') or data.get('side')
        status_str = data.get('status', 'OPEN').upper()
        
        return cls(
            client_order_id=data.get('client_order_id'),
            product_id=data.get('product_id'),
            order_side=OrderSide(side) if isinstance(side, str) else side,
            status=OrderStatus(status_str) if status_str in [e.value for e in OrderStatus] else OrderStatus.OPEN,
            size=safe_float(data.get('size'), 0.0),
            price=safe_float(data.get('price'), 0.0),
            filled_size=safe_float(data.get('filled_size'), 0.0),
            limit_price=safe_float(data.get('limit_price')),
            avg_price=safe_float(data.get('avg_price')),
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
        configured_limit_price: Original limit price from stealth order creation
        submitted_limit_price: Actual limit price that will be submitted to exchange
        reveal_pricing_policy: Policy that determined the price (enum value as string)
        reveal_price_source: How the price was sourced (RevealPriceSource enum value, e.g. ticker_best_ask)
        fallback_used: Whether configured limit was used as fallback (market data unavailable)
        market_source: Source of market data (ticker, snapshot, unavailable)
        market_bid: Best bid price at reveal time
        market_ask: Best ask price at reveal time
        target_movement: Profit target (decimal, e.g. 0.003 for 0.3%) resolved
            from the canonical ``order_parent`` row. Used by the reveal-time
            profitability gate. ``None`` when no target is configured.
        target_movement_type: ``'P'`` (percentage) or ``'A'`` (absolute);
            paired with ``target_movement``. ``None`` when target is missing.
        target_movement_source: Where ``target_movement`` was resolved from
            (e.g. ``'order_parent'``, ``'stealth_order'``, ``'unavailable'``).
            Recorded for audit so silent skips of the profitability gate are
            traceable.
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for persistence/serialization."""
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

    # ---- builders ----

    @classmethod
    def disabled(cls) -> 'RepricingPolicy':
        """Canonical \"no repricing\" instance. Equivalent to ``{\"enabled\": False}``."""
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
        )

    @classmethod
    def coerce(cls, value: Any) -> 'RepricingPolicy':
        """Accept a dict, ``None``, or an existing ``RepricingPolicy``.

        Lets internal helpers be called from both refactored sites and
        legacy dict callers (incl. tests) without forcing wrapping at every
        call site.
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
        }

    # ---- behavior helpers ----

    def compute_distance_bands(
        self, side: str, reference_price: float
    ) -> Dict[str, float]:
        """Resolve target/max prices around ``reference_price`` for ``side``.

        Encapsulates the percent-vs-absolute branch so callers don't have
        to inspect ``distance_type`` themselves.
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
    ) -> tuple:
        """Cap a reprice to ``max_step_per_reprice`` when slide mode is on.

        Returns ``(price, clamped)`` where ``clamped`` is True if the move
        was reduced. No-op when slide mode is off or step is non-positive.
        """
        if not self.slide_mode or self.max_step_per_reprice <= 0:
            return float(desired_price), False
        delta = float(desired_price) - float(current_price)
        if abs(delta) <= self.max_step_per_reprice:
            return float(desired_price), False
        direction = 1.0 if delta > 0 else -1.0
        return float(current_price) + direction * float(self.max_step_per_reprice), True

    @property
    def should_reprice_revealed(self) -> bool:
        """True iff repricing applies to already-revealed orders."""
        return self.enabled and self.allow_revealed_reprice

    @property
    def is_fixed_interval(self) -> bool:
        return self.update_mode is RepricingUpdateMode.FIXED
