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


import copy
import uuid
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Any, Iterator, Optional, Tuple, List

from configuration import (
    DEFAULT_MAX_ORDER_REPLACEMENT,
    PRODUCT_METADATA,
    get_trading_product_id,
    quantize_to_increment,
    safe_float,
)
from core.action_condition_guard import (
    ActionConditionGuard,
    SPOT_STANDING_MARKET_SOURCES,
    collect_spot_planned_budget_commitments,
    evaluate_spot_standing_price_limit,
    fetch_account_wallets,
    get_action_condition_guard_policy,
    normalize_action_guard_wallet_policy,
    rest_credentials_configured,
)
from core.enums import (
    ActionGuardPhase,
    CancelReentryDecision,
    CancelReentryState,
    Direction,
    FollowUpRevealDirection,
    OrderOwnershipProvenance,
    OrderSide,
    OrderStatus,
    PostFillRetreatReason,
    PostFillRetreatScope,
    ProductCapability,
    RepricingReferenceSource,
    RevealConditionType,
    RevealPricingPolicy,
    RevealPriceSource,
    RoundingDirection,
    SpotFollowUpTrigger,
    StandingPriceLimitPolicy,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.exceptions import (
    OrderPersistenceError,
    RevealPricingError,
    RevealConditionEvaluationError,
    RevealOrderSliceError,
    StealthOrderNotFoundError,
    StealthOrderPersistenceError,
)
from core.product_capability import evaluate_product_capability
from core.spot_follow_up_policy import evaluate_spot_follow_up_policy
from business.cancel_reentry_policy import (
    CancelReentryPolicy,
    CancelReentryRuntimeState,
    evaluate_cancel_reentry,
)
from business.post_fill_retreat_policy import PostFillRetreatPolicy
from business.stealth_condition_evaluator import (
    evaluate_stealth_reveal_condition,
    get_evaluator,
)
from core.models import MarketData, RepricingPolicy, RepricingState
from core.runtime_controller import INFLIGHT_REST_CANCEL, INFLIGHT_REST_PLACE, get_runtime_controller
from database.order import (
    get_parent_order,
    insert_order_parent,
    persist_filled_follow_up_atomic,
    prepare_controlled_admin_first_child_reveal_atomic,
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


def _filled_follow_up_stealth_order_id(
    *,
    original_stealth_order_id: str,
    source_client_order_id: str,
) -> str:
    """Return the restart-stable child identity for one FILLED placement."""

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                "coinbase://filled-follow-up/"
                f"{original_stealth_order_id}/{source_client_order_id}"
            ),
        )
    )


