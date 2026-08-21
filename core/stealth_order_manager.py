"""StealthOrderManager - unified order creation and reveal lifecycle control.

This module is the authoritative order creation path for both immediate and
condition-based execution. Orders are persisted, tracked in memory, evaluated
against reveal conditions, and then submitted as exchange limit orders.

Current feature set:
- Unified create_stealth_order() flow for parent and child/follow-up orders.
- Reveal condition support via evaluator factory:
    - time_delay (including immediate delay_seconds=0)
    - price threshold conditions
    - other evaluators provided by business.stealth_condition_evaluator
- Condition state tracking (first met, confirmed, status transitions).
- Adaptive slice sizing with per-order sizing strategy metadata.
- Pre/post submission hook pipeline for policy enforcement and enrichment.
- In-memory cache plus database persistence for restart resilience.
- Parent-child integration through order_parent table writes.
- O(1) revealed-order reverse lookup with _placed_order_index.

Critical ID semantics:
- stealth_order_id is used as client_order_id for internal lifecycle linkage.
- revealed_orders keeps both client_order_id and exchange order_id context.
- Internal lookups and follow-up orchestration should key off client_order_id.

Extension points:
- Add or customize reveal types in business.stealth_condition_evaluator.
- Register order_placement_hooks for pre-submission validation or post-submit
    side effects.
- Extend sizing_strategy handling for advanced execution profiles.

Example: immediate reveal order
    >>> order_id = manager.create_stealth_order(
    ...     product_id='BTC-USDC',
    ...     side='BUY',
    ...     total_size=0.25,
    ...     limit_price=42000.0,
    ...     reveal_condition={'type': 'time_delay', 'delay_seconds': 0},
    ... )

Example: price-triggered reveal order
    >>> order_id = manager.create_stealth_order(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     total_size=0.25,
    ...     limit_price=42500.0,
    ...     reveal_condition={
    ...         'type': 'price_threshold',
    ...         'price_threshold': 42400.0,
    ...         'direction': 'above',
    ...         'hold_duration_seconds': 2,
    ...     },
    ...     follow_up_reveal_direction='opposite',
    ... )

Example: evaluate and reveal from scheduler loop
    >>> should_reveal, reason = manager.should_trigger_reveal(order_id)
    >>> if should_reveal:
    ...     client_order_id = manager.reveal_order_slice(order_id)
    ...     assert isinstance(client_order_id, str)
"""


import uuid
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Callable, Dict, Any, Iterator, Mapping, Optional, Tuple, List

from configuration import (
    DEFAULT_MAX_ORDER_REPLACEMENT,
    get_product_metadata,
    safe_float,
)
from calculation.price_validation import normalize_price_for_product
from business.placement_response import classify_placement_response
from core.enums import (
    FollowUpRevealDirection,
    OrderPlacementOutcome,
    OrderSide,
    OrderStatus,
    PriceRoundingPolicy,
    RepricingReferenceSource,
    RevealConditionType,
    RevealPricingPolicy,
    RevealPriceSource,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.exceptions import (
    RevealPricingError,
    RevealConditionEvaluationError,
    RevealOrderSliceError,
    StealthOrderNotFoundError,
    StealthOrderPersistenceError,
)
from business.stealth_condition_evaluator import get_evaluator
from core.models import MarketData, RepricingPolicy, RepricingState
from core.runtime_controller import INFLIGHT_REST_PLACE, get_runtime_controller
from database.order import (
    get_parent_order,
    insert_order_parent,
    update_order_parent_price,
    update_order_parent_status,
)
from logging_service import get_logger


# ---------------------------------------------------------------------------
# Reveal-condition price-tracking helpers
# ---------------------------------------------------------------------------
# Per condition type, the JSON keys that represent ABSOLUTE price levels and
# therefore should track 1:1 with ``order["limit_price"]`` whenever anchor
# repricing moves the limit. Spread / ratio / time-delay fields are
# intentionally absent — they are not absolute prices.
_REVEAL_CONDITION_PRICE_FIELDS_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    RevealConditionType.PRICE_THRESHOLD.value: ("price_threshold",),
    RevealConditionType.CUMULATIVE_VOLUME.value: ("price_level",),
}


def _parse_json_container(value: Any, default: Any) -> Any:
    """Decode a JSON field while preserving its expected container type."""
    if value is None:
        return default
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
    return parsed if isinstance(parsed, type(default)) else default


def _iter_reveal_condition_price_fields(
    condition: Any,
) -> Iterator[Tuple[Dict[str, Any], str]]:
    """Yield ``(parent_dict, key)`` for every absolute-price field in a condition tree.

    Recurses into ``COMPOSITE`` conditions via the ``conditions`` list. Order
    types with no absolute price field (TIME_DELAY, SPREAD, PRODUCT_RATIO)
    yield nothing. Non-numeric values are skipped.
    """
    if not isinstance(condition, dict):
        return
    cond_type = str(condition.get("type") or "").lower()
    for field in _REVEAL_CONDITION_PRICE_FIELDS_BY_TYPE.get(cond_type, ()):
        if isinstance(condition.get(field), (int, float)):
            yield condition, field
    for sub in condition.get("conditions") or ():
        yield from _iter_reveal_condition_price_fields(sub)


def resolve_stealth_chain_root(stealth_order: Dict[str, Any]) -> str:
    """Return the chain-ROOT client_order_id for a stealth order.

    Flat hierarchy rule (``agent.md``): every child links to the original root,
    never to an intermediate slice. There are NO grandchildren in either the
    in-memory orderbook or the ``order_parent`` table.

    A stealth order is itself the root when ``parent_order_id`` is None.
    A follow-up stealth order carries ``parent_order_id`` pointing at the root
    set up by ``create_stealth_order`` — which is what every placement uuid,
    every ``insert_order_parent`` row, and every ``register_child_order`` call
    must use as the parent.

    This is the SINGLE source of truth for that resolution. Any code that needs
    the root of a stealth chain MUST call this function instead of open-coding
    ``stealth.get("parent_order_id") or stealth["stealth_order_id"]``. Six
    duplications of that line caused the 2026-04-27 grandchild incident; the
    static guard in
    ``tests/regression/test_flat_hierarchy_stealth_placement.py`` enforces
    that no caller reverts to inlining it.

    Raises:
        KeyError: if ``stealth_order["stealth_order_id"]`` is missing — that
            indicates a malformed dict and should fail loudly at the boundary.
    """

    return stealth_order.get("parent_order_id") or stealth_order["stealth_order_id"]


