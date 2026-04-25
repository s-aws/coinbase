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
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

from configuration import DEFAULT_MAX_ORDER_REPLACEMENT
from core.enums import FollowUpRevealDirection, RevealPricingPolicy, StealthLifecycleEvent, StealthOrderStatus
from business.stealth_condition_evaluator import get_evaluator
from database.order import insert_order_parent
from logging_service import get_logger


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
    
    def __init__(self, db_client, log_callback=None, order_placement_hooks=None):
        """
        Initialize StealthOrderManager.
        
        Args:
            db_client: Database client for persistence
            log_callback: Optional logging callback (log_type, message). Defaults to proper logging_service.
            order_placement_hooks: Optional OrderPlacementHookRegistry for pre/post submission hooks.
        """
        self.db_client = db_client
        self.logger = get_logger("StealthOrderManager")
        self.log_callback = log_callback or self._default_log
        self.in_memory_orders = {}  # For caching/quick access
        self._market_cache = {}  # Market data cache: product_id -> market_data
        self._placed_order_index = {}  # Index: placed_order_id -> stealth_order (O(1) lookup)
        
        # Order placement hooks for extensibility
        if order_placement_hooks is None:
            from integration.order_placement_hooks import get_global_placement_hook_registry
            order_placement_hooks = get_global_placement_hook_registry()
        self.order_placement_hooks = order_placement_hooks
    
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
        target_movement: float = 0.002,
        target_movement_type: str = "P",
        reveal_pricing_policy: Optional[str] = None,
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
        }
        
        # Store in memory for quick access
        self.in_memory_orders[stealth_order_id] = order_data
        
        # Persist to database
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
        
        # UNIFIED TRACKING: Insert into order_parent table (for both parent and child orders)
        # This ensures stealth orders are tracked in the same parent-child hierarchy as regular orders
        if parent_order_id:
            # This is a child/follow-up order - insert with parent reference
            insert_order_parent(
                client_order_id=stealth_order_id,
                product_id=product_id,
                side=side,
                size=total_size,
                price=limit_price,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
                max_order_replacement=0,  # Children don't have follow-ups
                current_order_replacement=0,
                status=StealthOrderStatus.PENDING.value,
                parent_order_id=parent_order_id
            )
        else:
            # This is a root order (no parent) - insert as parent
            effective_max_replacements = max_order_replacements if max_order_replacements is not None else DEFAULT_MAX_ORDER_REPLACEMENT
            
            insert_order_parent(
                client_order_id=stealth_order_id,
                product_id=product_id,
                side=side,
                size=total_size,
                price=limit_price,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
                max_order_replacement=effective_max_replacements,
                current_order_replacement=0,
                status=StealthOrderStatus.PENDING.value
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
        
        Returns:
            Tuple of (should_reveal: bool, reason: Optional[str])
        """
        order = self._get_stealth_order(stealth_order_id)
        
        if not order:
            return False, "Order not found"
        
        if order["status"] in [StealthOrderStatus.EXECUTED.value, StealthOrderStatus.CANCELLED.value]:
            return False, f"Order already {order['status']}"
        
        if order["remaining_size"] <= 0:
            return False, "All size already revealed"
        
        condition_met, reason = self.evaluate_conditions(stealth_order_id)
        return condition_met, reason
    
    def reveal_order_slice(self, stealth_order_id: str) -> Optional[str]:
        """
        Reveal next slice of hidden order based on adaptive sizing.
        
        Returns:
            client_order_id if slice was placed, None otherwise
        """
        order = self._get_stealth_order(stealth_order_id)
        
        if not order:
            return None
        
        # Calculate slice size
        slice_size = self._calculate_reveal_size(order)
        
        if slice_size <= 0:
            return None
        
        # Place actual limit order on exchange (NOT stealth - this IS the revealed placement)
        # Use REST API directly - DO NOT create another stealth order!
        placed_order_id = None
        placement_success = False
        placement_error = None
        exchange_order_id = None
        market_data = self._get_current_market_data(order["product_id"]) or {}
        market_bid = market_data.get("bid")
        market_ask = market_data.get("ask")
        market_spread = market_data.get("market_spread")
        if market_spread is None and market_bid is not None and market_ask is not None:
            try:
                market_spread = float(market_ask) - float(market_bid)
            except (TypeError, ValueError):
                market_spread = None
        
        try:
            from configuration import REST_CLIENT
            
            # ⚠️ CRITICAL: Use the stealth_order_id as client_order_id for the revealed order
            # This creates the direct link: stealth_order_id → placed order → fill event
            client_order_id = order["stealth_order_id"]
            
            # Build order dict for hooks (before REST submission)
            order_for_submission = {
                "product_id": order["product_id"],
                "side": order["side"],
                "limit_price": order["limit_price"],
                "base_size": slice_size,
                "client_order_id": client_order_id,
                "post_only": False,
                "stealth_order_id": stealth_order_id,
                "parent_order_id": order.get("parent_order_id"),
                "reason": order.get("reason"),
                "reveal_number": len(order.get("revealed_orders", [])) + 1,
                "reveal_condition_type": order.get("reveal_condition_type"),
                "reveal_condition_json": order.get("reveal_condition_json"),
                "condition_confirmed_at": order.get("condition_confirmed_at").isoformat() if hasattr(order.get("condition_confirmed_at"), "isoformat") else order.get("condition_confirmed_at"),
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
                    "placement_success": False,
                    "placement_error": placement_error,
                    "reveal_time": datetime.utcnow(),
                    "market_price": market_data.get("price"),
                    "market_bid": market_bid,
                    "market_ask": market_ask,
                    "market_spread": market_spread,
                    "market_volume_1m": market_data.get("volume_1m"),
                    "market_source": market_data.get("source"),
                }
                order["revealed_orders"].append(reveal_event)
                order["updated_at"] = datetime.utcnow()
                self._update_stealth_order(order)
                self._record_reveal_event(order, reveal_event)
                return None
            
            # Place order directly on the exchange via REST API
            # ⚠️ CRITICAL: Do NOT call create_limit_order_span() here as it creates another stealth order!
            # Use REST_CLIENT.place_limit_order() which is purpose-built for this
            order_result = REST_CLIENT.place_limit_order(
                product_id=order_for_submission["product_id"],
                side=order_for_submission["side"],
                limit_price=str(order_for_submission["limit_price"]),
                base_size=str(order_for_submission["base_size"]),
                client_order_id=order_for_submission["client_order_id"],
                post_only=order_for_submission["post_only"]
            )

            if isinstance(order_result, dict):
                success_response = order_result.get("success_response") or {}
                exchange_order_id = success_response.get("order_id") or order_result.get("order_id")
            
            # ✓ Use the client_order_id we sent (stealth_order_id)
            # When fill event arrives with this client_order_id, it links directly to stealth order
            placed_order_id = client_order_id
            placement_success = True
            
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
            self.log_callback("info", f"[LOT-TRACK] Stealth order revealed & placed: {stealth_order_id} ({order['side']} {slice_size} {order['product_id']} @ {order['limit_price']}, exchange_order_id={exchange_order_id})")
            
            self.log_callback("info", {
                "event": "stealth_order_slice_placed_successfully",
                "stealth_order_id": order['stealth_order_id'],
                "client_order_id": placed_order_id,
                "exchange_order_id": exchange_order_id,
                "size": slice_size,
                "product_id": order["product_id"],
                "limit_price": order["limit_price"]
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
            # ✗ EXCEPTION DURING PLACEMENT
            placed_order_id = str(uuid.uuid4())  # Fallback for tracking
            placement_error = str(e)
            
            self.log_callback("error", {
                "event": "stealth_order_slice_placement_exception",
                "stealth_order_id": order['stealth_order_id'],
                "size": slice_size,
                "product_id": order["product_id"],
                "exception": str(e),
                "note": "Exception while placing order on exchange. Order was NOT placed."
            })

            # 🔔 LIFECYCLE HOOK: REVEAL_FAILED
            self._dispatch_lifecycle_event(
                stealth_order_id=stealth_order_id,
                event=StealthLifecycleEvent.REVEAL_FAILED,
                order_data=order,
                extra={"failure_reason": placement_error, "size": slice_size},
        )
        
        # Record reveal event with placement status tracking
        reveal_event = {
            "reveal_number": len(order["revealed_orders"]) + 1,
            "revealed_size": slice_size,
            "placed_order_id": placed_order_id,
            "exchange_order_id": exchange_order_id,
            "placement_success": placement_success,  # ✓ Track if actually placed on exchange
            "placement_error": placement_error,      # Error message if failed
            "reveal_time": datetime.utcnow(),
            "market_price": market_data.get("price"),
            "market_bid": market_bid,
            "market_ask": market_ask,
            "market_spread": market_spread,
            "market_volume_1m": market_data.get("volume_1m"),
            "market_source": market_data.get("source"),
        }
        
        order["revealed_orders"].append(reveal_event)
        order["revealed_size"] += slice_size
        order["remaining_size"] = order["total_size"] - order["revealed_size"]
        order["visibility_score"] = order["revealed_size"] / order["total_size"]
        
        if order["remaining_size"] <= 0:
            order["status"] = StealthOrderStatus.REVEALED.value
        
        order["updated_at"] = datetime.utcnow()
        order["last_placement_at"] = datetime.utcnow()
        
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
    
    def cancel_stealth_order(self, stealth_order_id: str, reason: str = "User cancelled") -> bool:
        """
        Cancel a stealth order without placing it.
        
        Returns:
            True if successfully cancelled
        """
        order = self._get_stealth_order(stealth_order_id)
        
        if not order:
            return False
        
        if order["status"] == StealthOrderStatus.CANCELLED.value:
            return False
        
        order["status"] = StealthOrderStatus.CANCELLED.value
        order["updated_at"] = datetime.utcnow()
        order["notes"] = f"{order['notes']}\nCancelled: {reason}"
        
        self._update_stealth_order(order)
        return True
    
    # ===================== PRIVATE METHODS =====================
    
    def _calculate_reveal_size(self, order: Dict[str, Any]) -> float:
        """Calculate how much of hidden order to reveal now."""
        sizing_strategy = order.get("sizing_strategy_json", {})
        strategy_type = sizing_strategy.get("type", "fixed")
        
        if strategy_type == "fixed":
            return order.get("total_size", 0)
        
        elif strategy_type == "adaptive":
            return self._calculate_adaptive_reveal_size(order, sizing_strategy)
        
        elif strategy_type == "tranche":
            return self._calculate_tranche_reveal_size(order, sizing_strategy)
        
        else:
            return order.get("total_size", 0)
    
    def _calculate_adaptive_reveal_size(self, order: Dict[str, Any], strategy: Dict[str, Any]) -> float:
        """Calculate reveal size proportional to market volume."""
        base_size = float(strategy.get("base_size", order["total_size"]))
        volume_window = int(strategy.get("volume_window", 60))
        reveal_multiplier = float(strategy.get("reveal_multiplier", 0.1))
        max_reveal_pct = float(strategy.get("max_reveal_percentage", 0.5))
        
        # Get market volume in window
        market_volume = self._get_market_volume(order["product_id"], volume_window)
        baseline_volume = self._get_baseline_volume(order["product_id"])
        
        if baseline_volume <= 0:
            volume_ratio = 1.0
        else:
            volume_ratio = market_volume / baseline_volume
        
        # Calculate reveal: base_size * volume_ratio * multiplier
        reveal_size = base_size * volume_ratio * reveal_multiplier
        
        # Cap at max percentage of total hidden size
        max_reveal = order["total_size"] * max_reveal_pct
        reveal_size = min(reveal_size, max_reveal)
        
        # Don't exceed remaining
        reveal_size = min(reveal_size, order["remaining_size"])
        
        return reveal_size
    
    def _calculate_tranche_reveal_size(self, order: Dict[str, Any], strategy: Dict[str, Any]) -> float:
        """Calculate tranche-based reveals (25%, 50%, 75%, 100%)."""
        tranches = strategy.get("tranches", [0.25, 0.50, 0.75, 1.0])
        reveal_count = len(order["revealed_orders"])
        
        if reveal_count >= len(tranches):
            return 0
        
        tranche_pct = tranches[reveal_count]
        return order["total_size"] * tranche_pct - order["revealed_size"]
    
    def _get_stealth_order(self, stealth_order_id: str) -> Optional[Dict[str, Any]]:
        """Get stealth order from memory cache or database."""
        if stealth_order_id in self.in_memory_orders:
            return self.in_memory_orders[stealth_order_id]
        
        # Load from database
        order = self._load_stealth_order_from_db(stealth_order_id)
        if order:
            self.in_memory_orders[stealth_order_id] = order
        
        return order
    
    def _get_current_market_data(self, product_id: str) -> Dict[str, Any]:
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
        
        # Use provided target movement or inherit from original
        follow_up_target_movement = target_movement if target_movement is not None else original_order.get("target_movement")
        follow_up_target_movement_type = target_movement_type if target_movement is not None else original_order.get("target_movement_type", "P")
        
        # Create follow-up with same reveal condition and sizing strategy
        # Link the follow-up as a child order to the ORIGINAL root parent (not the filled child)
        # This maintains a flat, single-level Parent:Child hierarchy as per design
        follow_up_id = self.create_stealth_order(
            product_id=original_order["product_id"],
            side=side,
            total_size=total_size,
            limit_price=limit_price,
            reveal_condition=follow_up_condition,
            sizing_strategy=original_order.get("sizing_strategy_json", {}),
            parent_order_id=original_order.get("parent_order_id") or original_stealth_order_id,
            follow_up_reveal_direction=follow_up_reveal_direction or original_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value),
            reveal_pricing_policy=effective_pricing_policy,
            reason="follow_up_replacement",
            notes=f"Follow-up to {original_stealth_order_id[:8]}... {notes}"
        )
        
        # Set target movement on the new child order and persist to database
        if follow_up_id:
            follow_up_order = self._get_stealth_order(follow_up_id)
            if follow_up_order:
                follow_up_order["target_movement"] = follow_up_target_movement
                follow_up_order["target_movement_type"] = follow_up_target_movement_type
                self._update_stealth_order(follow_up_order)
        
        return follow_up_id
    
    # Database operations
    
    def _save_stealth_order_to_db(self, order: Dict[str, Any]):
        """Persist stealth order to database."""
        if not self.db_client:
            return
        
        try:
            self.db_client.execute_update(
                """INSERT INTO stealth_orders 
                   (stealth_order_id, product_id, side, total_size, remaining_size, 
                    limit_price, status, reveal_condition_type, reveal_condition_json, 
                    sizing_strategy_json, reason, notes, parent_order_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                 order.get('parent_order_id'))
            )
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_save_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
    
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
            
            self.db_client.execute_update(
                """UPDATE stealth_orders 
                   SET status = %s, revealed_size = %s, remaining_size = %s, 
                       executed_size = %s, revealed_orders = %s, last_placement_at = %s
                   WHERE stealth_order_id = %s""",
                (order['status'],
                 order.get('revealed_size', 0),
                 order.get('remaining_size', 0),
                 order.get('executed_size', 0),
                 revealed_orders_json,
                 last_placement,
                 order['stealth_order_id'])
            )
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_update_failed", "stealth_order_id": order['stealth_order_id'], "error": str(e)})
    
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
                
                # Helper function to parse JSON safely (handles both str and dict)
                def parse_json_field(value, default):
                    if value is None:
                        return default
                    if isinstance(value, dict):
                        return value  # Already parsed by PostgreSQL
                    if isinstance(value, str):
                        return json.loads(value)
                    return default
                
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
                    'reveal_condition_json': parse_json_field(row.get('reveal_condition_json'), {}),
                    'sizing_strategy_json': parse_json_field(row.get('sizing_strategy_json'), {}),
                    'reason': row.get('reason', ''),
                    'notes': row.get('notes', ''),
                    'parent_order_id': row.get('parent_order_id'),
                    'revealed_orders': parse_json_field(row.get('revealed_orders'), []),
                    'created_at': row.get('created_at'),
                    'condition_first_met_at': row.get('condition_first_met_at'),
                    'condition_confirmed_at': row.get('condition_confirmed_at'),
                }
        except Exception as e:
            self.log_callback("error", {"event": "stealth_order_load_failed", "stealth_order_id": stealth_order_id, "error": str(e)})
        
        return None
    
    def load_all_active_orders_from_db(self) -> int:
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
            return 0
        
        try:
            results = self.db_client.execute_query(
                """SELECT * FROM stealth_orders 
                   ORDER BY created_at ASC"""
            )
            
            # Helper function to parse JSON safely (handles both str and dict)
            def parse_json_field(value, default):
                if value is None:
                    return default
                if isinstance(value, dict):
                    return value  # Already parsed by PostgreSQL
                if isinstance(value, str):
                    return json.loads(value)
                return default
            
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
                        'reveal_condition_json': parse_json_field(row.get('reveal_condition_json'), {}),
                        'sizing_strategy_json': parse_json_field(row.get('sizing_strategy_json'), {}),
                        'reason': row.get('reason', ''),
                        'notes': row.get('notes', ''),
                        'parent_order_id': row.get('parent_order_id'),
                        'revealed_orders': parse_json_field(row.get('revealed_orders'), []),
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
                    loaded_count += 1
                except Exception as e:
                    self.log_callback("error", {"event": "stealth_order_load_item_failed", "stealth_order_id": row.get('stealth_order_id'), "error": str(e)})
            
            return loaded_count
        except Exception as e:
            self.log_callback("error", {"event": "stealth_orders_batch_load_failed", "error": str(e)})
            return 0
    
    def _record_reveal_event(self, order: Dict[str, Any], reveal_event: Dict[str, Any]):
        """Record reveal event to stealth_order_reveal_history table."""
        if not self.db_client:
            return
        
        try:
            # Get stealth_order_id from order dict (not reveal_event)
            stealth_order_id = order.get('stealth_order_id')
            if not stealth_order_id:
                return
            
            self.db_client.execute_update(
                """INSERT INTO stealth_order_reveal_history
                   (stealth_order_id, reveal_number, revealed_size, placement_price, placed_order_id,
                    exchange_order_id, market_price, market_bid, market_ask, market_spread, market_volume_1m,
                    reveal_trigger_reason, reveal_trigger_data)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (stealth_order_id,
                 reveal_event.get('reveal_number', 1),
                 reveal_event.get('revealed_size', 0),
                 reveal_event.get('placement_price'),
                 reveal_event.get('placed_order_id'),
                 reveal_event.get('exchange_order_id'),
                 reveal_event.get('market_price'),
                 reveal_event.get('market_bid'),
                 reveal_event.get('market_ask'),
                 reveal_event.get('market_spread'),
                 reveal_event.get('market_volume_1m'),
                 f"Price below {reveal_event.get('target_price', 'unknown')}",
                 json.dumps({
                     'market_price': reveal_event.get('market_price'),
                     'market_bid': reveal_event.get('market_bid'),
                     'market_ask': reveal_event.get('market_ask'),
                     'market_spread': reveal_event.get('market_spread'),
                     'market_volume_1m': reveal_event.get('market_volume_1m'),
                     'market_source': reveal_event.get('market_source'),
                     'reveal_time': reveal_event.get('reveal_time').isoformat() if hasattr(reveal_event.get('reveal_time'), 'isoformat') else None
                 }))
            )
        except Exception as e:
            self.log_callback("error", {"event": "stealth_reveal_event_recording_failed", "error": str(e)})