@dataclass(frozen=True)
class ControlledAdminChildRevealAuthority:
    """One-call in-process authority for one prepared first Admin child.

    The durable preparation remains the audit source of truth. This frozen
    object is an intentionally non-restartable capability: the issuing manager
    stores the exact object identity and consumes it on the first reveal call.
    It can bypass only the product ``STEALTH_REVEAL`` capability check; all
    ownership, portfolio, wallet, cap, profitability, payload, standing-price,
    and persistence guards continue to execute normally.
    """

    stealth_order_id: str
    root_client_order_id: str
    prepared_limit_price: float
    total_size: float
    reference_notional_usdc: float
    market_bid: str
    market_source: str
    market_observed_at: datetime
    portfolio_id: str
    correlation_id: str
    root_audit_id: str
    authority_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    reconciliation_plan_id: str
    batch_id: str
    batch_slot: int
    controlled_plan_sha256: Optional[str] = None


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
    
    def __init__(
        self,
        db_client,
        log_callback=None,
        order_placement_hooks=None,
        profit_validator=None,
        action_condition_guard_policy=None,
        fill_ledger_repo=None,
    ):
        """
        Initialize StealthOrderManager.
        
        Args:
            db_client: Database client for persistence
            log_callback: Optional logging callback (log_type, message). Defaults to proper logging_service.
            order_placement_hooks: Optional OrderPlacementHookRegistry for pre/post submission hooks.
            profit_validator: Optional ProfitValidator for reveal-time profitability revalidation.
            action_condition_guard_policy: Optional account/action guard policy override.
            fill_ledger_repo: Optional FillLedgerRepository for known spot inventory authority.
        """
        self.db_client = db_client
        self.logger = get_logger("StealthOrderManager")
        self.log_callback = log_callback or self._default_log
        self.in_memory_orders = {}  # For caching/quick access
        self._market_cache: Dict[str, MarketData] = {}  # product_id -> latest market snapshot
        self._placed_order_index = {}  # Index: placed_order_id -> stealth_order (O(1) lookup)
        self.profit_validator = profit_validator
        self.fill_ledger_repo = fill_ledger_repo
        # Throttle map for the "reveal returned size=0" diagnostic. Keyed
        # by stealth_order_id, value is the unix-timestamp of the last
        # emitted log line. See ``_maybe_log_no_slice``.
        self._no_slice_log_emitted_at: Dict[str, float] = {}
        self.action_condition_guard_policy = action_condition_guard_policy
        self._action_guard_blocked_until: Dict[str, float] = {}
        
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
            self.logger.warning(
                "Stealth schema migration failed "
                "[exception_class:%s]",
                type(e).__name__,
            )
    
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

    def snapshot_mutation_claims(self, stealth_order_id: str) -> Dict[Any, Optional[str]]:
        """Return read-only runtime mutation claim state for one stealth order.

        This is evidence only for Admin API/read-model consumers. It does not
        acquire, release, clear, or complete claims; mutation ownership still
        flows exclusively through :meth:`try_claim_mutation` and
        :meth:`release_mutation`.
        """
        from core.enums import StealthMutationKind

        lock = getattr(self, "_mutation_check_lock", None)
        if lock is None:
            import threading

            lock = threading.RLock()
            self._mutation_check_lock = lock

        with lock:
            return {
                kind: self._mutation_claims.state(kind, stealth_order_id)
                for kind in StealthMutationKind
            }

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
        1. :meth:`RepricingPolicy.from_anchor_repricing_policy_dict` does field-by-field clamping,
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
        policy = RepricingPolicy.from_anchor_repricing_policy_dict(
            anchor_repricing_policy
        )
        if policy.enabled and policy.target_distance <= 0:
            policy = RepricingPolicy.disabled()
        return policy.to_anchor_repricing_policy_dict()

    def _normalize_cancel_reentry_policy(
        self,
        cancel_reentry_policy: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Normalize cancel/re-entry policy for storage."""
        try:
            return (
                CancelReentryPolicy.from_cancel_reentry_policy_dict(
                    cancel_reentry_policy
                )
                .to_cancel_reentry_policy_dict()
            )
        except ValueError as exc:
            from core.exceptions import OrderCreationError

            raise OrderCreationError(
                f"invalid cancel_reentry_policy: {exc}"
            ) from exc

    def _normalize_post_fill_retreat_policy(
        self,
        post_fill_retreat_policy: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Normalize same-side post-fill retreat policy for storage."""
        return (
            PostFillRetreatPolicy.from_post_fill_retreat_policy_dict(
                post_fill_retreat_policy
            )
            .to_post_fill_retreat_policy_dict()
        )

    def _normalize_cancel_reentry_state(
        self,
        cancel_reentry_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Normalize cancel/re-entry runtime state for storage."""
        return (
            CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
                cancel_reentry_state
            )
            .to_cancel_reentry_runtime_state_dict()
        )

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
    def _apply_post_fill_retreat_offset_to_target_prices(
        target_prices: Dict[str, float],
        state: Dict[str, Any],
    ) -> Dict[str, float]:
        """Carry cumulative hidden-order retreat into future anchor reprices."""
        offset = safe_float(state.get("post_fill_retreat_offset"), default=0.0)
        if not offset:
            return target_prices
        adjusted = dict(target_prices)
        for key in ("target_price", "max_boundary_price"):
            adjusted[key] = float(adjusted[key]) + float(offset)
        return adjusted

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
        trading_product_id = get_trading_product_id(str(product_id or ""))
        metadata = PRODUCT_METADATA.get(product_id) or PRODUCT_METADATA.get(trading_product_id) or {}
        price_increment = metadata.get("price_increment")
        if not price_increment:
            return float(price)

        normalized_side = str(side or "").upper()
        direction = RoundingDirection.NEAREST.value
        if boundary_enforced:
            if normalized_side == OrderSide.BUY.value:
                direction = RoundingDirection.UP.value
            elif normalized_side == OrderSide.SELL.value:
                direction = RoundingDirection.DOWN.value

        try:
            return float(quantize_to_increment(float(price), str(price_increment), direction=direction))
        except (TypeError, ValueError):
            return float(price)

    # Maximum post-only retries per placement. Industry-standard repricing
    # ladder: original attempt + 2 retries, repricing 1 tick safer (away
    # from the touch) on each rejection. Surfacing on exhaustion is
    # intentional: silently demoting to taker would betray the
    # post-only intent of TOP_OF_BOOK / MIDPOINT reveals and charge the
    # operator the wrong fee tier.
    POST_ONLY_MAX_ATTEMPTS = 3

    def _get_price_increment(self, product_id: str) -> Optional[str]:
        """Return the price increment string for a product, or ``None`` if
        the product is unknown to ``PRODUCT_METADATA``.
        """
        trading_product_id = get_trading_product_id(str(product_id or ""))
        metadata = PRODUCT_METADATA.get(product_id) or PRODUCT_METADATA.get(trading_product_id) or {}
        increment = metadata.get("price_increment")
        return str(increment) if increment else None

    @staticmethod
    def _next_safer_tick(price: float, side: str, increment: str) -> float:
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
        try:
            new_price = float(quantize_to_increment(
                float(price), str(increment),
                direction=RoundingDirection.NEAREST.value,
            ))
        except (TypeError, ValueError):
            new_price = float(price)
        try:
            tick = float(increment)
        except (TypeError, ValueError):
            return new_price
        normalized_side = str(side or "").upper()
        if normalized_side == OrderSide.BUY.value:
            return new_price - tick
        if normalized_side == OrderSide.SELL.value:
            return new_price + tick
        return new_price

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
        candidates = [
            order_result.get("failure_reason"),
            (order_result.get("error_response") or {}).get("error"),
            (order_result.get("error_response") or {}).get("message"),
            (order_result.get("error_response") or {}).get("preview_failure_reason"),
        ]
        for value in candidates:
            if value and token in str(value).upper():
                return True
        return False

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

        controller = get_runtime_controller()
        controller.check_admission(INFLIGHT_REST_PLACE)

        bid = safe_float(market_data.get("bid"), default=None)
        ask = safe_float(market_data.get("ask"), default=None)
        normalized_side = str(order.get("side") or "").upper()
        policy = RepricingPolicy.coerce(policy)
        if policy.post_only_required:
            if normalized_side == "BUY" and ask and desired_price >= ask:
                return False
            if normalized_side == "SELL" and bid and desired_price <= bid:
                return False

        action_guard_ok, action_guard_failure = (
            self._evaluate_replacement_action_condition_guard(
                phase=ActionGuardPhase.REVEAL,
                product_id=str(order.get("product_id") or ""),
                side=str(order.get("side") or ""),
                size=remaining_size,
                limit_price=desired_price,
                existing_side=str(order.get("side") or ""),
                existing_size=remaining_size,
                existing_limit_price=current_price,
                stealth_order_id=order.get("stealth_order_id"),
                parent_order_id=order.get("parent_order_id"),
                replaced_client_order_id=state.get(
                    "active_placement_client_order_id"
                ),
                replaced_exchange_order_id=exchange_order_id,
            )
        )
        if not action_guard_ok:
            self.log_callback(
                "info",
                {
                    "event": "stealth_anchor_reprice_blocked_by_action_guard",
                    **(action_guard_failure or {}),
                },
            )
            return False

        # Track the cancel+replace as a single in-flight critical section so a
        # concurrent drain waits for both the cancellation and the replacement
        # placement to settle before transitioning to STOPPED.
        with controller.track_inflight(INFLIGHT_REST_PLACE):
            controller.check_admission(INFLIGHT_REST_PLACE)
            REST_CLIENT.cancel_orders(order_ids=[exchange_order_id])
            placement_client_order_id = str(uuid.uuid4())
            order_result = REST_CLIENT.place_limit_order(
                product_id=order["product_id"],
                side=order["side"],
                limit_price=str(desired_price),
                base_size=str(order["remaining_size"]),
                client_order_id=placement_client_order_id,
                post_only=policy.post_only_required,
            )
        success_response = order_result.get("success_response") if isinstance(order_result, dict) else {}
        new_exchange_order_id = (success_response or {}).get("order_id")

        # Ensure an order_parent row exists for the new placement uuid BEFORE any WS
        # event for it can arrive (FK violation guard, mirrors reveal_order_slice).
        # Flat hierarchy: resolve to chain root so a stealth follow-up's reveal
        # placement does not become a grandchild of the original root.
        root_parent_for_placement = resolve_stealth_chain_root(order)
        try:
            inherited_tm, inherited_tm_type, _src = \
                self._resolve_target_movement_for_plan(order["stealth_order_id"], order)
            insert_order_parent(
                client_order_id=placement_client_order_id,
                product_id=order["product_id"],
                side=order["side"],
                size=safe_float(order.get("remaining_size"), default=0.0),
                price=desired_price,
                target_movement=inherited_tm if inherited_tm is not None else 0.0,
                target_movement_type=inherited_tm_type or "P",
                max_order_replacement=int(order.get("max_order_replacements") or 0),
                current_order_replacement=0,
                status=OrderStatus.OPEN.value,
                parent_order_id=root_parent_for_placement,
                allow_partial_fills=bool(order.get("allow_partial_fills", False)),
            )
        except Exception as parent_insert_error:
            self.log_callback(
                "warning",
                {
                    "event": "anchor_reprice_order_parent_insert_failed",
                    "stealth_order_id": order["stealth_order_id"],
                    "placement_client_order_id": placement_client_order_id,
                    "error": str(parent_insert_error),
                },
            )

        self._mark_reveal_event_cancelled_for_reprice(
            order,
            state.get("active_placement_client_order_id"),
            reprice_reason,
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
        self._placed_order_index[placement_client_order_id] = order

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
        self._update_stealth_order(order)

        # Persist reprice to history table for audit (mirrors reveal_order_slice).
        try:
            self._record_reveal_event(order, reveal_event)
        except Exception as record_err:
            self.log_callback(
                "warning",
                {
                    "event": "anchor_reprice_record_reveal_event_failed",
                    "stealth_order_id": order["stealth_order_id"],
                    "placement_client_order_id": placement_client_order_id,
                    "error": str(record_err),
                },
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

        capability = evaluate_product_capability(
            product_id=order.get("product_id", ""),
            capability=ProductCapability.MOVE_REVEALED,
        )
        if not capability.allowed:
            raise StealthMoveError(
                f"cannot move stealth order {stealth_order_id!r}: "
                f"{capability.reason}",
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

        remaining_size = safe_float(order.get("remaining_size"), default=0.0) or 0.0
        action_guard_ok, action_guard_failure = (
            self._evaluate_replacement_action_condition_guard(
                phase=ActionGuardPhase.REVEAL,
                product_id=str(order.get("product_id") or ""),
                side=str(order.get("side") or ""),
                size=remaining_size,
                limit_price=new_price,
                existing_side=str(order.get("side") or ""),
                existing_size=remaining_size,
                existing_limit_price=old_submitted_price,
                stealth_order_id=stealth_order_id,
                parent_order_id=order.get("parent_order_id"),
                replaced_client_order_id=state.get(
                    "active_placement_client_order_id"
                ),
                replaced_exchange_order_id=str(old_exchange_order_id),
            )
        )
        if not action_guard_ok:
            self.log_callback(
                "info",
                {
                    "event": "stealth_move_planning_blocked_by_action_guard",
                    **(action_guard_failure or {}),
                },
            )
            raise StealthMoveError(
                f"cannot move stealth order {stealth_order_id!r}: "
                f"{(action_guard_failure or {}).get('reason', 'blocked')}",
                stealth_order_id=stealth_order_id,
                stage="validate",
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
        - If the place call raises **after** the cancel succeeded, mark
          the stealth order ``CANCELLED`` and persist; the original
          placement is gone from the exchange and the operator can issue
          a fresh ``create_stealth_order`` if desired.

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
            current_state = self._normalize_anchor_repricing_state(
                order.get("anchor_repricing_state_json")
            )
            remaining_size = (
                safe_float(order.get("remaining_size"), default=0.0) or 0.0
            )
            action_guard_ok, action_guard_failure = (
                self._evaluate_replacement_action_condition_guard(
                    phase=ActionGuardPhase.REVEAL,
                    product_id=str(order.get("product_id") or ""),
                    side=str(order.get("side") or ""),
                    size=remaining_size,
                    limit_price=new_price,
                    existing_side=str(order.get("side") or ""),
                    existing_size=remaining_size,
                    existing_limit_price=plan.old_submitted_price,
                    stealth_order_id=sid,
                    parent_order_id=order.get("parent_order_id"),
                    replaced_client_order_id=current_state.get(
                        "active_placement_client_order_id"
                    ),
                    replaced_exchange_order_id=plan.old_exchange_order_id,
                )
            )
            if not action_guard_ok:
                self.log_callback(
                    "info",
                    {
                        "event": "stealth_move_execution_blocked_by_action_guard",
                        **(action_guard_failure or {}),
                    },
                )
                raise StealthMoveError(
                    f"cannot execute move for stealth order {sid!r}: "
                    f"{(action_guard_failure or {}).get('reason', 'blocked')}",
                    stealth_order_id=sid,
                    stage="validate",
                )

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
                        old_placement_client_order_id=order.get(
                            "anchor_repricing_state_json", {}
                        ).get("active_placement_client_order_id"),
                        old_exchange_order_id=plan.old_exchange_order_id,
                        old_submitted_price=plan.old_submitted_price,
                        new_submitted_price=plan.new_configured_limit_price,
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
                order.get("anchor_repricing_state_json", {}).get(
                    "active_placement_client_order_id"
                ),
                f"move:{plan.reason.value if plan.reason is not None else 'unknown'}",
            )

            # === PLACE ===
            placement_client_order_id = str(uuid.uuid4())
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
            except Exception as place_exc:
                # POST-CANCEL FAILURE: original placement is gone from
                # the exchange. Mark the stealth order CANCELLED and
                # surface the failure so operators can decide to
                # resubmit manually.
                order["status"] = StealthOrderStatus.CANCELLED.value
                order["updated_at"] = datetime.utcnow()
                try:
                    self._update_stealth_order(order)
                except Exception:
                    pass  # Best-effort persistence on failure path.
                self.log_callback(
                    "error",
                    {
                        "event": "stealth_move_place_failed_after_cancel",
                        "stealth_order_id": sid,
                        "old_exchange_order_id": plan.old_exchange_order_id,
                        "new_placement_client_order_id": placement_client_order_id,
                        "error": str(place_exc),
                    },
                )
                try:
                    from database.order import insert_stealth_order_move
                    insert_stealth_order_move(
                        stealth_order_id=sid,
                        old_placement_client_order_id=order.get(
                            "anchor_repricing_state_json", {}
                        ).get("active_placement_client_order_id"),
                        old_exchange_order_id=plan.old_exchange_order_id,
                        old_submitted_price=plan.old_submitted_price,
                        new_placement_client_order_id=placement_client_order_id,
                        new_submitted_price=new_price,
                        reason=plan.reason.value if plan.reason is not None else None,
                        notes=plan.notes,
                        status="place_failed_after_cancel",
                        error_message=str(place_exc),
                        market_bid=plan.market_bid,
                        market_ask=plan.market_ask,
                    )
                except Exception:
                    pass
                raise StealthMoveError(
                    f"place failed AFTER cancel succeeded for {sid!r}: "
                    f"stealth order set to CANCELLED. Error: {place_exc}",
                    stealth_order_id=sid,
                    stage="place",
                ) from place_exc

            success_response = (
                order_result.get("success_response")
                if isinstance(order_result, dict)
                else {}
            )
            new_exchange_order_id = (success_response or {}).get("order_id")

            # === FK guard: insert order_parent for the new placement ===
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
                insert_order_parent(
                    client_order_id=placement_client_order_id,
                    product_id=order["product_id"],
                    side=order["side"],
                    size=safe_float(order.get("remaining_size"), default=0.0),
                    price=new_price,
                    target_movement=effective_tm if effective_tm is not None else 0.0,
                    target_movement_type=effective_tm_type or "P",
                    max_order_replacement=int(order.get("max_order_replacements") or 0),
                    current_order_replacement=0,
                    status=OrderStatus.OPEN.value,
                    parent_order_id=plan.root_parent_client_order_id,
                    allow_partial_fills=bool(order.get("allow_partial_fills", False)),
                )
            except Exception as parent_insert_error:
                self.log_callback(
                    "warning",
                    {
                        "event": "stealth_move_order_parent_insert_failed",
                        "stealth_order_id": sid,
                        "placement_client_order_id": placement_client_order_id,
                        "error": str(parent_insert_error),
                    },
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
            self._placed_order_index[placement_client_order_id] = order

            try:
                self._update_stealth_order(order)
            except Exception as persist_exc:
                self.log_callback(
                    "error",
                    {
                        "event": "stealth_move_persist_failed",
                        "stealth_order_id": sid,
                        "error": str(persist_exc),
                    },
                )
                raise StealthMoveError(
                    f"persist failed after successful move for {sid!r}: {persist_exc}",
                    stealth_order_id=sid,
                    stage="persist",
                ) from persist_exc

            try:
                self._record_reveal_event(order, move_reveal_event)
            except Exception:
                # Audit record is best-effort.
                pass

            try:
                from database.order import insert_stealth_order_move
                insert_stealth_order_move(
                    stealth_order_id=sid,
                    old_placement_client_order_id=order.get(
                        "anchor_repricing_state_json", {}
                    ).get("active_placement_client_order_id"),
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
                )
            except Exception:
                # Audit insertion is best-effort.
                pass

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

        controller = get_runtime_controller()
        if not controller.is_admitting():
            return 0

        capability = evaluate_product_capability(
            product_id=product_id,
            capability=ProductCapability.REPRICE_REVEALED,
        )
        if not capability.allowed:
            return 0

        processed = 0
        market_data = self._get_current_market_data(product_id)
        if (market_data or {}).get("source") != "ticker":
            return 0

        for stealth_order_id in list(self._get_active_stealth_orders()):
            if not controller.is_admitting():
                return processed
            order = self.in_memory_orders.get(stealth_order_id)
            if not order or order.get("product_id") != product_id:
                continue

            cancel_reentry_state = (
                CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
                    order.get("cancel_reentry_state_json")
                )
            )
            if cancel_reentry_state.state == CancelReentryState.CANCELLED_BY_POLICY:
                continue

            policy = RepricingPolicy.from_anchor_repricing_policy_dict(
                order.get("anchor_repricing_policy_json")
            )
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
                target_prices = self._apply_post_fill_retreat_offset_to_target_prices(
                    target_prices,
                    state,
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
                        action_guard_ok, action_guard_failure = (
                            self._evaluate_action_condition_guard(
                                phase=ActionGuardPhase.PLANNING,
                                product_id=str(order.get("product_id") or ""),
                                side=str(order.get("side") or ""),
                                size=(
                                    safe_float(
                                        order.get("remaining_size"),
                                        default=0.0,
                                    )
                                    or 0.0
                                ),
                                limit_price=desired_price,
                                stealth_order_id=stealth_order_id,
                                parent_order_id=order.get("parent_order_id"),
                            )
                        )
                        if not action_guard_ok:
                            state["reprice_reason"] = "blocked_by_action_guard"
                            state["last_action_guard_block_reason"] = (
                                action_guard_failure or {}
                            ).get("reason")
                            self.log_callback(
                                "info",
                                {
                                    "event": (
                                        "stealth_anchor_reprice_hidden_blocked_"
                                        "by_action_guard"
                                    ),
                                    **(action_guard_failure or {}),
                                },
                            )
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
                            continue

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

    def process_cancel_reentry_for_product(self, product_id: str) -> int:
        """Apply cancel/re-entry policy for eligible stealth orders on one product."""
        controller = get_runtime_controller()
        if not controller.is_admitting():
            return 0
        capability = evaluate_product_capability(
            product_id=product_id,
            capability=ProductCapability.CANCEL_REENTRY,
        )
        if not capability.allowed:
            return 0

        processed = 0
        market_data = self._get_current_market_data(product_id)
        if (market_data or {}).get("source") != "ticker":
            return 0

        for stealth_order_id in list(self._get_active_stealth_orders()):
            if not controller.is_admitting():
                return processed
            order = self.in_memory_orders.get(stealth_order_id)
            if not order or order.get("product_id") != product_id:
                continue

            try:
                policy = CancelReentryPolicy.from_cancel_reentry_policy_dict(
                    order.get("cancel_reentry_policy_json")
                )
            except ValueError as exc:
                self.log_callback(
                    "warning",
                    {
                        "event": "cancel_reentry_policy_invalid",
                        "stealth_order_id": stealth_order_id,
                        "error": str(exc),
                    },
                )
                continue

            if not policy.enabled:
                continue

            state = CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
                order.get("cancel_reentry_state_json")
            )
            evaluation = evaluate_cancel_reentry(order, market_data, policy, state)

            if evaluation.decision == CancelReentryDecision.CANCEL:
                if self._apply_cancel_reentry_cancel(order, state, evaluation):
                    processed += 1
            elif evaluation.decision == CancelReentryDecision.REENTER:
                if self._apply_cancel_reentry_reenter(order, state, evaluation):
                    processed += 1

        return processed

    def is_policy_cancelled_placement(
        self,
        order: Dict[str, Any],
        placement_client_order_id: str,
    ) -> bool:
        """Return True when a WS cancel belongs to a policy-triggered cancel."""
        state = CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
            order.get("cancel_reentry_state_json")
        )
        return (
            bool(placement_client_order_id)
            and state.cancelled_placement_client_order_id == placement_client_order_id
        )

    def _apply_cancel_reentry_cancel(
        self,
        order: Dict[str, Any],
        state: CancelReentryRuntimeState,
        evaluation: Any,
    ) -> bool:
        """Cancel the active revealed placement for cancel/re-entry policy."""
        from core.enums import StealthMutationKind
        from configuration import REST_CLIENT

        stealth_order_id = order.get("stealth_order_id")
        if not stealth_order_id:
            return False
        if safe_float(order.get("executed_size"), default=0.0) > 0:
            return False
        if order.get("status") != StealthOrderStatus.REVEALED.value:
            return False

        anchor_state = self._normalize_anchor_repricing_state(
            order.get("anchor_repricing_state_json")
        )
        placement_client_order_id = anchor_state.get("active_placement_client_order_id")
        exchange_order_id = anchor_state.get("active_exchange_order_id")
        if not exchange_order_id:
            return False

        if not self.try_claim_mutation(StealthMutationKind.MOVE, stealth_order_id):
            return False

        try:
            pre_cancel_state = CancelReentryRuntimeState(
                state=CancelReentryState.CANCELLED_BY_POLICY,
                last_cancel_at=state.last_cancel_at,
                last_reentry_at=state.last_reentry_at,
                reentry_count=state.reentry_count,
                cancelled_placement_client_order_id=placement_client_order_id,
                cancelled_exchange_order_id=exchange_order_id,
                last_reason=evaluation.reason,
            )
            order["cancel_reentry_state_json"] = (
                pre_cancel_state.to_cancel_reentry_runtime_state_dict()
            )
            try:
                with get_runtime_controller().track_inflight(INFLIGHT_REST_CANCEL):
                    REST_CLIENT.cancel_orders(order_ids=[exchange_order_id])
            except Exception as cancel_exc:
                order["cancel_reentry_state_json"] = (
                    state.to_cancel_reentry_runtime_state_dict()
                )
                self.log_callback(
                    "error",
                    {
                        "event": "cancel_reentry_cancel_failed",
                        "stealth_order_id": stealth_order_id,
                        "exchange_order_id": exchange_order_id,
                        "reason": evaluation.reason,
                        "error": str(cancel_exc),
                    },
                )
                return False

            self._mark_reveal_event_cancelled_for_reprice(
                order,
                placement_client_order_id,
                "cancel_reentry_policy",
            )

            now = datetime.utcnow()
            anchor_state["active_placement_client_order_id"] = None
            anchor_state["active_exchange_order_id"] = None
            anchor_state["active_exchange_price"] = None
            anchor_state["cancel_reentry_last_reference_price"] = evaluation.reference_price
            anchor_state["cancel_reentry_last_distance"] = evaluation.distance
            order["anchor_repricing_state_json"] = anchor_state

            order["status"] = StealthOrderStatus.HIDDEN.value
            order["revealed_size"] = 0.0
            order["remaining_size"] = float(order.get("total_size", 0) or 0)
            order["visibility_score"] = 0.0
            order["condition_first_met_at"] = None
            order["condition_confirmed_at"] = None
            order["updated_at"] = now

            policy_state = CancelReentryRuntimeState(
                state=CancelReentryState.CANCELLED_BY_POLICY,
                last_cancel_at=now.isoformat(),
                last_reentry_at=state.last_reentry_at,
                reentry_count=state.reentry_count,
                cancelled_placement_client_order_id=placement_client_order_id,
                cancelled_exchange_order_id=exchange_order_id,
                last_reason=evaluation.reason,
            )
            order["cancel_reentry_state_json"] = (
                policy_state.to_cancel_reentry_runtime_state_dict()
            )
            self._update_stealth_order(order)

            self.log_callback(
                "info",
                {
                    "event": "cancel_reentry_cancelled",
                    "stealth_order_id": stealth_order_id,
                    "placement_client_order_id": placement_client_order_id,
                    "exchange_order_id": exchange_order_id,
                    "reference_price": evaluation.reference_price,
                    "distance": evaluation.distance,
                    "reason": evaluation.reason,
                },
            )
            return True
        finally:
            self.release_mutation(StealthMutationKind.MOVE, stealth_order_id)

    def _apply_cancel_reentry_reenter(
        self,
        order: Dict[str, Any],
        state: CancelReentryRuntimeState,
        evaluation: Any,
    ) -> bool:
        """Re-enter a policy-cancelled stealth order through reveal_order_slice."""
        from core.enums import StealthMutationKind

        stealth_order_id = order.get("stealth_order_id")
        if not stealth_order_id:
            return False
        if safe_float(order.get("executed_size"), default=0.0) > 0:
            return False
        if state.state != CancelReentryState.CANCELLED_BY_POLICY:
            return False

        if not self.try_claim_mutation(StealthMutationKind.MOVE, stealth_order_id):
            return False

        try:
            now = datetime.utcnow()
            order["status"] = StealthOrderStatus.TRIGGERED.value
            order["condition_confirmed_at"] = now
            order["remaining_size"] = float(order.get("total_size", 0) or 0)
            order["revealed_size"] = 0.0
            order["visibility_score"] = 0.0

            placed_order_id = None
            try:
                placed_order_id = self.reveal_order_slice(stealth_order_id)
            except Exception as reveal_exc:
                self.log_callback(
                    "error",
                    {
                        "event": "cancel_reentry_reentry_failed",
                        "stealth_order_id": stealth_order_id,
                        "reason": evaluation.reason,
                        "error": str(reveal_exc),
                    },
                )

            if not placed_order_id:
                order["status"] = StealthOrderStatus.HIDDEN.value
                order["condition_confirmed_at"] = None
                order["cancel_reentry_state_json"] = (
                    state.to_cancel_reentry_runtime_state_dict()
                )
                self._update_stealth_order(order)
                return False

            fresh_order = self._get_stealth_order(stealth_order_id) or order
            policy_state = CancelReentryRuntimeState(
                state=CancelReentryState.RESTING,
                last_cancel_at=state.last_cancel_at,
                last_reentry_at=datetime.utcnow().isoformat(),
                reentry_count=state.reentry_count + 1,
                cancelled_placement_client_order_id=state.cancelled_placement_client_order_id,
                cancelled_exchange_order_id=state.cancelled_exchange_order_id,
                last_reason=evaluation.reason,
            )
            fresh_order["cancel_reentry_state_json"] = (
                policy_state.to_cancel_reentry_runtime_state_dict()
            )
            self._update_stealth_order(fresh_order)

            self.log_callback(
                "info",
                {
                    "event": "cancel_reentry_reentered",
                    "stealth_order_id": stealth_order_id,
                    "placement_client_order_id": placed_order_id,
                    "reference_price": evaluation.reference_price,
                    "distance": evaluation.distance,
                    "reason": evaluation.reason,
                    "reentry_count": policy_state.reentry_count,
                },
            )
            return True
        finally:
            self.release_mutation(StealthMutationKind.MOVE, stealth_order_id)

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
    # Action-condition guard (planning + reveal)
    # ------------------------------------------------------------------

    def _get_action_condition_guard_policy(self) -> Dict[str, Any]:
        """Return configured action-condition policy for account-level gates."""
        return get_action_condition_guard_policy(
            getattr(self, "action_condition_guard_policy", None)
        )

    @staticmethod
    def _rest_credentials_configured() -> bool:
        return rest_credentials_configured()

    def _get_account_wallets_for_action_guard(self) -> Dict[str, Any]:
        return fetch_account_wallets()

    def _get_spot_planned_budget_commitments(
        self,
        *,
        exclude_stealth_order_id: Optional[str] = None,
    ) -> Dict[str, float]:
        """Return local pre-exchange spot commitments by currency."""
        return collect_spot_planned_budget_commitments(
            getattr(self, "in_memory_orders", {}),
            exclude_stealth_order_id=exclude_stealth_order_id,
            product_metadata=PRODUCT_METADATA,
        )

    def _evaluate_spot_lot_authority_for_action(
        self,
        *,
        product_id: str,
        side: str,
        size: float,
        limit_price: float,
    ) -> Dict[str, Any]:
        """Return known-cost inventory authority for a spot sell action."""
        from business.spot_inventory_authority import (
            evaluate_spot_sell_lot_authority,
        )

        return evaluate_spot_sell_lot_authority(
            product_id=product_id,
            side=side,
            size=size,
            limit_price=limit_price,
            fill_ledger_repo=getattr(self, "fill_ledger_repo", None),
        ).to_dict()

    def _evaluate_action_condition_guard(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
        size: float,
        limit_price: float,
        stealth_order_id: Optional[str] = None,
        parent_order_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Evaluate account/action conditions for a planned or revealed action."""
        policy = self._get_action_condition_guard_policy()
        return ActionConditionGuard(
            policy=policy,
            credentials_configured=self._rest_credentials_configured,
            wallet_fetcher=self._get_account_wallets_for_action_guard,
            planned_budget_fetcher=(
                lambda: self._get_spot_planned_budget_commitments(
                    exclude_stealth_order_id=stealth_order_id,
                )
            ),
            lot_authority_evaluator=self._evaluate_spot_lot_authority_for_action,
        ).evaluate(
            phase=phase,
            product_id=product_id,
            side=side,
            size=size,
            limit_price=limit_price,
            stealth_order_id=stealth_order_id,
            parent_order_id=parent_order_id,
        )

    def _evaluate_replacement_action_condition_guard(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
        size: float,
        limit_price: float,
        existing_side: Optional[str] = None,
        existing_size: Optional[float] = None,
        existing_limit_price: Optional[float] = None,
        stealth_order_id: Optional[str] = None,
        parent_order_id: Optional[str] = None,
        replaced_client_order_id: Optional[str] = None,
        replaced_exchange_order_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Evaluate account/action conditions for a live replacement."""
        policy = self._get_action_condition_guard_policy()
        return ActionConditionGuard(
            policy=policy,
            credentials_configured=self._rest_credentials_configured,
            wallet_fetcher=self._get_account_wallets_for_action_guard,
            planned_budget_fetcher=(
                lambda: self._get_spot_planned_budget_commitments(
                    exclude_stealth_order_id=stealth_order_id,
                )
            ),
        ).evaluate_replacement(
            phase=phase,
            product_id=product_id,
            side=side,
            size=size,
            limit_price=limit_price,
            existing_side=existing_side,
            existing_size=existing_size,
            existing_limit_price=existing_limit_price,
            stealth_order_id=stealth_order_id,
            parent_order_id=parent_order_id,
            replaced_client_order_id=replaced_client_order_id,
            replaced_exchange_order_id=replaced_exchange_order_id,
        )

    def _get_action_guard_blocked_until(self, stealth_order_id: str) -> float:
        blocked_until = getattr(self, "_action_guard_blocked_until", None)
        if not isinstance(blocked_until, dict):
            blocked_until = {}
            self._action_guard_blocked_until = blocked_until
        return safe_float(blocked_until.get(stealth_order_id), default=0.0) or 0.0

    def _set_action_guard_blocked_until(self, stealth_order_id: str) -> None:
        policy = self._get_action_condition_guard_policy()
        wallet_policy = normalize_action_guard_wallet_policy(policy)
        retry_seconds = safe_float(
            wallet_policy.get("blocked_retry_seconds"),
            default=5.0,
        )
        retry_seconds = retry_seconds if retry_seconds and retry_seconds > 0 else 5.0
        blocked_until = getattr(self, "_action_guard_blocked_until", None)
        if not isinstance(blocked_until, dict):
            blocked_until = {}
            self._action_guard_blocked_until = blocked_until
        blocked_until[stealth_order_id] = time.monotonic() + retry_seconds

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
            self.logger.warning(
                f"[StealthOrderManager] _dispatch_lifecycle_event failed "
                f"({event}) for {stealth_order_id}: {exc}"
            )

    
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
        cancel_reentry_policy: Optional[Dict[str, Any]] = None,
        post_fill_retreat_policy: Optional[Dict[str, Any]] = None,
        require_persistence: bool = False,
    ) -> str:
        """
        Create an order with automated reveal condition.
        
        ARCHITECTURE: This is the canonical stealth-order creation path. Direct
        dashboard orders and portfolio sweep orders use their own guarded live
        placement entry points; stealth orders start in HIDDEN state pending
        their reveal condition being met.
        
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
            cancel_reentry_policy: Optional policy that cancels a revealed,
                                   zero-fill placement when it is too close to
                                   market and re-enters when safely away.
            post_fill_retreat_policy: Optional policy that lets this hidden
                                      order retreat when a same-product,
                                      same-side order fills.
            require_persistence: Require both the order_parent and
                                 stealth_orders rows before publishing the
                                 order to live in-memory evaluation.
            
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

        # Boundary validation: snap size to base_increment AND verify
        # base_min_size / quote_min_size before any DB write or in-memory
        # registration. Mirrors the price-quantize pattern used at reveal
        # time (_quantize_reprice_price) but for the size axis. Rejecting
        # here means an invalid size NEVER reaches the exchange and never
        # poisons the in-memory order map.
        from calculation.size_validation import validate_and_quantize_size
        from core.exceptions import OrderCreationError
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

        capability = evaluate_product_capability(
            product_id=product_id,
            capability=ProductCapability.STEALTH_PLANNING,
        )
        if not capability.allowed:
            raise OrderCreationError(
                "Stealth order rejected by product capability policy: "
                f"{capability.reason}",
                product_id=product_id,
                capability=capability.to_dict(),
            )

        normalized_cancel_reentry_policy = self._normalize_cancel_reentry_policy(cancel_reentry_policy)
        if normalized_cancel_reentry_policy.get("enabled"):
            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.CANCEL_REENTRY,
            )
            if not capability.allowed:
                raise OrderCreationError(
                    "Stealth order rejected by product capability policy: "
                    f"{capability.reason}",
                    product_id=product_id,
                    capability=capability.to_dict(),
                )

        if enable_hotpoint_replication:
            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.HOTPOINT_AUTO_PLACEMENT,
            )
            if not capability.allowed:
                raise OrderCreationError(
                    "Stealth order rejected by product capability policy: "
                    f"{capability.reason}",
                    product_id=product_id,
                    capability=capability.to_dict(),
                )

        action_guard_ok, action_guard_failure = self._evaluate_action_condition_guard(
            phase=ActionGuardPhase.PLANNING,
            product_id=product_id,
            side=side,
            size=float(total_size),
            limit_price=float(limit_price),
            stealth_order_id=stealth_order_id,
            parent_order_id=parent_order_id,
        )
        if not action_guard_ok:
            self.log_callback("warning", {
                "event": "stealth_order_planning_blocked_by_action_guard",
                **(action_guard_failure or {}),
            })
            raise OrderCreationError(
                "Stealth order rejected by action-condition guard: "
                f"{(action_guard_failure or {}).get('reason', 'blocked')}",
                product_id=product_id,
                guard=action_guard_failure,
            )

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
        normalized_post_fill_retreat_policy = self._normalize_post_fill_retreat_policy(post_fill_retreat_policy)

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
            "cancel_reentry_policy_json": normalized_cancel_reentry_policy,
            "cancel_reentry_state_json": self._normalize_cancel_reentry_state(None),
            "post_fill_retreat_policy_json": normalized_post_fill_retreat_policy,
        }
        
        def insert_tracking_row() -> Optional[int]:
            if parent_order_id:
                return insert_order_parent(
                    client_order_id=stealth_order_id,
                    product_id=product_id,
                    side=side,
                    size=total_size,
                    price=limit_price,
                    target_movement=target_movement,
                    target_movement_type=target_movement_type,
                    max_order_replacement=0,
                    current_order_replacement=0,
                    status=StealthOrderStatus.PENDING.value,
                    parent_order_id=parent_order_id,
                    allow_partial_fills=False,
                )

            effective_max_replacements = (
                max_order_replacements
                if max_order_replacements is not None
                else DEFAULT_MAX_ORDER_REPLACEMENT
            )
            return insert_order_parent(
                client_order_id=stealth_order_id,
                product_id=product_id,
                side=side,
                size=total_size,
                price=limit_price,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
                max_order_replacement=effective_max_replacements,
                current_order_replacement=0,
                status=StealthOrderStatus.PENDING.value,
                allow_partial_fills=allow_partial_fills,
                enable_hotpoint_replication=enable_hotpoint_replication,
            )

        if require_persistence:
            self._persist_new_stealth_order_strict(
                order_data,
                persist_rows=lambda: persist_filled_follow_up_atomic(
                    order=order_data,
                    target_movement=target_movement,
                    target_movement_type=target_movement_type,
                ),
            )
        else:
            # Legacy callers retain their best-effort behavior. FILLED
            # follow-ups opt into the strict path above.
            self.in_memory_orders[stealth_order_id] = order_data
            self._save_stealth_order_to_db(order_data)

        # 📊 LOT-TRACKING: Log stealth order creation
        reveal_type = reveal_condition.get("type", "time_delay")
        reveal_delay = reveal_condition.get("delay_seconds", 0) if reveal_type == "time_delay" else "N/A"
        self.log_callback("info", f"[LOT-TRACK] Stealth order created: {stealth_order_id} ({side} {total_size} {product_id} @ {limit_price}, reveal_type={reveal_type}, delay={reveal_delay}s)")

        # 🔔 LIFECYCLE HOOK: CREATED
        self._dispatch_lifecycle_event(
            stealth_order_id=stealth_order_id,
            event=StealthLifecycleEvent.CREATED,
            order_data=order_data,
        )

        # Strict creation already wrote both rows before publishing to memory.
        if not require_persistence:
            insert_tracking_row()
        
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
        condition_met, reason = evaluate_stealth_reveal_condition(
            evaluator,
            market_data,
            condition_config,
            order,
        )
        
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
        
        if order["status"] in [StealthOrderStatus.EXECUTED.value, StealthOrderStatus.CANCELLED.value]:
            return False, f"Order already {order['status']}"

        cancel_reentry_state = (
            CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
                order.get("cancel_reentry_state_json")
            )
        )
        if cancel_reentry_state.state == CancelReentryState.CANCELLED_BY_POLICY:
            return False, "Order is waiting for cancel/re-entry threshold"
        
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

    def _build_reveal_order_submission_payload(
        self,
        *,
        order: Dict[str, Any],
        stealth_order_id: str,
        reveal_plan: Any,
        slice_size: float,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """Build the canonical payload handed to reveal placement hooks.

        This is deliberately side-effect-free. The reveal path owns all state
        mutation and exchange submission; this helper only names the boundary
        between reveal planning and the placement attempt.
        """
        condition_confirmed_at = order.get("condition_confirmed_at")
        if hasattr(condition_confirmed_at, "isoformat"):
            condition_confirmed_at = condition_confirmed_at.isoformat()

        return {
            "product_id": order["product_id"],
            "side": order["side"],
            "limit_price": reveal_plan.submitted_limit_price,
            "base_size": slice_size,
            "client_order_id": client_order_id,
            "post_only": bool(getattr(reveal_plan, "post_only", False)),
            "stealth_order_id": stealth_order_id,
            "parent_order_id": order.get("parent_order_id"),
            "reason": order.get("reason"),
            "reveal_number": len(order.get("revealed_orders", [])) + 1,
            "reveal_condition_type": order.get("reveal_condition_type"),
            # Hooks receive a mutable payload. Keep durable reveal policy and
            # condition evidence isolated from hook-side enrichment/removal.
            "reveal_condition_json": copy.deepcopy(
                order.get("reveal_condition_json")
            ),
            "condition_confirmed_at": condition_confirmed_at,
            "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
            "reveal_price_source": reveal_plan.reveal_price_source,
        }

    def prepare_controlled_admin_first_child_reveal(
        self,
        *,
        stealth_order_id: str,
        expected_root_client_order_id: str,
        expected_portfolio_id: str,
        submitted_limit_price: float,
        max_notional_usdc: float,
        market_bid: str,
        market_source: str,
        market_observed_at: datetime,
        approval_snapshot_id: str,
        admission_audit_id: str,
        cap_guard_decision_id: str,
        reconciliation_plan_id: str,
        batch_id: str,
        batch_slot: int,
        expected_prior_preparation_sha256: Optional[str] = None,
        controlled_plan_sha256: Optional[str] = None,
    ) -> ControlledAdminChildRevealAuthority:
        """Durably prepare and authorize one far-price first Admin child.

        The database transaction owns the authoritative validation and price
        rewrite. The cache is changed only after that transaction commits.
        Returning a one-call object does not itself reveal or place the order.
        """

        child_id = str(stealth_order_id or "").strip()
        root_id = str(expected_root_client_order_id or "").strip()
        portfolio_id = str(expected_portfolio_id or "").strip()
        manager_portfolio_id = str(
            getattr(self, "expected_retail_portfolio_id", None) or ""
        ).strip()
        if not manager_portfolio_id or portfolio_id != manager_portfolio_id:
            raise OrderPersistenceError(
                error_type="ControlledAdminChildPortfolioScopeMismatch",
                message=(
                    "controlled Admin child portfolio must exactly match the "
                    "manager Test portfolio scope"
                ),
                operation="update",
                table="order_parent,stealth_orders",
                client_order_id=child_id,
                stealth_order_id=child_id,
            )

        order = self._get_stealth_order(child_id)
        if not isinstance(order, dict):
            raise OrderPersistenceError(
                error_type="ControlledAdminChildNotLoaded",
                message="controlled Admin child is not loaded",
                operation="update",
                table="stealth_orders",
                client_order_id=child_id,
                stealth_order_id=child_id,
            )
        if (
            str(order.get("stealth_order_id") or "") != child_id
            or str(order.get("parent_order_id") or "") != root_id
            or str(order.get("product_id") or "") != "BTC-USDC"
            or str(order.get("side") or "").upper() != OrderSide.SELL.value
            or str(order.get("status") or "").upper()
            not in {
                StealthOrderStatus.HIDDEN.value,
                StealthOrderStatus.PENDING.value,
                StealthOrderStatus.TRIGGERED.value,
            }
            or list(order.get("revealed_orders") or [])
            or (safe_float(order.get("revealed_size"), default=0.0) or 0.0)
            != 0.0
            or (safe_float(order.get("executed_size"), default=0.0) or 0.0)
            != 0.0
            or abs(
                (safe_float(order.get("remaining_size"), default=0.0) or 0.0)
                - (safe_float(order.get("total_size"), default=0.0) or 0.0)
            )
            > 1e-12
        ):
            raise OrderPersistenceError(
                error_type="ControlledAdminChildMemoryStateMismatch",
                message=(
                    "controlled Admin child cache is not the exact hidden, "
                    "unsubmitted first child"
                ),
                operation="update",
                table="stealth_orders",
                client_order_id=child_id,
                stealth_order_id=child_id,
            )

        quote_increment = self._get_price_increment("BTC-USDC")
        if not quote_increment:
            raise OrderPersistenceError(
                error_type="ControlledAdminChildIncrementMissing",
                message="BTC-USDC quote increment is unavailable",
                operation="update",
                table="stealth_orders",
                client_order_id=child_id,
                stealth_order_id=child_id,
            )

        authority_id = str(uuid.uuid4())
        prepared = prepare_controlled_admin_first_child_reveal_atomic(
            stealth_order_id=child_id,
            expected_root_client_order_id=root_id,
            expected_portfolio_id=portfolio_id,
            submitted_limit_price=submitted_limit_price,
            quote_increment=quote_increment,
            max_notional_usdc=max_notional_usdc,
            market_bid=market_bid,
            market_source=market_source,
            market_observed_at=market_observed_at,
            approval_snapshot_id=approval_snapshot_id,
            admission_audit_id=admission_audit_id,
            cap_guard_decision_id=cap_guard_decision_id,
            reconciliation_plan_id=reconciliation_plan_id,
            batch_id=batch_id,
            batch_slot=batch_slot,
            authority_id=authority_id,
            expected_prior_preparation_sha256=(
                expected_prior_preparation_sha256
            ),
            controlled_plan_sha256=controlled_plan_sha256,
        )

        prepared_price = float(prepared["prepared_limit_price"])
        prepared_condition = copy.deepcopy(prepared["reveal_condition_json"])
        prepared_state = copy.deepcopy(prepared["anchor_repricing_state_json"])
        # Durable success is established above. Only now publish the exact
        # prepared facts to the manager cache.
        order["limit_price"] = prepared_price
        order["status"] = StealthOrderStatus.HIDDEN.value
        order["reveal_condition_json"] = prepared_condition
        order["anchor_repricing_state_json"] = prepared_state
        order["condition_first_met_at"] = None
        order["condition_confirmed_at"] = None
        order["updated_at"] = datetime.utcnow()

        authority = ControlledAdminChildRevealAuthority(
            stealth_order_id=child_id,
            root_client_order_id=root_id,
            prepared_limit_price=prepared_price,
            total_size=float(order["total_size"]),
            reference_notional_usdc=float(prepared["reference_notional_usdc"]),
            market_bid=str(prepared["market_bid"]),
            market_source=str(prepared["market_source"]),
            market_observed_at=prepared["market_observed_at"],
            portfolio_id=str(prepared["portfolio_id"]),
            correlation_id=str(prepared["correlation_id"]),
            root_audit_id=str(prepared["root_audit_id"]),
            authority_id=authority_id,
            approval_snapshot_id=str(approval_snapshot_id),
            admission_audit_id=str(admission_audit_id),
            cap_guard_decision_id=str(cap_guard_decision_id),
            reconciliation_plan_id=str(reconciliation_plan_id),
            batch_id=str(batch_id),
            batch_slot=batch_slot,
            controlled_plan_sha256=prepared.get("controlled_plan_sha256"),
        )
        issued = getattr(
            self, "_controlled_admin_child_reveal_authorities", None
        )
        if not isinstance(issued, dict):
            issued = {}
            self._controlled_admin_child_reveal_authorities = issued
        issued[authority_id] = authority
        return authority

    def _consume_controlled_admin_child_reveal_authority(
        self,
        *,
        stealth_order_id: str,
        order: Dict[str, Any],
        authority: Optional[ControlledAdminChildRevealAuthority],
    ) -> Tuple[bool, Optional[str]]:
        """Consume and validate one manager-issued exact-child capability."""

        preparation = (
            (order.get("anchor_repricing_state_json") or {}).get(
                "controlled_admin_first_child_reveal_preparation"
            )
            or {}
        )
        if not isinstance(preparation, dict) or not preparation:
            return False, "controlled_admin_child_not_prepared"
        if authority is None:
            return False, "controlled_admin_authority_required"
        if not isinstance(authority, ControlledAdminChildRevealAuthority):
            return False, "controlled_admin_authority_type_mismatch"

        issued = getattr(
            self, "_controlled_admin_child_reveal_authorities", None
        )
        issued = issued if isinstance(issued, dict) else {}
        registered = issued.pop(authority.authority_id, None)
        if registered is not authority:
            return False, "controlled_admin_authority_not_issued"

        try:
            authority_market_bid = Decimal(str(authority.market_bid))
        except (InvalidOperation, TypeError, ValueError):
            return False, "controlled_admin_authority_market_bid_invalid"
        if not authority_market_bid.is_finite() or authority_market_bid <= 0:
            return False, "controlled_admin_authority_market_bid_invalid"
        if authority.market_source not in SPOT_STANDING_MARKET_SOURCES:
            return False, "controlled_admin_authority_market_source_invalid"
        if (
            not isinstance(authority.market_observed_at, datetime)
            or authority.market_observed_at.tzinfo is None
            or authority.market_observed_at.utcoffset() is None
        ):
            return False, "controlled_admin_authority_market_timestamp_invalid"
        authority_market_observed_at = authority.market_observed_at.astimezone(
            timezone.utc
        )

        controlled_plan_sha256 = authority.controlled_plan_sha256
        if controlled_plan_sha256 is not None and (
            not isinstance(controlled_plan_sha256, str)
            or len(controlled_plan_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in controlled_plan_sha256
            )
        ):
            return False, "controlled_admin_authority_plan_invalid"
        if preparation.get("controlled_plan_sha256") != controlled_plan_sha256:
            return False, "controlled_admin_authority_plan_mismatch"

        expected_fields = {
            "authority_id": authority.authority_id,
            "approval_snapshot_id": authority.approval_snapshot_id,
            "admission_audit_id": authority.admission_audit_id,
            "cap_guard_decision_id": authority.cap_guard_decision_id,
            "reconciliation_plan_id": authority.reconciliation_plan_id,
            "batch_id": authority.batch_id,
            "batch_slot": authority.batch_slot,
            "root_client_order_id": authority.root_client_order_id,
            "stealth_order_id": authority.stealth_order_id,
            "portfolio_id": authority.portfolio_id,
            "correlation_id": authority.correlation_id,
            "root_audit_id": authority.root_audit_id,
            "market_bid": authority.market_bid,
            "market_source": authority.market_source,
            "market_observed_at": authority_market_observed_at.isoformat(),
        }
        if any(preparation.get(key) != value for key, value in expected_fields.items()):
            return False, "controlled_admin_authority_audit_mismatch"
        if (
            authority.stealth_order_id != stealth_order_id
            or str(order.get("stealth_order_id") or "") != stealth_order_id
            or str(order.get("parent_order_id") or "")
            != authority.root_client_order_id
            or str(order.get("product_id") or "") != "BTC-USDC"
            or str(order.get("side") or "").upper() != OrderSide.SELL.value
            or str(order.get("status") or "").upper()
            != StealthOrderStatus.HIDDEN.value
            or list(order.get("revealed_orders") or [])
            or (safe_float(order.get("revealed_size"), default=0.0) or 0.0)
            != 0.0
            or (safe_float(order.get("executed_size"), default=0.0) or 0.0)
            != 0.0
            or abs(
                (safe_float(order.get("remaining_size"), default=0.0) or 0.0)
                - authority.total_size
            )
            > 1e-12
            or abs(
                (safe_float(order.get("limit_price"), default=0.0) or 0.0)
                - authority.prepared_limit_price
            )
            > 1e-12
            or abs(
                (
                    safe_float(
                        (order.get("reveal_condition_json") or {}).get(
                            "price_threshold"
                        ),
                        default=0.0,
                    )
                    or 0.0
                )
                - authority.prepared_limit_price
            )
            > 1e-12
        ):
            return False, "controlled_admin_authority_order_mismatch"
        return True, None

    def _resolve_admin_fill_follow_up_reveal_authority(
        self,
        *,
        stealth_order_id: str,
        order: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve immutable authority for an automatic Admin fill child.

        Mutable reveal-condition JSON is not ownership proof. The child must
        have the dedicated durable provenance, link to an Admin manual root,
        inherit the root's exact Test portfolio and trace fields, and retain
        the named standing-price policy. Missing/legacy evidence fails closed
        for any row related to this Admin chain.
        """

        parent_order_id = str(order.get("parent_order_id") or "").strip()
        marker = str(
            (order.get("reveal_condition_json") or {}).get(
                "standing_price_limit_policy"
            )
            or ""
        )
        child_row = None
        root_row = None
        ownership_read_error = None
        try:
            child_row = get_parent_order(stealth_order_id)
            if parent_order_id:
                root_row = get_parent_order(parent_order_id)
        except Exception as exc:
            ownership_read_error = type(exc).__name__

        child_row = child_row if isinstance(child_row, dict) else None
        root_row = root_row if isinstance(root_row, dict) else None
        child_provenance = str(
            (child_row or {}).get("ownership_provenance") or ""
        )
        root_provenance = str(
            (root_row or {}).get("ownership_provenance") or ""
        )
        expected_portfolio_id = str(
            getattr(self, "expected_retail_portfolio_id", None) or ""
        ).strip()
        required = bool(
            expected_portfolio_id
            or marker
            or child_provenance
            == OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
            or root_provenance
            == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            or (parent_order_id and ownership_read_error)
        )
        if not required:
            return {
                "required": False,
                "ready": True,
                "blockers": [],
                "policy": marker or None,
                "child_ownership_provenance": child_provenance or None,
                "root_ownership_provenance": root_provenance or None,
            }

        blockers: list[str] = []
        if ownership_read_error:
            blockers.append("admin_child_ownership_read_unavailable")
        if child_row is None:
            blockers.append("admin_child_order_parent_missing")
        if root_row is None:
            blockers.append("admin_child_root_order_parent_missing")
        if marker == "":
            blockers.append("admin_child_standing_price_policy_missing")
        elif marker != StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value:
            blockers.append("admin_child_standing_price_policy_mismatch")
        if child_provenance != (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        ):
            blockers.append("admin_child_ownership_provenance_mismatch")
        if root_provenance != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value:
            blockers.append("admin_child_root_ownership_provenance_mismatch")

        child_portfolio_id = str(
            (child_row or {}).get("retail_portfolio_id") or ""
        ).strip()
        root_portfolio_id = str(
            (root_row or {}).get("retail_portfolio_id") or ""
        ).strip()
        if not expected_portfolio_id:
            blockers.append("admin_child_expected_portfolio_scope_missing")
        elif (
            child_portfolio_id != expected_portfolio_id
            or root_portfolio_id != expected_portfolio_id
        ):
            blockers.append("admin_child_portfolio_scope_mismatch")

        child_correlation_id = str(
            (child_row or {}).get("correlation_id") or ""
        ).strip()
        root_correlation_id = str(
            (root_row or {}).get("correlation_id") or ""
        ).strip()
        child_audit_id = str((child_row or {}).get("audit_id") or "").strip()
        root_audit_id = str((root_row or {}).get("audit_id") or "").strip()
        if (
            not child_correlation_id
            or child_correlation_id != root_correlation_id
        ):
            blockers.append("admin_child_correlation_trace_mismatch")
        if not child_audit_id or child_audit_id != root_audit_id:
            blockers.append("admin_child_audit_trace_mismatch")

        child_parent_id = str(
            (child_row or {}).get("parent_order_id") or ""
        ).strip()
        if not parent_order_id or child_parent_id != parent_order_id:
            blockers.append("admin_child_flat_root_link_mismatch")
        if (root_row or {}).get("parent_order_id"):
            blockers.append("admin_child_root_is_nested")

        product_id = str(order.get("product_id") or "")
        side = str(order.get("side") or "").upper()
        total_size = safe_float(order.get("total_size"), default=0.0) or 0.0
        limit_price = safe_float(order.get("limit_price"), default=0.0) or 0.0
        if (
            str((child_row or {}).get("product_id") or "") != product_id
            or str((root_row or {}).get("product_id") or "") != product_id
        ):
            blockers.append("admin_child_product_scope_mismatch")
        if str((child_row or {}).get("side") or "").upper() != side:
            blockers.append("admin_child_side_mismatch")
        if abs(
            (safe_float((child_row or {}).get("size"), default=0.0) or 0.0)
            - total_size
        ) > 1e-12:
            blockers.append("admin_child_size_mismatch")
        if abs(
            (safe_float((child_row or {}).get("price"), default=0.0) or 0.0)
            - limit_price
        ) > 1e-12:
            blockers.append("admin_child_limit_price_mismatch")

        return {
            "required": True,
            "ready": not blockers,
            "blockers": blockers,
            "policy": marker or None,
            "expected_portfolio_id": expected_portfolio_id or None,
            "child_portfolio_id": child_portfolio_id or None,
            "root_portfolio_id": root_portfolio_id or None,
            "child_ownership_provenance": child_provenance or None,
            "root_ownership_provenance": root_provenance or None,
            "child_client_order_id": stealth_order_id,
            "root_client_order_id": parent_order_id or None,
        }

    def _record_admin_fill_follow_up_reveal_block(
        self,
        *,
        stealth_order_id: str,
        order: Dict[str, Any],
        block_category: str,
        failure_reason: str,
        evidence: Dict[str, Any],
        standing_price_limit: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist and emit one throttled pre-exchange Admin-child blocker."""

        state = dict(order.get("anchor_repricing_state_json") or {})
        decision = {
            "block_category": block_category,
            "failure_reason": failure_reason,
            "evidence": evidence,
        }
        if standing_price_limit is not None:
            decision["standing_price_limit"] = standing_price_limit
            state["standing_price_limit_policy"] = (
                StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value
            )
            state["standing_price_limit"] = standing_price_limit
            state["standing_price_limit_blocker"] = block_category

        repeated_decision = state.get("admin_fill_follow_up_reveal_block") == decision
        state["admin_fill_follow_up_reveal_block"] = decision
        order["anchor_repricing_state_json"] = state
        order["failure_reason"] = failure_reason
        order["last_lifecycle_event"] = (
            StealthLifecycleEvent.PLACEMENT_BLOCKED.value
        )
        self._set_action_guard_blocked_until(stealth_order_id)
        # Retry persistence even for an identical in-memory decision. A prior
        # database failure must not make the blocker permanently memory-only.
        self._update_stealth_order(order)
        if repeated_decision:
            return
        self.log_callback(
            "warning",
            {
                "event": "admin_fill_follow_up_reveal_blocked",
                "stealth_order_id": stealth_order_id,
                "block_category": block_category,
                "failure_reason": failure_reason,
                "evidence": evidence,
                "standing_price_limit": standing_price_limit,
            },
        )
        lifecycle_extra = {
            "failure_reason": failure_reason,
            "block_category": block_category,
            "admin_fill_follow_up_reveal_authority": evidence,
        }
        if standing_price_limit is not None:
            lifecycle_extra.update(
                {
                    "standing_price_limit_policy": (
                        StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value
                    ),
                    "standing_price_limit": standing_price_limit,
                }
            )
        self._dispatch_lifecycle_event(
            stealth_order_id=stealth_order_id,
            event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
            order_data=order,
            extra=lifecycle_extra,
        )

    def _clear_admin_fill_follow_up_reveal_block(
        self,
        *,
        stealth_order_id: str,
        order: Dict[str, Any],
    ) -> None:
        """Clear stale pre-exchange blocker evidence after confirmed placement."""

        state = dict(order.get("anchor_repricing_state_json") or {})
        for key in (
            "admin_fill_follow_up_reveal_block",
            "standing_price_limit_policy",
            "standing_price_limit",
            "standing_price_limit_blocker",
        ):
            state.pop(key, None)
        order["anchor_repricing_state_json"] = state
        order["failure_reason"] = None
        order["last_lifecycle_event"] = (
            StealthLifecycleEvent.REVEAL_SUCCEEDED.value
        )
        blocked_until = getattr(self, "_action_guard_blocked_until", None)
        if isinstance(blocked_until, dict):
            blocked_until.pop(stealth_order_id, None)

    def reveal_order_slice(
        self,
        stealth_order_id: str,
        *,
        controlled_admin_authority: Optional[
            ControlledAdminChildRevealAuthority
        ] = None,
    ) -> Optional[str]:
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
            controller = get_runtime_controller()
            controller.check_admission(INFLIGHT_REST_PLACE)
            order = self._get_stealth_order(stealth_order_id)
            
            if not order:
                raise RevealOrderSliceError(
                    f"Stealth order not found: {stealth_order_id}"
                )

            controlled_preparation = (
                (order.get("anchor_repricing_state_json") or {}).get(
                    "controlled_admin_first_child_reveal_preparation"
                )
                or None
            )
            controlled_capability_bypass = False
            if (
                controlled_preparation is not None
                or controlled_admin_authority is not None
            ):
                (
                    controlled_capability_bypass,
                    controlled_authority_blocker,
                ) = self._consume_controlled_admin_child_reveal_authority(
                    stealth_order_id=stealth_order_id,
                    order=order,
                    authority=controlled_admin_authority,
                )
                if not controlled_capability_bypass:
                    self._record_admin_fill_follow_up_reveal_block(
                        stealth_order_id=stealth_order_id,
                        order=order,
                        block_category=str(
                            controlled_authority_blocker
                            or "controlled_admin_authority_rejected"
                        ),
                        failure_reason=(
                            "Controlled Admin child reveal requires the exact "
                            "unused one-call manager authority; the child "
                            "remains pre-exchange."
                        ),
                        evidence={
                            "controlled_preparation": controlled_preparation,
                            "controlled_authority_blocker": (
                                controlled_authority_blocker
                            ),
                        },
                    )
                    return None
            
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

            blocked_until = self._get_action_guard_blocked_until(stealth_order_id)
            if (
                blocked_until > time.monotonic()
                and not controlled_capability_bypass
            ):
                return None

            admin_child_authority = (
                self._resolve_admin_fill_follow_up_reveal_authority(
                    stealth_order_id=stealth_order_id,
                    order=order,
                )
            )
            if (
                admin_child_authority.get("required")
                and not admin_child_authority.get("ready")
            ):
                authority_blockers = list(
                    admin_child_authority.get("blockers") or []
                )
                block_category = (
                    str(authority_blockers[0])
                    if authority_blockers
                    else "admin_child_reveal_authority_missing"
                )
                self._record_admin_fill_follow_up_reveal_block(
                    stealth_order_id=stealth_order_id,
                    order=order,
                    block_category=block_category,
                    failure_reason=(
                        "Automatic Admin fill child lacks immutable root/child "
                        "ownership, Test portfolio, trace, or standing-policy "
                        "evidence; the child remains pre-exchange."
                    ),
                    evidence=admin_child_authority,
                )
                return None

            if (
                admin_child_authority.get("required")
                and not controlled_capability_bypass
            ):
                self._record_admin_fill_follow_up_reveal_block(
                    stealth_order_id=stealth_order_id,
                    order=order,
                    block_category="controlled_admin_authority_required",
                    failure_reason=(
                        "Every Admin fill-follow-up exchange submission requires "
                        "the exact unused one-call controlled authority; ordinary "
                        "automatic and later-generation children remain hidden."
                    ),
                    evidence=admin_child_authority,
                )
                return None

            capability = evaluate_product_capability(
                product_id=order["product_id"],
                capability=ProductCapability.STEALTH_REVEAL,
            )
            if not capability.allowed and not controlled_capability_bypass:
                self.log_callback("warning", {
                    "event": "stealth_order_reveal_blocked_by_product_capability",
                    **capability.to_dict(),
                    "stealth_order_id": stealth_order_id,
                })
                self._dispatch_lifecycle_event(
                    stealth_order_id=stealth_order_id,
                    event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                    order_data=order,
                    extra={
                        "failure_reason": capability.reason,
                        **capability.to_dict(),
                    },
                )
                return None

            action_guard_ok, action_guard_failure = self._evaluate_action_condition_guard(
                phase=ActionGuardPhase.REVEAL,
                product_id=order["product_id"],
                side=order["side"],
                size=float(slice_size),
                limit_price=float(reveal_plan.submitted_limit_price),
                stealth_order_id=stealth_order_id,
                parent_order_id=order.get("parent_order_id"),
            )
            if not action_guard_ok:
                self._set_action_guard_blocked_until(stealth_order_id)
                self.log_callback("warning", {
                    "event": "stealth_order_reveal_blocked_by_action_guard",
                    **(action_guard_failure or {}),
                })
                self._dispatch_lifecycle_event(
                    stealth_order_id=stealth_order_id,
                    event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                    order_data=order,
                    extra={
                        "failure_reason": (
                            action_guard_failure or {}
                        ).get("reason", "action-condition guard blocked reveal"),
                        **(action_guard_failure or {}),
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
        
        # Place actual limit order on exchange (NOT stealth - this IS the revealed placement)
        # Use REST API directly - DO NOT create another stealth order!
        placed_order_id = None
        placement_success = False
        placement_error = None
        exchange_order_id = None
        client_order_id = None
        exchange_placement_succeeded = False
        
        # Get full market data (includes price, volume, source) - separate from plan's pricing decision
        market_data = self._get_current_market_data(order["product_id"]) or {}
        market_bid = reveal_plan.market_bid or market_data.get("bid")
        market_ask = reveal_plan.market_ask or market_data.get("ask")
        market_spread = None
        if market_bid is not None and market_ask is not None:
            try:
                market_spread = float(market_ask) - float(market_bid)
            except (TypeError, ValueError):
                market_spread = None
        
        try:
            from configuration import REST_CLIENT
            
            client_order_id = self._placement_client_order_id_for_order(order)
            
            order_for_submission = self._build_reveal_order_submission_payload(
                order=order,
                stealth_order_id=stealth_order_id,
                reveal_plan=reveal_plan,
                slice_size=slice_size,
                client_order_id=client_order_id,
            )
            # Capture the durable direct-child policy before extension hooks.
            # The hook payload intentionally contains the reveal-condition
            # mapping for enrichment, so reading the policy from ``order``
            # after hooks would let an in-process mutation remove the guard.
            standing_price_policy = str(
                (order.get("reveal_condition_json") or {}).get(
                    "standing_price_limit_policy"
                )
                or ""
            )
            immutable_submission_fields = {
                "product_id": str(order_for_submission.get("product_id") or ""),
                "side": str(order_for_submission.get("side") or "").upper(),
                "base_size": safe_float(
                    order_for_submission.get("base_size"), default=0.0
                ),
                "limit_price": safe_float(
                    order_for_submission.get("limit_price"), default=0.0
                ),
                "client_order_id": str(
                    order_for_submission.get("client_order_id") or ""
                ),
                "post_only": bool(order_for_submission.get("post_only")),
                "stealth_order_id": str(
                    order_for_submission.get("stealth_order_id") or ""
                ),
                "parent_order_id": str(
                    order_for_submission.get("parent_order_id") or ""
                ),
            }
            
            # 🪝 PRE-SUBMISSION HOOKS: Validate/modify order before REST submission
            # Extensions can raise exceptions to block placement or modify order fields
            try:
                self.order_placement_hooks.call_pre_submission_hooks(order_for_submission)
            except Exception as hook_error:
                # Hook validation failed - don't submit order
                placed_order_id = str(uuid.uuid4())  # Fallback for tracking
                placement_error = f"Pre-submission hook blocked: {str(hook_error)}"
                placement_success = False
                
                self.log_callback("warning", {
                    "event": "stealth_order_submission_blocked_by_hook",
                    "stealth_order_id": stealth_order_id,
                    "size": slice_size,
                    "product_id": order["product_id"],
                    "block_reason": placement_error,
                })

                # 🔔 LIFECYCLE HOOK: PLACEMENT_BLOCKED
                self._dispatch_lifecycle_event(
                    stealth_order_id=stealth_order_id,
                    event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                    order_data=order,
                    extra={"failure_reason": placement_error, "size": slice_size},
                )
                
                # Record the blocked reveal event and return
                reveal_event = {
                    "reveal_number": len(order["revealed_orders"]) + 1,
                    "revealed_size": 0,  # No size placed
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

            if admin_child_authority.get("required"):
                observed_submission_fields = {
                    "product_id": str(
                        order_for_submission.get("product_id") or ""
                    ),
                    "side": str(
                        order_for_submission.get("side") or ""
                    ).upper(),
                    "base_size": safe_float(
                        order_for_submission.get("base_size"), default=0.0
                    ),
                    "limit_price": safe_float(
                        order_for_submission.get("limit_price"), default=0.0
                    ),
                    "client_order_id": str(
                        order_for_submission.get("client_order_id") or ""
                    ),
                    "post_only": bool(order_for_submission.get("post_only")),
                    "stealth_order_id": str(
                        order_for_submission.get("stealth_order_id") or ""
                    ),
                    "parent_order_id": str(
                        order_for_submission.get("parent_order_id") or ""
                    ),
                }
                drifted_fields = sorted(
                    field
                    for field, expected_value in immutable_submission_fields.items()
                    if observed_submission_fields.get(field) != expected_value
                )
                if drifted_fields:
                    drift_evidence = {
                        **admin_child_authority,
                        "drifted_fields": drifted_fields,
                        "expected_submission_fields": immutable_submission_fields,
                        "observed_submission_fields": observed_submission_fields,
                    }
                    self._record_admin_fill_follow_up_reveal_block(
                        stealth_order_id=stealth_order_id,
                        order=order,
                        block_category="admin_child_submission_payload_drift",
                        failure_reason=(
                            "A pre-submission hook changed immutable Admin fill "
                            "child exchange fields after cap/wallet admission; "
                            "the child remains pre-exchange."
                        ),
                        evidence=drift_evidence,
                    )
                    return None
                if (
                    standing_price_policy
                    != StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value
                    or str(order_for_submission.get("reveal_pricing_policy") or "")
                    != RevealPricingPolicy.CONFIGURED_LIMIT.value
                    or bool(order_for_submission.get("post_only"))
                ):
                    plan_evidence = {
                        **admin_child_authority,
                        "reveal_pricing_policy": order_for_submission.get(
                            "reveal_pricing_policy"
                        ),
                        "post_only": bool(order_for_submission.get("post_only")),
                    }
                    self._record_admin_fill_follow_up_reveal_block(
                        stealth_order_id=stealth_order_id,
                        order=order,
                        block_category="admin_child_reveal_plan_not_authorized",
                        failure_reason=(
                            "Automatic Admin fill children require one immutable "
                            "configured-limit attempt; post-only retry semantics "
                            "are not authorized for this slice."
                        ),
                        evidence=plan_evidence,
                    )
                    return None
            
            # ─────────────────────────────────────────────────────────────────
            # PRE-REST: Persist order_parent row with the correct chain link
            # BEFORE submitting to the exchange. The WS confirmation for this
            # placement can race the post-REST code path (observed 2026-04-29:
            # user_event_thread_0 fell into OrderEngine.resolve_parent_client_order_id
            # `create_parent=True` branch and inserted f6281a12 as a ROOT row
            # with parent_order_id=NULL and max_order_replacement=101 BEFORE the
            # stealth manager's post-REST insert ran — the latter then hit a
            # UniqueViolation and the chain link was permanently lost).
            #
            # Inserting first guarantees:
            #   * parent_order_id is set to the resolved chain root
            #   * max_order_replacement / target_movement inherited from stealth
            #   * any racing WS-side resolve_parent_client_order_id call sees an
            #     existing row (insert_order_parent is idempotent) and no-ops
            #
            # On REST failure below we update the row to FAILED rather than
            # leaving a phantom PENDING row.
            # ─────────────────────────────────────────────────────────────────
            # ─── PLACEMENT PRE-INSERT (CHAIN LINKAGE) ───────────────────────
            # We pre-insert the order_parent row BEFORE each REST attempt so
            # the WS user-channel handler (which fires almost simultaneously
            # with REST return) finds an existing chain-linked row and does
            # NOT fall back to inserting it as a NEW ROOT. Inserting as root
            # orphans the placement from its stealth chain — see 2026-05-01
            # incident: post-only retry generated a fresh COID, no pre-insert
            # ran for the new COID, and the WS handler created a root row
            # (DB ID 64) instead of linking to chain root e30d58d8.
            #
            # The pre-insert is skipped when the placement COID equals the
            # stealth_order_id (no-reprice policy) — that path lets the WS
            # handler resolve the chain via stealth_order_id directly.
            #
            # Inside the retry loop we re-pre-insert for each NEW retry COID
            # and mark previous-attempt pre-inserts FAILED so the audit table
            # reflects what actually happened on the exchange.
            # ────────────────────────────────────────────────────────────────
            placement_pre_inserted = False
            pre_inserted_attempt_coids: set[str] = set()
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
                """Pre-insert an order_parent row for ``coid`` at ``price``.

                Returns True on success. Failures are logged and treated
                as non-fatal (a racing WS-side insert may already have
                created the row).
                """
                if coid == stealth_order_id:
                    return False
                if root_parent_for_placement is None:
                    return False
                try:
                    insert_order_parent(
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
                    pre_inserted_attempt_coids.add(coid)
                    return True
                except Exception as parent_insert_error:
                    self.log_callback(
                        "warning",
                        {
                            "event": "reveal_placement_order_parent_pre_insert_failed",
                            "stealth_order_id": stealth_order_id,
                            "placement_client_order_id": coid,
                            "error": str(parent_insert_error),
                        },
                    )
                    return False

            # Place order directly on the exchange via REST API
            # ⚠️ CRITICAL: Do NOT call create_limit_order_span() here as it creates another stealth order!
            # Use REST_CLIENT.place_limit_order() which is purpose-built for this
            # Tracked as in-flight so a concurrent drain waits for the placement
            # to settle before transitioning to STOPPED.
            #
            # exchange_placement_succeeded is the truthful indicator of
            # whether the order actually reached the exchange. It flips True
            # only after place_limit_order returns a successful placement; a
            # raised REST exception or rejected response must not drive live
            # placement bookkeeping. Any exception AFTER this point (audit-row
            # insert, hook, lifecycle dispatch) is post-placement bookkeeping
            # that must NOT be reported as "order was not placed".
            # See 2026-04-29 incident: a stale Order.from_dict shim was raising
            # post-REST and the exception handler logged the misleading
            # "Order was NOT placed" while the order was actually live and filling.
            # POST-ONLY RETRY LOOP
            # When post_only=True (TOP_OF_BOOK / MIDPOINT reveals) the
            # exchange will reject any limit that would cross the spread
            # with ``failure_reason == "POST_ONLY"``. We do NOT silently
            # demote to a taker fill (that would betray the operator's
            # post-only intent and charge the wrong fee tier). Instead
            # we reprice ONE tick safer (away from the touch) and retry
            # up to ``POST_ONLY_MAX_ATTEMPTS`` times.  On exhaustion we
            # surface ``PLACEMENT_BLOCKED`` and let the caller handle it
            # (no fallback to post_only=False).
            #
            # When post_only=False (CONFIGURED_LIMIT) we make exactly
            # one attempt and the existing error handling applies.
            retry_post_only = bool(order_for_submission.get("post_only"))
            max_attempts = self.POST_ONLY_MAX_ATTEMPTS if retry_post_only else 1
            attempt_price = float(order_for_submission["limit_price"])
            attempt_coid = order_for_submission["client_order_id"]
            price_increment = self._get_price_increment(order_for_submission["product_id"])
            order_result = None
            post_only_attempts = []
            for attempt_num in range(1, max_attempts + 1):
                if admin_child_authority.get("required"):
                    final_guard_ok, final_guard_failure = (
                        self._evaluate_action_condition_guard(
                            phase=ActionGuardPhase.REVEAL,
                            product_id=order_for_submission["product_id"],
                            side=order_for_submission["side"],
                            size=float(order_for_submission["base_size"]),
                            limit_price=float(attempt_price),
                            stealth_order_id=stealth_order_id,
                            parent_order_id=order.get("parent_order_id"),
                        )
                    )
                    if not final_guard_ok:
                        guard_evidence = {
                            **admin_child_authority,
                            "action_condition_guard": final_guard_failure,
                        }
                        self._record_admin_fill_follow_up_reveal_block(
                            stealth_order_id=stealth_order_id,
                            order=order,
                            block_category=(
                                str(
                                    (final_guard_failure or {}).get(
                                        "block_category"
                                    )
                                    or "admin_child_final_action_guard_blocked"
                                )
                            ),
                            failure_reason=(
                                str((final_guard_failure or {}).get("reason") or "")
                                or "Final Admin child wallet/cap guard blocked reveal"
                            ),
                            evidence=guard_evidence,
                        )
                        return None
                    if controlled_capability_bypass:
                        if not isinstance(
                            controlled_admin_authority,
                            ControlledAdminChildRevealAuthority,
                        ):
                            self._record_admin_fill_follow_up_reveal_block(
                                stealth_order_id=stealth_order_id,
                                order=order,
                                block_category=(
                                    "controlled_admin_authority_type_mismatch"
                                ),
                                failure_reason=(
                                    "Controlled Admin child market evidence is "
                                    "not bound to the consumed one-call authority."
                                ),
                                evidence=admin_child_authority,
                            )
                            return None
                        latest_market = {
                            "bid": controlled_admin_authority.market_bid,
                            "source": controlled_admin_authority.market_source,
                            "time": (
                                controlled_admin_authority.market_observed_at
                            ),
                        }
                    else:
                        latest_market = (
                            self._get_current_market_data(
                                order_for_submission["product_id"]
                            )
                            or {}
                        )
                    standing_price_limit = evaluate_spot_standing_price_limit(
                        side=order_for_submission["side"],
                        limit_price=attempt_price,
                        best_bid=latest_market.get("bid"),
                        market_source=latest_market.get("source"),
                        market_observed_at=latest_market.get("time"),
                    )
                    if not standing_price_limit["allowed"]:
                        blocker = str(
                            standing_price_limit.get("blocker")
                            or "standing_price_limit_not_authorized"
                        )
                        failure_reason = (
                            "Automatic direct-root child reveal is outside the "
                            "operator standing price authority or lacks a live "
                            "ticker bid; the child remains pre-exchange."
                        )
                        self._record_admin_fill_follow_up_reveal_block(
                            stealth_order_id=stealth_order_id,
                            order=order,
                            block_category=blocker,
                            failure_reason=failure_reason,
                            evidence=admin_child_authority,
                            standing_price_limit=standing_price_limit,
                        )
                        return None
                with controller.track_inflight(INFLIGHT_REST_PLACE):
                    controller.check_admission(INFLIGHT_REST_PLACE)
                    # Pre-insert chain-linked row for THIS attempt's COID before
                    # the REST call so the WS handler can resolve the parent.
                    if _pre_insert_placement_row(attempt_coid, attempt_price):
                        placement_pre_inserted = True
                    order_result = REST_CLIENT.place_limit_order(
                        product_id=order_for_submission["product_id"],
                        side=order_for_submission["side"],
                        limit_price=str(attempt_price),
                        base_size=str(order_for_submission["base_size"]),
                        client_order_id=attempt_coid,
                        post_only=retry_post_only,
                    )

                order_result_succeeded = (
                    not isinstance(order_result, dict)
                    or bool(order_result.get("success"))
                    or bool(order_result.get("success_response"))
                )
                if order_result_succeeded:
                    # Success (or non-dict legacy shape) — keep the COID
                    # and price actually used for downstream bookkeeping.
                    order_for_submission["limit_price"] = attempt_price
                    order_for_submission["client_order_id"] = attempt_coid
                    client_order_id = attempt_coid
                    exchange_placement_succeeded = True
                    break

                if not retry_post_only or not self._is_post_only_rejection(order_result):
                    # Not a post-only rejection — fall through to the
                    # existing error path with the current order_result.
                    order_for_submission["limit_price"] = attempt_price
                    order_for_submission["client_order_id"] = attempt_coid
                    client_order_id = attempt_coid
                    break

                # POST_ONLY rejection: record + reprice for next attempt
                rejected_failure_reason = (
                    order_result.get("failure_reason")
                    or (order_result.get("error_response") or {}).get("error")
                    or "POST_ONLY"
                )
                post_only_attempts.append({
                    "attempt": attempt_num,
                    "rejected_at_price": attempt_price,
                    "client_order_id": attempt_coid,
                    "failure_reason": rejected_failure_reason,
                })

                # Mark the pre-inserted row for this rejected COID as FAILED
                # so the audit table reflects that this COID never made it
                # onto the exchange. Best-effort: a missing row (race lost
                # to WS handler) is fine — its status will be reconciled by
                # downstream WS event handling.
                if attempt_coid in pre_inserted_attempt_coids:
                    try:
                        update_order_parent_status(
                            attempt_coid, OrderStatus.FAILED.value
                        )
                    except Exception as status_update_error:
                        self.log_callback(
                            "warning",
                            {
                                "event": "post_only_rejected_status_update_failed",
                                "stealth_order_id": stealth_order_id,
                                "rejected_client_order_id": attempt_coid,
                                "error": str(status_update_error),
                            },
                        )

                if attempt_num == max_attempts:
                    # Exhausted — leave order_result as the final
                    # rejection for the surface-and-stop block below.
                    order_for_submission["limit_price"] = attempt_price
                    order_for_submission["client_order_id"] = attempt_coid
                    client_order_id = attempt_coid
                    break

                if not price_increment:
                    # No tick metadata — cannot safely reprice. Surface
                    # the rejection rather than guess.
                    self.log_callback("warning", {
                        "event": "stealth_order_post_only_retry_skipped_no_increment",
                        "stealth_order_id": stealth_order_id,
                        "product_id": order_for_submission["product_id"],
                        "attempt": attempt_num,
                        "rejected_at_price": attempt_price,
                    })
                    order_for_submission["limit_price"] = attempt_price
                    order_for_submission["client_order_id"] = attempt_coid
                    client_order_id = attempt_coid
                    break

                next_price = self._next_safer_tick(
                    attempt_price,
                    order_for_submission["side"],
                    price_increment,
                )
                # Fresh client_order_id per retry: a rejected attempt may
                # or may not consume the COID at the exchange and the
                # safe assumption is that it does. Reusing would risk a
                # spurious DUPLICATE_CLIENT_ORDER_ID rejection that
                # masks the real POST_ONLY symptom.
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

            # SURFACE-AND-STOP on post-only retry exhaustion. Done BEFORE
            # the success-path bookkeeping below so we don't pretend the
            # order was placed.
            if (
                retry_post_only
                and isinstance(order_result, dict)
                and not (order_result.get("success") or order_result.get("success_response"))
                and self._is_post_only_rejection(order_result)
                and len(post_only_attempts) >= max_attempts
            ):
                final_failure_reason = (
                    order_result.get("failure_reason")
                    or (order_result.get("error_response") or {}).get("error")
                    or "POST_ONLY"
                )
                self.log_callback("warning", {
                    "event": "stealth_order_post_only_retries_exhausted",
                    "stealth_order_id": stealth_order_id,
                    "product_id": order_for_submission["product_id"],
                    "side": order_for_submission["side"],
                    "attempts": post_only_attempts,
                    "final_failure_reason": final_failure_reason,
                    "note": (
                        "Post-only rejected on every attempt after "
                        "repricing 1 tick safer each time. Not falling "
                        "back to taker — operator intent was post-only."
                    ),
                })
                self._dispatch_lifecycle_event(
                    stealth_order_id=stealth_order_id,
                    event=StealthLifecycleEvent.PLACEMENT_BLOCKED,
                    order_data=order,
                    extra={
                        "block_category": "post_only_rejected_after_retries",
                        "attempts": post_only_attempts,
                        "final_price": attempt_price,
                        "final_failure_reason": final_failure_reason,
                    },
                )
                # Raise into the existing exception handler so order
                # state, audit rows, and downstream cleanup all run via
                # the single failure path.
                raise RuntimeError(
                    f"POST_ONLY rejected after {len(post_only_attempts)} "
                    f"attempts (final price {attempt_price}); refusing "
                    f"silent demotion to taker."
                )

            if (
                isinstance(order_result, dict)
                and not (order_result.get("success") or order_result.get("success_response"))
            ):
                failure_reason = (
                    order_result.get("failure_reason")
                    or (order_result.get("error_response") or {}).get("error")
                    or (order_result.get("error_response") or {}).get("message")
                    or "exchange rejected placement"
                )
                raise RuntimeError(f"Exchange rejected placement: {failure_reason}")

            if isinstance(order_result, dict):
                success_response = order_result.get("success_response") or {}
                exchange_order_id = success_response.get("order_id") or order_result.get("order_id")
            
            # ✓ Use the client_order_id we sent (stealth_order_id)
            # When fill event arrives with this client_order_id, it links directly to stealth order
            placed_order_id = client_order_id
            placement_success = True
            if admin_child_authority.get("required"):
                self._clear_admin_fill_follow_up_reveal_block(
                    stealth_order_id=stealth_order_id,
                    order=order,
                )

            # NOTE: order_parent row was inserted PRE-REST above (see
            # placement_pre_inserted). Do not re-insert here — the WS event
            # handler and our pre-insert are the two writers, and the
            # pre-insert is now guaranteed to win the race.

            # 🪝 POST-SUBMISSION HOOKS: Log/track submission after REST call succeeds
            # Exceptions here are logged but don't affect placement
            try:
                self.order_placement_hooks.call_post_submission_hooks(order_for_submission, order_result)
            except Exception as hook_error:
                # Post-hook error - log but don't fail (order is already placed)
                self.log_callback("warning", {
                    "event": "post_submission_hook_exception",
                    "stealth_order_id": stealth_order_id,
                    "error": str(hook_error),
                    "note": "Order was placed successfully, but post-submission hook failed"
                })
            
            # 📊 LOT-TRACKING: Log order placement
            # Use the ACTUALLY-SUBMITTED price (post-retry), not the
            # plan's pre-retry price, so audit logs match what the
            # exchange actually saw.
            actual_submitted_price = float(order_for_submission["limit_price"])
            post_only_retried = bool(post_only_attempts)
            self.log_callback("info", f"[LOT-TRACK] Stealth order revealed & placed: {stealth_order_id} ({order['side']} {slice_size} {order['product_id']} @ {actual_submitted_price}, reveal_policy={reveal_plan.reveal_pricing_policy}, exchange_order_id={exchange_order_id})")

            self.log_callback("info", {
                "event": "stealth_order_slice_placed_successfully",
                "stealth_order_id": order['stealth_order_id'],
                "client_order_id": placed_order_id,
                "exchange_order_id": exchange_order_id,
                "size": slice_size,
                "product_id": order["product_id"],
                "configured_limit_price": reveal_plan.configured_limit_price,
                # Plan's pre-retry submitted price (kept for audit
                # comparability with non-retry placements).
                "planned_submitted_limit_price": reveal_plan.submitted_limit_price,
                # Actually-submitted price after any post-only retries.
                "submitted_limit_price": actual_submitted_price,
                "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
                "reveal_price_source": (
                    "post_only_retry"
                    if post_only_retried
                    else reveal_plan.reveal_price_source
                ),
                "post_only_retry_attempts": len(post_only_attempts),
            })

            # 🔔 LIFECYCLE HOOK: REVEAL_SUCCEEDED
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
        except Exception as e:
            # ✗ EXCEPTION DURING PLACEMENT OR POST-PLACEMENT BOOKKEEPING
            # exchange_placement_succeeded distinguishes:
            #   - REST call raised or returned a rejected placement => order is
            #     NOT on the exchange
            #   - REST placement succeeded, exception came from post-placement
            #     code (audit insert, hook, lifecycle dispatch) => order IS
            #     LIVE on the exchange and we just lost the bookkeeping link
            # The second case is operationally critical: emitting "order was not
            # placed" caused the 2026-04-29 incident where the exchange filled
            # the order and we never created the follow-up.
            placed_order_id = client_order_id or str(uuid.uuid4())
            placement_error = str(e)
            placement_success = exchange_placement_succeeded

            if exchange_placement_succeeded:
                self.log_callback("error", {
                    "event": "stealth_order_slice_post_placement_exception",
                    "stealth_order_id": order['stealth_order_id'],
                    "client_order_id": placed_order_id,
                    "exchange_order_id": exchange_order_id,
                    "size": slice_size,
                    "product_id": order["product_id"],
                    "exception": str(e),
                    "note": (
                        "REST place_limit_order SUCCEEDED but post-placement "
                        "bookkeeping raised. Order IS LIVE on the exchange; "
                        "operator action may be required to reconcile follow-up."
                    ),
                })
            else:
                self.log_callback("error", {
                    "event": "stealth_order_slice_placement_exception",
                    "stealth_order_id": order['stealth_order_id'],
                    "size": slice_size,
                    "product_id": order["product_id"],
                    "exception": str(e),
                    "note": "REST place_limit_order raised. Order was NOT placed on the exchange.",
                })

                # Mark the pre-inserted order_parent row as FAILED so it does
                # not linger as a phantom PENDING placement. Only attempt this
                # if the pre-insert succeeded above.
                if placement_pre_inserted:
                    try:
                        update_order_parent_status(client_order_id, OrderStatus.FAILED.value)
                    except Exception as status_err:
                        self.log_callback(
                            "warning",
                            {
                                "event": "reveal_placement_order_parent_failed_status_update_failed",
                                "stealth_order_id": stealth_order_id,
                                "placement_client_order_id": client_order_id,
                                "error": str(status_err),
                            },
                        )
            
            # 🔔 LIFECYCLE HOOK: REVEAL_FAILED
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.REVEAL_FAILED,
                order_data=order,
                extra={"failure_reason": placement_error, "size": slice_size},
            )
        
        # Record reveal event with placement status tracking and plan audit trail
        reveal_event = {
            "reveal_number": len(order["revealed_orders"]) + 1,
            "revealed_size": slice_size if placement_success else 0,
            "placement_price": reveal_plan.submitted_limit_price,
            "placed_order_id": placed_order_id,
            "placement_client_order_id": placed_order_id,
            "exchange_order_id": exchange_order_id,
            "placement_success": placement_success,  # ✓ Track if actually placed on exchange
            "placement_status": "placed" if placement_success else "failed",
            "placement_error": placement_error,      # Error message if failed
            "reveal_time": datetime.utcnow(),
            "market_price": market_data.get("price"),
            "market_bid": market_bid,
            "market_ask": market_ask,
            "market_spread": market_spread,
            "market_volume_1m": market_data.get("volume_1m"),
            "market_source": market_data.get("source"),
            # Reveal execution plan audit trail (for post-reveal analysis/profitability recheck)
            "configured_limit_price": reveal_plan.configured_limit_price,
            "submitted_limit_price": reveal_plan.submitted_limit_price,
            "reveal_pricing_policy": reveal_plan.reveal_pricing_policy,
            "reveal_price_source": reveal_plan.reveal_price_source,
            "reveal_price_fallback_used": reveal_plan.fallback_used,
        }
        
        order["revealed_orders"].append(reveal_event)
        if not placement_success:
            order["updated_at"] = datetime.utcnow()
            self._update_stealth_order(order)
            self._record_reveal_event(order, reveal_event)
            return None

        order["revealed_size"] += slice_size
        order["remaining_size"] = order["total_size"] - order["revealed_size"]
        order["visibility_score"] = order["revealed_size"] / order["total_size"]
        
        if order["remaining_size"] <= 0:
            order["status"] = StealthOrderStatus.REVEALED.value
        
        order["updated_at"] = datetime.utcnow()
        order["last_placement_at"] = datetime.utcnow()

        anchor_state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
        anchor_state["active_placement_client_order_id"] = placed_order_id
        anchor_state["active_exchange_order_id"] = exchange_order_id
        anchor_state["active_exchange_price"] = reveal_plan.submitted_limit_price
        anchor_state["current_logical_limit_price"] = reveal_plan.submitted_limit_price
        order["anchor_repricing_state_json"] = anchor_state
        
        # Persist updates
        self._update_stealth_order(order)
        self._record_reveal_event(order, reveal_event)
        
        # Index the placed order for O(1) lookup in find_stealth_order_by_placed_order_id()
        self._placed_order_index[placed_order_id] = order
        
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

        When ``cancel_exchange`` is True (default) and the order is REVEALED,
        the tracked exchange placement must be cancelled through REST before
        the stealth order is marked CANCELLED. If the live cancel cannot be
        proven, local state remains unchanged so it does not hide a live
        Coinbase placement.

        Args:
            stealth_order_id: Internal stealth order id (client_order_id).
            reason: Free-text reason recorded in notes / lifecycle event.
            cancel_exchange: REST cancel of the active exchange order before
                flipping local status. Set False only when the caller has
                already cancelled (or never placed) the exchange order.

        Returns:
            True if the local status flipped to CANCELLED. False if the order
            was missing/already cancelled or a required exchange cancel failed.
        """
        order = self._get_stealth_order(stealth_order_id)

        if not order:
            return False

        if order["status"] == StealthOrderStatus.CANCELLED.value:
            return False

        if (
            cancel_exchange
            and order.get("status") == StealthOrderStatus.REVEALED.value
            and not self._cancel_active_exchange_order_for_manual_cancel(order, reason)
        ):
            return False

        order["status"] = StealthOrderStatus.CANCELLED.value
        order["updated_at"] = datetime.utcnow()
        order["notes"] = f"{order['notes']}\nCancelled: {reason}"

        self._update_stealth_order(order)
        return True

    def _cancel_active_exchange_order_for_manual_cancel(
        self, order: Dict[str, Any], reason: str
    ) -> bool:
        """Cancel the live exchange order tracked by anchor repricing state.

        Manual cancellation may only flip a REVEALED stealth order to local
        CANCELLED after Coinbase cancellation succeeds. Failures leave both
        local status and active placement pointers intact for reconciliation.
        """
        state = self._normalize_anchor_repricing_state(
            order.get("anchor_repricing_state_json")
        )
        placement_client_order_id = state.get("active_placement_client_order_id")
        exchange_order_id = state.get("active_exchange_order_id")
        if not exchange_order_id:
            self.log_callback(
                "warning",
                {
                    "event": "stealth_cancel_exchange_missing_order_id",
                    "stealth_order_id": order.get("stealth_order_id"),
                    "placement_client_order_id": placement_client_order_id,
                    "reason": reason,
                },
            )
            return False

        from configuration import REST_CLIENT

        try:
            with get_runtime_controller().track_inflight(INFLIGHT_REST_CANCEL):
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
                "error",
                {
                    "event": "stealth_cancel_exchange_failed",
                    "stealth_order_id": order.get("stealth_order_id"),
                    "exchange_order_id": exchange_order_id,
                    "reason": reason,
                    "error": str(cancel_exc),
                },
            )
            return False

        state["active_exchange_order_id"] = None
        state["active_placement_client_order_id"] = None
        order["anchor_repricing_state_json"] = state
        return True
    
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
        from business.stealth_reveal_strategy import compute_reveal_strategy_slice_size

        sizing_strategy = order.get("sizing_strategy_json", {}) or {}
        strategy_type = sizing_strategy.get("type", "fixed")
        strategy = get_reveal_strategy(
            strategy_type,
            sizing_strategy,
            market_volume_provider=self._get_market_volume,
            baseline_volume_provider=self._get_baseline_volume,
        )
        return compute_reveal_strategy_slice_size(strategy, order)

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
        if product_id in self._market_cache:
            return self._market_cache[product_id]

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

    def apply_same_side_post_fill_retreat(
        self,
        filled_order: Dict[str, Any],
        *,
        filled_placement_client_order_id: Optional[str] = None,
        filled_price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retreat the nearest eligible hidden same-side order after a fill.

        This mutates only hidden, non-live stealth orders. Revealed exchange
        placements remain under the existing cancel/move/reprice paths.
        """
        if not filled_order:
            return None

        source_stealth_order_id = str(filled_order.get("stealth_order_id") or "")
        source_key = str(filled_placement_client_order_id or source_stealth_order_id or "")
        product_id = str(filled_order.get("product_id") or "")
        side = str(filled_order.get("side") or "").upper()
        if not source_key or not product_id or side not in {OrderSide.BUY.value, OrderSide.SELL.value}:
            return None

        fill_reference_price = safe_float(filled_price, default=None)
        if fill_reference_price is None or fill_reference_price <= 0:
            source_state = self._normalize_anchor_repricing_state(
                filled_order.get("anchor_repricing_state_json")
            )
            fill_reference_price = safe_float(
                source_state.get("active_exchange_price"),
                default=safe_float(filled_order.get("limit_price"), default=None),
            )
        if fill_reference_price is None or fill_reference_price <= 0:
            return None

        hidden_statuses = {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
        }

        for order in list(self.in_memory_orders.values()):
            state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
            if source_key in list(state.get("post_fill_retreat_source_order_ids") or []):
                return None

        candidates: List[Tuple[float, str, Dict[str, Any], PostFillRetreatPolicy]] = []
        for stealth_order_id, order in list(self.in_memory_orders.items()):
            if str(stealth_order_id) == source_stealth_order_id:
                continue
            if order.get("product_id") != product_id:
                continue
            if str(order.get("side") or "").upper() != side:
                continue
            if str(order.get("status") or "").upper() not in hidden_statuses:
                continue

            state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
            if state.get("active_placement_client_order_id") or state.get("active_exchange_order_id"):
                continue

            policy = PostFillRetreatPolicy.from_post_fill_retreat_policy_dict(
                order.get("post_fill_retreat_policy_json")
            )
            if not policy.enabled:
                continue
            if policy.scope is not PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE:
                continue

            candidate_price = safe_float(order.get("limit_price"), default=None)
            if candidate_price is None or candidate_price <= 0:
                continue
            candidates.append(
                (
                    abs(candidate_price - fill_reference_price),
                    str(stealth_order_id),
                    order,
                    policy,
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        _, target_stealth_order_id, target_order, target_policy = candidates[0]

        from core.enums import StealthMutationKind

        if not self.try_claim_mutation(StealthMutationKind.RETREAT, target_stealth_order_id):
            return None

        try:
            current_status = str(target_order.get("status") or "").upper()
            if current_status not in hidden_statuses:
                return None
            return self._apply_post_fill_retreat_to_hidden_order(
                target_order,
                target_policy,
                source_key=source_key,
                source_stealth_order_id=source_stealth_order_id,
                fill_reference_price=fill_reference_price,
            )
        finally:
            self.release_mutation(StealthMutationKind.RETREAT, target_stealth_order_id)

    def _apply_post_fill_retreat_to_hidden_order(
        self,
        order: Dict[str, Any],
        policy: PostFillRetreatPolicy,
        *,
        source_key: str,
        source_stealth_order_id: str,
        fill_reference_price: float,
    ) -> Optional[Dict[str, Any]]:
        increment = self._get_price_increment(order.get("product_id"))
        price_tick = safe_float(increment, default=0.0)
        if price_tick <= 0:
            return None

        current_price = safe_float(order.get("limit_price"), default=None)
        if current_price is None or current_price <= 0:
            return None

        normalized_side = str(order.get("side") or "").upper()
        retreat_amount = float(price_tick) * int(policy.retreat_ticks)
        if normalized_side == OrderSide.BUY.value:
            raw_new_price = current_price - retreat_amount
        elif normalized_side == OrderSide.SELL.value:
            raw_new_price = current_price + retreat_amount
        else:
            return None

        new_price = self._quantize_reprice_price(
            order.get("product_id"),
            normalized_side,
            raw_new_price,
            boundary_enforced=False,
        )
        if new_price <= 0 or new_price == current_price:
            return None

        now = datetime.utcnow()
        state = self._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
        applied_sources = list(state.get("post_fill_retreat_source_order_ids") or [])
        if source_key in applied_sources:
            return None

        self._apply_reveal_condition_price_tracking(order, state, new_price)
        order["limit_price"] = new_price
        order["status"] = StealthOrderStatus.HIDDEN.value
        order["condition_first_met_at"] = None
        order["condition_confirmed_at"] = None
        order["updated_at"] = now

        applied_sources.append(source_key)
        state["post_fill_retreat_source_order_ids"] = applied_sources
        state["post_fill_retreat_offset"] = (
            safe_float(state.get("post_fill_retreat_offset"), default=0.0)
            + (new_price - current_price)
        )
        state["post_fill_retreat_count"] = int(
            safe_float(state.get("post_fill_retreat_count"), default=0.0)
        ) + 1
        state["last_post_fill_retreat_at"] = now.isoformat()
        state["last_post_fill_retreat_source_order_id"] = source_stealth_order_id
        state["last_post_fill_retreat_source_placement_client_order_id"] = source_key
        state["last_post_fill_retreat_from_price"] = current_price
        state["last_post_fill_retreat_to_price"] = new_price
        state["last_post_fill_retreat_fill_price"] = fill_reference_price
        state["current_logical_limit_price"] = new_price
        state["reprice_reason"] = PostFillRetreatReason.SAME_SIDE_FILL.value
        order["anchor_repricing_state_json"] = state

        self._update_stealth_order(order)
        result = {
            "stealth_order_id": order.get("stealth_order_id"),
            "source_stealth_order_id": source_stealth_order_id,
            "source_placement_client_order_id": source_key,
            "previous_price": current_price,
            "new_price": new_price,
            "retreat_ticks": policy.retreat_ticks,
            "price_tick": price_tick,
            "fill_reference_price": fill_reference_price,
        }
        self.log_callback(
            "info",
            {
                "event": "same_side_post_fill_retreat_applied",
                **result,
            },
        )
        return result
    
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
        target_movement_type: str = "P",
        cancel_reentry_policy: Optional[Dict[str, Any]] = None,
        post_fill_retreat_policy: Optional[Dict[str, Any]] = None,
        follow_up_trigger: Optional[str] = None,
        source_client_order_id: Optional[str] = None,
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
            cancel_reentry_policy: Optional override for cancel/re-entry policy. If None,
                inherits from original only when that policy allows follow-up inheritance.
            post_fill_retreat_policy: Optional override for same-side post-fill retreat.
                If None, inherits from original only when that policy allows follow-up inheritance.
            follow_up_trigger: Event that requested this follow-up
                (filled, partial_fill, or cancelled).
            source_client_order_id: Filled placement identity used to derive a
                restart-stable child id for exactly-once FILLED replay.
            
        Returns:
            New stealth_order_id if created, None if original not found
        """
        original_order = self._get_stealth_order(original_stealth_order_id)
        if not original_order:
            return None

        spot_follow_up = evaluate_spot_follow_up_policy(
            product_id=original_order["product_id"],
            source_side=original_order.get("side"),
            follow_up_side=side,
            trigger=follow_up_trigger or SpotFollowUpTrigger.FILLED.value,
        )
        if not spot_follow_up.allowed:
            self.log_callback(
                "warning",
                {
                    "event": "spot_follow_up_blocked",
                    "original_stealth_order_id": original_stealth_order_id,
                    **spot_follow_up.to_dict(),
                },
            )
            return None
        
        # Use provided reveal condition or inherit from original
        follow_up_condition = reveal_condition if reveal_condition is not None else original_order.get("reveal_condition_json", {})
        inherited_pricing_policy = original_order.get("reveal_pricing_policy") or "configured_limit"
        effective_pricing_policy = reveal_pricing_policy or inherited_pricing_policy
        # Inherit anchor-repricing policy unless explicitly opted out. Build via
        # ``RepricingPolicy`` so the inheritance check uses the dataclass field
        # (not a magic string lookup) and on-disk shape stays identical.
        original_repricing = RepricingPolicy.from_anchor_repricing_policy_dict(
            original_order.get("anchor_repricing_policy_json")
        )
        if original_repricing.inherit_to_follow_ups:
            anchor_repricing_policy = original_repricing.to_anchor_repricing_policy_dict()
        else:
            anchor_repricing_policy = (
                RepricingPolicy.disabled().to_anchor_repricing_policy_dict()
            )

        if cancel_reentry_policy is not None:
            inherited_cancel_reentry_policy = self._normalize_cancel_reentry_policy(
                cancel_reentry_policy
            )
        else:
            original_cancel_reentry = CancelReentryPolicy.from_cancel_reentry_policy_dict(
                original_order.get("cancel_reentry_policy_json")
            )
            if original_cancel_reentry.inherit_to_follow_ups:
                inherited_cancel_reentry_policy = (
                    original_cancel_reentry.to_cancel_reentry_policy_dict()
                )
            else:
                inherited_cancel_reentry_policy = (
                    CancelReentryPolicy.disabled().to_cancel_reentry_policy_dict()
                )

        if post_fill_retreat_policy is not None:
            inherited_post_fill_retreat_policy = self._normalize_post_fill_retreat_policy(
                post_fill_retreat_policy
            )
        else:
            original_post_fill_retreat = (
                PostFillRetreatPolicy.from_post_fill_retreat_policy_dict(
                    original_order.get("post_fill_retreat_policy_json")
                )
            )
            if original_post_fill_retreat.inherit_to_follow_ups:
                inherited_post_fill_retreat_policy = (
                    original_post_fill_retreat.to_post_fill_retreat_policy_dict()
                )
            else:
                inherited_post_fill_retreat_policy = (
                    PostFillRetreatPolicy.disabled().to_post_fill_retreat_policy_dict()
                )
        
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
        normalized_trigger = str(
            getattr(follow_up_trigger, "value", follow_up_trigger) or ""
        ).lower()
        if normalized_trigger == SpotFollowUpTrigger.FILLED.value:
            if not source_client_order_id:
                raise StealthOrderPersistenceError(
                    "FILLED follow-up requires source_client_order_id"
                )
            follow_up_stealth_order_id = _filled_follow_up_stealth_order_id(
                original_stealth_order_id=original_stealth_order_id,
                source_client_order_id=str(source_client_order_id),
            )
        else:
            follow_up_stealth_order_id = str(uuid.uuid4())

        # Apply post-fill retreat if configured. The inherited policy
        # owns the decision; helper returns ``limit_price`` unchanged
        # when retreat is disabled (distance == 0). Tick-align the
        # result via the same chokepoint used at reveal time so the
        # follow-up posts on a valid price grid.
        retreat_policy = RepricingPolicy.from_anchor_repricing_policy_dict(
            anchor_repricing_policy
        )
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
            cancel_reentry_policy=inherited_cancel_reentry_policy,
            post_fill_retreat_policy=inherited_post_fill_retreat_policy,
            target_movement=follow_up_target_movement,
            target_movement_type=follow_up_target_movement_type,
            stealth_order_id=follow_up_stealth_order_id,
            require_persistence=(
                str(
                    getattr(follow_up_trigger, "value", follow_up_trigger) or ""
                ).lower()
                == SpotFollowUpTrigger.FILLED.value
            ),
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

    def create_direct_root_fill_follow_up_stealth_order(
        self,
        *,
        root_parent_client_order_id: str,
        source_client_order_id: str,
        product_id: str,
        source_side: str,
        side: str,
        total_size: float,
        limit_price: float,
        target_movement: float,
        target_movement_type: str = "P",
    ) -> Optional[str]:
        """Create one deterministic hidden child for an owned direct root fill."""

        spot_follow_up = evaluate_spot_follow_up_policy(
            product_id=product_id,
            source_side=source_side,
            follow_up_side=side,
            trigger=SpotFollowUpTrigger.FILLED.value,
        )
        if not spot_follow_up.allowed:
            self.log_callback(
                "warning",
                {
                    "event": "direct_root_spot_follow_up_blocked",
                    "root_parent_client_order_id": root_parent_client_order_id,
                    **spot_follow_up.to_dict(),
                },
            )
            return None

        follow_up_id = _filled_follow_up_stealth_order_id(
            original_stealth_order_id=root_parent_client_order_id,
            source_client_order_id=source_client_order_id,
        )
        normalized_side = str(side or "").upper()
        reveal_direction = (
            Direction.ABOVE.value
            if normalized_side == OrderSide.SELL.value
            else Direction.BELOW.value
        )
        return self.create_stealth_order(
            product_id=product_id,
            side=normalized_side,
            total_size=total_size,
            limit_price=limit_price,
            reveal_condition={
                "type": RevealConditionType.PRICE_THRESHOLD.value,
                "price_threshold": float(limit_price),
                "direction": reveal_direction,
                "hold_duration_seconds": 0,
                "standing_price_limit_policy": (
                    StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value
                ),
            },
            sizing_strategy={"type": "fixed"},
            parent_order_id=root_parent_client_order_id,
            follow_up_reveal_direction=FollowUpRevealDirection.OPPOSITE.value,
            reveal_pricing_policy="configured_limit",
            reason="follow_up_replacement",
            notes="Automatic follow-up from owned direct Admin root fill",
            target_movement=target_movement,
            target_movement_type=target_movement_type,
            stealth_order_id=follow_up_id,
            require_persistence=True,
        )
    
    # Database operations
    
    def _persist_new_stealth_order_strict(
        self,
        order: Dict[str, Any],
        *,
        persist_rows: Callable[[], Optional[tuple[int, bool]]],
    ) -> None:
        """Persist both required rows before exposing a FILLED follow-up."""

        stealth_order_id = str(order["stealth_order_id"])
        persistence_result = persist_rows()
        if persistence_result is None:
            raise StealthOrderPersistenceError(
                "Strict stealth creation did not return an atomic result"
            )
        _parent_row_id, stealth_row_created = persistence_result
        if not stealth_row_created:
            if stealth_order_id not in self.in_memory_orders:
                raise StealthOrderPersistenceError(
                    "Existing atomic FILLED follow-up was not hydrated"
                )
            return

        self.in_memory_orders[stealth_order_id] = order

    def _save_stealth_order_to_db(
        self,
        order: Dict[str, Any],
        *,
        raise_on_error: bool = False,
    ) -> bool:
        """Persist stealth order to database."""
        if not self.db_client:
            if raise_on_error:
                raise StealthOrderPersistenceError(
                    "Strict stealth persistence requires a database client"
                )
            return False
        
        try:
            rows_affected = self.db_client.execute_update(
                """INSERT INTO stealth_orders 
                   (stealth_order_id, product_id, side, total_size, remaining_size,
                    limit_price, status, reveal_condition_type, reveal_condition_json,
                    sizing_strategy_json, reason, notes, parent_order_id,
                    anchor_repricing_policy_json, anchor_repricing_state_json,
                    cancel_reentry_policy_json, cancel_reentry_state_json,
                    post_fill_retreat_policy_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                   json.dumps(order.get('cancel_reentry_policy_json', {})),
                   json.dumps(order.get('cancel_reentry_state_json', {})),
                   json.dumps(order.get('post_fill_retreat_policy_json', {"enabled": False})))
            )
            if rows_affected != 1:
                if raise_on_error:
                    raise StealthOrderPersistenceError(
                        "stealth_orders insert did not affect exactly one row"
                    )
                return False
            return True
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_save_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
            if raise_on_error:
                if isinstance(e, StealthOrderPersistenceError):
                    raise
                raise StealthOrderPersistenceError(
                    f"Failed to persist stealth order {order['stealth_order_id']}: {e}"
                ) from e
            return False
    
    def _update_stealth_order(self, order: Dict[str, Any]):
        """Update stealth order in database."""
        if not self.db_client:
            return
        
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
            cancel_reentry_state = order.get('cancel_reentry_state_json', {})
            cancel_reentry_state_json = json.dumps({
                key: value.isoformat() if hasattr(value, 'isoformat') else value
                for key, value in dict(cancel_reentry_state or {}).items()
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
            
            self.db_client.execute_update(
                """UPDATE stealth_orders 
                   SET status = %s, revealed_size = %s, remaining_size = %s, 
                       executed_size = %s, revealed_orders = %s, last_placement_at = %s,
                       limit_price = %s, reveal_condition_json = %s,
                        anchor_repricing_policy_json = %s, anchor_repricing_state_json = %s,
                        cancel_reentry_policy_json = %s, cancel_reentry_state_json = %s,
                        post_fill_retreat_policy_json = %s,
                        condition_first_met_at = %s, condition_confirmed_at = %s,
                        last_lifecycle_event = %s, failure_reason = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE stealth_order_id = %s""",
                (order['status'],
                 order.get('revealed_size', 0),
                 order.get('remaining_size', 0),
                 order.get('executed_size', 0),
                 revealed_orders_json,
                 last_placement,
                 order.get('limit_price'),
                 json.dumps(order.get('reveal_condition_json', {})),
                  json.dumps(order.get('anchor_repricing_policy_json', {})),
                  anchor_repricing_state_json,
                  json.dumps(order.get('cancel_reentry_policy_json', {})),
                  cancel_reentry_state_json,
                  json.dumps(order.get('post_fill_retreat_policy_json', {"enabled": False})),
                  condition_first_met_at,
                  condition_confirmed_at,
                  order.get('last_lifecycle_event'),
                  order.get('failure_reason'),
                  order['stealth_order_id'])
            )
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_update_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
    
    @staticmethod
    def _parse_stealth_order_json_field(value: Any, default: Any) -> Any:
        """Parse JSONB/text fields returned by stealth order queries."""
        if value is None:
            return default
        if isinstance(value, type(default)):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default
        return default

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
                
                return {
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
                    'reveal_condition_json': self._parse_stealth_order_json_field(
                        row.get('reveal_condition_json'), {}
                    ),
                    'sizing_strategy_json': self._parse_stealth_order_json_field(
                        row.get('sizing_strategy_json'), {}
                    ),
                    'reason': row.get('reason', ''),
                    'notes': row.get('notes', ''),
                    'parent_order_id': row.get('parent_order_id'),
                    'revealed_orders': self._parse_stealth_order_json_field(
                        row.get('revealed_orders'), []
                    ),
                    'anchor_repricing_policy_json': self._parse_stealth_order_json_field(
                        row.get('anchor_repricing_policy_json'), {}
                    ),
                    'anchor_repricing_state_json': self._parse_stealth_order_json_field(
                        row.get('anchor_repricing_state_json'), {}
                    ),
                    'cancel_reentry_policy_json': self._parse_stealth_order_json_field(
                        row.get('cancel_reentry_policy_json'), {}
                    ),
                    'cancel_reentry_state_json': self._parse_stealth_order_json_field(
                        row.get('cancel_reentry_state_json'), {}
                    ),
                    'post_fill_retreat_policy_json': self._parse_stealth_order_json_field(
                        row.get('post_fill_retreat_policy_json'), {"enabled": False}
                    ),
                    'created_at': row.get('created_at'),
                    'condition_first_met_at': row.get('condition_first_met_at'),
                    'condition_confirmed_at': row.get('condition_confirmed_at'),
                }
        except Exception as exc:
            self.log_callback(
                "error",
                {
                    "event": "stealth_order_load_failed",
                    "error_class": type(exc).__name__,
                },
            )
        
        return None
    
    def load_all_active_orders_from_db(
        self,
        *,
        raise_on_error: bool = False,
    ) -> int:
        """Load all stealth orders from database into memory.
        
        Loads all orders (HIDDEN, PENDING, TRIGGERED, REVEALED, EXECUTED, CANCELLED)
        to ensure UI displays the complete history and current state of stealth orders.
        
        Status handling on restart:
        - HIDDEN, PENDING, TRIGGERED: Reset to HIDDEN for fresh condition evaluation
        - REVEALED: Keep as-is (in-flight orders may complete)
        - EXECUTED: Keep as-is (historical record for UI display)
        - CANCELLED: Keep as-is (historical record for UI display)
        
        Returns:
            Number of orders loaded
        """
        if not self.db_client:
            if raise_on_error:
                raise RuntimeError(
                    "Stealth order hydration requires a database client"
                )
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
                    
                    order_data = {
                        'stealth_order_id': stealth_order_id,
                        'product_id': row['product_id'],
                        'side': row['side'],
                        'total_size': float(row['total_size']),
                        'revealed_size': float(row.get('revealed_size', 0)),
                        'remaining_size': float(row.get('remaining_size', 0)),
                        'executed_size': float(row.get('executed_size', 0)),
                        'limit_price': float(row['limit_price']),
                        'status': db_status if db_status in ['REVEALED', 'EXECUTED', 'CANCELLED'] else 'HIDDEN',
                        'reveal_condition_type': condition_type,
                        'reveal_condition_json': self._parse_stealth_order_json_field(
                            row.get('reveal_condition_json'), {}
                        ),
                        'sizing_strategy_json': self._parse_stealth_order_json_field(
                            row.get('sizing_strategy_json'), {}
                        ),
                        'reason': row.get('reason', ''),
                        'notes': row.get('notes', ''),
                        'parent_order_id': row.get('parent_order_id'),
                        'revealed_orders': self._parse_stealth_order_json_field(
                            row.get('revealed_orders'), []
                        ),
                        'anchor_repricing_policy_json': self._parse_stealth_order_json_field(
                            row.get('anchor_repricing_policy_json'), {}
                        ),
                        'anchor_repricing_state_json': self._parse_stealth_order_json_field(
                            row.get('anchor_repricing_state_json'), {}
                        ),
                        'cancel_reentry_policy_json': self._parse_stealth_order_json_field(
                            row.get('cancel_reentry_policy_json'), {}
                        ),
                        'cancel_reentry_state_json': self._parse_stealth_order_json_field(
                            row.get('cancel_reentry_state_json'), {}
                        ),
                        'post_fill_retreat_policy_json': self._parse_stealth_order_json_field(
                            row.get('post_fill_retreat_policy_json'), {"enabled": False}
                        ),
                        'created_at': row.get('created_at'),
                        'updated_at': row.get('updated_at'),
                        'visibility_score': float(row.get('visibility_score', 0.0)),
                        'last_placement_at': row.get('last_placement_at'),
                        'condition_first_met_at': None if db_status in ['HIDDEN', 'PENDING', 'TRIGGERED'] else condition_first_met,
                        'condition_confirmed_at': None if db_status in ['HIDDEN', 'PENDING', 'TRIGGERED'] else condition_confirmed,
                        'revealed_count': 0,
                        'condition_monitoring_start': None,
                    }
                    
                    self.in_memory_orders[stealth_order_id] = order_data
                    for reveal_event in order_data.get('revealed_orders', []):
                        if not isinstance(reveal_event, dict):
                            continue
                        placed_order_id = (
                            reveal_event.get('placement_client_order_id')
                            or reveal_event.get('placed_order_id')
                        )
                        if placed_order_id:
                            self._placed_order_index[str(placed_order_id)] = order_data
                    loaded_count += 1
                except Exception as e:
                    self.log_callback(
                        "error",
                        {
                            "event": "stealth_order_load_item_failed",
                            "exception_class": type(e).__name__,
                        },
                    )
                    if raise_on_error:
                        raise
            
            return loaded_count
        except Exception as e:
            self.log_callback(
                "error",
                {
                    "event": "stealth_orders_batch_load_failed",
                    "exception_class": type(e).__name__,
                },
            )
            if raise_on_error:
                raise
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

    def _record_reveal_event(self, order: Dict[str, Any], reveal_event: Dict[str, Any]):
        """Record reveal event to stealth_order_reveal_history table.
        
        Uses UPSERT (INSERT ... ON CONFLICT) to handle idempotent recording.
        If the same (stealth_order_id, reveal_number) is recorded twice, it updates
        with the latest data instead of failing. This handles race conditions or retries.
        """
        if not self.db_client:
            return
        
        try:
            # Get stealth_order_id from order dict (not reveal_event)
            stealth_order_id = order.get('stealth_order_id')
            if not stealth_order_id:
                return
            
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
            self.db_client.execute_update(
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
        except Exception as e:
            self.log_callback("error", {"event": "stealth_reveal_event_recording_failed", "error": str(e)})