class StealthOrderManager:
    """Unified order creation manager with condition-driven reveal lifecycle.

    All parent and follow-up orders are created through this class and begin in
    hidden/pending lifecycle states until reveal conditions are satisfied.

    Runtime responsibilities:
    - Persist order intent and lifecycle metadata.
    - Evaluate reveal conditions via evaluator factory.
    - Submit revealed slices to exchange through placement flow.
    - Track revealed/remaining/executed quantities.
    - Maintain parent-child linkage metadata for downstream order engine logic.
    - Expose hook points for pre/post order placement business rules.

    Integration guidance:
    - Use this manager to create both immediate and delayed orders.
    - Prefer client_order_id (stealth_order_id) for internal orchestration.
    - Add new reveal behaviors by extending evaluator types, not by branching
        parallel creation paths.

    Example: extending evaluator types
        >>> # In business/stealth_condition_evaluator.py
        >>> class LiquidityWallEvaluator(ConditionEvaluator):
        ...     def evaluate(self, market_data, condition_config, order_data):
        ...         wall_size = condition_config.get('wall_size', 0)
        ...         bid_size = market_data.get('best_bid_size', 0)
        ...         return (bid_size >= wall_size, f'bid_size={bid_size}, wall_size={wall_size}')
        >>>
        >>> # Register in get_evaluator()
        >>> # evaluators['liquidity_wall'] = LiquidityWallEvaluator
        >>>
        >>> # Then use the new condition type when creating an order
        >>> order_id = manager.create_stealth_order(
        ...     product_id='BTC-USDC',
        ...     side='BUY',
        ...     total_size=0.5,
        ...     limit_price=42000.0,
        ...     reveal_condition={
        ...         'type': 'liquidity_wall',
        ...         'wall_size': 25.0,
        ...     },
        ... )
    """
    
    def __init__(self, db_client, log_callback=None, order_placement_hooks=None, profit_validator=None):
        """
        Initialize StealthOrderManager.
        
        Args:
            db_client: Database client for persistence
            log_callback: Optional logging callback (log_type, message). Defaults to proper logging_service.
            order_placement_hooks: Optional OrderPlacementHookRegistry for pre/post submission hooks.
            profit_validator: Optional ProfitValidator for reveal-time profitability revalidation.
        """
        self.db_client = db_client
        self.logger = get_logger("StealthOrderManager")
        self.log_callback = log_callback or self._default_log
        self.in_memory_orders = {}  # For caching/quick access
        self._creation_lock = RLock()
        self._market_cache: Dict[str, MarketData] = {}  # product_id -> latest market snapshot
        self._placed_order_index = {}  # Index: placed_order_id -> stealth_order (O(1) lookup)
        self.profit_validator = profit_validator
        # Throttle map for the "reveal returned size=0" diagnostic. Keyed
        # by stealth_order_id, value is the unix-timestamp of the last
        # emitted log line. See ``_maybe_log_no_slice``.
        self._no_slice_log_emitted_at: Dict[str, float] = {}
        
        # Order placement hooks for extensibility
        if order_placement_hooks is None:
            from integration.order_placement_hooks import get_global_placement_hook_registry
            order_placement_hooks = get_global_placement_hook_registry()
        self.order_placement_hooks = order_placement_hooks

        # Mutation claim ledger.  Serialises in-flight mutations against
        # a single stealth order so the manual "move REVEALED" path and
        # the ticker-driven anchor reprice loop cannot both cancel /
        # replace the same exchange order at the same time.  Keyed on
        # :class:`core.enums.StealthMutationKind` (MOVE / REPRICE).
        # Stealth mutations are repeatable, so callers must use
        # :meth:`release_mutation` in both success and failure paths;
        # there is no terminal ``done`` state and intentionally no
        # ``complete_mutation`` method.
        from core.enums import StealthMutationKind
        from core.orderbook import ClaimLedger

        self._mutation_claims = ClaimLedger(StealthMutationKind)

        # Ensure database schema is up to date with all migrations
        self._ensure_schema_migrations()
    
    def _ensure_schema_migrations(self):
        """Ensure stealth_orders table has all required columns including recent migrations.
        
        This runs the migration that adds anchor_repricing_policy_json and other new columns
        if they don't already exist. Safe to call multiple times (uses IF NOT EXISTS).
        """
        if not self.db_client:
            return
        
        try:
            from database.order import create_stealth_orders_table
            create_stealth_orders_table()
            self.logger.debug("✓ Stealth order schema migration completed")
        except Exception as e:
            self.logger.warning(f"✗ Failed to run schema migration: {type(e).__name__}: {e}")
    
    def _default_log(self, log_type: str, message: str):
        """Log using proper logging_service with timestamps."""
        if isinstance(message, (dict, list)):
            message = json.dumps(message, sort_keys=True, default=str)
        
        log_type_lower = log_type.lower()
        if log_type_lower in ('debug',):
            self.logger.debug(message)
        elif log_type_lower in ('info',):
            self.logger.info(message)
        elif log_type_lower in ('warning',):
            self.logger.warning(message)
        elif log_type_lower in ('error',):
            self.logger.error(message)
        else:
            self.logger.info(message)

    # ------------------------------------------------------------------
    # Mutation claim API
    # ------------------------------------------------------------------
    #
    # Thin wrappers around :attr:`_mutation_claims` so the call sites
    # (the manual move executor and the ticker-driven anchor reprice
    # loop) read clearly and so a new caller cannot accidentally pass an
    # un-validated ``kind`` string \u2014 the underlying ledger validates
    # against :class:`core.enums.StealthMutationKind` at the boundary.
    #
    # No ``complete_mutation`` exists by design: stealth mutations are
    # repeatable.  Both success and failure paths must call
    # :meth:`release_mutation`.

    def try_claim_mutation(self, kind, stealth_order_id: str) -> bool:
        """Atomically claim mutation rights for one stealth order.

        Returns ``True`` if the caller now owns the claim and must call
        :meth:`release_mutation` once finished (success *or* failure).
        Returns ``False`` if any other in-flight mutation \u2014 of *any*
        :class:`StealthMutationKind` \u2014 is already held against the same
        stealth order.

        Cross-kind exclusion is enforced here at the wrapper layer (rather
        than inside :class:`ClaimLedger`) so the ledger stays a generic
        per-(kind, key) primitive that the follow-up FILLED / CANCELLED
        case can keep using as independent namespaces. Stealth mutations
        require **mutual exclusion** because both MOVE and REPRICE
        cancel-and-replace the same exchange order; running both
        concurrently would double-cancel, leak phantom placements, and
        violate the ``order_parent`` FK guard.
        """
        from core.enums import StealthMutationKind

        # Lazy lock: callers that build the manager via __new__ (e.g. the
        # regression-test bare-instance pattern) get a default lock without
        # having to mirror full __init__ wiring.
        lock = getattr(self, "_mutation_check_lock", None)
        if lock is None:
            import threading
            lock = threading.RLock()
            self._mutation_check_lock = lock

        with lock:
            for other in StealthMutationKind:
                if other == kind:
                    continue
                if self._mutation_claims.state(other, stealth_order_id) == "processing":
                    return False
            return self._mutation_claims.try_claim(kind, stealth_order_id)

    def release_mutation(self, kind, stealth_order_id: str) -> None:
        """Release a previously-acquired mutation claim.

        No-op if the slot is absent or already released.  Stealth
        mutations are repeatable, so the slot returns to the *absent*
        state and the next mutation of the same kind may proceed.
        """

        self._mutation_claims.release(kind, stealth_order_id)

    def _normalize_reveal_pricing_policy(
        self,
        reveal_pricing_policy: Optional[str],
        reveal_condition: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve effective reveal pricing policy with validation.

        Precedence:
        1) explicit reveal_pricing_policy argument
        2) reveal_condition["reveal_pricing_policy"]
        3) default "configured_limit"
        
        Returns:
            Validated policy string (configured_limit, top_of_book, or midpoint)
        """
        candidate = reveal_pricing_policy
        if candidate is None and isinstance(reveal_condition, dict):
            candidate = reveal_condition.get("reveal_pricing_policy")
        
        if candidate is None:
            candidate = "configured_limit"
        
        candidate_value = str(candidate).strip().lower()
        allowed_values = {"configured_limit", "top_of_book", "midpoint"}
        
        if candidate_value not in allowed_values:
            self.logger.warning(
                f"Invalid reveal_pricing_policy: {candidate}. Using configured_limit. "
                f"Allowed: {sorted(allowed_values)}"
            )
            return "configured_limit"
        
        return candidate_value

    def _resolve_post_only_from_policy(
        self,
        reveal_pricing_policy: Optional[str],
        reveal_condition: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Canonical helper: derive post_only intent from a reveal pricing policy.

        TOP_OF_BOOK / MIDPOINT rest as makers (post_only=True);
        CONFIGURED_LIMIT submits as taker (post_only=False, conservative).
        Unknown / missing policies fall back to CONFIGURED_LIMIT.

        Single source of truth for ``post_only`` derivation across pre-flight,
        anchor-reprice, follow-up pre-check and reveal-time validation paths.
        """
        from core.enums import RevealPricingPolicy

        normalized = self._normalize_reveal_pricing_policy(
            reveal_pricing_policy=reveal_pricing_policy,
            reveal_condition=reveal_condition,
        )
        try:
            policy_enum = RevealPricingPolicy(normalized)
        except ValueError:
            policy_enum = RevealPricingPolicy.CONFIGURED_LIMIT
        return policy_enum.implies_post_only()

    def _resolve_reveal_limit_price(
        self,
        side: str,
        configured_limit_price: float,
        market_data: Dict[str, Any],
        reveal_pricing_policy: str,
    ) -> Tuple[float, str, bool]:
        """Resolve reveal limit price based on policy.

        Returns:
            (submitted_limit_price, reveal_price_source, fallback_used)
        """
        reveal_price_source = RevealPriceSource.CONFIGURED_LIMIT.value
        fallback_used = False
        
        market_source = market_data.get("source")
        market_bid = market_data.get("bid")
        market_ask = market_data.get("ask")
        normalized_side = str(side or "").upper()
        
        if reveal_pricing_policy == "configured_limit":
            return configured_limit_price, reveal_price_source, fallback_used
        
        if reveal_pricing_policy == "top_of_book":
            if market_source == "ticker":
                try:
                    if normalized_side == "BUY" and market_ask is not None and float(market_ask) > 0:
                        return float(market_ask), RevealPriceSource.TICKER_BEST_ASK.value, False
                    if normalized_side == "SELL" and market_bid is not None and float(market_bid) > 0:
                        return float(market_bid), RevealPriceSource.TICKER_BEST_BID.value, False
                except (TypeError, ValueError):
                    pass
            return configured_limit_price, RevealPriceSource.CONFIGURED_LIMIT.value, True
        
        if reveal_pricing_policy == "midpoint":
            if market_source == "ticker":
                try:
                    if (market_bid is not None and market_ask is not None and 
                        float(market_bid) > 0 and float(market_ask) > 0):
                        midpoint = (float(market_bid) + float(market_ask)) / 2.0
                        return midpoint, RevealPriceSource.TICKER_MIDPOINT.value, False
                except (TypeError, ValueError):
                    pass
            return configured_limit_price, RevealPriceSource.CONFIGURED_LIMIT.value, True
        
        return configured_limit_price, RevealPriceSource.CONFIGURED_LIMIT.value, True

    def _normalize_anchor_repricing_policy(
        self,
        anchor_repricing_policy: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Normalize anchor-repricing policy for storage.

        Two-step canonicalisation:
        1. :meth:`RepricingPolicy.from_dict` does field-by-field clamping,
           enum coercion, and slide-mode coupling.
        2. The storage gate below collapses semantically meaningless
           configurations (``enabled=True`` but no ``target_distance``) to
           a disabled policy so downstream code can rely on the
           ``enabled`` flag alone.

        Returns a dict (JSONB-compatible, on-disk shape preserved).
        Consumers that read an already-stored policy should use
        :meth:`RepricingPolicy.coerce` directly — they don't need this
        gate because storage already enforced it.
        """
        policy = RepricingPolicy.from_dict(anchor_repricing_policy)
        if policy.enabled and policy.target_distance <= 0:
            policy = RepricingPolicy.disabled()
        return policy.to_dict()

    @staticmethod
    def _parse_runtime_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None

    def _normalize_anchor_repricing_state(
        self,
        anchor_repricing_state: Optional[Dict[str, Any]],
    ) -> RepricingState:
        state: RepricingState = dict(anchor_repricing_state or {})  # type: ignore[assignment]
        state.setdefault("reprice_history", [])
        return state

    def _apply_reveal_condition_price_tracking(
        self,
        order: Dict[str, Any],
        state: Dict[str, Any],
        new_limit_price: float,
    ) -> bool:
        """Update reveal_condition price thresholds in lock-step with a reprice.

        Preserves the original offset between every absolute-price field in
        ``reveal_condition_json`` and ``order["limit_price"]``. The offsets are
        captured lazily on first invocation (using the order's pre-reprice
        limit_price as baseline) and persisted in
        ``state["reveal_condition_price_offsets"]`` for subsequent reprices.

        Designed to be extensible: future "do-not-cross" / minimum guards can
        clamp the resulting threshold against a profit floor without changing
        callers (see ``agent.md`` integrated-by-design pattern).

        Args:
            order:           The stealth order dict (mutated in place).
            state:           The (already normalized) anchor_repricing_state dict
                             — also mutated to persist offsets.
            new_limit_price: The new ``limit_price`` that will be applied.

        Returns:
            True when at least one threshold field was updated, False otherwise
            (no price-bearing fields, missing baseline, etc.).
        """
        reveal_condition = order.get("reveal_condition_json")
        if not isinstance(reveal_condition, dict):
            return False

        baseline_limit = safe_float(order.get("limit_price"), default=None)
        new_limit = safe_float(new_limit_price, default=None)
        if baseline_limit is None or new_limit is None:
            return False

        # Lazy-init: snapshot offsets from baseline (pre-first-reprice values).
        offsets = state.get("reveal_condition_price_offsets")
        if not isinstance(offsets, dict):
            offsets = {}
            for parent, key in _iter_reveal_condition_price_fields(reveal_condition):
                offsets[key] = float(parent[key]) - baseline_limit
            state["reveal_condition_price_offsets"] = offsets

        if not offsets:
            return False

        updated = False
        for parent, key in _iter_reveal_condition_price_fields(reveal_condition):
            offset = offsets.get(key)
            if offset is None:
                continue
            new_value = new_limit + float(offset)
            if parent[key] != new_value:
                parent[key] = new_value
                updated = True

        if updated:
            order["reveal_condition_json"] = reveal_condition
        return updated

    def _resolve_reference_price(
        self,
        side: str,
        market_data: Dict[str, Any],
        policy: Any,
    ) -> Tuple[Optional[float], str]:
        policy = RepricingPolicy.coerce(policy)
        price = safe_float(market_data.get("price"), default=None)
        bid = safe_float(market_data.get("bid"), default=None)
        ask = safe_float(market_data.get("ask"), default=None)
        normalized_side = str(side or "").upper()

        ref = policy.reference_price_source
        if ref is RepricingReferenceSource.LAST_TRADE and price and price > 0:
            return price, "ticker_last_trade"

        if ref is RepricingReferenceSource.MIDPOINT and bid and ask and bid > 0 and ask > 0:
            return (bid + ask) / 2.0, "ticker_midpoint"

        if ref is RepricingReferenceSource.TOP_OF_BOOK:
            if normalized_side == "BUY" and bid and bid > 0:
                return bid, "ticker_best_bid"
            if normalized_side == "SELL" and ask and ask > 0:
                return ask, "ticker_best_ask"

        if price and price > 0:
            return price, "ticker_last_trade"
        if bid and ask and bid > 0 and ask > 0:
            return (bid + ask) / 2.0, "ticker_midpoint"
        if bid and bid > 0:
            return bid, "ticker_best_bid"
        if ask and ask > 0:
            return ask, "ticker_best_ask"
        return None, "unavailable"

    def _compute_reference_target_prices(
        self,
        side: str,
        reference_price: float,
        policy: Any,
    ) -> Dict[str, float]:
        return RepricingPolicy.coerce(policy).compute_distance_bands(side, reference_price)

    @staticmethod
    def _apply_slide_step_clamp(
        current_price: float,
        desired_price: float,
        policy: Any,
    ) -> tuple[float, bool]:
        """Cap reprice movement to ``max_step_per_reprice`` when slide_mode is on."""
        return RepricingPolicy.coerce(policy).clamp_to_step(current_price, desired_price)

    def _quantize_reprice_price(
        self,
        product_id: str,
        side: str,
        price: float,
        *,
        boundary_enforced: bool = False,
    ) -> float:
        """Snap repricing price to product-specific minimum price increment.

        For normal repricing, we use nearest tick to preserve intent.
        For boundary-enforced repricing, use directional quantization so BUY
        does not drift below boundary and SELL does not drift above boundary.
        """
        normalized_side = str(side or "").upper()
        rounding_policy = PriceRoundingPolicy.NEAREST
        if boundary_enforced:
            if normalized_side == OrderSide.BUY.value:
                rounding_policy = PriceRoundingPolicy.UP
            elif normalized_side == OrderSide.SELL.value:
                rounding_policy = PriceRoundingPolicy.DOWN

        result = normalize_price_for_product(
            price,
            product_id=str(product_id or ""),
            side=normalized_side,
            policy=rounding_policy,
        )
        if not result.ok or result.effective_price is None:
            raise ValueError(result.reason or "price normalization failed")
        return float(result.effective_price)

    # Maximum post-only retries per placement. Industry-standard repricing
    # ladder: original attempt + 2 retries, repricing 1 tick safer (away
    # from the touch) on each rejection. Surfacing on exhaustion is
    # intentional: silently demoting to taker would betray the
    # post-only intent of TOP_OF_BOOK / MIDPOINT reveals and charge the
    # operator the wrong fee tier.
    POST_ONLY_MAX_ATTEMPTS = 3

    def _get_price_increment(self, product_id: str) -> Optional[str]:
        """Return the current authoritative price increment, when available."""
        metadata = get_product_metadata(str(product_id or ""))
        increment = metadata.get("price_increment")
        return str(increment) if increment else None

    @staticmethod
    def _next_safer_tick(price: float, side: str, product_id: str) -> float:
        """Return ``price`` moved one ``increment`` AWAY from the opposing
        touch, so a re-submitted post-only order will not cross the
        spread.

        - ``BUY``: subtract one tick (retreat from the ask).
        - ``SELL``: add one tick (retreat from the bid).

        This is the OPPOSITE direction from price aggression
        (bid-up / ask-down). A ``POST_ONLY`` rejection means the order
        would have crossed; the only safe response is to step back, not
        forward.
        """
        normalized = normalize_price_for_product(
            price,
            product_id=product_id,
            side=side,
            policy=PriceRoundingPolicy.NEAREST,
        )
        if (
            not normalized.ok
            or normalized.effective_price is None
            or normalized.increment is None
        ):
            raise ValueError(normalized.reason or "price normalization failed")

        new_price = Decimal(str(normalized.effective_price))
        tick = Decimal(normalized.increment)
        normalized_side = str(side or "").upper()
        if normalized_side == OrderSide.BUY.value:
            candidate = new_price - tick
        elif normalized_side == OrderSide.SELL.value:
            candidate = new_price + tick
        else:
            raise ValueError(f"unsupported order side: {side!r}")

        result = normalize_price_for_product(
            candidate,
            product_id=product_id,
            side=side,
            policy=PriceRoundingPolicy.NEAREST,
        )
        if not result.ok or result.effective_price is None:
            raise ValueError(result.reason or "price normalization failed")
        return float(result.effective_price)

    @staticmethod
    def _is_post_only_rejection(order_result: Any) -> bool:
        """Return True if a Coinbase ``place_limit_order`` response shape
        indicates a POST_ONLY rejection.

        Coinbase surfaces post-only crossings as ``failure_reason ==
        "POST_ONLY"`` (or nested under ``error_response.error``). We
        match on the canonical token, case-insensitively, so SDK
        wording drift does not silently disable the retry path.
        """
        if not isinstance(order_result, dict):
            return False
        if order_result.get("success"):
            return False
        token = "POST_ONLY"
        error_response = order_result.get("error_response")
        candidates = [order_result.get("failure_reason")]
        if isinstance(error_response, Mapping):
            candidates.extend((
                error_response.get("error"),
                error_response.get("message"),
                error_response.get("preview_failure_reason"),
            ))
        else:
            candidates.append(error_response)
        for value in candidates:
            if value and token in str(value).upper():
                return True
        return False

    def _mark_placement_parent_failed(
        self,
        placement_client_order_id: Optional[str],
        *,
        stealth_order_id: str,
    ) -> None:
        """Best-effort terminal status for a placement audit row.

        The order-parent row may have been created by the stealth root,
        pre-inserted immediately before REST, or won by the websocket writer.
        In every case an unaccepted placement must not remain PENDING/OPEN.
        """
        if not placement_client_order_id:
            return
        try:
            update_order_parent_status(
                placement_client_order_id,
                OrderStatus.FAILED.value,
            )
        except Exception as status_error:
            self.log_callback(
                "warning",
                {
                    "event": "placement_parent_failed_status_update_failed",
                    "stealth_order_id": stealth_order_id,
                    "placement_client_order_id": placement_client_order_id,
                    "error": str(status_error),
                },
            )

    def _index_accepted_placement(
        self,
        order: Dict[str, Any],
        placement_client_order_id: Any,
        *,
        source: str,
    ) -> bool:
        """Index one proven accepted placement without ownership overwrite."""
        placement_id = (
            placement_client_order_id.strip()
            if isinstance(placement_client_order_id, str)
            else ""
        )
        if not placement_id:
            self.log_callback("error", {
                "event": "accepted_placement_index_invalid_id",
                "stealth_order_id": order.get("stealth_order_id"),
                "index_source": source,
            })
            return False

        existing_owner = self._placed_order_index.get(placement_id)
        if existing_owner is not None and existing_owner is not order:
            reason = (
                f"placement client_order_id {placement_id!r} is already owned "
                f"by stealth order {existing_owner.get('stealth_order_id')!r}"
            )
            order["placement_index_error"] = reason
            self.log_callback("error", {
                "event": "accepted_placement_index_owner_conflict",
                "stealth_order_id": order.get("stealth_order_id"),
                "existing_stealth_order_id": existing_owner.get(
                    "stealth_order_id"
                ),
                "placement_client_order_id": placement_id,
                "index_source": source,
                "error": reason,
            })
            return False

        self._placed_order_index[placement_id] = order
        return True

    def _restore_hydrated_placement_index(
        self,
        order: Dict[str, Any],
    ) -> int:
        """Restore only locally persisted, explicitly accepted placements."""
        restored = 0
        for reveal_event in order.get("revealed_orders") or []:
            if not isinstance(reveal_event, dict):
                continue
            if reveal_event.get("placement_success") is not True:
                continue
            exchange_order_id = reveal_event.get("exchange_order_id")
            if not (
                isinstance(exchange_order_id, str)
                and exchange_order_id.strip()
            ):
                continue
            placement_id = (
                reveal_event.get("placement_client_order_id")
                or reveal_event.get("placed_order_id")
            )
            if self._index_accepted_placement(
                order,
                placement_id,
                source="database_hydration",
            ):
                restored += 1
        return restored

    def _record_accepted_local_finalization_error(
        self,
        order: Dict[str, Any],
        *,
        placement_client_order_id: str,
        exchange_order_id: str,
        stage: str,
        error: Exception,
        reveal_event: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Report bookkeeping failure after exchange acceptance.

        Once acceptance has been classified, a hook, persistence, or audit
        failure is never a placement failure and must never invite a retry.
        Keep that distinction in one path shared by reveal, anchor reprice,
        and manual move finalization.
        """
        error_text = f"{stage}: {error}"[:512]
        if reveal_event is not None:
            existing_error = reveal_event.get("placement_error")
            reveal_event["placement_error"] = (
                f"{existing_error}; {error_text}"
                if existing_error
                else error_text
            )
            reveal_event["local_finalization_error"] = error_text

        event_name = {
            "reveal": "stealth_order_slice_local_finalization_error",
            "anchor_reprice": "stealth_anchor_reprice_local_finalization_error",
            "move": "stealth_move_local_finalization_error",
        }.get(stage.split(".", 1)[0], "stealth_placement_local_finalization_error")
        self.log_callback(
            "error",
            {
                "event": event_name,
                "stealth_order_id": order.get("stealth_order_id"),
                "placement_client_order_id": placement_client_order_id,
                "exchange_order_id": exchange_order_id,
                "finalization_stage": stage,
                "error": str(error),
                "note": (
                    "Exchange acceptance is confirmed. "
                    "Order IS LIVE on the exchange; do not resubmit."
                ),
            },
        )
        return error_text

    def _run_accepted_local_finalization_step(
        self,
        order: Dict[str, Any],
        *,
        placement_client_order_id: str,
        exchange_order_id: str,
        stage: str,
        operation: Callable[[], Any],
        incomplete_message: str,
        reveal_event: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Run one local step without changing accepted placement truth."""
        try:
            result = operation()
        except Exception as error:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=exchange_order_id,
                stage=stage,
                error=error,
                reveal_event=reveal_event,
            )
            return False
        if result is False:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=exchange_order_id,
                stage=stage,
                error=RuntimeError(incomplete_message),
                reveal_event=reveal_event,
            )
            return False
        return True

    def _run_terminal_failure_persistence_step(
        self,
        order: Dict[str, Any],
        *,
        placement_client_order_id: Optional[str],
        outcome: OrderPlacementOutcome,
        stage: str,
        operation: Callable[[], Any],
    ) -> bool:
        """Persist terminal placement failure without hiding DB failure."""
        try:
            result = operation()
            if result is not False:
                return True
            error: Exception = RuntimeError("database operation did not complete")
        except Exception as operation_error:
            error = operation_error
        self.log_callback(
            "error",
            {
                "event": "terminal_placement_failure_persistence_failed",
                "stealth_order_id": order.get("stealth_order_id"),
                "placement_client_order_id": placement_client_order_id,
                "placement_outcome": outcome.value,
                "persistence_stage": stage,
                "error": str(error),
                "note": (
                    "Placement remains terminal in memory and will not be retried; "
                    "the local failure record was not fully persisted."
                ),
            },
        )
        return False

    def _record_terminal_placement_failure(
        self,
        order: Dict[str, Any],
        *,
        placement_client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        submitted_price: float,
        failure_reason: str,
        outcome: OrderPlacementOutcome,
        attempted_size: float,
        market_data: Optional[Dict[str, Any]] = None,
        audit_fields: Optional[Dict[str, Any]] = None,
        clear_active_placement: bool = False,
    ) -> Dict[str, Any]:
        """Persist one failed/indeterminate placement without consuming size.

        This is the single failure path shared by reveal, move, and anchor
        replacement.  It deliberately does not update reveal counters, index
        the client id, invoke success hooks, or retain a new active exchange
        pointer.
        """
        stealth_order_id = str(order["stealth_order_id"])
        bounded_reason = str(failure_reason or "placement was not accepted")[:512]
        market_data = market_data or {}
        market_bid = market_data.get("bid")
        market_ask = market_data.get("ask")
        market_spread = None
        if market_bid is not None and market_ask is not None:
            try:
                market_spread = float(market_ask) - float(market_bid)
            except (TypeError, ValueError):
                market_spread = None

        reveal_event: Dict[str, Any] = {
            "reveal_number": len(order.get("revealed_orders") or []) + 1,
            "revealed_size": 0.0,
            "placement_price": float(submitted_price),
            "placed_order_id": placement_client_order_id,
            "placement_client_order_id": placement_client_order_id,
            "exchange_order_id": exchange_order_id,
            "placement_success": False,
            "placement_status": outcome.value.lower(),
            "placement_error": bounded_reason,
            "reveal_time": datetime.utcnow(),
            "market_price": market_data.get("price"),
            "market_bid": market_bid,
            "market_ask": market_ask,
            "market_spread": market_spread,
            "market_volume_1m": market_data.get("volume_1m"),
            "market_source": market_data.get("source"),
        }
        if audit_fields:
            reveal_event.update(audit_fields)

        order.setdefault("revealed_orders", []).append(reveal_event)
        order["status"] = StealthOrderStatus.ERROR.value
        order["failure_reason"] = bounded_reason
        order["updated_at"] = datetime.utcnow()

        if clear_active_placement:
            anchor_state = self._normalize_anchor_repricing_state(
                order.get("anchor_repricing_state_json")
            )
            anchor_state["active_placement_client_order_id"] = None
            anchor_state["active_exchange_order_id"] = None
            anchor_state["active_exchange_price"] = None
            order["anchor_repricing_state_json"] = anchor_state

        self._mark_placement_parent_failed(
            placement_client_order_id,
            stealth_order_id=stealth_order_id,
        )
        self._run_terminal_failure_persistence_step(
            order,
            placement_client_order_id=placement_client_order_id,
            outcome=outcome,
            stage="stealth_order",
            operation=lambda: self._update_stealth_order(order),
        )
        self._run_terminal_failure_persistence_step(
            order,
            placement_client_order_id=placement_client_order_id,
            outcome=outcome,
            stage="reveal_history",
            operation=lambda: self._record_reveal_event(order, reveal_event),
        )
        self._dispatch_lifecycle_event(
            stealth_order_id=stealth_order_id,
            event=StealthLifecycleEvent.REVEAL_FAILED,
            order_data=order,
            extra={
                "failure_reason": bounded_reason,
                "size": float(attempted_size),
                "placed_order_id": placement_client_order_id,
                "exchange_order_id": exchange_order_id,
                "placement_outcome": outcome.value,
            },
        )
        return reveal_event

    def _should_skip_anchor_reprice(
        self,
        state: Dict[str, Any],
        policy: Any,
        desired_price: float,
        current_price: float,
        force_due: bool,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        policy = RepricingPolicy.coerce(policy)
        price_delta = abs(float(desired_price) - float(current_price))
        hysteresis_abs = abs(float(current_price)) * (policy.hysteresis_bps / 10000.0)
        if price_delta < max(policy.min_price_change, hysteresis_abs):
            return True

        last_reprice_at = self._parse_runtime_datetime(state.get("last_reprice_at"))
        if not force_due and last_reprice_at is not None:
            elapsed = (datetime.utcnow() - last_reprice_at).total_seconds()
            if elapsed < policy.min_reprice_interval_seconds:
                return True

        history = list(state.get("reprice_history") or [])
        cutoff = datetime.utcnow() - timedelta(hours=1)
        recent = [
            ts for ts in history
            if self._parse_runtime_datetime(ts) and self._parse_runtime_datetime(ts) >= cutoff
        ]
        state["reprice_history"] = [
            ts.isoformat() if isinstance(ts, datetime) else ts for ts in recent
        ]
        if len(recent) >= policy.max_reprices_per_hour:
            return True

        # Phase 2: Spread monitoring guardrail
        if policy.enable_spread_monitoring and market_data:
            bid = safe_float(market_data.get("bid"), default=None)
            ask = safe_float(market_data.get("ask"), default=None)
            if bid and ask and bid > 0 and ask > 0:
                spread_bps = ((ask - bid) / ((bid + ask) / 2.0)) * 10000.0
                if spread_bps > policy.max_spread_bps:
                    return True

        # Phase 2: Volume requirement guardrail
        if policy.require_minimum_volume > 0 and market_data:
            volume_1m = safe_float(market_data.get("volume_1m"), default=0.0)
            if volume_1m < policy.require_minimum_volume:
                return True

        return False

    def _next_anchor_reprice_seconds(
        self,
        policy: Any,
        current_price: float,
        target_price: float,
        max_boundary_price: float,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Calculate next repricing interval, with volatility adjustment."""
        policy = RepricingPolicy.coerce(policy)
        if policy.is_fixed_interval:
            return policy.fixed_interval_seconds

        # Adaptive timing based on price gaps
        target_gap = abs(current_price - target_price)
        max_gap = abs(current_price - max_boundary_price)
        if max_gap <= 0:
            interval = 60
        elif target_gap <= max(0.01, abs(target_price) * 0.0005):
            interval = 300
        elif target_gap < max_gap:
            interval = 120
        else:
            interval = 60

        # Phase 2: Volatility-based adjustment
        if market_data:
            bid = safe_float(market_data.get("bid"), default=None)
            ask = safe_float(market_data.get("ask"), default=None)
            if bid and ask and bid > 0 and ask > 0:
                spread_pct = ((ask - bid) / ((bid + ask) / 2.0)) * 10000.0
                if spread_pct > 50:  # High volatility (>50 bps)
                    interval = int(interval * policy.volatility_sensitivity)

        # Hard cap from max_reprice_window_seconds
        return min(interval, policy.max_reprice_window_seconds)

    def _validate_anchor_reprice_profitability(
        self,
        order: Dict[str, Any],
        candidate_entry_price: float,
    ) -> Tuple[bool, Optional[str]]:
        """Validate that repricing to candidate entry price remains profitable.

        Uses the same ProfitValidator target-movement derivation used by reveal
        revalidation, but evaluates a candidate repriced entry before applying it.

        Returns:
            (is_profitable, reason_if_blocked)
        """
        if not self.profit_validator:
            return True, None

        try:
            side_raw = str(order.get("side") or "").upper()
            try:
                parent_side = OrderSide(side_raw)
            except ValueError:
                return True, None

            target_movement = safe_float(order.get("target_movement"), default=0.0)
            target_movement_type = order.get("target_movement_type")
            if target_movement <= 0:
                return True, None

            order_size = safe_float(order.get("remaining_size"), default=0.0)
            if order_size <= 0:
                order_size = safe_float(order.get("total_size"), default=0.0)

            entry_price = safe_float(candidate_entry_price, default=0.0)
            if order_size <= 0 or entry_price <= 0:
                return True, None

            if not hasattr(self.profit_validator, "derive_follow_up_price_from_target"):
                return True, None

            follow_up_price = self.profit_validator.derive_follow_up_price_from_target(
                parent_filled_price=entry_price,
                parent_side=parent_side.value,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
            )
            if follow_up_price is None or follow_up_price <= 0:
                return True, None

            # Validator auto-resolves product_type, contract_size, and position_side
            # from product_id via its injected orderbook (single source of truth).
            product_id = order.get("product_id", "")

            # post_only follows the order's reveal pricing policy. TOP_OF_BOOK
            # / MIDPOINT anchor-reprices rest as makers; CONFIGURED_LIMIT
            # submits as taker. Without this, every TOP_OF_BOOK reprice was
            # being checked at the (much higher) taker rate and over-rejecting
            # otherwise-profitable repricings.
            will_be_post_only = self._resolve_post_only_from_policy(
                reveal_pricing_policy=order.get("reveal_pricing_policy"),
                reveal_condition=order.get("reveal_condition_json"),
            )

            validation = self.profit_validator.validate_order_profitability(
                parent_filled_price=entry_price,
                parent_side=parent_side.value,
                follow_up_price=follow_up_price,
                order_size=order_size,
                min_margin_pct=0.0,
                product_id=product_id,
                post_only=will_be_post_only,
            )

            is_profitable = bool(validation.get("is_profitable", False))
            if is_profitable:
                return True, None

            net_profit = safe_float(validation.get("net_profit"), default=0.0)
            return False, (
                f"blocked_unprofitable: projected net profit {net_profit:.8f} "
                f"at entry {entry_price}"
            )
        except Exception as exc:
            # Validation issues should never break repricing loop.
            self.logger.warning(
                f"Anchor repricing profitability validation failed for "
                f"{order.get('stealth_order_id')}: {exc}"
            )
            return True, None

    def _placement_client_order_id_for_order(self, order: Dict[str, Any]) -> str:
        policy = RepricingPolicy.coerce(order.get("anchor_repricing_policy_json"))
        if policy.should_reprice_revealed:
            return str(uuid.uuid4())
        return order["stealth_order_id"]

    def _mark_reveal_event_cancelled_for_reprice(
        self,
        order: Dict[str, Any],
        placed_order_id: Optional[str],
        reprice_reason: str,
    ) -> None:
        for reveal_event in reversed(order.get("revealed_orders") or []):
            if not isinstance(reveal_event, dict):
                continue
            if reveal_event.get("placed_order_id") != placed_order_id:
                continue
            reveal_event["cancelled_for_reprice"] = True
            reveal_event["reprice_reason"] = reprice_reason
            break

    def _apply_revealed_anchor_reprice(
        self,
        order: Dict[str, Any],
        policy: Any,
        state: Dict[str, Any],
        market_data: Dict[str, Any],
        desired_price: float,
        target_price: float,
        max_boundary_price: float,
        reprice_reason: str,
    ) -> bool:
        # Guard: nothing left to reprice. The reprice tick fires on a timer
        # against the stealth dict, so a placement that filled between ticks
        # leaves the canonical fields (`remaining_size`, `revealed_size`)
        # consistent while `state.active_exchange_order_id` may still hold the
        # now-filled exchange order id.  Without this guard we would
        # `cancel_orders` an already-filled order, then place a 0-size
        # replacement and write a phantom `order_parent` row (size=0).  See
        # 2026-04-27 audit for the production incident.
        remaining_size = safe_float(order.get("remaining_size"), default=0.0)
        if remaining_size <= 0:
            state["active_exchange_order_id"] = None
            state["active_placement_client_order_id"] = None
            return False

        exchange_order_id = state.get("active_exchange_order_id")
        current_price = safe_float(state.get("active_exchange_price"), default=order.get("limit_price"))
        if not exchange_order_id or current_price is None:
            return False

        force_due = reprice_reason == "outside_max_boundary"
        if self._should_skip_anchor_reprice(state, policy, desired_price, current_price, force_due, market_data):
            return False

        from configuration import REST_CLIENT

        bid = safe_float(market_data.get("bid"), default=None)
        ask = safe_float(market_data.get("ask"), default=None)
        normalized_side = str(order.get("side") or "").upper()
        policy = RepricingPolicy.coerce(policy)
        if policy.post_only_required:
            if normalized_side == "BUY" and ask and desired_price >= ask:
                return False
            if normalized_side == "SELL" and bid and desired_price <= bid:
                return False

        try:
            desired_price = self._quantize_reprice_price(
                order["product_id"],
                order["side"],
                desired_price,
                boundary_enforced=(reprice_reason == "outside_max_boundary"),
            )
        except ValueError as normalization_error:
            self.log_callback(
                "error",
                {
                    "event": "stealth_anchor_reprice_price_invalid",
                    "stealth_order_id": order["stealth_order_id"],
                    "product_id": order["product_id"],
                    "requested_price": desired_price,
                    "error": str(normalization_error),
                    "note": "Existing exchange order was left unchanged.",
                },
            )
            return False

        REST_CLIENT.cancel_orders(order_ids=[exchange_order_id])

        self._mark_reveal_event_cancelled_for_reprice(
            order,
            state.get("active_placement_client_order_id"),
            reprice_reason,
        )

        placement_client_order_id = str(uuid.uuid4())

        # Pre-insert the chain link before REST so a fast websocket acceptance
        # cannot create this placement as an unrelated root.
        root_parent_for_placement = resolve_stealth_chain_root(order)
        placement_parent_inserted = False
        placement_parent_error: Optional[Exception] = None
        try:
            inherited_tm, inherited_tm_type, _src = \
                self._resolve_target_movement_for_plan(order["stealth_order_id"], order)
            placement_parent_id = insert_order_parent(
                client_order_id=placement_client_order_id,
                product_id=order["product_id"],
                side=order["side"],
                size=safe_float(order.get("remaining_size"), default=0.0),
                price=desired_price,
                target_movement=inherited_tm if inherited_tm is not None else 0.0,
                target_movement_type=inherited_tm_type or "P",
                max_order_replacement=int(order.get("max_order_replacements") or 0),
                current_order_replacement=0,
                status=OrderStatus.PENDING.value,
                parent_order_id=root_parent_for_placement,
                allow_partial_fills=bool(order.get("allow_partial_fills", False)),
            )
            placement_parent_inserted = placement_parent_id is not None
            if not placement_parent_inserted:
                placement_parent_error = RuntimeError(
                    "order_parent insert returned no row id"
                )
        except Exception as parent_insert_error:
            placement_parent_error = parent_insert_error
            self.log_callback(
                "warning",
                {
                    "event": "anchor_reprice_order_parent_insert_failed",
                    "stealth_order_id": order["stealth_order_id"],
                    "placement_client_order_id": placement_client_order_id,
                    "error": str(parent_insert_error),
                },
            )

        order_result = None
        try:
            # Track the cancel+replace as a single in-flight critical section
            # so a concurrent drain waits for replacement placement to settle.
            with get_runtime_controller().track_inflight(INFLIGHT_REST_PLACE):
                order_result = REST_CLIENT.place_limit_order(
                    product_id=order["product_id"],
                    side=order["side"],
                    limit_price=str(desired_price),
                    base_size=str(order["remaining_size"]),
                    client_order_id=placement_client_order_id,
                    post_only=policy.post_only_required,
                )
            classification = classify_placement_response(
                order_result,
                expected_client_order_id=placement_client_order_id,
            )
        except Exception as placement_exception:
            classification = classify_placement_response(
                expected_client_order_id=placement_client_order_id,
                exception=placement_exception,
            )

        if not classification.accepted:
            failure_reason = (
                classification.failure_reason
                or f"placement outcome {classification.outcome.value}"
            )
            self._record_terminal_placement_failure(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=classification.exchange_order_id,
                submitted_price=desired_price,
                failure_reason=failure_reason,
                outcome=classification.outcome,
                attempted_size=remaining_size,
                market_data=market_data,
                audit_fields={
                    "cancelled_for_reprice": False,
                    "reference_price_source": state.get("last_reference_source"),
                    "reference_price": state.get("last_reference_price"),
                    "reference_bid": state.get("last_reference_bid"),
                    "reference_ask": state.get("last_reference_ask"),
                    "anchor_target_price": target_price,
                    "anchor_max_price": max_boundary_price,
                    "reprice_reason": reprice_reason,
                },
                clear_active_placement=True,
            )
            self.log_callback(
                "error",
                {
                    "event": "stealth_anchor_reprice_placement_failed",
                    "stealth_order_id": order["stealth_order_id"],
                    "placement_client_order_id": placement_client_order_id,
                    "placement_outcome": classification.outcome.value,
                    "failure_reason": failure_reason,
                    "old_exchange_order_id": exchange_order_id,
                    "parent_row_pre_inserted": placement_parent_inserted,
                },
            )
            return False

        new_exchange_order_id = classification.exchange_order_id
        index_succeeded = self._index_accepted_placement(
            order,
            placement_client_order_id,
            source="anchor_reprice_acceptance",
        )

        reveal_event = {
            "reveal_number": len(order.get("revealed_orders", [])) + 1,
            "revealed_size": order.get("remaining_size", 0.0),
            "placement_price": desired_price,
            "placed_order_id": placement_client_order_id,
            "placement_client_order_id": placement_client_order_id,
            "exchange_order_id": new_exchange_order_id,
            "placement_success": True,
            "placement_status": "repriced",
            "placement_error": None,
            "cancelled_for_reprice": False,
            "reveal_time": datetime.utcnow(),
            "market_price": market_data.get("price"),
            "market_bid": bid,
            "market_ask": ask,
            "market_spread": (ask - bid) if bid is not None and ask is not None else None,
            "market_volume_1m": market_data.get("volume_1m"),
            "market_source": market_data.get("source"),
            "reference_price_source": state.get("last_reference_source"),
            "reference_price": state.get("last_reference_price"),
            "reference_bid": state.get("last_reference_bid"),
            "reference_ask": state.get("last_reference_ask"),
            "anchor_target_price": target_price,
            "anchor_max_price": max_boundary_price,
            "reprice_reason": reprice_reason,
        }
        order.setdefault("revealed_orders", []).append(reveal_event)
        if not index_succeeded:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=new_exchange_order_id,
                stage="anchor_reprice.index_accepted_placement",
                error=RuntimeError(
                    order.get("placement_index_error")
                    or "accepted placement could not be indexed"
                ),
                reveal_event=reveal_event,
            )

        if placement_parent_error is not None:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=new_exchange_order_id,
                stage="anchor_reprice.preinsert_parent",
                error=placement_parent_error,
                reveal_event=reveal_event,
            )

        now = datetime.utcnow()
        state["active_placement_client_order_id"] = placement_client_order_id
        state["active_exchange_order_id"] = new_exchange_order_id
        state["active_exchange_price"] = desired_price
        state["current_logical_limit_price"] = desired_price
        state["last_reprice_at"] = now
        state["reprice_reason"] = reprice_reason
        state.setdefault("reprice_history", []).append(now.isoformat())
        state["next_reprice_at"] = (now + timedelta(seconds=self._next_anchor_reprice_seconds(policy, desired_price, target_price, max_boundary_price, market_data))).isoformat()

        # Track reveal_condition price thresholds in lock-step with the new limit.
        # Must run BEFORE we mutate order["limit_price"] so the helper can read
        # the pre-reprice limit as the offset baseline on first invocation.
        self._apply_reveal_condition_price_tracking(order, state, desired_price)

        order["anchor_repricing_state_json"] = state
        order["limit_price"] = desired_price
        order["updated_at"] = now
        self._run_accepted_local_finalization_step(
            order,
            placement_client_order_id=placement_client_order_id,
            exchange_order_id=new_exchange_order_id,
            stage="anchor_reprice.persist_stealth_order",
            operation=lambda: self._update_stealth_order(order),
            incomplete_message="stealth order database update did not complete",
            reveal_event=reveal_event,
        )

        # Persist reprice to history table for audit (mirrors reveal_order_slice).
        self._run_accepted_local_finalization_step(
            order,
            placement_client_order_id=placement_client_order_id,
            exchange_order_id=new_exchange_order_id,
            stage="anchor_reprice.persist_reveal_event",
            operation=lambda: self._record_reveal_event(order, reveal_event),
            incomplete_message="reveal history database update did not complete",
            reveal_event=reveal_event,
        )

        self.log_callback(
            "debug",
            {
                "event": "stealth_anchor_reprice_revealed_applied",
                "stealth_order_id": order["stealth_order_id"],
                "product_id": order["product_id"],
                "side": order["side"],
                "previous_exchange_order_id": exchange_order_id,
                "previous_price": current_price,
                "new_placement_client_order_id": placement_client_order_id,
                "new_exchange_order_id": new_exchange_order_id,
                "new_price": desired_price,
                "anchor_target_price": target_price,
                "anchor_max_price": max_boundary_price,
                "reprice_reason": reprice_reason,
                "reference_price_source": state.get("last_reference_source"),
                "reference_price": state.get("last_reference_price"),
                "market_bid": bid,
                "market_ask": ask,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Move REVEALED stealth order (cancel-and-replace at new price)
    # ------------------------------------------------------------------
    #
    # Coinbase exposes no order-edit endpoint, so a "move" is implemented
    # the same way the ticker-driven anchor reprice does it: cancel the
    # existing exchange order, place a fresh one at the new price, and
    # reset per-order reveal/repricing state so the new placement starts
    # with a clean slate (post-reveal repricing policy still applies).
    #
    # Concurrency: both ``build_stealth_move_plan`` and
    # ``execute_stealth_move`` are designed to be invoked from the
    # dashboard websocket thread, while the ticker-driven reprice loop
    # runs in the user-event thread. ``execute_stealth_move`` claims the
    # MOVE mutation slot before any exchange call; the reprice loop
    # claims the REPRICE slot for each iteration. The wrapper layer
    # enforces cross-kind exclusion per stealth order id (see
    # :meth:`try_claim_mutation`).
    #
    # v1 scope (pinned by tests/regression/test_stealth_move_revealed.py):
    # - Order must be REVEALED with executed_size == 0.
    # - Move resets ``anchor_repricing_state_json`` to defaults.
    # - Flat hierarchy preserved via ``resolve_stealth_chain_root``.
    # - Failure after cancel succeeds → stealth order set to CANCELLED.

    def build_stealth_move_plan(
        self,
        stealth_order_id: str,
        new_limit_price: float,
        *,
        new_target_movement: Optional[float] = None,
        new_target_movement_type: Optional[str] = None,
        reason: Optional[Any] = None,
        notes: Optional[str] = None,
    ) -> "StealthMovePlan":
        """Build an immutable plan for moving a REVEALED stealth order.

        Validates eligibility (REVEALED status, no partial fill, valid
        price, active exchange order id), captures the old placement's
        identity and price for the audit row, and composes a
        :class:`RevealExecutionPlan` describing the *new* placement using
        ``CONFIGURED_LIMIT`` policy — the user is choosing the new price
        explicitly, so no policy-based price discovery happens at move
        time. The stealth order's persisted ``reveal_pricing_policy``
        stays untouched and continues to govern any future automatic
        repricing on the new placement.

        Raises:
            StealthMoveError: validation failed; nothing has been mutated.
        """
        from core.enums import (
            RevealPriceSource,
            RevealPricingPolicy,
            StealthMoveReason,
            StealthOrderStatus,
        )
        from core.exceptions import StealthMoveError
        from core.models import RevealExecutionPlan, StealthMovePlan

        order = self._get_stealth_order(stealth_order_id)
        if order is None:
            raise StealthMoveError(
                f"stealth order {stealth_order_id!r} not found",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )

        status = str(order.get("status") or "")
        if status != StealthOrderStatus.REVEALED.value:
            raise StealthMoveError(
                f"cannot move stealth order {stealth_order_id!r}: "
                f"status is {status!r}, expected REVEALED",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )

        executed_size = safe_float(order.get("executed_size"), default=0.0)
        if executed_size > 0:
            raise StealthMoveError(
                f"cannot move stealth order {stealth_order_id!r}: "
                f"executed_size={executed_size} (v1 supports zero-fill moves only; "
                f"partial-fill / reduce-only moves are out of scope)",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )

        new_price = safe_float(new_limit_price, default=0.0)
        if new_price <= 0:
            raise StealthMoveError(
                f"new_limit_price must be > 0, got {new_limit_price!r}",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )

        price_check = normalize_price_for_product(
            new_price,
            product_id=str(order.get("product_id") or ""),
            side=order.get("side"),
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if not price_check.ok or price_check.effective_price is None:
            raise StealthMoveError(
                f"new_limit_price failed product boundary validation: "
                f"{price_check.reason}",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )
        new_price = float(price_check.effective_price)

        state = self._normalize_anchor_repricing_state(
            order.get("anchor_repricing_state_json")
        )
        old_exchange_order_id = state.get("active_exchange_order_id")
        if not old_exchange_order_id:
            raise StealthMoveError(
                f"cannot move stealth order {stealth_order_id!r}: "
                f"no active_exchange_order_id in repricing state "
                f"(was the order revealed?)",
                stealth_order_id=stealth_order_id,
                stage="validate",
            )
        old_submitted_price = safe_float(
            state.get("active_exchange_price"),
            default=safe_float(order.get("limit_price"), default=0.0),
        )

        market_data = self._get_current_market_data(order.get("product_id", "")) or {}

        # Compose a RevealExecutionPlan describing the *new* placement.
        # The user picked the price explicitly → CONFIGURED_LIMIT policy
        # with no fallback; this is symmetric with how parent moves
        # work today (operator chooses the new price).
        reveal_plan = RevealExecutionPlan(
            configured_limit_price=new_price,
            submitted_limit_price=new_price,
            reveal_pricing_policy=RevealPricingPolicy.CONFIGURED_LIMIT.value,
            reveal_price_source=RevealPriceSource.CONFIGURED_LIMIT.value,
            fallback_used=False,
            market_source=market_data.get("source"),
            market_bid=safe_float(market_data.get("bid"), default=None),
            market_ask=safe_float(market_data.get("ask"), default=None),
        )

        target_movement, target_movement_type, target_movement_source = \
            self._resolve_target_movement_for_plan(stealth_order_id, order)
        reveal_plan.target_movement = (
            new_target_movement if new_target_movement is not None else target_movement
        )
        reveal_plan.target_movement_type = (
            new_target_movement_type if new_target_movement_type is not None
            else target_movement_type
        )
        reveal_plan.target_movement_source = target_movement_source

        try:
            root_parent_for_placement = resolve_stealth_chain_root(order)
        except Exception:
            root_parent_for_placement = order.get("parent_order_id") or stealth_order_id

        return StealthMovePlan(
            stealth_order_id=stealth_order_id,
            root_parent_client_order_id=root_parent_for_placement,
            old_exchange_order_id=str(old_exchange_order_id),
            old_submitted_price=old_submitted_price,
            new_configured_limit_price=new_price,
            reveal_plan=reveal_plan,
            reason=reason or StealthMoveReason.MANUAL_USER_MOVE,
            new_target_movement=new_target_movement,
            new_target_movement_type=new_target_movement_type,
            reset_repricing_state=True,
            reset_reveal_counters=True,
            notes=notes,
            market_bid=safe_float(market_data.get("bid"), default=None),
            market_ask=safe_float(market_data.get("ask"), default=None),
        )

    def execute_stealth_move(self, plan: "StealthMovePlan") -> "StealthMoveResult":
        """Execute a previously-built :class:`StealthMovePlan`.

        Acquires the MOVE mutation claim, cancels the old exchange
        order, places a fresh one at ``plan.reveal_plan.submitted_limit_price``,
        resets per-order reveal/repricing state, and persists the
        stealth order plus a follow-on reveal-event audit record.

        Failure handling:
        - If the claim cannot be acquired, raise without side effects.
        - If the cancel call raises, raise without side effects.
        - If placement fails **after** cancellation succeeds, mark the
          stealth order ``ERROR`` and persist the placement failure.

        Returns:
            :class:`StealthMoveResult` with the new placement's internal
            client_order_id, the exchange order id (when present in the
            REST response), and the submitted limit price.

        Raises:
            StealthMoveError: see ``stage`` field for where it failed.
        """
        from core.enums import StealthMutationKind, StealthOrderStatus
        from core.exceptions import StealthMoveError
        from configuration import REST_CLIENT

        sid = plan.stealth_order_id
        if not self.try_claim_mutation(StealthMutationKind.MOVE, sid):
            raise StealthMoveError(
                f"another mutation is in flight for stealth order {sid!r}",
                stealth_order_id=sid,
                stage="claim",
            )

        try:
            order = self._get_stealth_order(sid)
            if order is None:
                raise StealthMoveError(
                    f"stealth order {sid!r} disappeared between plan-build and execute",
                    stealth_order_id=sid,
                    stage="validate",
                )

            new_price = safe_float(
                plan.reveal_plan.submitted_limit_price,
                default=plan.new_configured_limit_price,
            )
            price_check = normalize_price_for_product(
                new_price,
                product_id=str(order.get("product_id") or ""),
                side=order.get("side"),
                policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
            )
            if not price_check.ok or price_check.effective_price is None:
                raise StealthMoveError(
                    f"move price failed product boundary validation: "
                    f"{price_check.reason}",
                    stealth_order_id=sid,
                    stage="validate",
                )
            new_price = float(price_check.effective_price)
            old_placement_client_order_id = order.get(
                "anchor_repricing_state_json", {}
            ).get("active_placement_client_order_id")

            # === CANCEL ===
            try:
                with get_runtime_controller().track_inflight(INFLIGHT_REST_PLACE):
                    REST_CLIENT.cancel_orders(order_ids=[plan.old_exchange_order_id])
            except Exception as cancel_exc:
                self.log_callback(
                    "error",
                    {
                        "event": "stealth_move_cancel_failed",
                        "stealth_order_id": sid,
                        "old_exchange_order_id": plan.old_exchange_order_id,
                        "error": str(cancel_exc),
                    },
                )
                try:
                    from database.order import insert_stealth_order_move
                    insert_stealth_order_move(
                        stealth_order_id=sid,
                        old_placement_client_order_id=old_placement_client_order_id,
                        old_exchange_order_id=plan.old_exchange_order_id,
                        old_submitted_price=plan.old_submitted_price,
                        new_submitted_price=new_price,
                        reason=plan.reason.value if plan.reason is not None else None,
                        notes=plan.notes,
                        status="cancel_failed",
                        error_message=str(cancel_exc),
                        market_bid=plan.market_bid,
                        market_ask=plan.market_ask,
                    )
                except Exception:
                    pass
                raise StealthMoveError(
                    f"cancel failed for {plan.old_exchange_order_id!r}: {cancel_exc}",
                    stealth_order_id=sid,
                    stage="cancel",
                ) from cancel_exc

            # Mark the existing reveal event as cancelled-for-move (audit).
            self._mark_reveal_event_cancelled_for_reprice(
                order,
                old_placement_client_order_id,
                f"move:{plan.reason.value if plan.reason is not None else 'unknown'}",
            )

            # === PLACE ===
            placement_client_order_id = str(uuid.uuid4())

            # Pre-insert the chain-linked parent row before REST so websocket
            # acceptance cannot race in and create a detached root.
            placement_parent_inserted = False
            placement_parent_error: Optional[Exception] = None
            try:
                inherited_tm, inherited_tm_type, _src = \
                    self._resolve_target_movement_for_plan(sid, order)
                effective_tm = (
                    plan.new_target_movement
                    if plan.new_target_movement is not None
                    else inherited_tm
                )
                effective_tm_type = (
                    plan.new_target_movement_type
                    if plan.new_target_movement_type is not None
                    else inherited_tm_type
                )
                placement_parent_id = insert_order_parent(
                    client_order_id=placement_client_order_id,
                    product_id=order["product_id"],
                    side=order["side"],
                    size=safe_float(order.get("remaining_size"), default=0.0),
                    price=new_price,
                    target_movement=effective_tm if effective_tm is not None else 0.0,
                    target_movement_type=effective_tm_type or "P",
                    max_order_replacement=int(order.get("max_order_replacements") or 0),
                    current_order_replacement=0,
                    status=OrderStatus.PENDING.value,
                    parent_order_id=plan.root_parent_client_order_id,
                    allow_partial_fills=bool(order.get("allow_partial_fills", False)),
                )
                placement_parent_inserted = placement_parent_id is not None
                if not placement_parent_inserted:
                    placement_parent_error = RuntimeError(
                        "order_parent insert returned no row id"
                    )
            except Exception as parent_insert_error:
                placement_parent_error = parent_insert_error
                self.log_callback(
                    "warning",
                    {
                        "event": "stealth_move_order_parent_insert_failed",
                        "stealth_order_id": sid,
                        "placement_client_order_id": placement_client_order_id,
                        "error": str(parent_insert_error),
                    },
                )

            order_result = None
            try:
                with get_runtime_controller().track_inflight(INFLIGHT_REST_PLACE):
                    order_result = REST_CLIENT.place_limit_order(
                        product_id=order["product_id"],
                        side=order["side"],
                        limit_price=str(new_price),
                        base_size=str(safe_float(order.get("remaining_size"), default=0.0)),
                        client_order_id=placement_client_order_id,
                        post_only=False,
                    )
                classification = classify_placement_response(
                    order_result,
                    expected_client_order_id=placement_client_order_id,
                )
            except Exception as place_exception:
                classification = classify_placement_response(
                    expected_client_order_id=placement_client_order_id,
                    exception=place_exception,
                )

            if not classification.accepted:
                failure_reason = (
                    classification.failure_reason
                    or f"placement outcome {classification.outcome.value}"
                )
                self._record_terminal_placement_failure(
                    order,
                    placement_client_order_id=placement_client_order_id,
                    exchange_order_id=classification.exchange_order_id,
                    submitted_price=new_price,
                    failure_reason=failure_reason,
                    outcome=classification.outcome,
                    attempted_size=safe_float(order.get("remaining_size"), default=0.0),
                    market_data={
                        "bid": plan.market_bid,
                        "ask": plan.market_ask,
                        "source": plan.reveal_plan.market_source,
                    },
                    audit_fields={
                        "move_reason": (
                            plan.reason.value if plan.reason is not None else None
                        ),
                        "move_notes": plan.notes,
                        "previous_exchange_order_id": plan.old_exchange_order_id,
                        "previous_submitted_price": plan.old_submitted_price,
                    },
                    clear_active_placement=True,
                )
                self.log_callback(
                    "error",
                    {
                        "event": "stealth_move_place_failed_after_cancel",
                        "stealth_order_id": sid,
                        "old_exchange_order_id": plan.old_exchange_order_id,
                        "new_placement_client_order_id": placement_client_order_id,
                        "placement_outcome": classification.outcome.value,
                        "failure_reason": failure_reason,
                        "parent_row_pre_inserted": placement_parent_inserted,
                    },
                )
                try:
                    from database.order import insert_stealth_order_move
                    insert_stealth_order_move(
                        stealth_order_id=sid,
                        old_placement_client_order_id=old_placement_client_order_id,
                        old_exchange_order_id=plan.old_exchange_order_id,
                        old_submitted_price=plan.old_submitted_price,
                        new_placement_client_order_id=placement_client_order_id,
                        new_exchange_order_id=classification.exchange_order_id,
                        new_submitted_price=new_price,
                        reason=plan.reason.value if plan.reason is not None else None,
                        notes=plan.notes,
                        status="place_failed_after_cancel",
                        error_message=failure_reason,
                        market_bid=plan.market_bid,
                        market_ask=plan.market_ask,
                    )
                except Exception:
                    pass
                raise StealthMoveError(
                    f"place failed AFTER cancel succeeded for {sid!r}: "
                    f"stealth order set to ERROR. {failure_reason}",
                    stealth_order_id=sid,
                    stage="place",
                )

            new_exchange_order_id = classification.exchange_order_id
            index_succeeded = self._index_accepted_placement(
                order,
                placement_client_order_id,
                source="move_acceptance",
            )

            # === RESET STATE ===
            now = datetime.utcnow()
            if plan.reset_repricing_state:
                fresh_state = self._normalize_anchor_repricing_state(None)
            else:
                fresh_state = self._normalize_anchor_repricing_state(
                    order.get("anchor_repricing_state_json")
                )
            fresh_state["active_placement_client_order_id"] = placement_client_order_id
            fresh_state["active_exchange_order_id"] = new_exchange_order_id
            fresh_state["active_exchange_price"] = new_price
            fresh_state["current_logical_limit_price"] = new_price
            fresh_state["last_reprice_at"] = now.isoformat()
            fresh_state["reprice_reason"] = (
                f"move:{plan.reason.value if plan.reason is not None else 'unknown'}"
            )

            order["anchor_repricing_state_json"] = fresh_state
            if plan.reset_reveal_counters:
                order["revealed_orders"] = []
            order["limit_price"] = new_price
            if plan.new_target_movement is not None:
                order["target_movement"] = plan.new_target_movement
            if plan.new_target_movement_type is not None:
                order["target_movement_type"] = plan.new_target_movement_type
            order["updated_at"] = now

            # Record a single reveal event for the new placement so the
            # audit history accounts for the move.
            move_reveal_event = {
                "reveal_number": 1,
                "revealed_size": safe_float(order.get("remaining_size"), default=0.0),
                "placement_price": new_price,
                "placed_order_id": placement_client_order_id,
                "placement_client_order_id": placement_client_order_id,
                "exchange_order_id": new_exchange_order_id,
                "placement_success": True,
                "placement_status": "moved",
                "placement_error": None,
                "cancelled_for_reprice": False,
                "reveal_time": now,
                "market_bid": plan.market_bid,
                "market_ask": plan.market_ask,
                "market_source": plan.reveal_plan.market_source,
                "move_reason": (
                    plan.reason.value if plan.reason is not None else None
                ),
                "move_notes": plan.notes,
                "previous_exchange_order_id": plan.old_exchange_order_id,
                "previous_submitted_price": plan.old_submitted_price,
            }
            order.setdefault("revealed_orders", []).append(move_reveal_event)
            if not index_succeeded:
                self._record_accepted_local_finalization_error(
                    order,
                    placement_client_order_id=placement_client_order_id,
                    exchange_order_id=new_exchange_order_id,
                    stage="move.index_accepted_placement",
                    error=RuntimeError(
                        order.get("placement_index_error")
                        or "accepted placement could not be indexed"
                    ),
                    reveal_event=move_reveal_event,
                )

            if placement_parent_error is not None:
                self._record_accepted_local_finalization_error(
                    order,
                    placement_client_order_id=placement_client_order_id,
                    exchange_order_id=new_exchange_order_id,
                    stage="move.preinsert_parent",
                    error=placement_parent_error,
                    reveal_event=move_reveal_event,
                )

            self._run_accepted_local_finalization_step(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=new_exchange_order_id,
                stage="move.persist_stealth_order",
                operation=lambda: self._update_stealth_order(order),
                incomplete_message="stealth order database update did not complete",
                reveal_event=move_reveal_event,
            )

            self._run_accepted_local_finalization_step(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=new_exchange_order_id,
                stage="move.persist_reveal_event",
                operation=lambda: self._record_reveal_event(
                    order,
                    move_reveal_event,
                ),
                incomplete_message="reveal history database update did not complete",
                reveal_event=move_reveal_event,
            )

            from database.order import insert_stealth_order_move
            self._run_accepted_local_finalization_step(
                order,
                placement_client_order_id=placement_client_order_id,
                exchange_order_id=new_exchange_order_id,
                stage="move.persist_move_audit",
                operation=lambda: insert_stealth_order_move(
                    stealth_order_id=sid,
                    old_placement_client_order_id=old_placement_client_order_id,
                    old_exchange_order_id=plan.old_exchange_order_id,
                    old_submitted_price=plan.old_submitted_price,
                    new_placement_client_order_id=placement_client_order_id,
                    new_exchange_order_id=new_exchange_order_id,
                    new_submitted_price=new_price,
                    reason=plan.reason.value if plan.reason is not None else None,
                    notes=plan.notes,
                    status="completed",
                    market_bid=plan.market_bid,
                    market_ask=plan.market_ask,
                ) is not None,
                incomplete_message="move audit database insert did not complete",
                reveal_event=move_reveal_event,
            )

            self.log_callback(
                "info",
                {
                    "event": "stealth_move_completed",
                    "stealth_order_id": sid,
                    "old_exchange_order_id": plan.old_exchange_order_id,
                    "new_exchange_order_id": new_exchange_order_id,
                    "new_placement_client_order_id": placement_client_order_id,
                    "old_price": plan.old_submitted_price,
                    "new_price": new_price,
                    "reason": (
                        plan.reason.value if plan.reason is not None else None
                    ),
                },
            )

            from core.models import StealthMoveResult
            return StealthMoveResult(
                new_placement_client_order_id=placement_client_order_id,
                new_exchange_order_id=new_exchange_order_id,
                new_submitted_price=new_price,
            )
        finally:
            # Mutations are repeatable: always release, never complete.
            self.release_mutation(StealthMutationKind.MOVE, sid)

    def process_anchor_repricing_for_product(self, product_id: str) -> int:
        """Apply ticker-anchored repricing for eligible stealth orders on one product."""
        from core.enums import StealthMutationKind

        processed = 0
        market_data = self._get_current_market_data(product_id)
        if (market_data or {}).get("source") != "ticker":
            return 0

        for stealth_order_id in list(self._get_active_stealth_orders()):
            order = self.in_memory_orders.get(stealth_order_id)
            if not order or order.get("product_id") != product_id:
                continue

            policy = RepricingPolicy.from_dict(order.get("anchor_repricing_policy_json"))
            if not policy.enabled:
                continue

            # Mutation claim: cross-kind exclusion at the wrapper layer
            # ensures we cannot run while a manual MOVE is in flight on
            # the same sid (and vice-versa). Fail-soft: if we can't claim,
            # the next ticker tick will retry.
            if not self.try_claim_mutation(StealthMutationKind.REPRICE, stealth_order_id):
                continue

            try:
                state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
                next_reprice_at = self._parse_runtime_datetime(state.get("next_reprice_at"))
                if next_reprice_at and next_reprice_at > datetime.utcnow():
                    continue

                reference_price, reference_source = self._resolve_reference_price(
                    order.get("side"),
                    market_data,
                    policy,
                )
                if reference_price is None or reference_price <= 0:
                    continue

                target_prices = self._compute_reference_target_prices(
                    order.get("side"),
                    reference_price,
                    policy,
                )

                current_price = safe_float(
                    state.get("active_exchange_price") if order.get("status") == StealthOrderStatus.REVEALED.value else order.get("limit_price"),
                    default=order.get("limit_price"),
                )
                desired_price = target_prices["target_price"]
                reprice_reason = "reference_price_updated"

                normalized_side = str(order.get("side") or "").upper()
                max_boundary_price = target_prices["max_boundary_price"]
                outside_max = (
                    normalized_side == "BUY" and current_price < max_boundary_price
                ) or (
                    normalized_side != "BUY" and current_price > max_boundary_price
                )
                if outside_max:
                    desired_price = max_boundary_price
                    reprice_reason = "outside_max_boundary"

                desired_price, slide_clamped = self._apply_slide_step_clamp(
                    current_price, desired_price, policy,
                )
                if slide_clamped:
                    reprice_reason = f"{reprice_reason}_slide_step"

                desired_price = self._quantize_reprice_price(
                    order.get("product_id"),
                    order.get("side"),
                    desired_price,
                    boundary_enforced=outside_max,
                )

                now = datetime.utcnow()
                state.update({
                    "last_reference_source": reference_source,
                    "last_reference_price": reference_price,
                    "last_reference_bid": safe_float(market_data.get("bid"), default=None),
                    "last_reference_ask": safe_float(market_data.get("ask"), default=None),
                    "last_reference_at": now.isoformat(),
                })

                profitable, profitability_reason = self._validate_anchor_reprice_profitability(
                    order,
                    desired_price,
                )
                if not profitable:
                    state["reprice_reason"] = "blocked_unprofitable"
                    state["last_profitability_block_reason"] = profitability_reason
                    state["next_reprice_at"] = (
                        now + timedelta(
                            seconds=self._next_anchor_reprice_seconds(
                                policy,
                                current_price,
                                target_prices["target_price"],
                                max_boundary_price,
                                market_data,
                            )
                        )
                    ).isoformat()
                    order["anchor_repricing_state_json"] = state
                    self._update_stealth_order(order)
                    self.log_callback(
                        "info",
                        {
                            "event": "stealth_anchor_reprice_blocked_unprofitable",
                            "stealth_order_id": stealth_order_id,
                            "product_id": product_id,
                            "side": order.get("side"),
                            "current_price": current_price,
                            "desired_price": desired_price,
                            "anchor_target_price": target_prices["target_price"],
                            "anchor_max_price": max_boundary_price,
                            "reason": profitability_reason,
                            "reference_price_source": reference_source,
                            "reference_price": reference_price,
                        },
                    )
                    continue

                if order.get("status") in {StealthOrderStatus.HIDDEN.value, StealthOrderStatus.PENDING.value, StealthOrderStatus.TRIGGERED.value}:
                    if not self._should_skip_anchor_reprice(state, policy, desired_price, current_price, outside_max, market_data):
                        # Track reveal_condition price thresholds before mutating limit_price
                        # so the helper can capture the pre-reprice baseline on first call.
                        self._apply_reveal_condition_price_tracking(order, state, desired_price)
                        order["limit_price"] = desired_price
                        order["updated_at"] = now
                        state["current_logical_limit_price"] = desired_price
                        state["last_reprice_at"] = now.isoformat()
                        state["reprice_reason"] = reprice_reason
                        state.setdefault("reprice_history", []).append(now.isoformat())
                        processed += 1
                        self.log_callback(
                            "debug",
                            {
                                "event": "stealth_anchor_reprice_hidden_applied",
                                "stealth_order_id": stealth_order_id,
                                "product_id": product_id,
                                "side": order.get("side"),
                                "previous_price": current_price,
                                "new_price": desired_price,
                                "anchor_target_price": target_prices["target_price"],
                                "anchor_max_price": max_boundary_price,
                                "reprice_reason": reprice_reason,
                                "reference_price_source": reference_source,
                                "reference_price": reference_price,
                                "market_bid": market_data.get("bid"),
                                "market_ask": market_data.get("ask"),
                            },
                        )

                    state["next_reprice_at"] = (now + timedelta(seconds=self._next_anchor_reprice_seconds(policy, desired_price, target_prices["target_price"], max_boundary_price, market_data))).isoformat()
                    order["anchor_repricing_state_json"] = state
                    self._update_stealth_order(order)
                    continue

                if order.get("status") == StealthOrderStatus.REVEALED.value and policy.allow_revealed_reprice:
                    if self._apply_revealed_anchor_reprice(
                        order,
                        policy,
                        state,
                        market_data,
                        desired_price,
                        target_prices["target_price"],
                        max_boundary_price,
                        reprice_reason,
                    ):
                        processed += 1
                    else:
                        state["next_reprice_at"] = (now + timedelta(seconds=self._next_anchor_reprice_seconds(policy, current_price, target_prices["target_price"], max_boundary_price, market_data))).isoformat()
                        order["anchor_repricing_state_json"] = state
                        self._update_stealth_order(order)
            finally:
                self.release_mutation(StealthMutationKind.REPRICE, stealth_order_id)

        return processed

    def build_reveal_execution_plan(
        self,
        stealth_order_id: str,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> Optional['RevealExecutionPlan']:
        """Build reveal execution plan for a stealth order.

        Determines the limit price that will be used when revealing the order
        based on the order's reveal_pricing_policy and current market conditions.
        
        Args:
            stealth_order_id: ID of stealth order to plan reveal for
            market_data: Optional override for market data (default: uses _market_cache)
            
        Returns:
            RevealExecutionPlan with pricing decision, or None if order not found
        """
        from core.models import RevealExecutionPlan
        from core.enums import OrderSide, RevealPriceSource, RevealPricingPolicy
        
        order = self._get_stealth_order(stealth_order_id)
        if not order:
            return None
        
        if market_data is None:
            market_data = self._get_current_market_data(order.get("product_id", ""))
        
        reveal_pricing_policy = self._normalize_reveal_pricing_policy(
            reveal_pricing_policy=order.get("reveal_pricing_policy"),
            reveal_condition=order.get("reveal_condition_json"),
        )
        
        configured_limit_price = float(order.get("limit_price", 0.0))
        
        submitted_limit_price, reveal_price_source, fallback_used = self._resolve_reveal_limit_price(
            side=order.get("side", ""),
            configured_limit_price=configured_limit_price,
            market_data=market_data,
            reveal_pricing_policy=reveal_pricing_policy,
        )

        # Track ``fallback_used`` semantically. The resolver's flag means
        # "market data unknown / unusable" (legit reason to demote
        # post_only because we never saw bid/ask). The GUARD below also
        # sets ``fallback_used=True`` for the wire model (back-compat
        # with dashboard + tests) but it fires when we DID see the
        # market and chose a price *more* maker-favourable than the
        # policy would have. Conflating the two demoted post_only on
        # every guard fire and over-rejected legitimate maker reveals.
        market_data_unknown = fallback_used

        # === GUARD: never submit a price worse than the configured target ===
        # When a pricing policy (e.g., top_of_book) would produce a price that erodes
        # the user's target margin (BUY higher / SELL lower than configured), fall back
        # to the configured limit price. This preserves the user's intent while still
        # allowing the policy to improve the price when market conditions are favourable.
        side_raw = str(order.get("side") or "").upper()
        if configured_limit_price > 0 and submitted_limit_price > 0:
            policy_price_is_worse = (
                (side_raw == OrderSide.BUY.value and submitted_limit_price > configured_limit_price)
                or (side_raw == OrderSide.SELL.value and submitted_limit_price < configured_limit_price)
            )
            if policy_price_is_worse:
                self.logger.debug(
                    f"Reveal pricing policy {reveal_pricing_policy} produced {submitted_limit_price} "
                    f"worse than configured {configured_limit_price} for {side_raw} "
                    f"({stealth_order_id}); falling back to configured limit price"
                )
                submitted_limit_price = configured_limit_price
                reveal_price_source = RevealPriceSource.CONFIGURED_LIMIT.value
                # Wire-level back-compat: the plan still reports fallback_used.
                # But ``market_data_unknown`` stays False — we KNOW the
                # market and just picked a more conservative price.
                fallback_used = True

        price_check = normalize_price_for_product(
            submitted_limit_price,
            product_id=str(order.get("product_id") or ""),
            side=side_raw,
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if not price_check.ok or price_check.effective_price is None:
            raise RevealPricingError(
                f"Reveal price rejected at product boundary: {price_check.reason}",
                configured_price=configured_limit_price,
                fallback_used=fallback_used,
                stealth_order_id=stealth_order_id,
            )
        submitted_limit_price = float(price_check.effective_price)

        # Resolve post_only from the policy (single source of truth in
        # ``RevealPricingPolicy.implies_post_only``). TOP_OF_BOOK / MIDPOINT
        # rest as makers; CONFIGURED_LIMIT submits as a taker because the
        # caller's price may cross the spread. ONLY demote post_only when
        # market data was unusable — the guard-driven fallback chooses a
        # price strictly inside the spread and is more maker-likely than
        # the policy's own choice would have been, so keep post_only=True.
        try:
            policy_enum = RevealPricingPolicy(reveal_pricing_policy)
        except ValueError:
            policy_enum = RevealPricingPolicy.CONFIGURED_LIMIT
        if market_data_unknown and reveal_price_source == RevealPriceSource.CONFIGURED_LIMIT.value:
            policy_enum = RevealPricingPolicy.CONFIGURED_LIMIT
        post_only_required = policy_enum.implies_post_only()

        plan = RevealExecutionPlan(
            configured_limit_price=configured_limit_price,
            submitted_limit_price=submitted_limit_price,
            reveal_pricing_policy=reveal_pricing_policy,
            reveal_price_source=reveal_price_source,
            fallback_used=fallback_used,
            market_source=market_data.get("source"),
            market_bid=market_data.get("bid"),
            market_ask=market_data.get("ask"),
            post_only=post_only_required,
        )

        # Resolve canonical profit target from order_parent (single source of truth).
        # The stealth_orders row may have NULL target_movement for root orders; the
        # authoritative value lives on order_parent.
        target_movement, target_movement_type, target_movement_source = \
            self._resolve_target_movement_for_plan(stealth_order_id, order)
        plan.target_movement = target_movement
        plan.target_movement_type = target_movement_type
        plan.target_movement_source = target_movement_source

        return plan

    def _resolve_target_movement_for_plan(
        self,
        stealth_order_id: str,
        order: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[str], str]:
        """Resolve canonical (target_movement, target_movement_type, source).

        Lookup precedence:
        1. ``order_parent`` row (canonical) — keyed by ``stealth_order_id``.
        2. In-memory stealth ``order`` dict (fallback if DB lookup fails).
        3. ``unavailable`` — caller decides whether to skip the gate.
        """
        try:
            parent_row = get_parent_order(stealth_order_id)
        except Exception as exc:
            self.logger.warning(
                f"Failed to fetch order_parent for target_movement lookup "
                f"({stealth_order_id}): {exc}"
            )
            parent_row = None

        if parent_row is not None:
            tm = safe_float(parent_row.get("target_movement"), default=0.0)
            tm_type = parent_row.get("target_movement_type")
            if tm > 0 and tm_type:
                return tm, str(tm_type), "order_parent"

        # Fallback: stealth_orders dict (rarely populated for root orders)
        tm = safe_float(order.get("target_movement"), default=0.0)
        tm_type = order.get("target_movement_type")
        if tm > 0 and tm_type:
            return tm, str(tm_type), "stealth_order"

        return None, None, "unavailable"

    # ------------------------------------------------------------------
    # Profitability-failure log throttling (paired with reveal_order_slice)
    # ------------------------------------------------------------------
    #
    # The stealth bridge polls reveal candidacy every ~100 ms. If a stealth
    # order is economically stuck (e.g. configured target_movement is
    # structurally below the mandatory FUTURE fee floor), every poll re-runs
    # the same validation, raises the same exception, and would emit the
    # same WARN line. At ~10 Hz that's ~600 identical lines/minute per stuck
    # order — drowns the log and contributes nothing diagnostically.
    #
    # Strategy: treat each unique (submitted_price, target_movement,
    # target_movement_type) tuple as a distinct failure "signature". Emit
    # the WARN once per signature, then suppress repeats for
    # ``_PROFIT_FAILURE_LOG_COOLDOWN_SECONDS`` while the signature is
    # unchanged. When the price slides far enough to change the signature
    # (anchor repricing moves limit_price), the new signature emits its
    # own line so we still see the situation evolving. The suppressed-count
    # is included in the next emitted record so nothing is silently dropped.

    _PROFIT_FAILURE_LOG_COOLDOWN_SECONDS = 60.0

    def _should_emit_profitability_failure(
        self,
        stealth_order_id: str,
        order: Dict[str, Any],
        reveal_plan: 'RevealExecutionPlan',
    ) -> bool:
        """Return True iff the WARN log line should be emitted now.

        Signature is built from the inputs that drive the validation
        outcome. Anything that would change the math (price, target,
        target type) bumps the signature and re-emits.

        Side-effect on suppression: increments a counter on the order dict
        so the next emitted log can report how many silent retries
        occurred. State lives on the in-memory order dict (transient,
        not persisted) — exactly the right scope.
        """
        signature = (
            round(safe_float(reveal_plan.submitted_limit_price, default=0.0), 2),
            round(safe_float(reveal_plan.target_movement, default=0.0), 8),
            str(reveal_plan.target_movement_type or ""),
        )
        now = time.monotonic()
        last_signature = order.get("_profit_failure_signature")
        last_log_at = order.get("_profit_failure_last_log_at", 0.0)

        if (last_signature == signature
                and (now - last_log_at) < self._PROFIT_FAILURE_LOG_COOLDOWN_SECONDS):
            order["_profit_failure_suppressed_since_last_log"] = (
                order.get("_profit_failure_suppressed_since_last_log", 0) + 1
            )
            return False

        order["_profit_failure_signature"] = signature
        order["_profit_failure_last_log_at"] = now
        # Reset on emit; next suppression starts fresh from zero.
        order["_profit_failure_suppressed_since_last_log"] = 0
        return True

    def _compute_min_viable_target_movement(
        self,
        *,
        parent_filled_price: float,
        order_size: float,
        target_movement_type: Optional[str],
        total_fees: float,
        product_id: str,
    ) -> Optional[float]:
        """Estimate the minimum ``target_movement`` value (in the
        configured units) that would clear the current total-fee load.

        This is an APPROXIMATION using the current total_fees figure
        (which depends on the proposed follow-up price); for the
        diagnostic message it's accurate enough to point the operator at
        the right order of magnitude. Returns ``None`` when the math
        can't be computed (missing inputs, unknown product context).

        For FUTURE products the mandatory $0.15/contract fee scales with
        contract count, so a percentage target that's viable at 1
        contract can be infeasible at 10. This helper makes that
        relationship visible in the failed-validation log.
        """
        if parent_filled_price <= 0 or order_size <= 0 or total_fees <= 0:
            return None

        # Resolve effective_size (units) from contracts when the product
        # has a contract_size. Use the validator's orderbook so we don't
        # duplicate the resolution logic.
        effective_size = order_size
        try:
            if (self.profit_validator is not None
                    and getattr(self.profit_validator, "orderbook", None) is not None
                    and product_id):
                ctx = self.profit_validator._resolve_product_context(product_id)
                contract_size = ctx.get("contract_size")
                if (ctx.get("product_type") == "FUTURE"
                        and contract_size and contract_size > 0):
                    effective_size = order_size * float(contract_size)
        except Exception:
            # Diagnostic helper: never let a context-resolution failure
            # break the log emission path. Fall back to raw order_size.
            pass

        type_label = str(target_movement_type or "P").upper()
        if type_label == "A":
            # Absolute price-points: gross_profit = move * effective_size
            # Need: move * effective_size > total_fees
            return total_fees / effective_size
        # Default: percentage of parent_filled_price
        # Need: move_pct * parent_filled_price * effective_size > total_fees
        denom = parent_filled_price * effective_size
        if denom <= 0:
            return None
        return total_fees / denom

    def _check_target_movement_feasibility(
        self,
        *,
        product_id: str,
        side: str,
        limit_price: float,
        order_size: float,
        target_movement: float,
        target_movement_type: Optional[str],
        reveal_pricing_policy: Optional[str] = None,
    ) -> Optional[str]:
        """Pre-flight: return a reason string if the configured target is
        provably below the round-trip fee floor at the configured price,
        else ``None``.

        Uses the same validator math the reveal path uses
        (``validate_order_profitability``), so a target that passes here
        can still fail at reveal if market drift moves the price
        materially. To absorb that drift the check uses a soft floor of
        ``95%`` of the strict min-viable: only reject when the target
        would be infeasible even after a generous price-drift cushion.

        ``reveal_pricing_policy`` controls which fee tier is charged in
        the math: maker rate when the policy implies ``post_only=True``
        (TOP_OF_BOOK / MIDPOINT), taker rate otherwise (CONFIGURED_LIMIT).
        Mirrors the resolution applied at reveal time so the two checks
        agree.

        Returns ``None`` (= feasible) on any computation failure so a
        diagnostic helper never blocks legitimate orders.
        """
        if self.profit_validator is None:
            return None
        if not hasattr(self.profit_validator, "derive_follow_up_price_from_target"):
            return None
        if not hasattr(self.profit_validator, "validate_order_profitability"):
            return None

        # Resolve post_only intent from the policy via the canonical helper.
        # Unknown / missing policy → CONFIGURED_LIMIT (taker), the
        # conservative assumption.
        will_be_post_only = self._resolve_post_only_from_policy(
            reveal_pricing_policy=reveal_pricing_policy,
        )

        try:
            try:
                parent_side = OrderSide(str(side or "").upper()).value
            except ValueError:
                return None

            follow_up_price = self.profit_validator.derive_follow_up_price_from_target(
                parent_filled_price=limit_price,
                parent_side=parent_side,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
            )
            if not follow_up_price or follow_up_price <= 0:
                return None

            validation = self.profit_validator.validate_order_profitability(
                parent_filled_price=limit_price,
                parent_side=parent_side,
                follow_up_price=follow_up_price,
                order_size=order_size,
                min_margin_pct=0.0,
                product_id=product_id,
                post_only=will_be_post_only,
            )
            if bool(validation.get("is_profitable", False)):
                return None

            total_fees = safe_float(validation.get("total_fees"), default=0.0)
            min_viable = self._compute_min_viable_target_movement(
                parent_filled_price=limit_price,
                order_size=order_size,
                target_movement_type=target_movement_type,
                total_fees=total_fees,
                product_id=product_id,
            )
            if min_viable is None or min_viable <= 0:
                return None

            # Soft floor: only reject when the configured target is below
            # 95% of strict min-viable. Above that, accept and let the
            # reveal-time check make the final call (price may have moved
            # in our favour by then).
            soft_floor = min_viable * 0.95
            if target_movement >= soft_floor:
                return None

            type_label = (target_movement_type or "P").upper()
            if type_label == "P":
                return (
                    f"configured target_movement={target_movement:.6f} (P), "
                    f"minimum viable ~= {min_viable:.6f} (P) at limit_price={limit_price}. "
                    f"Round-trip fees ({total_fees:.4f}) exceed projected gross profit. "
                    f"Either raise target_movement or reduce order size to lower the "
                    f"per-contract mandatory-fee burden."
                )
            return (
                f"configured target_movement={target_movement:.4f} (A), "
                f"minimum viable ~= {min_viable:.4f} (A) at limit_price={limit_price}. "
                f"Round-trip fees ({total_fees:.4f}) exceed projected gross profit."
            )
        except Exception as exc:
            self.logger.debug(
                f"Pre-flight feasibility check skipped due to error: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    def _validate_reveal_profitability(
        self,
        stealth_order_id: str,
        reveal_execution_plan: 'RevealExecutionPlan',
    ) -> Tuple[bool, Optional[str]]:
        """Validate profitability at reveal time using updated market data.

        Checks if the order will still be profitable after fees using the
        submitted_limit_price from the reveal plan and current market conditions.
        
        Raises:
            RevealPricingError: If profitability validation fails (fallback_used=True)
        
        Returns:
            (is_profitable, failure_reason) - failure_reason is None if profitable
        """
        if not self.profit_validator:
            # No validator configured, assume profitable
            return True, None
        
        order = self._get_stealth_order(stealth_order_id)
        if not order:
            raise RevealPricingError(
                "Stealth order not found during profitability validation",
                stealth_order_id=stealth_order_id,
                fallback_used=False
            )
        
        try:
            parent_side_raw = str(order.get("side") or "").upper()
            try:
                parent_side = OrderSide(parent_side_raw)
            except ValueError:
                self.logger.warning(
                    "Skipping reveal profitability validation due to invalid side "
                    f"for {stealth_order_id}: side={parent_side_raw}"
                )
                return True, None

            order_size = safe_float(order.get("total_size"), default=0.0)
            parent_filled_price = safe_float(reveal_execution_plan.submitted_limit_price, default=0.0)
            # Use target resolved by the plan (canonical: order_parent row).
            target_movement = safe_float(reveal_execution_plan.target_movement, default=0.0)
            target_movement_type = reveal_execution_plan.target_movement_type

            if target_movement <= 0:
                # No explicit target configured, do not block reveal.
                self.logger.info(
                    "Skipping reveal profitability validation: no target_movement "
                    f"available for {stealth_order_id} "
                    f"(source={reveal_execution_plan.target_movement_source})"
                )
                return True, None

            if order_size <= 0 or parent_filled_price <= 0:
                # Invalid input should not block reveal; fail open and log for diagnosis.
                self.logger.warning(
                    "Skipping reveal profitability validation due to invalid input "
                    f"for {stealth_order_id}: side={parent_side.value}, size={order_size}, price={parent_filled_price}"
                )
                return True, None

            if not hasattr(self.profit_validator, "derive_follow_up_price_from_target"):
                self.logger.warning(
                    "Profit validator missing derive_follow_up_price_from_target; "
                    f"skipping reveal profitability validation for {stealth_order_id}"
                )
                return True, None

            follow_up_price = self.profit_validator.derive_follow_up_price_from_target(
                parent_filled_price=parent_filled_price,
                parent_side=parent_side.value,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
            )
            if follow_up_price is None or follow_up_price <= 0:
                self.logger.warning(
                    "Skipping reveal profitability validation due to invalid derived follow-up price "
                    f"for {stealth_order_id}: side={parent_side.value}, price={parent_filled_price}, "
                    f"movement={target_movement}, movement_type={target_movement_type}"
                )
                return True, None

            # Validator auto-resolves product_type, contract_size, and position_side
            # from product_id via its injected orderbook (single source of truth).
            product_id = order.get("product_id", "")

            # Honour the plan's post_only intent so the fee tier matches
            # what the exchange will actually charge if the placement
            # succeeds. A TOP_OF_BOOK reveal that rests as a maker is
            # cheaper than the configured-limit (taker) case.
            will_be_post_only = bool(getattr(reveal_execution_plan, "post_only", False))

            validation = self.profit_validator.validate_order_profitability(
                parent_filled_price=parent_filled_price,
                parent_side=parent_side.value,
                follow_up_price=follow_up_price,
                order_size=order_size,
                min_margin_pct=0.0,
                product_id=product_id,
                post_only=will_be_post_only,
            )

            is_profitable = bool(validation.get("is_profitable", False))
            
            if not is_profitable:
                net_profit = safe_float(validation.get("net_profit"), default=0.0)
                gross_profit = safe_float(validation.get("gross_profit"), default=0.0)
                total_fees = safe_float(validation.get("total_fees"), default=0.0)
                percentage_fees = safe_float(validation.get("percentage_fees"), default=0.0)
                mandatory_fees = safe_float(validation.get("mandatory_fees"), default=0.0)

                # Build an actionable diagnostic so the operator sees WHY
                # the target is unreachable, not just THAT it is. The
                # mandatory FUTURE fee scales with contract count, not
                # notional, so a percentage target that worked at 1
                # contract can be structurally infeasible at 10.
                min_viable = self._compute_min_viable_target_movement(
                    parent_filled_price=parent_filled_price,
                    order_size=order_size,
                    target_movement_type=target_movement_type,
                    total_fees=total_fees,
                    product_id=product_id,
                )
                diag = (
                    f"gross={gross_profit:.4f} fees={total_fees:.4f} "
                    f"(pct={percentage_fees:.4f} mandatory={mandatory_fees:.4f})"
                )
                if min_viable is not None and target_movement is not None:
                    type_label = (target_movement_type or "P").upper()
                    if type_label == "P":
                        diag += (
                            f"; configured target_movement={target_movement:.6f} (P), "
                            f"minimum viable ~= {min_viable:.6f} (P)"
                        )
                    else:
                        diag += (
                            f"; configured target_movement={target_movement:.4f} (A), "
                            f"minimum viable ~= {min_viable:.4f} (A)"
                        )

                failure_msg = (
                    f"Reveal price {reveal_execution_plan.submitted_limit_price} "
                    f"would not meet profit target "
                    f"(projected net profit: {net_profit:.8f}; {diag})"
                )
                raise RevealPricingError(
                    failure_msg,
                    configured_price=reveal_execution_plan.configured_limit_price,
                    fallback_used=reveal_execution_plan.fallback_used,
                    stealth_order_id=stealth_order_id
                )
            
            return True, None
            
        except RevealPricingError:
            # Re-raise known exceptions
            raise
        except Exception as e:
            # Validation error - log but don't block reveal
            self.logger.warning(
                f"Profitability revalidation failed for {stealth_order_id}: {e}"
            )
            return True, None

    def _dispatch_lifecycle_event(
        self,
        stealth_order_id: str,
        event: StealthLifecycleEvent,
        order_data: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Fire StealthLifecycleEvent hooks via the global StealthLifecycleHookRegistry.

        Builds the standard context dict from ``order_data`` and optional ``extra``
        overrides, then calls the global registry. Exceptions are caught and logged
        so that a misbehaving subscriber never disrupts the evaluation loop.

        Context keys populated:
            product_id, side, product_type (inferred), size, total_size,
            limit_price, reason, parent_order_id, timestamp, placed_order_id,
            failure_reason — all sourced from order_data or extra.

        This method uses a lazy import to avoid circular imports at module load time.

        Args:
            stealth_order_id: UUID of the stealth order.
            event:            The lifecycle event to dispatch.
            order_data:       The stealth order dict from in_memory_orders.
            extra:            Optional overrides / additions (e.g. failure_reason, size).
        """
        try:
            from integration.stealth_lifecycle_hooks import (
                get_global_stealth_lifecycle_hook_registry,
            )
            market_data = self._get_current_market_data(order_data.get("product_id", ""))
            market_bid = market_data.get("bid")
            market_ask = market_data.get("ask")
            market_spread = market_data.get("market_spread")
            if market_spread is None and market_bid is not None and market_ask is not None:
                try:
                    market_spread = float(market_ask) - float(market_bid)
                except (TypeError, ValueError):
                    market_spread = None

            context: Dict[str, Any] = {
                "product_id": order_data.get("product_id", ""),
                "side": order_data.get("side", ""),
                "product_type": "FUTURE" if any(
                    s in order_data.get("product_id", "")
                    for s in ("DEC", "JAN", "FEB", "MAR", "APR")
                ) else "SPOT",
                "size": float(order_data.get("revealed_size", 0.0)),
                "total_size": float(order_data.get("total_size", 0.0)),
                "limit_price": float(order_data.get("limit_price", 0.0)),
                "reason": order_data.get("reason", ""),
                "parent_order_id": order_data.get("parent_order_id"),
                "status": order_data.get("status"),
                "remaining_size": float(order_data.get("remaining_size", 0.0)),
                "executed_size": float(order_data.get("executed_size", 0.0)),
                "reveal_condition_type": order_data.get("reveal_condition_type"),
                "reveal_condition": order_data.get("reveal_condition_json"),
                "condition_first_met_at": order_data.get("condition_first_met_at"),
                "condition_confirmed_at": order_data.get("condition_confirmed_at"),
                "revealed_count": len(order_data.get("revealed_orders", [])),
                "market_price": market_data.get("price"),
                "market_bid": market_bid,
                "market_ask": market_ask,
                "market_spread": market_spread,
                "market_volume_1m": market_data.get("volume_1m"),
                "market_source": market_data.get("source"),
                "timestamp": datetime.utcnow(),
                "placed_order_id": None,
                "exchange_order_id": None,
                "failure_reason": None,
            }
            if extra:
                context.update(extra)

            get_global_stealth_lifecycle_hook_registry().call_on_transition(
                stealth_order_id=stealth_order_id,
                event=event,
                context=context,
            )
        except Exception as exc:
            # Never let lifecycle hook dispatch crash the caller
            message = (
                f"[StealthOrderManager] _dispatch_lifecycle_event failed "
                f"({event}) for {stealth_order_id}: {exc}"
            )
            if getattr(self, "logger", None) is not None:
                self.logger.warning(message)
            elif getattr(self, "log_callback", None) is not None:
                self.log_callback("warning", message)

    
    def create_stealth_order(
        self,
        product_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        reveal_condition: Dict[str, Any],
        sizing_strategy: Optional[Dict[str, Any]] = None,
        parent_order_id: Optional[str] = None,
        follow_up_reveal_direction: Optional[str] = None,
        reason: str = "normal_placement",
        notes: str = "",
        stealth_order_id: Optional[str] = None,
        max_order_replacements: Optional[int] = None,
        target_movement: float = 0.0,
        target_movement_type: str = "P",
        reveal_pricing_policy: Optional[str] = None,
        allow_partial_fills: bool = False,
        anchor_repricing_policy: Optional[Dict[str, Any]] = None,
        enable_hotpoint_replication: bool = False,
    ) -> str:
        """
        Create an order with automated reveal condition.
        
        ARCHITECTURE: This is the ONLY way orders are created. All orders start
        in HIDDEN state pending their reveal condition being met.
        
        Args:
            product_id: Product to trade (e.g., 'BTC-USDC')
            side: 'BUY' or 'SELL'
            total_size: Total amount to eventually buy/sell
            limit_price: Limit price for the order
            reveal_condition: Dict specifying when/how order transitions to exchange.
                             Examples:
                             - Immediate: {'type': 'time_delay', 'delay_seconds': 0}
                             - Time-based: {'type': 'time_delay', 'delay_seconds': 300}
                             - Price-based: {'type': 'price', 'price_threshold': 41000,
                                           'direction': 'below', 'hold_duration_seconds': 10}
            sizing_strategy: Dict specifying adaptive reveal sizing (default: fixed)
                            Example: {'type': 'volume_proportional', 'min_reveal': 0.1}
            parent_order_id: Client order ID if this is a child/follow-up order
            follow_up_reveal_direction: Direction for follow-up reveals (FollowUpRevealDirection.SAME or OPPOSITE).
                                       Accepts enum or string value. Defaults to OPPOSITE.
            reason: Reason for order (e.g., 'normal_placement', 'follow_up_replacement')
            notes: Additional notes for tracking
            stealth_order_id: Optional UUID provided by caller (UI or engine). 
                             If not provided, a new UUID is generated.
                             Used to enable deterministic order IDs from UI.
            max_order_replacements: Maximum number of follow-up orders allowed (default: from config)
            target_movement: Target profit/movement percentage (default: 0.0)
            target_movement_type: Type of target ('P' for percentage, 'A' for absolute, default 'P')
            reveal_pricing_policy: Per-order reveal pricing policy (configured_limit, top_of_book, midpoint).
                                  If None, defaults to configured_limit.
            
        Returns:
            order_id (UUID string) - Used as client_order_id for all internal tracking
            
        Example:
            >>> # Immediate reveal (traditional order)
            >>> order_id = manager.create_stealth_order(
            ...     product_id="BTC-USDC",
            ...     side="BUY",
            ...     total_size=5.0,
            ...     limit_price=41000.00,
            ...     reveal_condition={'type': 'time_delay', 'delay_seconds': 0}
            ... )
            
            >>> # Price-triggered reveal (stealth execution)
            >>> order_id = manager.create_stealth_order(
            ...     product_id="BTC-USDC",
            ...     side="BUY",
            ...     total_size=5.0,
            ...     limit_price=41000.00,
            ...     reveal_condition={
            ...         "type": "price",
            ...         "price_threshold": 41000.00,
            ...         "direction": "below",
            ...         "hold_duration_seconds": 2,
            ...     },
            ...     follow_up_reveal_direction="opposite"
            ... )
            
            >>> # UI-provided UUID (for deterministic order tracking)
            >>> order_id = manager.create_stealth_order(
            ...     product_id="BTC-USDC",
            ...     side="BUY",
            ...     total_size=5.0,
            ...     limit_price=41000.00,
            ...     reveal_condition={'type': 'time_delay', 'delay_seconds': 60},
            ...     stealth_order_id="550e8400-e29b-41d4-a716-446655440000"
            ... )
        """
        # ⚠️ CRITICAL: Use provided stealth_order_id or generate a new one
        # This ensures deterministic IDs when UI provides them, and proper generation for follow-ups
        if not stealth_order_id:
            stealth_order_id = str(uuid.uuid4())

        from core.exceptions import OrderCreationError

        price_check = normalize_price_for_product(
            limit_price,
            product_id=product_id,
            side=side,
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if not price_check.ok or price_check.effective_price is None:
            raise OrderCreationError(
                f"Stealth order rejected at price boundary: {price_check.reason}"
            )
        requested_limit_price = limit_price
        limit_price = float(price_check.effective_price)
        if price_check.adjusted:
            self.log_callback(
                "info",
                {
                    "event": "stealth_order_limit_price_normalized",
                    "stealth_order_id": stealth_order_id,
                    "product_id": product_id,
                    "side": str(side),
                    "requested_limit_price": requested_limit_price,
                    "effective_limit_price": limit_price,
                    "price_increment": price_check.increment,
                    "rounding_policy": price_check.policy.value,
                    "rounding_direction": price_check.rounding_direction.value,
                },
            )

        # Boundary validation: snap size to base_increment AND verify
        # base_min_size / quote_min_size before any DB write or in-memory
        # registration. Mirrors the price-quantize pattern used at reveal
        # time (_quantize_reprice_price) but for the size axis. Rejecting
        # here means an invalid size NEVER reaches the exchange and never
        # poisons the in-memory order map.
        from calculation.size_validation import validate_and_quantize_size
        size_check = validate_and_quantize_size(
            total_size,
            product_id=product_id,
            price=limit_price,
        )
        if not size_check.ok:
            raise OrderCreationError(
                f"Stealth order rejected at boundary: {size_check.reason}"
            )
        total_size = size_check.size

        # Pre-flight profitability check (root orders only). Catches the
        # "target_movement below fee floor" misconfiguration at submission
        # rather than 30 minutes later when the reveal condition triggers
        # and produces an unfillable order. Children inherit the parent's
        # economics and don't carry their own target, so skip them.
        if parent_order_id is None and target_movement and target_movement > 0:
            infeasible_reason = self._check_target_movement_feasibility(
                product_id=product_id,
                side=side,
                limit_price=float(limit_price),
                order_size=float(total_size),
                target_movement=float(target_movement),
                target_movement_type=target_movement_type,
                reveal_pricing_policy=reveal_pricing_policy,
            )
            if infeasible_reason is not None:
                raise OrderCreationError(
                    f"Stealth order rejected: configured target_movement is below "
                    f"the round-trip fee floor at the configured limit price. "
                    f"{infeasible_reason}"
                )

        normalized_anchor_repricing_policy = self._normalize_anchor_repricing_policy(anchor_repricing_policy)

        order_data = {
            "stealth_order_id": stealth_order_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "product_id": product_id,
            "side": side,
            "total_size": float(total_size),
            "limit_price": float(limit_price),
            "revealed_size": 0.0,
            "remaining_size": float(total_size),
            "status": StealthOrderStatus.HIDDEN.value,
            "visibility_score": 0.0,
            "reveal_condition_type": reveal_condition.get("type", "time_delay"),
            "reveal_condition_json": reveal_condition,
            "reveal_pricing_policy": reveal_pricing_policy or "configured_limit",
            "follow_up_reveal_direction": follow_up_reveal_direction or FollowUpRevealDirection.OPPOSITE.value,
            "sizing_strategy_json": sizing_strategy or {"type": "fixed"},
            "parent_order_id": parent_order_id,
            "reason": reason,
            "notes": notes,
            "revealed_orders": [],
            "executed_size": 0.0,
            "condition_first_met_at": None,
            "condition_confirmed_at": None,
            "allow_partial_fills": allow_partial_fills,
            "anchor_repricing_policy_json": normalized_anchor_repricing_policy,
            "anchor_repricing_state_json": self._normalize_anchor_repricing_state(None),
        }
        
        # UNIFIED TRACKING: Insert into order_parent table (for both parent and child orders)
        # This ensures stealth orders are tracked in the same parent-child hierarchy as regular orders
        effective_max_replacements = (
            0
            if parent_order_id
            else (
                max_order_replacements
                if max_order_replacements is not None
                else DEFAULT_MAX_ORDER_REPLACEMENT
            )
        )
        parent_insert_args = {
            "client_order_id": stealth_order_id,
            "product_id": product_id,
            "side": side,
            "size": total_size,
            "price": limit_price,
            "target_movement": target_movement,
            "target_movement_type": target_movement_type,
            "max_order_replacement": effective_max_replacements,
            "current_order_replacement": 0,
            "status": StealthOrderStatus.PENDING.value,
            "parent_order_id": parent_order_id,
            "allow_partial_fills": (
                False if parent_order_id else allow_partial_fills
            ),
            "enable_hotpoint_replication": (
                False if parent_order_id else enable_hotpoint_replication
            ),
            "reject_existing": True,
        }
        with self._creation_lock:
            if stealth_order_id in self.in_memory_orders:
                raise OrderCreationError(
                    "Stealth order client_order_id already exists in memory",
                    client_order_id=stealth_order_id,
                )

            # Persist a fail-closed row first. If this process stops between
            # creation writes, hydration sees ERROR and cannot submit it.
            order_data["status"] = StealthOrderStatus.ERROR.value
            order_data["failure_reason"] = "creation persistence incomplete"
            try:
                stealth_saved = self._save_stealth_order_to_db(order_data)
            except Exception as stealth_save_error:
                stealth_saved = False
                save_failure_reason = str(stealth_save_error)
            else:
                save_failure_reason = "database write did not complete"
            if not stealth_saved:
                raise OrderCreationError(
                    f"Stealth order persistence failed: {save_failure_reason}",
                    client_order_id=stealth_order_id,
                )

            try:
                parent_db_id = insert_order_parent(**parent_insert_args)
            except Exception as parent_error:
                order_data["failure_reason"] = (
                    f"parent persistence failed: {parent_error}"
                )[:512]
                self._update_stealth_order(order_data)
                raise OrderCreationError(
                    f"Stealth order parent persistence failed: {parent_error}",
                    client_order_id=stealth_order_id,
                ) from parent_error
            if parent_db_id is None:
                order_data["failure_reason"] = (
                    "parent persistence returned no row id"
                )
                self._update_stealth_order(order_data)
                raise OrderCreationError(
                    "Stealth order parent persistence returned no row id",
                    client_order_id=stealth_order_id,
                )

            order_data["status"] = StealthOrderStatus.HIDDEN.value
            order_data["failure_reason"] = None
            if not self._update_stealth_order(order_data):
                # This parent was proven newly inserted by reject_existing.
                self._mark_placement_parent_failed(
                    stealth_order_id=stealth_order_id,
                    placement_client_order_id=stealth_order_id,
                )
                raise OrderCreationError(
                    "Stealth order activation persistence failed",
                    client_order_id=stealth_order_id,
                )

            # The order becomes locally active only after both durable rows
            # exist and the fail-closed database state has been activated.
            self.in_memory_orders[stealth_order_id] = order_data

        reveal_type = reveal_condition.get("type", "time_delay")
        reveal_delay = (
            reveal_condition.get("delay_seconds", 0)
            if reveal_type == "time_delay"
            else "N/A"
        )
        self.log_callback(
            "info",
            f"[LOT-TRACK] Stealth order created: {stealth_order_id} "
            f"({side} {total_size} {product_id} @ {limit_price}, "
            f"reveal_type={reveal_type}, delay={reveal_delay}s)",
        )
        self._dispatch_lifecycle_event(
            stealth_order_id=stealth_order_id,
            event=StealthLifecycleEvent.CREATED,
            order_data=order_data,
        )

        return stealth_order_id
    
    def evaluate_conditions(self, stealth_order_id: str) -> Tuple[bool, Optional[str]]:
        """
        Evaluate if reveal condition is met for a stealth order.
        
        Args:
            stealth_order_id: ID of stealth order to evaluate
            
        Returns:
            Tuple of (condition_met: bool, reason: Optional[str])
        """
        order = self._get_stealth_order(stealth_order_id)
        if not order:
            return False, "Stealth order not found"
        
        # Get current market data (would come from OrderEngine's market data)
        market_data = self._get_current_market_data(order["product_id"])
        market_source = market_data.get("source", "unknown")
        if market_source != "ticker":
            return False, f"Waiting for live ticker market data (source={market_source})"
        
        # Get evaluator for this condition type
        condition_type = order.get("reveal_condition_type", "time_delay")
        condition_config = order.get("reveal_condition_json", {})
        
        evaluator = get_evaluator(condition_type)
        condition_met, reason = evaluator.evaluate(market_data, condition_config, order)
        
        # Update condition tracking
        if condition_met and not order.get("condition_confirmed_at"):
            order["condition_confirmed_at"] = datetime.utcnow()
            order["status"] = StealthOrderStatus.TRIGGERED.value
            self._update_stealth_order(order)
            # 📊 LOT-TRACKING: Log condition met
            market_price = market_data.get("price", "unknown") if market_data else "unknown"
            self.log_callback("info", f"[LOT-TRACK] Stealth order condition met: {order['stealth_order_id']} ({order['side']} {order['total_size']} {order['product_id']} @ {order['limit_price']}, market_price={market_price})")
            # 🔔 LIFECYCLE HOOK: CONDITION_MET
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.CONDITION_MET,
                order_data=order,
            )
        elif not condition_met and order.get("condition_first_met_at") is None:
            # First time condition partially met
            if reason and ("watching" in reason or "waiting" in reason):
                order["condition_first_met_at"] = datetime.utcnow()
                order["status"] = StealthOrderStatus.PENDING.value
                self._update_stealth_order(order)
                # 🔔 LIFECYCLE HOOK: CONDITION_WATCHING
                self._dispatch_lifecycle_event(
                    stealth_order_id=stealth_order_id,
                    event=StealthLifecycleEvent.CONDITION_WATCHING,
                    order_data=order,
                )
        
        return condition_met, reason
    
    def should_trigger_reveal(self, stealth_order_id: str) -> Tuple[bool, Optional[str]]:
        """
        Determine if order should be revealed now.
        
        Combines condition evaluation with status checks.
        
        Snapshot-commit semantics: once the reveal condition has fired
        (status == TRIGGERED), the bridge commits to placing on the next
        admitting tick WITHOUT re-evaluating the live condition. The
        ``hold_duration_seconds`` gate already exists to filter ticker
        noise; re-running the evaluator after that gate has passed
        defeats its purpose and silently strands orders when the
        triggering tick ages out (incident 2026-05-03 stealth
        4b6d2185: SELL @ 78190, ticker briefly touched 78195, status
        flipped TRIGGERED, then last-trade fell back below threshold
        and every subsequent re-evaluation returned False with no log
        and no placement).
        
        Returns:
            Tuple of (should_reveal: bool, reason: Optional[str])
        """
        order = self._get_stealth_order(stealth_order_id)
        
        if not order:
            return False, "Order not found"

        placeable_statuses = {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
        }
        if (
            order.get("_price_validation_pending")
            or order.get("status") in placeable_statuses
        ):
            if not self._validate_local_price_read_only(order):
                return False, order.get(
                    "price_validation_error",
                    "Stored price validation is pending runtime metadata",
                )
        
        terminal_statuses = {
            StealthOrderStatus.ERROR.value,
            StealthOrderStatus.EXECUTED.value,
            StealthOrderStatus.CANCELLED.value,
        }
        if order["status"] in terminal_statuses:
            return False, f"Order already {order['status']}"
        
        if order["remaining_size"] <= 0:
            return False, "All size already revealed"
        
        # Snapshot commit: TRIGGERED means the condition gate (including
        # any hold_duration) already passed. Place on the next tick.
        # REVEALED is set only when remaining_size <= 0 (handled above);
        # a TRIGGERED order with remaining_size > 0 is awaiting placement
        # of either the first slice or a follow-up slice.
        if order["status"] == StealthOrderStatus.TRIGGERED.value:
            return True, "Reveal condition previously committed (snapshot semantics)"
        
        condition_met, reason = self.evaluate_conditions(stealth_order_id)
        return condition_met, reason
    
    def reveal_order_slice(self, stealth_order_id: str) -> Optional[str]:
        """Reveal next slice of hidden order based on adaptive sizing.
        
        Integrates reveal execution planning:
        - Builds reveal execution plan based on pricing policy
        - Validates profitability at reveal time (if validator configured)
        - Uses plan's submitted price for order placement
        - Records plan details in reveal event audit trail
        
        Returns:
            client_order_id if slice was placed, None otherwise
            
        Raises:
            RevealPricingError: If profitability validation fails
            RevealOrderSliceError: If order slice operation fails
        """
        try:
            order = self._get_stealth_order(stealth_order_id)
            
            if not order:
                raise RevealOrderSliceError(
                    f"Stealth order not found: {stealth_order_id}"
                )
            
            # Calculate slice size (delegates to RevealStrategy in
            # business/stealth_reveal_strategy.py).
            slice_size = self._calculate_reveal_size(order)

            if slice_size <= 0:
                # Throttled diagnostic so a tranche-iceberg lock or a
                # fully-covered fixed strategy doesn't silently no-op
                # at the bridge poll rate. Pattern parallels the
                # 2026-05-03 stranded-order incident: silent loops
                # at high frequency are unobservable.
                self._maybe_log_no_slice(stealth_order_id, order)
                return None
            
            # === PHASE 1: Build reveal execution plan ===
            # Determines what price to use for reveal based on policy and market conditions
            reveal_plan = self.build_reveal_execution_plan(stealth_order_id)
            if not reveal_plan:
                raise RevealOrderSliceError(
                    "Failed to build reveal execution plan",
                )
            
            # === PHASE 2: Validate profitability at reveal time ===
            # Checks if order will still meet profit target using reveal plan's price
            if self.profit_validator:
                try:
                    is_profitable, profit_reason = self._validate_reveal_profitability(
                        stealth_order_id=stealth_order_id,
                        reveal_execution_plan=reveal_plan,
                    )
                    if not is_profitable:
                        # Order would not be profitable with reveal price - block it
                        self.log_callback("warning", {
                            "event": "stealth_order_reveal_blocked_by_profitability",
                            "stealth_order_id": stealth_order_id,
                            "reason": profit_reason,
                            "reveal_price": reveal_plan.submitted_limit_price,
                            "configured_price": reveal_plan.configured_limit_price,
                        })
                        return None
                except RevealPricingError as e:
                    # Profitability validation raised. The stealth bridge
                    # retries reveal at ~10 Hz; without throttling, an
                    # economically-stuck stealth order produces hundreds of
                    # identical WARN lines per second. Suppress repeats of
                    # the same failure signature within a cooldown window.
                    if not self._should_emit_profitability_failure(
                            stealth_order_id, order, reveal_plan):
                        return None
                    suppressed_repeats = order.pop(
                        "_profit_failure_suppressed_since_last_log", 0
                    )
                    self.log_callback("warning", {
                        "event": "stealth_order_profitability_validation_failed",
                        "stealth_order_id": stealth_order_id,
                        "reason": str(e),
                        "fallback_used": e.fallback_used,
                        "suppressed_repeats": suppressed_repeats,
                        "reveal_pricing_policy": getattr(
                            reveal_plan, "reveal_pricing_policy", None
                        ),
                        "post_only": bool(getattr(reveal_plan, "post_only", False)),
                    })
                    # Surface to the dashboard via the lifecycle stream.
                    # PLACEMENT_BLOCKED is the right semantic: we made a
                    # pre-submission decision to NOT place because the
                    # economics don't clear the fee floor. Subscribers
                    # (dashboard, alerting) can render this prominently
                    # rather than relying on operators tailing logs.
                    self._dispatch_lifecycle_event(
                        stealth_order_id=stealth_order_id,
                        event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                        order_data=order,
                        extra={
                            "failure_reason": str(e),
                            "block_category": "unprofitable_at_reveal",
                            "fallback_used": e.fallback_used,
                            "suppressed_repeats": suppressed_repeats,
                            "reveal_price": reveal_plan.submitted_limit_price,
                            "configured_price": reveal_plan.configured_limit_price,
                        },
                    )
                    return None
        except RevealOrderSliceError as e:
            # Order not found or slice failed
            self.log_callback("error", {
                "event": "stealth_order_slice_error",
                "stealth_order_id": stealth_order_id,
                "error": str(e),
            })
            raise
        except RevealPricingError as e:
            # Pricing-related error
            self.log_callback("error", {
                "event": "stealth_order_reveal_pricing_error",
                "stealth_order_id": stealth_order_id,
                "error": str(e),
                "fallback_used": e.fallback_used,
            })
            raise
        
        # Place the revealed slice directly on the exchange. A REST return is
        # not acceptance: every attempt is classified fail-closed before any
        # success bookkeeping is allowed to run.
        from configuration import REST_CLIENT

        market_data = self._get_current_market_data(order["product_id"]) or {}
        market_bid = reveal_plan.market_bid or market_data.get("bid")
        market_ask = reveal_plan.market_ask or market_data.get("ask")
        market_spread = None
        if market_bid is not None and market_ask is not None:
            try:
                market_spread = float(market_ask) - float(market_bid)
            except (TypeError, ValueError):
                market_spread = None
        placement_market_data = dict(market_data)
        placement_market_data["bid"] = market_bid
        placement_market_data["ask"] = market_ask

        # Preserve the extension contract: pre-submission hooks receive the
        # ordinary placement identity and may still change ``post_only``.
        # Identity is pinned again after hooks before any local/REST write.
        retry_post_only = bool(getattr(reveal_plan, "post_only", False))
        client_order_id = self._placement_client_order_id_for_order(order)
        order_for_submission = {
            "product_id": order["product_id"],
            "side": order["side"],
            "limit_price": reveal_plan.submitted_limit_price,
            "base_size": slice_size,
            "client_order_id": client_order_id,
            "post_only": retry_post_only,
            "stealth_order_id": stealth_order_id,
            "parent_order_id": order.get("parent_order_id"),
            "reason": order.get("reason"),
            "reveal_number": len(order.get("revealed_orders", [])) + 1,
            "reveal_condition_type": order.get("reveal_condition_type"),
            "reveal_condition_json": order.get("reveal_condition_json"),
            "condition_confirmed_at": (
                order.get("condition_confirmed_at").isoformat()
                if hasattr(order.get("condition_confirmed_at"), "isoformat")
                else order.get("condition_confirmed_at")
            ),
            "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
            "reveal_price_source": reveal_plan.reveal_price_source,
        }

        try:
            self.order_placement_hooks.call_pre_submission_hooks(order_for_submission)
        except Exception as hook_error:
            placed_order_id = str(uuid.uuid4())
            placement_error = f"Pre-submission hook blocked: {hook_error}"
            self.log_callback("warning", {
                "event": "stealth_order_submission_blocked_by_hook",
                "stealth_order_id": stealth_order_id,
                "size": slice_size,
                "product_id": order["product_id"],
                "block_reason": placement_error,
            })
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                order_data=order,
                extra={"failure_reason": placement_error, "size": slice_size},
            )
            reveal_event = {
                "reveal_number": len(order["revealed_orders"]) + 1,
                "revealed_size": 0,
                "placed_order_id": placed_order_id,
                "placement_client_order_id": placed_order_id,
                "placement_success": False,
                "placement_error": placement_error,
                "reveal_time": datetime.utcnow(),
                "market_price": market_data.get("price"),
                "market_bid": market_bid,
                "market_ask": market_ask,
                "market_spread": market_spread,
                "market_volume_1m": market_data.get("volume_1m"),
                "market_source": market_data.get("source"),
                "configured_limit_price": reveal_plan.configured_limit_price,
                "submitted_limit_price": reveal_plan.submitted_limit_price,
                "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
                "reveal_price_source": reveal_plan.reveal_price_source,
                "reveal_price_fallback_used": reveal_plan.fallback_used,
            }
            order["revealed_orders"].append(reveal_event)
            order["updated_at"] = datetime.utcnow()
            self._update_stealth_order(order)
            self._record_reveal_event(order, reveal_event)
            return None

        # Hooks may enrich pricing flags, but identity/routing fields are
        # internal invariants and cannot be rewritten by extensions.
        order_for_submission["product_id"] = order["product_id"]
        order_for_submission["side"] = order["side"]
        order_for_submission["client_order_id"] = client_order_id
        order_for_submission["stealth_order_id"] = stealth_order_id

        retry_post_only = bool(order_for_submission.get("post_only"))
        order_for_submission["post_only"] = retry_post_only
        # A retryable POST_ONLY ladder needs a distinct child row for every
        # attempt, including the first. Reusing the stealth root id would make
        # the first rejection terminalize the logical root and leave a later
        # accepted retry without its own flat-hierarchy row.
        if retry_post_only and client_order_id == stealth_order_id:
            client_order_id = str(uuid.uuid4())
            order_for_submission["client_order_id"] = client_order_id

        # Hooks may modify the price. Re-normalize after every hook and before
        # either the parent-row write or REST submission.
        price_check = normalize_price_for_product(
            order_for_submission.get("limit_price"),
            product_id=order_for_submission["product_id"],
            side=order_for_submission["side"],
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if not price_check.ok or price_check.effective_price is None:
            failure_reason = (
                f"submission price failed product boundary validation: "
                f"{price_check.reason}"
            )
            # No REST request was attempted, so this is a retriable local
            # placement block—not an indeterminate exchange outcome.
            self.log_callback("warning", {
                "event": "stealth_order_slice_price_blocked",
                "stealth_order_id": stealth_order_id,
                "client_order_id": client_order_id,
                "failure_reason": failure_reason,
            })
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                order_data=order,
                extra={
                    "failure_reason": failure_reason,
                    "block_category": "invalid_submission_price",
                    "size": slice_size,
                    "requested_submission_price": order_for_submission.get(
                        "limit_price"
                    ),
                },
            )
            return None

        order_for_submission["limit_price"] = float(price_check.effective_price)
        order_for_submission["client_order_id"] = client_order_id

        placement_parent_errors: Dict[str, Exception] = {}
        root_parent_for_placement = (
            resolve_stealth_chain_root(order)
            if client_order_id != stealth_order_id
            else None
        )
        try:
            inherited_tm, inherited_tm_type, _src = \
                self._resolve_target_movement_for_plan(stealth_order_id, order)
        except Exception:
            inherited_tm, inherited_tm_type = None, None

        def _pre_insert_placement_row(coid: str, price: float) -> bool:
            if coid == stealth_order_id or root_parent_for_placement is None:
                if update_order_parent_price(coid, price):
                    return True
                parent_update_error = RuntimeError(
                    "order_parent price update did not complete"
                )
                placement_parent_errors[coid] = parent_update_error
                self.log_callback("warning", {
                    "event": "reveal_placement_order_parent_price_update_failed",
                    "stealth_order_id": stealth_order_id,
                    "placement_client_order_id": coid,
                    "error": str(parent_update_error),
                })
                return False
            try:
                placement_parent_id = insert_order_parent(
                    client_order_id=coid,
                    product_id=order["product_id"],
                    side=order["side"],
                    size=slice_size,
                    price=price,
                    target_movement=inherited_tm if inherited_tm is not None else 0.0,
                    target_movement_type=inherited_tm_type or "P",
                    max_order_replacement=int(order.get("max_order_replacements") or 0),
                    current_order_replacement=0,
                    status=OrderStatus.PENDING.value,
                    parent_order_id=root_parent_for_placement,
                    allow_partial_fills=bool(order.get("allow_partial_fills", False)),
                )
                if placement_parent_id is None:
                    parent_insert_error = RuntimeError(
                        "order_parent insert returned no row id"
                    )
                    placement_parent_errors[coid] = parent_insert_error
                    self.log_callback("warning", {
                        "event": "reveal_placement_order_parent_pre_insert_failed",
                        "stealth_order_id": stealth_order_id,
                        "placement_client_order_id": coid,
                        "error": str(parent_insert_error),
                    })
                    return False
                return True
            except Exception as parent_insert_error:
                placement_parent_errors[coid] = parent_insert_error
                self.log_callback("warning", {
                    "event": "reveal_placement_order_parent_pre_insert_failed",
                    "stealth_order_id": stealth_order_id,
                    "placement_client_order_id": coid,
                    "error": str(parent_insert_error),
                })
                return False

        max_attempts = self.POST_ONLY_MAX_ATTEMPTS if retry_post_only else 1
        attempt_price = float(order_for_submission["limit_price"])
        attempt_coid = client_order_id
        price_increment = self._get_price_increment(order_for_submission["product_id"])
        order_result = None
        classification = None
        post_only_attempts: List[Dict[str, Any]] = []
        retry_abort_reason = None

        for attempt_num in range(1, max_attempts + 1):
            _pre_insert_placement_row(attempt_coid, attempt_price)
            try:
                with get_runtime_controller().track_inflight(INFLIGHT_REST_PLACE):
                    order_result = REST_CLIENT.place_limit_order(
                        product_id=order_for_submission["product_id"],
                        side=order_for_submission["side"],
                        limit_price=str(attempt_price),
                        base_size=str(order_for_submission["base_size"]),
                        client_order_id=attempt_coid,
                        post_only=retry_post_only,
                    )
                classification = classify_placement_response(
                    order_result,
                    expected_client_order_id=attempt_coid,
                )
            except Exception as placement_exception:
                classification = classify_placement_response(
                    expected_client_order_id=attempt_coid,
                    exception=placement_exception,
                )

            order_for_submission["limit_price"] = attempt_price
            order_for_submission["client_order_id"] = attempt_coid
            client_order_id = attempt_coid

            if classification.accepted:
                break

            is_retryable_post_only = (
                retry_post_only
                and classification.outcome is OrderPlacementOutcome.REJECTED
                and self._is_post_only_rejection(order_result)
            )
            if not is_retryable_post_only:
                break

            rejected_failure_reason = classification.failure_reason or "POST_ONLY"
            post_only_attempts.append({
                "attempt": attempt_num,
                "rejected_at_price": attempt_price,
                "client_order_id": attempt_coid,
                "failure_reason": rejected_failure_reason,
            })
            self._mark_placement_parent_failed(
                attempt_coid,
                stealth_order_id=stealth_order_id,
            )
            if attempt_num == max_attempts:
                break

            try:
                next_price = self._next_safer_tick(
                    attempt_price,
                    order_for_submission["side"],
                    order_for_submission["product_id"],
                )
            except ValueError as retry_price_error:
                retry_abort_reason = (
                    f"post-only retry price normalization failed: "
                    f"{retry_price_error}"
                )
                break

            next_coid = str(uuid.uuid4())
            self.log_callback("info", {
                "event": "stealth_order_post_only_retry",
                "stealth_order_id": stealth_order_id,
                "product_id": order_for_submission["product_id"],
                "side": order_for_submission["side"],
                "attempt": attempt_num,
                "next_attempt": attempt_num + 1,
                "rejected_at_price": attempt_price,
                "next_attempt_price": next_price,
                "tick_increment": price_increment,
                "rejected_client_order_id": attempt_coid,
                "next_client_order_id": next_coid,
                "failure_reason": rejected_failure_reason,
            })
            attempt_price = next_price
            attempt_coid = next_coid

        if classification is None or not classification.accepted:
            failure_outcome = (
                classification.outcome
                if classification is not None
                else OrderPlacementOutcome.INDETERMINATE
            )
            failure_reason = retry_abort_reason or (
                classification.failure_reason
                if classification is not None
                else "placement attempt produced no classification"
            )
            if post_only_attempts:
                self.log_callback("warning", {
                    "event": "stealth_order_post_only_retries_exhausted",
                    "stealth_order_id": stealth_order_id,
                    "product_id": order_for_submission["product_id"],
                    "side": order_for_submission["side"],
                    "attempts": post_only_attempts,
                    "final_failure_reason": failure_reason,
                    "note": "Post-only intent was preserved; no taker fallback occurred.",
                })
            self._record_terminal_placement_failure(
                order,
                placement_client_order_id=client_order_id,
                exchange_order_id=(
                    classification.exchange_order_id
                    if classification is not None
                    else None
                ),
                submitted_price=attempt_price,
                failure_reason=failure_reason,
                outcome=failure_outcome,
                attempted_size=slice_size,
                market_data=placement_market_data,
                audit_fields={
                    "configured_limit_price": reveal_plan.configured_limit_price,
                    "submitted_limit_price": attempt_price,
                    "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
                    "reveal_price_source": (
                        "post_only_retry"
                        if post_only_attempts
                        else reveal_plan.reveal_price_source
                    ),
                    "reveal_price_fallback_used": reveal_plan.fallback_used,
                    "post_only_retry_attempts": len(post_only_attempts),
                },
            )
            self.log_callback("error", {
                "event": "stealth_order_slice_placement_failed",
                "stealth_order_id": stealth_order_id,
                "client_order_id": client_order_id,
                "placement_outcome": failure_outcome.value,
                "failure_reason": failure_reason,
                "size": slice_size,
                "product_id": order["product_id"],
            })
            return None

        placed_order_id = client_order_id
        exchange_order_id = classification.exchange_order_id
        placement_success = True
        actual_submitted_price = float(order_for_submission["limit_price"])
        post_only_retried = bool(post_only_attempts)

        # Acceptance is already proven. Establish local ownership immediately
        # at the acceptance boundary, before hooks, lifecycle subscribers, or
        # database I/O can block while a websocket OPEN/FILL event arrives.
        index_succeeded = self._index_accepted_placement(
            order,
            placed_order_id,
            source="reveal_acceptance",
        )

        # Record the accepted reveal and consume size only after acceptance,
        # but before any fallible local-finalization callback. This prevents a
        # live accepted order from remaining TRIGGERED and being resubmitted.
        reveal_event = {
            "reveal_number": len(order["revealed_orders"]) + 1,
            "revealed_size": slice_size,
            "placement_price": actual_submitted_price,
            "placed_order_id": placed_order_id,
            "placement_client_order_id": placed_order_id,
            "exchange_order_id": exchange_order_id,
            "placement_success": placement_success,  # ✓ Track if actually placed on exchange
            "placement_status": "placed",
            "placement_error": None,
            "reveal_time": datetime.utcnow(),
            "market_price": market_data.get("price"),
            "market_bid": market_bid,
            "market_ask": market_ask,
            "market_spread": market_spread,
            "market_volume_1m": market_data.get("volume_1m"),
            "market_source": market_data.get("source"),
            # Reveal execution plan audit trail (for post-reveal analysis/profitability recheck)
            "configured_limit_price": reveal_plan.configured_limit_price,
            "submitted_limit_price": actual_submitted_price,
            "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
            "reveal_price_source": (
                "post_only_retry"
                if post_only_retried
                else reveal_plan.reveal_price_source
            ),
            "reveal_price_fallback_used": reveal_plan.fallback_used,
            "post_only_retry_attempts": len(post_only_attempts),
        }
        
        order["revealed_orders"].append(reveal_event)
        order["revealed_size"] += slice_size
        order["remaining_size"] = order["total_size"] - order["revealed_size"]
        order["visibility_score"] = order["revealed_size"] / order["total_size"]
        
        if order["remaining_size"] <= 0:
            order["status"] = StealthOrderStatus.REVEALED.value

        # A previously retriable PLACEMENT_BLOCKED reason is no longer the
        # current state once this slice is explicitly accepted.
        order["failure_reason"] = None
        
        order["updated_at"] = datetime.utcnow()
        order["last_placement_at"] = datetime.utcnow()

        anchor_state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
        anchor_state["active_placement_client_order_id"] = placed_order_id
        anchor_state["active_exchange_order_id"] = exchange_order_id
        anchor_state["active_exchange_price"] = actual_submitted_price
        anchor_state["current_logical_limit_price"] = actual_submitted_price
        order["anchor_repricing_state_json"] = anchor_state

        if not index_succeeded:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placed_order_id,
                exchange_order_id=exchange_order_id,
                stage="reveal.index_accepted_placement",
                error=RuntimeError(
                    order.get("placement_index_error")
                    or "accepted placement could not be indexed"
                ),
                reveal_event=reveal_event,
            )

        placement_parent_error = placement_parent_errors.get(placed_order_id)
        if placement_parent_error is not None:
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placed_order_id,
                exchange_order_id=exchange_order_id,
                stage="reveal.preinsert_parent",
                error=placement_parent_error,
                reveal_event=reveal_event,
            )

        # Any hook/bookkeeping exception from this point is a local-
        # finalization error and must never cause a resubmission or downgrade
        # the live exchange order to failed.
        try:
            hook_errors = self.order_placement_hooks.call_post_submission_hooks(
                order_for_submission,
                order_result,
            )
        except Exception as hook_error:
            hook_errors = [hook_error]
        if hook_errors:
            hook_error = RuntimeError(
                "; ".join(str(error) for error in hook_errors)
            )
            self._record_accepted_local_finalization_error(
                order,
                placement_client_order_id=placed_order_id,
                exchange_order_id=exchange_order_id,
                stage="reveal.post_submission_hook",
                error=hook_error,
                reveal_event=reveal_event,
            )

        self.log_callback("info", f"[LOT-TRACK] Stealth order revealed & placed: {stealth_order_id} ({order['side']} {slice_size} {order['product_id']} @ {actual_submitted_price}, reveal_policy={reveal_plan.reveal_pricing_policy}, exchange_order_id={exchange_order_id})")
        self.log_callback("info", {
            "event": "stealth_order_slice_placed_successfully",
            "stealth_order_id": order["stealth_order_id"],
            "client_order_id": placed_order_id,
            "exchange_order_id": exchange_order_id,
            "size": slice_size,
            "product_id": order["product_id"],
            "configured_limit_price": reveal_plan.configured_limit_price,
            "planned_submitted_limit_price": reveal_plan.submitted_limit_price,
            "submitted_limit_price": actual_submitted_price,
            "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
            "reveal_price_source": (
                "post_only_retry"
                if post_only_retried
                else reveal_plan.reveal_price_source
            ),
            "post_only_retry_attempts": len(post_only_attempts),
        })
        self._dispatch_lifecycle_event(
            stealth_order_id=stealth_order_id,
            event=StealthLifecycleEvent.REVEAL_SUCCEEDED,
            order_data=order,
            extra={
                "placed_order_id": placed_order_id,
                "exchange_order_id": exchange_order_id,
                "size": slice_size,
            },
        )

        # Persist updates without changing accepted placement truth.
        self._run_accepted_local_finalization_step(
            order,
            placement_client_order_id=placed_order_id,
            exchange_order_id=exchange_order_id,
            stage="reveal.persist_stealth_order",
            operation=lambda: self._update_stealth_order(order),
            incomplete_message="stealth order database update did not complete",
            reveal_event=reveal_event,
        )
        self._run_accepted_local_finalization_step(
            order,
            placement_client_order_id=placed_order_id,
            exchange_order_id=exchange_order_id,
            stage="reveal.persist_reveal_event",
            operation=lambda: self._record_reveal_event(order, reveal_event),
            incomplete_message="reveal history database update did not complete",
            reveal_event=reveal_event,
        )
        
        return placed_order_id
    
    def update_execution(self, stealth_order_id: str, executed_size: float, order_status: str = StealthOrderStatus.EXECUTED.value):
        """
        Update stealth order with execution information.
        
        Args:
            stealth_order_id: ID of stealth order
            executed_size: Amount filled
            order_status: New status (EXECUTED, PARTIALLY_FILLED, etc.)
        """
        order = self._get_stealth_order(stealth_order_id)
        
        if not order:
            return
        
        placed_order_id = None
        exchange_order_id = None
        revealed_orders = order.get("revealed_orders") or []
        if revealed_orders and isinstance(revealed_orders[-1], dict):
            placed_order_id = revealed_orders[-1].get("placed_order_id")
            exchange_order_id = revealed_orders[-1].get("exchange_order_id")

        order["executed_size"] = float(executed_size)
        order["updated_at"] = datetime.utcnow()
        anchor_state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
        if order_status in {StealthOrderStatus.EXECUTED.value, StealthOrderStatus.CANCELLED.value}:
            if anchor_state.get("active_placement_client_order_id") == placed_order_id:
                anchor_state["active_placement_client_order_id"] = None
                anchor_state["active_exchange_order_id"] = None
                anchor_state["active_exchange_price"] = None
                order["anchor_repricing_state_json"] = anchor_state

        if order_status == StealthOrderStatus.EXECUTED.value:
            self._update_stealth_order(order)
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.FILL_RECEIVED,
                order_data=order,
                extra={
                    "size": float(executed_size),
                    "placed_order_id": placed_order_id,
                    "exchange_order_id": exchange_order_id,
                    "status": StealthOrderStatus.REVEALED.value,
                },
            )

        order["status"] = order_status
        
        # 📊 LOT-TRACKING: Log execution
        self.log_callback("info", f"[LOT-TRACK] Stealth order executed: {stealth_order_id} ({order['side']} {executed_size} of {order['total_size']} {order['product_id']}, status={order_status})")
        
        self._update_stealth_order(order)

        if order_status == StealthOrderStatus.EXECUTED.value:
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.EXECUTED,
                order_data=order,
                extra={
                    "size": float(executed_size),
                    "placed_order_id": placed_order_id,
                    "exchange_order_id": exchange_order_id,
                },
            )
        elif order_status == StealthOrderStatus.CANCELLED.value:
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.CANCELLED,
                order_data=order,
                extra={
                    "size": float(executed_size),
                    "placed_order_id": placed_order_id,
                    "exchange_order_id": exchange_order_id,
                },
            )
    
    def cancel_stealth_order(
        self,
        stealth_order_id: str,
        reason: str = "User cancelled",
        cancel_exchange: bool = True,
    ) -> bool:
        """
        Cancel a stealth order.

        When ``cancel_exchange`` is True (default) and the order has a live
        exchange placement tracked in ``anchor_repricing_state_json
        .active_exchange_order_id``, that exchange order is best-effort
        cancelled via REST before the stealth order is marked CANCELLED.
        Failures to cancel on the exchange are logged but do not block the
        local status flip — the local lifecycle must always reach a
        terminal state so the reveal evaluator stops touching this order.

        Args:
            stealth_order_id: Internal stealth order id (client_order_id).
            reason: Free-text reason recorded in notes / lifecycle event.
            cancel_exchange: Best-effort REST cancel of the active exchange
                order before flipping local status. Set False only when the
                caller has already cancelled (or never placed) the exchange
                order.

        Returns:
            True if the local status flipped to CANCELLED. The exchange
            cancel result does not affect the return value.
        """
        order = self._get_stealth_order(stealth_order_id)

        if not order:
            return False

        if order["status"] == StealthOrderStatus.CANCELLED.value:
            return False

        if cancel_exchange:
            self._best_effort_cancel_active_exchange_order(order, reason)

        order["status"] = StealthOrderStatus.CANCELLED.value
        order["updated_at"] = datetime.utcnow()
        order["notes"] = f"{order['notes']}\nCancelled: {reason}"

        self._update_stealth_order(order)
        return True

    def _best_effort_cancel_active_exchange_order(
        self, order: Dict[str, Any], reason: str
    ) -> None:
        """Cancel the live exchange order tracked by anchor repricing state.

        Best-effort: any exception (REST failure, order already gone, etc.)
        is logged and swallowed so the local CANCELLED transition is never
        blocked. Also clears the in-memory ``active_exchange_order_id`` so
        subsequent reprice checks do not retry the stale id.
        """
        state = order.get("anchor_repricing_state_json") or {}
        exchange_order_id = state.get("active_exchange_order_id")
        if not exchange_order_id:
            return

        from configuration import REST_CLIENT

        try:
            with get_runtime_controller().track_inflight(INFLIGHT_REST_PLACE):
                REST_CLIENT.cancel_orders(order_ids=[exchange_order_id])
            self.log_callback(
                "info",
                {
                    "event": "stealth_cancel_exchange_ok",
                    "stealth_order_id": order.get("stealth_order_id"),
                    "exchange_order_id": exchange_order_id,
                    "reason": reason,
                },
            )
        except Exception as cancel_exc:
            self.log_callback(
                "warning",
                {
                    "event": "stealth_cancel_exchange_failed",
                    "stealth_order_id": order.get("stealth_order_id"),
                    "exchange_order_id": exchange_order_id,
                    "reason": reason,
                    "error": str(cancel_exc),
                },
            )

        # Clear the pointer either way: on success the order is gone; on
        # failure we still don't want subsequent reprice loops to try to
        # cancel/replace it again under a now-CANCELLED stealth order.
        state["active_exchange_order_id"] = None
        state["active_placement_client_order_id"] = None
        order["anchor_repricing_state_json"] = state
    
    # ===================== PRIVATE METHODS =====================
    
    def _calculate_reveal_size(self, order: Dict[str, Any]) -> float:
        """Calculate how much of hidden order to reveal now.

        Delegates to a ``RevealStrategy`` instance from
        ``business.stealth_reveal_strategy``. Strategies are pure
        size-computation functions; iceberg pacing is encoded inside
        ``TrancheRevealStrategy`` by inspecting
        ``anchor_repricing_state_json.active_placement_client_order_id``
        (the same SSOT the reprice flow uses).

        See 2026-05-03 incident notes in the strategy module for the
        rationale behind this extraction.
        """
        from business.stealth_reveal_strategy import get_reveal_strategy

        sizing_strategy = order.get("sizing_strategy_json", {}) or {}
        strategy_type = sizing_strategy.get("type", "fixed")
        strategy = get_reveal_strategy(
            strategy_type,
            sizing_strategy,
            market_volume_provider=self._get_market_volume,
            baseline_volume_provider=self._get_baseline_volume,
        )
        return strategy.next_slice_size(order)

    # Throttle window for the "reveal returned size=0" diagnostic.
    # 30s matches the operator's expected feedback latency for a
    # never-progressing stealth without spamming the log at 10 Hz.
    _NO_SLICE_LOG_COOLDOWN_SECONDS = 30.0

    def _maybe_log_no_slice(
        self, stealth_order_id: str, order: Dict[str, Any]
    ) -> None:
        """Throttled INFO when ``_calculate_reveal_size`` returns 0.

        The bridge polls at ~10 Hz. Without throttling, a TRIGGERED
        stealth whose strategy returns 0 (iceberg lock, fully-covered
        fixed, exhausted tranche schedule) would emit ~10 lines/sec.
        We log once per ``_NO_SLICE_LOG_COOLDOWN_SECONDS`` per stealth
        so the operator sees "why isn't this progressing?" without
        drowning in repeats.

        Invariant: at least one line per status transition that lands
        in the "no-slice" branch. Caller is responsible for clearing
        ``_no_slice_log_emitted_at[stealth_order_id]`` if the throttle
        needs to be reset (e.g. on cancel / restart).
        """
        import time

        now = time.time()
        last = self._no_slice_log_emitted_at.get(stealth_order_id, 0.0)
        if now - last < self._NO_SLICE_LOG_COOLDOWN_SECONDS:
            return
        self._no_slice_log_emitted_at[stealth_order_id] = now

        state = order.get("anchor_repricing_state_json") or {}
        active = state.get("active_placement_client_order_id")
        sizing = order.get("sizing_strategy_json") or {}
        self.log_callback("info", {
            "event": "stealth_reveal_no_slice",
            "stealth_order_id": stealth_order_id,
            "strategy_type": sizing.get("type", "fixed"),
            "iceberg_mode": sizing.get("iceberg_mode"),
            "status": order.get("status"),
            "total_size": float(order.get("total_size", 0) or 0),
            "revealed_size": float(order.get("revealed_size", 0) or 0),
            "executed_size": float(order.get("executed_size", 0) or 0),
            "active_placement_client_order_id": active,
            "throttle": (
                f"1_emit_per_{int(self._NO_SLICE_LOG_COOLDOWN_SECONDS)}s"
            ),
        })

    
    def _get_stealth_order(self, stealth_order_id: str, raise_if_missing: bool = False) -> Optional[Dict[str, Any]]:
        """Get stealth order from memory cache or database.
        
        Args:
            stealth_order_id: ID of stealth order to retrieve
            raise_if_missing: If True, raise StealthOrderNotFoundError instead of returning None
            
        Returns:
            Stealth order dict or None if not found
            
        Raises:
            StealthOrderNotFoundError: If raise_if_missing=True and order not found
        """
        if stealth_order_id in self.in_memory_orders:
            return self.in_memory_orders[stealth_order_id]
        
        # Load from database
        order = self._load_stealth_order_from_db(stealth_order_id)
        if order:
            self.in_memory_orders[stealth_order_id] = order
            return order
        
        if raise_if_missing:
            raise StealthOrderNotFoundError("stealth_order_id", stealth_order_id)
        
        return None
    
    def _get_current_market_data(self, product_id: str) -> MarketData:
        """Get current market data from cache (populated by StealthOrderBridge)."""
        market_cache = getattr(self, "_market_cache", {})
        if product_id in market_cache:
            return market_cache[product_id]

        # Return placeholder if data not available yet
        return {
            "product_id": product_id,
            "price": 0,
            "bid": 0,
            "ask": 0,
            "volume_1m": 0,
            "source": "unavailable",
        }
    
    def _get_market_volume(self, product_id: str, seconds: int) -> float:
        """Get market volume over specified time window."""
        # Would aggregate from recent trades
        return 0
    
    def _get_baseline_volume(self, product_id: str) -> float:
        """Get baseline volume for product."""
        # Would calculate from historical data
        return 1000
    
    def _get_active_stealth_orders(self) -> List[str]:
        """Get list of active stealth order IDs."""
        active_statuses = [
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
            StealthOrderStatus.REVEALED.value
        ]
        return [
            sid for sid, order in self.in_memory_orders.items()
            if order.get("status") in active_statuses
        ]
    
    def _serialize_order_for_json(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Convert order dict to JSON-serializable format.
        
        Converts datetime objects to ISO format strings and Decimal to float.
        """
        from decimal import Decimal
        
        serialized = order.copy()
        
        # Convert Decimal values to float
        for key, value in serialized.items():
            if isinstance(value, Decimal):
                serialized[key] = float(value)
        
        # Convert datetime objects to ISO format strings
        for key in ['created_at', 'updated_at', 'condition_first_met_at', 'condition_confirmed_at', 'last_placement_at']:
            if key in serialized and serialized[key]:
                if hasattr(serialized[key], 'isoformat'):
                    serialized[key] = serialized[key].isoformat()
        
        # Also handle revealed_orders array which contains datetime objects
        if 'revealed_orders' in serialized and isinstance(serialized['revealed_orders'], list):
            serialized_events = []
            for event in serialized['revealed_orders']:
                serialized_event = event.copy() if isinstance(event, dict) else event
                if isinstance(serialized_event, dict):
                    # Convert Decimal values in reveal events
                    for key, value in serialized_event.items():
                        if isinstance(value, Decimal):
                            serialized_event[key] = float(value)
                    # Convert datetime objects in reveal events
                    for dt_key in ['reveal_time', 'created_at', 'timestamp']:
                        if dt_key in serialized_event and serialized_event[dt_key]:
                            if hasattr(serialized_event[dt_key], 'isoformat'):
                                serialized_event[dt_key] = serialized_event[dt_key].isoformat()
                serialized_events.append(serialized_event)
            serialized['revealed_orders'] = serialized_events
        
        return serialized
    
    def get_serializable_orders(self) -> Dict[str, Any]:
        """Get all orders in JSON-serializable format."""
        return {oid: self._serialize_order_for_json(order) 
                for oid, order in self.in_memory_orders.items()}
    
    def sync_target_movement_to_cache(self, stealth_order_id: str, target_movement: float, target_movement_type: str) -> bool:
        """Sync target_movement changes to in-memory cache.
        
        Called after target_movement is updated in the database (order_parent table).
        Updates the in-memory cache immediately so UI gets fresh data.
        
        Args:
            stealth_order_id: The stealth order to update
            target_movement: New target movement value
            target_movement_type: New target movement type ('P' or 'A')
            
        Returns:
            True if successful, False if order not found in cache
        """
        order = self.in_memory_orders.get(stealth_order_id)
        if not order:
            return False
        
        order['target_movement'] = target_movement
        order['target_movement_type'] = target_movement_type
        order['updated_at'] = datetime.utcnow()
        
        return True
    
    def find_stealth_order_by_placed_order_id(self, placed_order_id: str) -> Optional[Dict[str, Any]]:
        """Find stealth order that revealed the given placed_order_id.
        
        Uses indexed lookup for O(1) performance instead of iterating all orders.
        
        Args:
            placed_order_id: The order ID placed on the exchange
            
        Returns:
            Stealth order dict if found, None otherwise
        """
        return self._placed_order_index.get(placed_order_id)

    def sync_exchange_order_id_for_placed_order(self, placed_order_id: str, exchange_order_id: str) -> bool:
        """Backfill audit-only exchange_order_id once websocket data provides it."""
        if not placed_order_id or not exchange_order_id:
            return False

        order = self.find_stealth_order_by_placed_order_id(placed_order_id)
        if not order:
            return False

        updated = False
        revealed_orders = order.get("revealed_orders") or []
        for reveal_event in reversed(revealed_orders):
            if not isinstance(reveal_event, dict):
                continue
            if reveal_event.get("placed_order_id") != placed_order_id:
                continue
            existing_exchange_order_id = reveal_event.get("exchange_order_id")
            if existing_exchange_order_id == exchange_order_id:
                return True
            if existing_exchange_order_id:
                return False
            reveal_event["exchange_order_id"] = exchange_order_id
            anchor_state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
            if anchor_state.get("active_placement_client_order_id") == placed_order_id:
                anchor_state["active_exchange_order_id"] = exchange_order_id
                order["anchor_repricing_state_json"] = anchor_state
            order["updated_at"] = datetime.utcnow()
            self._update_stealth_order(order)
            updated = True
            break

        if self.db_client:
            try:
                from database.order import update_stealth_audit_exchange_order_id

                update_stealth_audit_exchange_order_id(
                    stealth_order_id=order["stealth_order_id"],
                    placed_order_id=placed_order_id,
                    exchange_order_id=exchange_order_id,
                )
            except Exception as exc:
                self.log_callback(
                    "warning",
                    {
                        "event": "stealth_exchange_order_id_audit_sync_failed",
                        "stealth_order_id": order.get("stealth_order_id"),
                        "placed_order_id": placed_order_id,
                        "exchange_order_id": exchange_order_id,
                        "error": str(exc),
                    },
                )

        return updated
    
    def create_follow_up_stealth_order(
        self,
        original_stealth_order_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        reveal_condition: Optional[Dict[str, Any]] = None,
        follow_up_reveal_direction: Optional[str] = None,
        reveal_pricing_policy: Optional[str] = None,
        notes: str = "",
        target_movement: Optional[float] = None,
        target_movement_type: str = "P"
    ) -> Optional[str]:
        """Create a follow-up stealth order with same conditions as original.
        
        Used when a revealed stealth order fills and needs to be replaced on opposite side.
        
        Args:
            original_stealth_order_id: The stealth order that just filled
            side: Side for the follow-up ('BUY' or 'SELL')
            total_size: Size for follow-up order
            limit_price: Price for follow-up order
            reveal_condition: Optional override for reveal condition. If not provided, uses original's condition.
            follow_up_reveal_direction: Direction strategy for follow-up (FollowUpRevealDirection.SAME or OPPOSITE).
                                       Accepts enum or string value. If None, inherits from original.
                                       - SAME: Keep same side (BUY stays BUY, SELL stays SELL)
                                       - OPPOSITE: Flip side (BUY becomes SELL, SELL becomes BUY)
            reveal_pricing_policy: Optional pricing policy override. If None, inherits from original order.
            notes: Additional notes
            target_movement: Optional override for target movement. If not provided, uses original's target_movement.
            target_movement_type: Type for target movement ('P' or 'A'). Default 'P'.
            
        Returns:
            New stealth_order_id if created, None if original not found
        """
        original_order = self._get_stealth_order(original_stealth_order_id)
        if not original_order:
            return None
        
        # Use provided reveal condition or inherit from original
        follow_up_condition = reveal_condition if reveal_condition is not None else original_order.get("reveal_condition_json", {})
        inherited_pricing_policy = original_order.get("reveal_pricing_policy") or "configured_limit"
        effective_pricing_policy = reveal_pricing_policy or inherited_pricing_policy
        # Inherit anchor-repricing policy unless explicitly opted out. Build via
        # ``RepricingPolicy`` so the inheritance check uses the dataclass field
        # (not a magic string lookup) and on-disk shape stays identical.
        original_repricing = RepricingPolicy.from_dict(
            original_order.get("anchor_repricing_policy_json")
        )
        if original_repricing.inherit_to_follow_ups:
            anchor_repricing_policy = original_repricing.to_dict()
        else:
            anchor_repricing_policy = RepricingPolicy.disabled().to_dict()
        
        # Use provided target movement or inherit from original. Resolve via the
        # canonical resolver so root stealth orders (which keep target_movement on
        # the order_parent row, not the in-memory dict) are handled correctly.
        if target_movement is not None:
            follow_up_target_movement = target_movement
            follow_up_target_movement_type = target_movement_type
        else:
            inherited_tm, inherited_tm_type, _src = \
                self._resolve_target_movement_for_plan(original_stealth_order_id, original_order)
            follow_up_target_movement = inherited_tm if inherited_tm is not None else 0.0
            follow_up_target_movement_type = inherited_tm_type or "P"

        # Create follow-up with same reveal condition and sizing strategy
        # Link the follow-up as a child order to the ORIGINAL root parent (not the filled child)
        # This maintains a flat, single-level Parent:Child hierarchy as per design

        # Pre-generate the follow-up's stealth_order_id so we can use it
        # as the deterministic seed for retreat jitter BEFORE creating
        # the order. Same UUID then flows into create_stealth_order so
        # the seed and the persisted coid match (audit-replayable).
        follow_up_stealth_order_id = str(uuid.uuid4())

        # Apply post-fill retreat if configured. The inherited policy
        # owns the decision; helper returns ``limit_price`` unchanged
        # when retreat is disabled (distance == 0). Tick-align the
        # result via the same chokepoint used at reveal time so the
        # follow-up posts on a valid price grid.
        retreat_policy = RepricingPolicy.from_dict(anchor_repricing_policy)
        anchored_limit_price = retreat_policy.compute_follow_up_price(
            anchor_price=float(limit_price),
            side=side,
            follow_up_client_order_id=follow_up_stealth_order_id,
        )
        retreat_applied = anchored_limit_price != float(limit_price)
        if retreat_applied:
            anchored_limit_price = self._quantize_reprice_price(
                product_id=original_order["product_id"],
                side=side,
                price=anchored_limit_price,
                boundary_enforced=False,
            )
        # Audit trail: stuff the actual retreat values used into the
        # notes string. This is the only structured channel that
        # currently survives end-to-end through ``create_stealth_order``
        # without a schema change. If a dedicated audit field is added
        # later, move this there. (See genai_tools/ for the related TODO
        # if/when one is opened for stealth event audit fields.)
        retreat_audit = (
            f" [retreat: anchor={float(limit_price):.8f} "
            f"posted={anchored_limit_price:.8f} "
            f"distance={retreat_policy.follow_up_retreat_distance} "
            f"jitter={retreat_policy.follow_up_retreat_jitter}]"
            if retreat_applied else ""
        )

        follow_up_id = self.create_stealth_order(
            product_id=original_order["product_id"],
            side=side,
            total_size=total_size,
            limit_price=anchored_limit_price,
            reveal_condition=follow_up_condition,
            sizing_strategy=original_order.get("sizing_strategy_json", {}),
            parent_order_id=resolve_stealth_chain_root(original_order),
            follow_up_reveal_direction=follow_up_reveal_direction or original_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value),
            reveal_pricing_policy=effective_pricing_policy,
            reason="follow_up_replacement",
            notes=f"Follow-up to {original_stealth_order_id[:8]}... {notes}{retreat_audit}",
            anchor_repricing_policy=anchor_repricing_policy,
            target_movement=follow_up_target_movement,
            target_movement_type=follow_up_target_movement_type,
            stealth_order_id=follow_up_stealth_order_id,
        )

        # Mirror the target onto the in-memory stealth dict so cached lookups
        # match the canonical order_parent row written by create_stealth_order.
        if follow_up_id:
            follow_up_order = self._get_stealth_order(follow_up_id)
            if follow_up_order:
                follow_up_order["target_movement"] = follow_up_target_movement
                follow_up_order["target_movement_type"] = follow_up_target_movement_type
                # Structured audit (programmatic counterpart to the human-readable
                # ``notes`` summary). Lives on the in-memory order so dashboards
                # and debugging tools can answer "what retreat was applied to
                # this follow-up?" without parsing free-form text. Always
                # populated, even when retreat was a no-op (so consumers don't
                # have to disambiguate "missing field" from "no retreat").
                follow_up_order["follow_up_audit"] = {
                    "parent_stealth_order_id": original_stealth_order_id,
                    "anchor_price":            float(limit_price),
                    "posted_price":            float(anchored_limit_price),
                    "retreat_applied":         retreat_applied,
                    "retreat_distance":        retreat_policy.follow_up_retreat_distance,
                    "retreat_jitter":          retreat_policy.follow_up_retreat_jitter,
                    "jitter_seed":             follow_up_stealth_order_id,
                }
                self._update_stealth_order(follow_up_order)
        
        return follow_up_id
    
    # Database operations

    def _validate_local_price_read_only(
        self,
        order: Dict[str, Any],
    ) -> bool:
        """Validate a stored limit price without repairing persistent state.

        A restart must not silently rewrite historical/local intent. A known
        invalid price makes a not-yet-placed order ERROR. Missing metadata
        cannot prove invalidity, so validation remains pending and placement
        is deferred. Already-live and historical terminal orders retain their
        ownership/status and carry a diagnostic instead of being reclassified.
        """
        product_id = str(order.get("product_id") or "")
        metadata = get_product_metadata(product_id)
        metadata_available = metadata.get("price_increment") not in (None, "")
        result = normalize_price_for_product(
            order.get("limit_price"),
            product_id=product_id,
            side=order.get("side"),
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if result.ok and not result.adjusted:
            order.pop("_price_validation_pending", None)
            order.pop("price_validation_error", None)
            return True

        if not metadata_available:
            reason = (
                f"stored limit_price validation deferred because runtime "
                f"price_increment metadata is unavailable for {product_id}. "
                f"Database row was not modified."
            )
            should_log = order.get("price_validation_error") != reason
            order["_price_validation_pending"] = True
            order["price_validation_error"] = reason[:512]
            if should_log:
                self.log_callback("warning", {
                    "event": "stealth_order_hydration_price_metadata_unavailable",
                    "stealth_order_id": order.get("stealth_order_id"),
                    "product_id": product_id,
                    "side": order.get("side"),
                    "stored_limit_price": order.get("limit_price"),
                    "failure_reason": reason,
                    "status_preserved": order.get("status"),
                    "database_modified": False,
                })
            return False

        if result.ok:
            reason = (
                f"stored limit_price {result.requested_price} is off the "
                f"{result.increment} tick grid; canonical value would be "
                f"{result.effective_price}. Database row was not modified."
            )
        else:
            reason = (
                f"stored limit_price could not be validated: {result.reason}. "
                f"Database row was not modified."
            )
        order.pop("_price_validation_pending", None)
        order["price_validation_error"] = reason[:512]
        placeable_statuses = {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
        }
        previous_status = order.get("status")
        if previous_status in placeable_statuses:
            order["status"] = StealthOrderStatus.ERROR.value
            order["failure_reason"] = reason[:512]
        self.log_callback("error", {
            "event": "stealth_order_hydration_price_invalid",
            "stealth_order_id": order.get("stealth_order_id"),
            "product_id": order.get("product_id"),
            "side": order.get("side"),
            "stored_limit_price": order.get("limit_price"),
            "failure_reason": reason,
            "previous_status": previous_status,
            "status_after_validation": order.get("status"),
            "database_modified": False,
        })
        return False

    @staticmethod
    def _require_canonical_persisted_price(order: Dict[str, Any]) -> None:
        """Reject, but never repair, an invalid price at the DB boundary."""
        result = normalize_price_for_product(
            order.get("limit_price"),
            product_id=str(order.get("product_id") or ""),
            side=order.get("side"),
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        )
        if result.ok and not result.adjusted:
            return
        reason = result.reason if not result.ok else (
            f"price {result.requested_price} is off the {result.increment} "
            f"tick grid (canonical {result.effective_price})"
        )
        raise StealthOrderPersistenceError(
            f"Refusing non-canonical stealth_orders price write: {reason}"
        )
    
    def _save_stealth_order_to_db(self, order: Dict[str, Any]) -> bool:
        """Persist stealth order to database."""
        if not self.db_client:
            order["_persisted_limit_price"] = order.get("limit_price")
            return True
        self._require_canonical_persisted_price(order)
        
        try:
            rows_affected = self.db_client.execute_update(
                """INSERT INTO stealth_orders 
                   (stealth_order_id, product_id, side, total_size, remaining_size, 
                    limit_price, status, reveal_condition_type, reveal_condition_json, 
                          sizing_strategy_json, reason, notes, parent_order_id,
                          anchor_repricing_policy_json, anchor_repricing_state_json,
                          failure_reason)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (order['stealth_order_id'],
                 order['product_id'],
                 order['side'],
                 order['total_size'],
                 order['remaining_size'],
                 order['limit_price'],
                 order['status'],
                 order.get('reveal_condition_type', 'time_delay'),
                 json.dumps(order.get('reveal_condition_json', {})),
                 json.dumps(order.get('sizing_strategy_json', {})),
                 order.get('reason', ''),
                 order.get('notes', ''),
                  order.get('parent_order_id'),
                  json.dumps(order.get('anchor_repricing_policy_json', {})),
                  json.dumps(order.get('anchor_repricing_state_json', {})),
                  order.get('failure_reason'))
            )
            if isinstance(rows_affected, int) and rows_affected <= 0:
                return False
            order["_persisted_limit_price"] = order.get("limit_price")
            return True
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_save_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
            return False
    
    def _update_stealth_order(self, order: Dict[str, Any]) -> bool:
        """Update stealth order in database and report whether it completed."""
        if not self.db_client:
            return True
        persisted_price_missing = object()
        persisted_price = order.get(
            '_persisted_limit_price',
            persisted_price_missing,
        )
        try:
            write_limit_price = (
                persisted_price is persisted_price_missing
                or Decimal(str(persisted_price))
                != Decimal(str(order.get('limit_price')))
            )
        except Exception:
            write_limit_price = True
        if write_limit_price:
            self._require_canonical_persisted_price(order)
        
        try:
            # Convert datetime to string for database storage
            last_placement = order.get('last_placement_at')
            if hasattr(last_placement, 'isoformat'):
                last_placement = last_placement.isoformat()
            
            # Serialize revealed_orders, converting any datetime objects
            revealed_orders = order.get('revealed_orders', [])
            revealed_orders_json = json.dumps([
                {
                    **event,
                    'reveal_time': event.get('reveal_time').isoformat() if hasattr(event.get('reveal_time'), 'isoformat') else event.get('reveal_time')
                }
                for event in revealed_orders
            ])
            anchor_repricing_state = order.get('anchor_repricing_state_json', {})
            anchor_repricing_state_json = json.dumps({
                key: value.isoformat() if hasattr(value, 'isoformat') else value
                for key, value in dict(anchor_repricing_state or {}).items()
            })

            # Condition timestamps: serialise datetimes to ISO strings.
            # These mark when the reveal condition first became plausible
            # (``..._first_met_at``) and when it was firmly confirmed
            # (``..._confirmed_at``). Without persistence the post-restart
            # view reverts to NULL and the operator can't see how long a
            # stealth waited before triggering.
            def _iso_or_none(value):
                if value is None:
                    return None
                return value.isoformat() if hasattr(value, 'isoformat') else value

            condition_first_met_at = _iso_or_none(order.get('condition_first_met_at'))
            condition_confirmed_at = _iso_or_none(order.get('condition_confirmed_at'))
            write_failure_reason = 'failure_reason' in order
            
            rows_affected = self.db_client.execute_update(
                """UPDATE stealth_orders 
                   SET status = %s, revealed_size = %s, remaining_size = %s, 
                       executed_size = %s, revealed_orders = %s, last_placement_at = %s,
                       limit_price = CASE WHEN %s THEN %s ELSE limit_price END,
                       reveal_condition_json = %s,
                       anchor_repricing_policy_json = %s, anchor_repricing_state_json = %s,
                       condition_first_met_at = %s, condition_confirmed_at = %s,
                       failure_reason = CASE WHEN %s THEN %s ELSE failure_reason END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE stealth_order_id = %s""",
                (order['status'],
                 order.get('revealed_size', 0),
                 order.get('remaining_size', 0),
                 order.get('executed_size', 0),
                 revealed_orders_json,
                 last_placement,
                 write_limit_price,
                 order.get('limit_price'),
                 json.dumps(order.get('reveal_condition_json', {})),
                 json.dumps(order.get('anchor_repricing_policy_json', {})),
                 anchor_repricing_state_json,
                 condition_first_met_at,
                 condition_confirmed_at,
                 write_failure_reason,
                 order.get('failure_reason'),
                 order['stealth_order_id'])
            )
            if isinstance(rows_affected, int) and rows_affected <= 0:
                return False
            if write_limit_price:
                order['_persisted_limit_price'] = order.get('limit_price')
            return True
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_update_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
            return False
    
    def _load_stealth_order_from_db(self, stealth_order_id: str) -> Optional[Dict[str, Any]]:
        """Load stealth order from database."""
        if not self.db_client:
            return None
        
        try:
            results = self.db_client.execute_query(
                """SELECT * FROM stealth_orders WHERE stealth_order_id = %s""",
                (str(stealth_order_id),)
            )
            if results:
                row = results[0]
                
                order_data = {
                    'stealth_order_id': row['stealth_order_id'],
                    'product_id': row['product_id'],
                    'side': row['side'],
                    'total_size': float(row['total_size']),
                    'revealed_size': float(row.get('revealed_size', 0)),
                    'remaining_size': float(row.get('remaining_size', 0)),
                    'executed_size': float(row.get('executed_size', 0)),
                    'limit_price': float(row['limit_price']),
                    'status': row['status'],
                    'reveal_condition_type': row.get('reveal_condition_type', 'time_delay'),
                    'reveal_condition_json': _parse_json_container(row.get('reveal_condition_json'), {}),
                    'sizing_strategy_json': _parse_json_container(row.get('sizing_strategy_json'), {}),
                    'reason': row.get('reason', ''),
                    'notes': row.get('notes', ''),
                    'parent_order_id': row.get('parent_order_id'),
                    'revealed_orders': _parse_json_container(row.get('revealed_orders'), []),
                    'anchor_repricing_policy_json': _parse_json_container(row.get('anchor_repricing_policy_json'), {}),
                    'anchor_repricing_state_json': _parse_json_container(row.get('anchor_repricing_state_json'), {}),
                    'created_at': row.get('created_at'),
                    'condition_first_met_at': row.get('condition_first_met_at'),
                    'condition_confirmed_at': row.get('condition_confirmed_at'),
                    'failure_reason': row.get('failure_reason'),
                    '_persisted_limit_price': float(row['limit_price']),
                }
                self._validate_local_price_read_only(order_data)
                self._restore_hydrated_placement_index(order_data)
                return order_data
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_load_failed", "stealth_order_id": stealth_order_id, "error": str(e)})
        
        return None
    
    def load_all_active_orders_from_db(self) -> int:
        """Load all stealth orders from database into memory.
        
        Loads all orders (HIDDEN, PENDING, TRIGGERED, REVEALED, EXECUTED,
        CANCELLED, ERROR)
        to ensure UI displays the complete history and current state of stealth orders.
        
        Status handling on restart:
        - HIDDEN, PENDING, TRIGGERED: Reset to HIDDEN for fresh condition evaluation
        - REVEALED: Keep as-is (in-flight orders may complete)
        - EXECUTED: Keep as-is (historical record for UI display)
        - CANCELLED: Keep as-is (historical record for UI display)
        - ERROR: Keep as-is (terminal operator-visible placement failure)

        Existing stored prices are validated read-only. An off-grid or
        otherwise invalid row is loaded as in-memory ERROR and is never
        rewritten during hydration.
        
        Returns:
            Number of orders loaded
        """
        if not self.db_client:
            return 0
        
        try:
            results = self.db_client.execute_query(
                """SELECT * FROM stealth_orders 
                   ORDER BY created_at ASC"""
            )
            
            loaded_count = 0
            for row in results:
                try:
                    stealth_order_id = str(row['stealth_order_id'])
                    db_status = row['status']
                    condition_type = row.get('reveal_condition_type', 'time_delay')
                    condition_first_met = row.get('condition_first_met_at')
                    condition_confirmed = row.get('condition_confirmed_at')
                    
                    preserved_statuses = {
                        StealthOrderStatus.REVEALED.value,
                        StealthOrderStatus.EXECUTED.value,
                        StealthOrderStatus.CANCELLED.value,
                        StealthOrderStatus.ERROR.value,
                    }
                    reset_statuses = {
                        StealthOrderStatus.HIDDEN.value,
                        StealthOrderStatus.PENDING.value,
                        StealthOrderStatus.TRIGGERED.value,
                    }
                    order_data = {
                        'stealth_order_id': stealth_order_id,
                        'product_id': row['product_id'],
                        'side': row['side'],
                        'total_size': float(row['total_size']),
                        'revealed_size': float(row.get('revealed_size', 0)),
                        'remaining_size': float(row.get('remaining_size', 0)),
                        'executed_size': float(row.get('executed_size', 0)),
                        'limit_price': float(row['limit_price']),
                        'status': (
                            db_status
                            if db_status in preserved_statuses
                            else StealthOrderStatus.HIDDEN.value
                        ),
                        'reveal_condition_type': condition_type,
                        'reveal_condition_json': _parse_json_container(row.get('reveal_condition_json'), {}),
                        'sizing_strategy_json': _parse_json_container(row.get('sizing_strategy_json'), {}),
                        'reason': row.get('reason', ''),
                        'notes': row.get('notes', ''),
                        'parent_order_id': row.get('parent_order_id'),
                        'revealed_orders': _parse_json_container(row.get('revealed_orders'), []),
                        'anchor_repricing_policy_json': _parse_json_container(row.get('anchor_repricing_policy_json'), {}),
                        'anchor_repricing_state_json': _parse_json_container(row.get('anchor_repricing_state_json'), {}),
                        'created_at': row.get('created_at'),
                        'updated_at': row.get('updated_at'),
                        'visibility_score': float(row.get('visibility_score', 0.0)),
                        'last_placement_at': row.get('last_placement_at'),
                        'condition_first_met_at': None if db_status in reset_statuses else condition_first_met,
                        'condition_confirmed_at': None if db_status in reset_statuses else condition_confirmed,
                        'failure_reason': row.get('failure_reason'),
                        '_persisted_limit_price': float(row['limit_price']),
                        'revealed_count': 0,
                        'condition_monitoring_start': None,
                    }
                    
                    self._validate_local_price_read_only(order_data)
                    self.in_memory_orders[stealth_order_id] = order_data
                    self._restore_hydrated_placement_index(order_data)
                    loaded_count += 1
                except Exception as e:
                    self.log_callback("error", {"event": "stealth_order_load_item_failed", "stealth_order_id": row.get('stealth_order_id'), "error": str(e)})
            
            return loaded_count
        except Exception as e:
            self.log_callback("error", {"event": "stealth_orders_batch_load_failed", "error": str(e)})
            return 0

    def _format_reveal_trigger_reason(
        self,
        order: Dict[str, Any],
        reveal_event: Dict[str, Any],
    ) -> str:
        """Build a human-readable trigger reason for the reveal_history audit row.

        Pulls the actual reveal_condition off the stealth order so reprice rows
        and price-condition reveals don't render as ``"Price below unknown"``.
        Falls back to the configured limit price when the condition lacks an
        explicit threshold.
        """
        reprice_reason = reveal_event.get('reprice_reason')
        if reveal_event.get('placement_status') == 'repriced' and reprice_reason:
            return f"Anchor reprice: {reprice_reason}"
        condition = order.get('reveal_condition_json') or {}
        cond_type = str(condition.get('type') or order.get('reveal_condition_type') or '').lower()
        if cond_type == 'price':
            direction = str(condition.get('direction') or '').lower()
            threshold = condition.get('price_threshold')
            if threshold is None:
                threshold = order.get('limit_price')
            verb = 'above' if direction == 'above' else ('below' if direction == 'below' else 'crosses')
            return f"Price {verb} {threshold}"
        if cond_type == 'time_delay':
            delay = condition.get('delay_seconds')
            return f"Time delay {delay}s elapsed" if delay else "Time delay elapsed"
        if cond_type:
            return f"Condition met: {cond_type}"
        return "Reveal condition met"

    def _record_reveal_event(
        self,
        order: Dict[str, Any],
        reveal_event: Dict[str, Any],
    ) -> bool:
        """Record reveal event to stealth_order_reveal_history table.
        
        Uses UPSERT (INSERT ... ON CONFLICT) to handle idempotent recording.
        If the same (stealth_order_id, reveal_number) is recorded twice, it updates
        with the latest data instead of failing. This handles race conditions or retries.
        """
        if not getattr(self, "db_client", None):
            return True
        
        try:
            # Get stealth_order_id from order dict (not reveal_event)
            stealth_order_id = order.get('stealth_order_id')
            if not stealth_order_id:
                return False
            
            reveal_number = reveal_event.get('reveal_number', 1)
            revealed_size = reveal_event.get('revealed_size', 0)
            placement_price = reveal_event.get('placement_price')
            placed_order_id = reveal_event.get('placed_order_id')
            exchange_order_id = reveal_event.get('exchange_order_id')
            market_price = reveal_event.get('market_price')
            market_bid = reveal_event.get('market_bid')
            market_ask = reveal_event.get('market_ask')
            market_spread = reveal_event.get('market_spread')
            market_volume_1m = reveal_event.get('market_volume_1m')
            # Build a meaningful trigger reason from the stealth's reveal_condition
            # rather than a generic "Price below unknown" stub.
            trigger_reason = self._format_reveal_trigger_reason(order, reveal_event)
            # New audit columns (nullable; safe for legacy reveal events).
            placement_client_order_id = reveal_event.get('placement_client_order_id')
            placement_status = reveal_event.get('placement_status')
            placement_success = reveal_event.get('placement_success')
            cancelled_for_reprice = reveal_event.get('cancelled_for_reprice')
            reprice_reason = reveal_event.get('reprice_reason')
            anchor_target_price = reveal_event.get('anchor_target_price')
            anchor_max_price = reveal_event.get('anchor_max_price')
            reference_price_source = reveal_event.get('reference_price_source')
            reference_price = reveal_event.get('reference_price')
            reference_bid = reveal_event.get('reference_bid')
            reference_ask = reveal_event.get('reference_ask')
            market_source = reveal_event.get('market_source')
            # Classify event for downstream filtering.
            if placement_status == 'repriced' or reprice_reason:
                reveal_event_type = 'reprice'
            elif placement_success is False:
                reveal_event_type = 'reveal_blocked'
            else:
                reveal_event_type = 'reveal'
            trigger_data = json.dumps({
                'market_price': market_price,
                'market_bid': market_bid,
                'market_ask': market_ask,
                'market_spread': market_spread,
                'market_volume_1m': market_volume_1m,
                'market_source': market_source,
                'reveal_time': reveal_event.get('reveal_time').isoformat() if hasattr(reveal_event.get('reveal_time'), 'isoformat') else None
            })

            # Use UPSERT to handle duplicate reveals (idempotent recording)
            rows_affected = self.db_client.execute_update(
                """INSERT INTO stealth_order_reveal_history
                   (stealth_order_id, reveal_number, revealed_size, placement_price, placed_order_id,
                    exchange_order_id, market_price, market_bid, market_ask, market_spread, market_volume_1m,
                    reveal_trigger_reason, reveal_trigger_data,
                    placement_client_order_id, placement_status, placement_success,
                    cancelled_for_reprice, reprice_reason, reveal_event_type,
                    anchor_target_price, anchor_max_price,
                    reference_price_source, reference_price, reference_bid, reference_ask,
                    market_source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (stealth_order_id, reveal_number) DO UPDATE SET
                       revealed_size = EXCLUDED.revealed_size,
                       placement_price = EXCLUDED.placement_price,
                       placed_order_id = EXCLUDED.placed_order_id,
                       exchange_order_id = EXCLUDED.exchange_order_id,
                       market_price = EXCLUDED.market_price,
                       market_bid = EXCLUDED.market_bid,
                       market_ask = EXCLUDED.market_ask,
                       market_spread = EXCLUDED.market_spread,
                       market_volume_1m = EXCLUDED.market_volume_1m,
                       reveal_trigger_reason = EXCLUDED.reveal_trigger_reason,
                       reveal_trigger_data = EXCLUDED.reveal_trigger_data,
                       placement_client_order_id = EXCLUDED.placement_client_order_id,
                       placement_status = EXCLUDED.placement_status,
                       placement_success = EXCLUDED.placement_success,
                       cancelled_for_reprice = EXCLUDED.cancelled_for_reprice,
                       reprice_reason = EXCLUDED.reprice_reason,
                       reveal_event_type = EXCLUDED.reveal_event_type,
                       anchor_target_price = EXCLUDED.anchor_target_price,
                       anchor_max_price = EXCLUDED.anchor_max_price,
                       reference_price_source = EXCLUDED.reference_price_source,
                       reference_price = EXCLUDED.reference_price,
                       reference_bid = EXCLUDED.reference_bid,
                       reference_ask = EXCLUDED.reference_ask,
                       market_source = EXCLUDED.market_source""",
                (stealth_order_id, reveal_number, revealed_size, placement_price, placed_order_id,
                 exchange_order_id, market_price, market_bid, market_ask, market_spread, market_volume_1m,
                 trigger_reason, trigger_data,
                 placement_client_order_id, placement_status, placement_success,
                 cancelled_for_reprice, reprice_reason, reveal_event_type,
                 anchor_target_price, anchor_max_price,
                 reference_price_source, reference_price, reference_bid, reference_ask,
                 market_source)
            )
            if isinstance(rows_affected, int):
                return rows_affected > 0
            return True
        except Exception as e:
            self.log_callback("error", {"event": "stealth_reveal_event_recording_failed", "error": str(e)})
            return False
