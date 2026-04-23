"""Stealth Order Manager - The unified order creation and lifecycle system.

All orders in the system flow through this manager with automated reveal conditions.
Orders are created in HIDDEN state and automatically revealed based on their
reveal_condition (time-based, price-based, or immediate).

Key Concepts:
- reveal_condition: Controls when/how an order transitions from HIDDEN to PENDING to FILLED
- delay_seconds: For time-based reveals (0 = immediate, 300 = 5 minutes, etc.)
- price_condition: For price-based reveals (reveal when price drops below X, etc.)
- Parent:Child Relationships: 1:Many - one parent order can have many follow-ups

The term "stealth" reflects the internal implementation but from the API perspective,
all orders are just orders with configurable reveal timing. """


import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

from configuration import DEFAULT_MAX_ORDER_REPLACEMENT
from core.enums import FollowUpRevealDirection, StealthOrderStatus
from business.stealth_condition_evaluator import get_evaluator
from database.order import insert_order_parent


class StealthOrderManager:
    """Manages the complete lifecycle of all orders with automated reveal conditions.
    
    ARCHITECTURE: This is now the ONLY order creation and management system.
    All orders flow through this system:
    - Orders start in HIDDEN state with a reveal_condition
    - The reveal_condition controls when/how orders transition to the exchange
    - A reveal_condition with delay=0 creates immediate reveals (traditional orders)
    - More complex conditions enable sophisticated trading strategies
    
    The term "stealth" is internal - from the API perspective, these are just orders
    with configurable reveal timing.
    
    Features:
    - Create orders with flexible reveal conditions (time-based, price-based, etc.)
    - Evaluate conditions in real-time
    - Adaptive sizing (volume-proportional reveals)
    - Track execution and history
    - Database integration
    - Parent:Child order relationships (1:Many)
    """
    
    def __init__(self, db_client, log_callback=None):
        """
        Initialize StealthOrderManager.
        
        Args:
            db_client: Database client for persistence
            log_callback: Optional logging callback (log_type, message). Defaults to print fallback.
        """
        self.db_client = db_client
        self.log_callback = log_callback or self._default_log
        self.in_memory_orders = {}  # For caching/quick access
        self._market_cache = {}  # Market data cache: product_id -> market_data
        self._placed_order_index = {}  # Index: placed_order_id -> stealth_order (O(1) lookup)
    
    def _default_log(self, log_type: str, message: str):
        """Fallback logging if no callback provided."""
        if isinstance(message, (dict, list)):
            message = json.dumps(message, sort_keys=True, default=str)
        print(f"[{log_type.upper()}] {message}")

    
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
        target_movement_type: str = "P"
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
        elif not condition_met and order.get("condition_first_met_at") is None:
            # First time condition partially met
            if reason and ("watching" in reason or "waiting" in reason):
                order["condition_first_met_at"] = datetime.utcnow()
                order["status"] = StealthOrderStatus.PENDING.value
                self._update_stealth_order(order)
        
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
        
        try:
            from configuration import REST_CLIENT
            
            # ⚠️ CRITICAL: Use the stealth_order_id as client_order_id for the revealed order
            # This creates the direct link: stealth_order_id → placed order → fill event
            client_order_id = order["stealth_order_id"]
            
            # Place order directly on the exchange via REST API
            # ⚠️ CRITICAL: Do NOT call create_limit_order_span() here as it creates another stealth order!
            # Use REST_CLIENT.place_limit_order() which is purpose-built for this
            order_result = REST_CLIENT.place_limit_order(
                product_id=order["product_id"],
                side=order["side"],
                limit_price=str(order["limit_price"]),
                base_size=str(slice_size),
                client_order_id=client_order_id,
                post_only=False
            )
            
            # ✓ Use the client_order_id we sent (stealth_order_id)
            # When fill event arrives with this client_order_id, it links directly to stealth order
            placed_order_id = client_order_id
            placement_success = True
            
            self.log_callback("info", {
                "event": "stealth_order_slice_placed_successfully",
                "stealth_order_id": order['stealth_order_id'],
                "client_order_id": placed_order_id,
                "size": slice_size,
                "product_id": order["product_id"],
                "limit_price": order["limit_price"]
            })
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
        
        # Record reveal event with placement status tracking
        reveal_event = {
            "reveal_number": len(order["revealed_orders"]) + 1,
            "revealed_size": slice_size,
            "placed_order_id": placed_order_id,
            "placement_success": placement_success,  # ✓ Track if actually placed on exchange
            "placement_error": placement_error,      # Error message if failed
            "reveal_time": datetime.utcnow(),
            "market_price": self._get_current_market_data(order["product_id"]).get("price"),
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
        
        order["executed_size"] = float(executed_size)
        order["status"] = order_status
        order["updated_at"] = datetime.utcnow()
        
        self._update_stealth_order(order)
    
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
    
    def create_follow_up_stealth_order(
        self,
        original_stealth_order_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        reveal_condition: Optional[Dict[str, Any]] = None,
        follow_up_reveal_direction: Optional[str] = None,
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
                    reveal_trigger_reason, reveal_trigger_data)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (stealth_order_id,
                 reveal_event.get('reveal_number', 1),
                 reveal_event.get('revealed_size', 0),
                 reveal_event.get('placement_price'),
                 reveal_event.get('placed_order_id'),
                 f"Price below {reveal_event.get('target_price', 'unknown')}",
                 json.dumps({
                     'market_price': reveal_event.get('market_price'),
                     'reveal_time': reveal_event.get('reveal_time').isoformat() if hasattr(reveal_event.get('reveal_time'), 'isoformat') else None
                 }))
            )
        except Exception as e:
            self.log_callback("error", {"event": "stealth_reveal_event_recording_failed", "error": str(e)})
