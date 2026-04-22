"""OrderEngine - Multithreaded trading engine for Coinbase Advanced API.

Core responsibilities:
- Real-time order event processing via WebSocket
- Parent-child order relationship lifecycle management  
- Automatic follow-up order creation on fills/cancellations
- Position tracking for derivatives
- Thread-safe orderbook state synchronization with database

ARCHITECTURE: Unified Order System
===================================

All orders flow through StealthOrderManager with automated reveal conditions:
- Orders are created via StealthOrderManager.create_stealth_order()
- Orders start in HIDDEN state with a reveal_condition
- Conditions are evaluated continuously (time-based, price-based, immediate)
- When condition is met, order transitions to PENDING, then to FILLED/CANCELLED
- OrderEngine processes fill events and creates follow-up orders

Parent:Child Order Relationships (1:Many)
=========================================

The system enforces a 1:Many parent-child relationship:
- ONE parent order can have MANY child orders (follow-ups)
- Parent: The initial order that triggers follow-up creation
- Child: Orders created when parent fills or is cancelled
- Example: 
  - Create parent order: BUY 10 @ $40,000 (via reveal condition)
  - Parent fills
  - OrderEngine detects fill and creates follow-up child: SELL 10 @ $41,000
  
Data Structures:
- order_parent_ids: Dict[parent_id → {orders: [child_ids], ...}]
- child_order_ids: Dict[child_id → parent_id]

This module maintains:
- Live WebSocket connection for real-time order updates
- Parent-child order relationships and lifecycle
- Automatic follow-up creation logic
- Order deduplication with thread-safe event processing
- In-memory orderbook state synchronized with PostgreSQL
- Position tracking for futures contracts
"""

import json
import threading
from time import sleep
from queue import Queue, Full
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from coinbase.websocket import WSClient, WSClientConnectionClosedException

from external import CoinbaseWebSocketClient

from configuration import (
    DEFAULT_MAX_ORDER_REPLACEMENT,
    calculate_new_order_move_from_snapshot,
    apply_calculated_position_update,
    get_futures_positions,
)

from core.constants import get_local_now
from core.enums import OrderStatus, OrderSide, ProductType, FollowUpRevealDirection, Direction, TargetMovementType, ChannelType, StealthOrderStatus
from calculation.resolver import resolve_order_size, resolve_order_side
from calculation.formatter import safe_float
from bridges.calculator_bridge import CalculatorBridge
from bridges.processor_bridge import ProcessorBridge
from bridges.event_bridge import EventBridge

# Dashboard integration (optional - will fail gracefully if dashboard_server not available)
try:
    from dashboard_server import update_order, update_position, add_log_entry, update_engine_status, broadcast_ticker, record_spread_tick
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    def update_order(*args, **kwargs): pass
    def update_position(*args, **kwargs): pass
    def add_log_entry(*args, **kwargs): pass
    def update_engine_status(*args, **kwargs): pass
    def broadcast_ticker(*args, **kwargs): pass
    def record_spread_tick(*args, **kwargs): pass


class OrderEngine:
    """Multithreaded trading engine for Coinbase Advanced API order management.
    
    Orchestrates real-time order processing, parent-child order relationship tracking,
    and automatic follow-up order creation. Handles all threading, state management,
    and event deduplication.
    
    Attributes:
        orderbook: OrderBook instance (source-of-truth for orders/positions).
        db_helper: Database client for persisting parent/child orders.
        subscription: Subscription config (products, channels).
        api_key: Coinbase API key for websocket authentication.
        api_secret: Coinbase API secret for websocket authentication.
        order_post_only: Dict mapping side ('BUY'/'SELL') to post_only flag.
        websocket_thread_maximum: Number of websocket connection threads.
        max_workers: Thread pool size for event processing.
        max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval (seconds).
        max_seen_event_buckets: Number of rolling dedup hash buckets.
        ticker: Dict mapping product_id to last ticker data.
        ticker_lock: Thread lock for ticker updates.
        orderbook_lock: Thread lock for orderbook mutations.
        event_executor: ThreadPoolExecutor for user event processing.
        event_queue: Dict mapping channel name to Queue.
        logging_flags: Dict controlling which log types are emitted.
        debug_logging_enabled: Whether to include debug fields in logs.
        calc_bridge: CalculatorBridge instance for order calculations.
        proc_bridge: ProcessorBridge instance for order processing.
        evt_bridge: EventBridge instance for event deduplication and bucket rotation.
        websocket_events: Event type schemas (internal reference).
    
    Example:
        >>> from core.order_engine import OrderEngine
        >>> engine = OrderEngine(
        ...     orderbook=ORDERBOOK,
        ...     db_helper=DB_HELPER,
        ...     subscription=Subscription,
        ...     api_key=API_KEY,
        ...     api_secret=API_SECRET,
        ...     order_post_only=ORDER_POST_ONLY,
        ...     websocket_thread_maximum=2,
        ...     max_workers=8
        ... )
        >>> engine.logging_flags['order'] = True  # Enable order logging
        >>> engine.run_forever()  # Start all background threads and loop
    """

    def __init__(
        self,
        orderbook,
        db_helper,
        subscription,
        api_key,
        api_secret,
        order_post_only,
        websocket_thread_maximum=3,
        max_workers=16,
        max_rotate_seen_events_bucket_seconds=60,
        max_seen_event_buckets=3,
        queue_maxsize=10000,
        stealth_order_bridge=None,
    ) -> None:
        """Initialize the OrderEngine with configuration and state.
        
        Args:
            orderbook: OrderBook instance for state tracking.
            db_helper: Database client module.
            subscription: Subscription config object.
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            order_post_only: Dict mapping order side to post_only flag.
            websocket_thread_maximum: Number of parallel websocket threads (default 3).
            max_workers: Thread pool size (default 16).
            max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval (default 60).
            max_seen_event_buckets: Number of dedup buckets (default 3).
            queue_maxsize: Max size for event queues (default 10000).
            stealth_order_bridge: Optional StealthOrderBridge for market data updates.
        """
        self.orderbook = orderbook
        self.db_helper = db_helper
        self.subscription = subscription
        self.api_key = api_key
        self.api_secret = api_secret
        self.order_post_only = order_post_only
        self.stealth_order_bridge = stealth_order_bridge

        self.websocket_thread_maximum = websocket_thread_maximum
        self.max_rotate_seen_events_bucket_seconds = max_rotate_seen_events_bucket_seconds
        self.max_seen_event_buckets = max_seen_event_buckets
        self.queue_maxsize = queue_maxsize

        self.ticker = {}
        self.ticker_lock = threading.Lock()
        self.orderbook_lock = threading.Lock()

        self.event_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="user_event_thread",
        )

        self.event_queue = {
            channel: Queue(maxsize=self.queue_maxsize)
            for channel in self.subscription.channels
        }

        self.logging_flags = {
            "snapshot": False,
            "open": True,
            "filled": True,
            "cancelled": True,
            "update": True,
            "user": False,
            "ticker": False,
            "connection": True,
            "event": True,
            "order": True,
            "database": True,
            "warning": True,
            "error": True,
            "reconcile": True,
        }
        self.debug_logging_enabled = False
        
        # Phase 4 Integration: CalculatorBridge, ProcessorBridge, & EventBridge
        self.calc_bridge = CalculatorBridge()
        self.proc_bridge = ProcessorBridge()
        self.evt_bridge = EventBridge(
            max_dedup_buckets=max_seen_event_buckets,
            dedup_bucket_duration_secs=max_rotate_seen_events_bucket_seconds,
        )
        
        # Profit Tracking: FeeManager and ProfitValidator for profitable order validation
        from configuration import REST_CLIENT
        from calculation.fee_manager import FeeManager
        from calculation.profit_validator import ProfitValidator
        
        self.fee_manager = FeeManager(REST_CLIENT, log_callback=self.log_message)
        self.profit_validator = ProfitValidator(fee_manager=self.fee_manager)

        self.websocket_events = {
            "SNAPSHOT": {
                "type": "snapshot",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
            "OPEN": {"type": "open", "orders": []},
            "FILLED": {"type": "filled", "orders": []},
            "CANCELLED": {"type": "cancelled", "orders": []},
            "UPDATE": {
                "type": "update",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
        }

        self.orderbook.db_helper = self.db_helper

    def log_message(self, log_type: str, message) -> None:
        """Log a message if the log type is enabled.
        
        Formats message with timestamp and thread name. Converts dicts/lists to JSON.
        
        Args:
            log_type: Log category (enabled via logging_flags dict).
            message: Message text or dict/list to log.
        
        Returns:
            None
        
        Example:
            >>> engine.log_message("order", {"event": "order_placed", "id": "123"})
        """
        if not self.logging_flags.get(log_type, False):
            return

        if isinstance(message, (dict, list)):
            message = json.dumps(message, sort_keys=True, default=str)

        from logging_service import get_logger
        logger = get_logger("OrderEngine")
        logger.info(f"{threading.current_thread().name} [{log_type.upper()}] {message}")

    @staticmethod
    def order_limit_price_or_avg_price(order: dict) -> float:
        """Extract the price from an order, preferring limit_price over avg_price.
        
        Args:
            order: Order dict with optional 'limit_price' and 'avg_price' fields.
        
        Returns:
            The price as a float (limit_price if present and > 0, else avg_price).
        
        Example:
            >>> price = OrderEngine.order_limit_price_or_avg_price(
            ...     {'limit_price': '100.50', 'avg_price': '100.00'})
            >>> price
            100.5
        """
        if order.get("limit_price") and float(order["limit_price"]) > 0:
            return float(order["limit_price"])
        return float(order["avg_price"])

    def build_order_log_context(self, order: dict) -> dict:
        """Build a concise log dict from order data.
        
        Extracts key fields for logging without dumping entire order.
        
        Args:
            order: Order dict.
        
        Returns:
            Dict with client_order_id, order_id, product_type, product_id, side, status, price.
        
        Example:
            >>> ctx = engine.build_order_log_context({'client_order_id': 'id123', ...})
            >>> ctx['product_id']
            'BTC-USDC'
        """
        if not order:
            return {}

        price = None
        try:
            price = self.order_limit_price_or_avg_price(order)
        except Exception:
            price = None

        return {
            "client_order_id": order.get("client_order_id"),
            "order_id": order.get("order_id"),
            "product_type": self.normalize_product_type(order),
            "product_id": order.get("product_id"),
            "side": order.get("order_side") or order.get("side"),
            "status": order.get("status"),
            "price": price,
        }

    def build_event_log_payload(self, event: str, **kwargs) -> dict:
        """Build a structured log payload with event name and kwargs.
        
        Args:
            event: Event name.
            **kwargs: Additional fields to include.
        
        Returns:
            Dict with 'event' key plus all kwargs.
        
        Example:
            >>> payload = engine.build_event_log_payload(
            ...     'order_placed', product_id='BTC-USDC', side='BUY')
            >>> payload['event']
            'order_placed'
        """
        payload = {"event": event}
        payload.update(kwargs)
        return payload

    def include_debug_fields(self, **kwargs) -> dict:
        """Return kwargs dict only if debug_logging_enabled is True.
        
        Used to conditionally include verbose fields in logs.
        
        Args:
            **kwargs: Fields to include if debugging.
        
        Returns:
            kwargs if debug enabled, else {}.
        
        Example:
            >>> debug_ctx = engine.include_debug_fields(raw_order={...})
            >>> len(debug_ctx)  # 0 if debug disabled, 1 if enabled
        """
        if not self.debug_logging_enabled:
            return {}
        return {
            key: value for key, value in kwargs.items()
            if value is not None
        }

    def normalize_product_type(self, order: dict) -> str:
        """Determine if order is SPOT or FUTURE.
        
        Checks order field, product metadata, and product_id suffix.
        Thread-safe access to orderbook.
        
        Args:
            order: Order dict.
        
        Returns:
            'SPOT' or 'FUTURE'.
        
        Example:
            >>> ptype = engine.normalize_product_type({'product_id': 'BTC-USDC'})
            >>> ptype
            'SPOT'
        """
        product_type = str(order.get("product_type") or "").upper()
        if product_type in {"SPOT", "FUTURE"}:
            return product_type

        product_id = order.get("product_id")
        with self.orderbook_lock:
            product = self.orderbook.product.get(product_id, {})

        configured_product_type = str(product.get("product_type") or "").upper()
        if configured_product_type in {"SPOT", "FUTURE"}:
            return configured_product_type

        if product_id and product_id.endswith("-CDE"):
            return "FUTURE"
        return "SPOT"

    # Note: resolve_order_size is now imported from calculation.resolver

    def resolve_profit_target(self, order: dict) -> float:
        """Get configured profit target % for an order.
        
        Args:
            order: Order dict with product_id and order_side.
        
        Returns:
            Profit % (e.g., 0.004 for 0.4%).
        
        Example:
            >>> profit = engine.resolve_profit_target({'product_id': 'BTC-USDC', 'order_side': 'BUY'})
            >>> profit
            0.004
        """
        product_type = self.normalize_product_type(order)
        product_id = order.get("product_id")
        order_side = order.get("order_side")

        product_profit = self.orderbook.profit.get(product_id)
        if isinstance(product_profit, dict) and order_side in product_profit:
            return product_profit[order_side]

        type_profit = self.orderbook.profit.get(product_type, {})
        return type_profit[order_side]

    def get_orderbook_snapshot(self) -> dict:
        """Get thread-safe snapshot of orderbook state.
        
        Deep copies mutable state to prevent concurrent modification issues.
        
        Returns:
            Dict with order, positions, product, profit, mandatory_fee_per_contract,
            parent_order_ids, child_order_ids keys.
        
        Example:
            >>> snap = engine.get_orderbook_snapshot()
            >>> orders = snap['order']
        """
        with self.orderbook_lock:
            return {
                "order": deepcopy(self.orderbook.order),
                "positions": deepcopy(self.orderbook.positions),
                "product": self.orderbook.product,
                "profit": self.orderbook.profit,
                "mandatory_fee_per_contract": self.orderbook.mandatory_fee_per_contract,
                "parent_order_ids": deepcopy(self.orderbook.parent_order_ids),
                "child_order_ids": deepcopy(self.orderbook.child_order_ids),
            }

    def refresh_positions_if_needed(self, product_id: str) -> None:
        """Refresh futures positions from API if product_id not in cache.
        
        Args:
            product_id: Product ID to check/refresh.
        
        Returns:
            None
        
        Example:
            >>> engine.refresh_positions_if_needed('BIP-20DEC30-CDE')
        """
        with self.orderbook_lock:
            future_positions = self.orderbook.positions.setdefault("FUTURE", {})
            if product_id in future_positions:
                return

        try:
            refreshed_positions = get_futures_positions()
        except Exception as e:
            self.log_message("error", f"Failed to refresh futures positions for {product_id}: {e}")
            return

        with self.orderbook_lock:
            self.orderbook.positions["FUTURE"] = refreshed_positions

    def resolve_parent_client_order_id(self, client_order_id: str, order: dict = None, create_parent: bool = False, status: str = None) -> tuple:
        """Resolve if an order is a parent or find its parent.
        
        Returns (is_parent: bool, parent_client_order_id: str).
        Optionally creates a new parent entry if create_parent=True.
        
        Args:
            client_order_id: The order to resolve.
            order: Order data (required if create_parent=True).
            create_parent: Whether to create parent entry if not found.
            status: Order status (for parent creation).
        
        Returns:
            Tuple (is_parent, parent_client_order_id).
        
        Example:
            >>> is_parent, parent_id = engine.resolve_parent_client_order_id('order_123')
            >>> if is_parent:
            ...     print(f"This is a parent order")
        """
        is_parent = False
        parent_client_order_id = None

        if client_order_id in self.orderbook.parent_order_ids:
            is_parent = True
            parent_client_order_id = client_order_id

        elif client_order_id in self.orderbook.child_order_ids:
            parent_client_order_id = self.orderbook.child_order_ids[client_order_id]

        elif create_parent and order is not None:
            max_order_replacement = getattr(
                self.orderbook,
                "default_max_order_replacement",
                DEFAULT_MAX_ORDER_REPLACEMENT,
            )

            self.orderbook.parent_order_ids[client_order_id] = {
                "orders": [],
                "target_movement": {
                    "movement": self.resolve_profit_target(order),
                    "type": "P",
                },
                "max_order_replacement": max_order_replacement,
                "current_order_replacement": 0,
            }

            self.log_message(
                "order",
                self.build_event_log_payload(
                    "parent_order_entry_created",
                    source=self.build_order_log_context(order),
                ),
            )

            parent_id = self.db_helper.insert_order_parent(
                client_order_id=client_order_id,
                product_id=order["product_id"],
                side=order["order_side"],
                size=float(resolve_order_size(order)),
                price=float(self.order_limit_price_or_avg_price(order)),
                target_movement=float(
                    self.orderbook.parent_order_ids[client_order_id]["target_movement"]["movement"]
                ),
                status=status or order.get("status"),
                max_order_replacement=self.orderbook.parent_order_ids[client_order_id]["max_order_replacement"],
                current_order_replacement=self.orderbook.parent_order_ids[client_order_id]["current_order_replacement"],
            )

            self.orderbook.parent_order_ids[client_order_id]["parent_id"] = parent_id
            is_parent = True
            parent_client_order_id = client_order_id

        return is_parent, parent_client_order_id

    def claim_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> bool:
        """Atomically claim processing rights for a follow-up order.
        
        Prevents duplicate follow-up creation by setting processing flag.
        Returns False if already claimed or done.
        
        Args:
            processed_flag_name: Flag dict name ('filled' or 'cancelled').
            client_order_id: Order to claim.
        
        Returns:
            True if claimed, False if already in progress/done.
        
        Example:
            >>> if engine.claim_follow_up_processing('filled', 'order_123'):
            ...     # Do follow-up work
        """
        with self.orderbook_lock:
            processed_flags = getattr(self.orderbook, processed_flag_name, None)
            if not isinstance(processed_flags, dict):
                return False

            state = processed_flags.get(client_order_id)

            if state in {"processing", "done", True}:
                return False

            processed_flags[client_order_id] = "processing"
            return True

    def release_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> None:
        """Release a processing claim (on error, before retry).
        
        Args:
            processed_flag_name: Flag dict name.
            client_order_id: Order to release.
        
        Returns:
            None
        """
        with self.orderbook_lock:
            processed_flags = getattr(self.orderbook, processed_flag_name, None)
            if not isinstance(processed_flags, dict):
                return

            if processed_flags.get(client_order_id) == "processing":
                processed_flags.pop(client_order_id, None)

    def complete_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> None:
        """Mark follow-up processing as complete (prevents future retries).
        
        Args:
            processed_flag_name: Flag dict name.
            client_order_id: Order to complete.
        
        Returns:
            None
        """
        with self.orderbook_lock:
            processed_flags = getattr(self.orderbook, processed_flag_name, None)
            if not isinstance(processed_flags, dict):
                return

            processed_flags[client_order_id] = "done"

    def register_child_order(self, child_client_order_id: str, parent_client_order_id: str) -> None:
        """Register a child order under a parent in the orderbook.
        
        Maintains bidirectional mappings:
        - parent_order_ids[parent][orders] list contains child
        - child_order_ids[child] points to parent
        
        Args:
            child_client_order_id: The child order to register.
            parent_client_order_id: The parent order to register under.
        
        Returns:
            None
        
        Example:
            >>> engine.register_child_order('child_123', 'parent_123')
            >>> # Now child_123 is tracked as child of parent_123
        """
        with self.orderbook_lock:
            # Ensure parent entry exists
            if parent_client_order_id not in self.orderbook.parent_order_ids:
                self.orderbook.parent_order_ids[parent_client_order_id] = {
                    "orders": [],
                    "target_movement": {"movement": 0, "type": "P"},
                    "max_order_replacement": getattr(
                        self.orderbook,
                        "default_max_order_replacement",
                        DEFAULT_MAX_ORDER_REPLACEMENT,
                    ),
                    "current_order_replacement": 0,
                }
            
            # Add child to parent's orders list if not already there
            if child_client_order_id not in self.orderbook.parent_order_ids[parent_client_order_id]["orders"]:
                self.orderbook.parent_order_ids[parent_client_order_id]["orders"].append(child_client_order_id)
            
            # Map child to parent
            self.orderbook.child_order_ids[child_client_order_id] = parent_client_order_id

    def _update_dashboard_order_status(self, client_order_id: str, order: dict, status: str) -> None:
        """Update dashboard with current order status.
        
        Extracts order details and pushes to dashboard, plus logs the update.
        
        Args:
            client_order_id: The order's client order ID.
            order: Order data dict.
            status: Order status (OPEN, CANCELLED, FILLED, FAILED, etc.).
        
        Returns:
            None
        
        Example:
            >>> self._update_dashboard_order_status('order_123', order_data, 'FILLED')
        """
        order_side = resolve_order_side(order)
        order_size = resolve_order_size(order)
        filled_size = safe_float(order.get("filled_size"), default=0.0)
        
        # Push to dashboard
        update_order(client_order_id, {
            "order_id": order.get("id", client_order_id),
            "client_order_id": client_order_id,
            "product_id": order.get("product_id"),
            "side": order_side,
            "size": order_size,
            "price": order.get("limit_price"),
            "filled_size": filled_size,
            "status": status,
        })
        
        # Log the update
        product_id = order.get("product_id", "UNKNOWN")
        if status == OrderStatus.FAILED:
            add_log_entry("ERROR", f"Order FAILED: {product_id} {order_side} - Check account balance/margin")
        elif status == OrderStatus.OPEN:
            add_log_entry("INFO", f"Order OPEN: {product_id} {order_side} {order_size}")
        elif status == OrderStatus.CANCELLED:
            add_log_entry("INFO", f"Order CANCELLED: {product_id} {order_side} {order_size}")
        elif status == OrderStatus.FILLED:
            add_log_entry("INFO", f"Order FILLED: {product_id} {order_side} {order_size}")

    def _is_external_order(self, client_order_id: str) -> bool:
        """Check if an order is external (not created by our engine).
        
        External orders are ones placed directly via Coinbase UI or API,
        not by our automated order engine.
        
        Args:
            client_order_id: The order's client order ID.
        
        Returns:
            True if order is external (not in our orderbook), False if it's ours.
        
        Example:
            >>> if self._is_external_order('order_123'):
            ...     # Just track it, don't create follow-ups
        """
        return (
            client_order_id not in self.orderbook.parent_order_ids
            and client_order_id not in self.orderbook.child_order_ids
        )

    def _handle_external_order_tracking(
        self,
        client_order_id: str,
        order: dict,
        event_type: str,
        processed_flag_name: str = None,
    ) -> bool:
        """Track external orders (for record-keeping, no follow-ups).
        
        For external orders that we didn't create:
        - Creates a parent entry for tracking purposes
        - Logs the event with appropriate context
        - Completes follow-up processing to prevent retries
        
        Args:
            client_order_id: The order's client order ID.
            order: Order data dict.
            event_type: Type of event ('cancelled' or 'filled').
            processed_flag_name: Flag dict name for completion ('cancelled' or 'filled').
        
        Returns:
            True (indicating we handled this external order and should return early).
        
        Example:
            >>> if self._handle_external_order_tracking('order_123', order, 'cancelled', 'cancelled'):
            ...     return  # Already handled
        """
        # Create a parent entry for tracking purposes only
        with self.orderbook_lock:
            is_parent, parent_client_order_id = self.resolve_parent_client_order_id(
                client_order_id,
                order=order,
                create_parent=True,
                status=event_type.upper(),
            )
        
        # Log the external order event
        event_name = f"external_order_{event_type}"
        self.log_message(
            "order",
            self.build_follow_up_log_payload(
                event_name,
                source_order=order,
                parent_client_order_id=parent_client_order_id,
                details={"reason": "external_order_no_follow_up"},
            ),
        )
        
        # Complete processing to prevent follow-up retries
        if processed_flag_name:
            self.complete_follow_up_processing(processed_flag_name, client_order_id)
        
        return True

    def build_follow_up_log_payload(
        self,
        event: str,
        source_order: dict = None,
        parent_client_order_id: str = None,
        parent_target_movement = None,
        new_order: dict = None,
        attempted_new_order: dict = None,
        details: dict = None,
    ) -> dict:
        """Build structured log payload for follow-up order events.
        
        Args:
            event: Event name.
            source_order: Original order that triggered follow-up.
            parent_client_order_id: Parent order ID.
            parent_target_movement: Parent order's target movement percentage.
            new_order: Newly placed order data.
            attempted_new_order: Order data if placement failed.
            details: Additional details dict.
        
        Returns:
            Structured log payload dict.
        
        Example:
            >>> payload = engine.build_follow_up_log_payload(
            ...     'follow_up_order_placed',
            ...     source_order=order,
            ...     new_order={'client_order_id': 'new_123'}
            ... )
        """
        payload = {"event": event}

        if parent_client_order_id is not None:
            payload["parent_client_order_id"] = parent_client_order_id

        if parent_target_movement is not None:
            payload["parent_target_movement"] = parent_target_movement

        if source_order is not None:
            payload["source"] = self.build_order_log_context(source_order)

        if new_order is not None:
            payload["new"] = new_order

        if attempted_new_order is not None:
            payload["attempted_new"] = attempted_new_order

        if details:
            payload["details"] = details

        return payload

    def on_open(self) -> None:
        """Callback when websocket connection opens.
        
        Returns:
            None
        """
        self.log_message("connection", "Connection Opened!")

    def on_message(self, msg: str) -> None:
        """Process incoming websocket message.
        
        Parses JSON, deduplicates events using EventBridge, and enqueues for processing.
        
        Args:
            msg: Raw websocket message (JSON string).
        
        Returns:
            None
        """
        try:
            json_msg = json.loads(msg)
            channel = json_msg.get("channel")

            if any((
                "events" not in json_msg,
                channel == ChannelType.SUBSCRIPTIONS.value,
                not channel,
                channel not in self.event_queue,
            )):
                return

            for event in json_msg["events"]:
                # Use EventBridge for duplicate detection
                if self.evt_bridge.is_duplicate_event(event):
                    continue

                try:
                    self.event_queue[channel].put(deepcopy(event), timeout=0.01)

                    # Use EventBridge to mark event as seen
                    self.evt_bridge.mark_event_seen(event)

                except Full:
                    self.log_message(
                        "warning",
                        self.build_event_log_payload(
                            "event_queue_full",
                            channel=channel,
                            **self.include_debug_fields(dropped_event=event),
                        ),
                    )

        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "websocket_message_processing_exception",
                    error=str(e),
                    raw_message=msg,
                ),
            )

    def process_user_event(self, event: dict) -> None:
        """Process user-channel event (orders or positions).
        
        Dispatches to process_user_order or process_user_snapshot.
        
        Args:
            event: Event dict with 'type' and 'orders'/'positions' keys.
        
        Returns:
            None
        """
        try:
            if event["type"].upper() not in self.websocket_events:
                self.log_message(
                    "event",
                    self.build_event_log_payload(
                        "user_event_ignored",
                        **self.include_debug_fields(received_event=event),
                    ),
                )
                return

            if "orders" in event and event["type"].upper() in ["OPEN", "FILLED", "CANCELLED", "UPDATE"]:
                for order in event["orders"]:
                    if "client_order_id" not in order:
                        self.log_message(
                            "warning",
                            self.build_event_log_payload(
                                "missing_client_order_id_in_order_event",
                                source=self.build_order_log_context(order),
                                **self.include_debug_fields(raw_order=order),
                            ),
                        )
                        continue
                    self.process_user_order(order)

            elif "positions" in event:
                self.process_user_snapshot(event)

        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "user_event_processing_error",
                    error=str(e),
                    **self.include_debug_fields(received_event=event),
                ),
            )

    def process_user_snapshot(self, snapshot: dict) -> None:
        """Process position snapshot from websocket.
        
        Updates in-memory futures positions.
        
        Args:
            snapshot: Event dict with 'positions' key.
        
        Returns:
            None
        """
        for _, items in snapshot["positions"].items():
            if not items:
                continue

            for item in items:
                with self.orderbook_lock:
                    self.orderbook.positions["FUTURE"][item["product_id"]] = {
                        "side": item["side"].upper(),
                        "number_of_contracts": item["number_of_contracts"],
                        "realized_pnl": item["realized_pnl"],
                        "unrealized_pnl": item["unrealized_pnl"],
                        "entry_price": item["entry_price"],
                    }

                self.log_message(
                    "snapshot",
                    self.build_event_log_payload(
                        "futures_position_snapshot_updated",
                        product_id=item["product_id"],
                        position=self.orderbook.positions["FUTURE"][item["product_id"]],
                    ),
                )

    def process_user_order(self, order: dict) -> None:
        """Process order event (state transitions).
        
        Updates orderbook, dispatches to fill/cancel handlers, persists to DB.
        
        Args:
            order: Order event dict.
        
        Returns:
            None
        """
        client_order_id = order.get("client_order_id")
        status = order.get("status")

        normalized_order = deepcopy(order)
        normalized_order["product_type"] = self.normalize_product_type(normalized_order)
        outstanding_hold_amount = safe_float(
            normalized_order.get("outstanding_hold_amount"),
            default=0.0,
        )

        with self.orderbook_lock:
            self.orderbook.order[client_order_id] = normalized_order

        if status == OrderStatus.FILLED and outstanding_hold_amount > 0:
            self.log_message(
                "order",
                self.build_event_log_payload(
                    "filled_order_waiting_for_hold_clear",
                    source=self.build_order_log_context(normalized_order),
                    outstanding_hold_amount=normalized_order.get("outstanding_hold_amount"),
                ),
            )
            return

        order = normalized_order

        try:
            # NOTE: All child orders in this system are stealth orders (stored in stealth_orders table).
            # Stealth orders are managed by StealthOrderManager, not via order_child table updates.
            # Therefore, we only update parent orders (stored in order_parent table).
            if client_order_id in self.orderbook.parent_order_ids:
                self.db_helper.update_order_parent_status(
                    client_order_id=client_order_id,
                    status=status,
                )
        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "database_order_status_update_failed",
                    error=str(e),
                    source=self.build_order_log_context(order),
                    **self.include_debug_fields(raw_order=order),
                ),
            )

        if status == "SNAPSHOT":
            return
        if status == OrderStatus.CANCEL_QUEUED:
            return
        if status == OrderStatus.PENDING:
            return
        if status == OrderStatus.FAILED:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "order_failed",
                    source=self.build_order_log_context(order),
                    **self.include_debug_fields(raw_order=order),
                ),
            )
            self._update_dashboard_order_status(client_order_id, order, status)
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            return
        if status == OrderStatus.OPEN:
            self._update_dashboard_order_status(client_order_id, order, status)
            return
        if status == OrderStatus.CANCELLED:
            self.handle_cancelled_order(order)
            self._update_dashboard_order_status(client_order_id, order, status)
            return
        if status == OrderStatus.FILLED:
            self.handle_filled_order(order)
            self._update_dashboard_order_status(client_order_id, order, status)
            return

        self.log_message(
            "warning",
            self.build_event_log_payload(
                "unrecognized_order_status",
                status=status,
                source=self.build_order_log_context(order),
            ),
        )

    def apply_position_update(self, order_template: dict) -> None:
        """Apply position update from order template to orderbook.
        
        Args:
            order_template: Template dict (may have 'position_update' key).
        
        Returns:
            None
        """
        position_update = order_template.get("position_update")
        if not position_update:
            return
        with self.orderbook_lock:
            apply_calculated_position_update(self.orderbook.positions, position_update)
            
            # Push position updates to dashboard
            for product_id, position_data in self.orderbook.positions.items():
                update_position(product_id, {
                    "product_id": product_id,
                    "type": position_data.get("type", "UNKNOWN"),
                    "amount": position_data.get("amount", 0),
                    "entry_price": position_data.get("entry_price", 0),
                    "current_value": position_data.get("current_value", 0),
                    "entry_cost": position_data.get("entry_cost", 0),
                })

    def compute_order_template(self, client_order_id: str, target_movement: dict = None) -> dict:
        """Compute follow-up order template for a given order.
        
        Args:
            client_order_id: Order to compute template for.
            target_movement: Optional override for profit target.
        
        Returns:
            Order template dict or {} if computation fails.
        
        Example:
            >>> template = engine.compute_order_template('order_123')
            >>> print(template['start_price'])
        """
        snapshot = self.get_orderbook_snapshot()
        order = snapshot["order"].get(client_order_id)
        if not order:
            return {}

        if self.normalize_product_type(order) == ProductType.FUTURE:
            product_id = order.get("product_id")
            if product_id not in snapshot.get("positions", {}).get("FUTURE", {}):
                self.refresh_positions_if_needed(product_id)
                snapshot = self.get_orderbook_snapshot()

        return calculate_new_order_move_from_snapshot(
            snapshot,
            order_id=client_order_id,
            target_movement=target_movement,
        )

    def child_order_already_exists(self, parent_client_order_id: str, order_template: dict) -> bool:
        """Check if a child order matching the template already exists.
        
        Queries database to prevent duplicate child orders.
        
        Args:
            parent_client_order_id: Parent order ID.
            order_template: New order template to check.
        
        Returns:
            True if child order already exists, False otherwise.
        
        Example:
            >>> exists = engine.child_order_already_exists('parent_123', template)
            >>> if not exists:
            ...     # Safe to place new order
        """
        if not parent_client_order_id:
            self.log_message(
                "warning",
                f"Order {parent_client_order_id} not found in parent or child order book."
            )
            return False

        if hasattr(self.db_helper, "child_order_exists"):
            try:
                return bool(self.db_helper.child_order_exists(
                    parent_client_order_id=parent_client_order_id,
                    product_id=order_template["product_id"],
                    side=order_template["side"],
                    size=float(order_template["order_base_size"]),
                    price=float(order_template["start_price"]),
                ))
            except TypeError:
                try:
                    return bool(self.db_helper.child_order_exists(parent_client_order_id, order_template))
                except Exception as e:
                    self.log_message(
                        "warning",
                        self.build_event_log_payload(
                            "child_order_exists_check_failed",
                            parent_client_order_id=parent_client_order_id,
                            attempted_new_order=order_template,
                            error=str(e),
                        ),
                    )
            except Exception as e:
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "child_order_exists_check_failed",
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order=order_template,
                        error=str(e),
                    ),
                )

        return False

    def resolve_parent_target_movement(self, parent_client_order_id: str) -> dict:
        """Get configured profit target for a parent order.
        
        Args:
            parent_client_order_id: Parent order ID.
        
        Returns:
            Dict with 'type' and 'movement' keys, or None if parent not found.
        """
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_client_order_id, {})
            return deepcopy(parent.get("target_movement"))

    def resolve_parent_replacement_state(self, parent_client_order_id: str) -> dict:
        """Get current and max replacement counts for a parent order.
        
        Args:
            parent_client_order_id: Parent order ID.
        
        Returns:
            Dict with 'max_order_replacement' and 'current_order_replacement' keys.
        """
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_client_order_id, {})

            return {
                "max_order_replacement": int(parent["max_order_replacement"]),
                "current_order_replacement": int(parent["current_order_replacement"]),
            }

    def can_create_follow_up_order(self, parent_client_order_id: str) -> tuple:
        """Check if a follow-up order can be created for a parent.
        
        Compares current replacement count vs max allowed.
        
        Args:
            parent_client_order_id: Parent order ID.
        
        Returns:
            Tuple (can_create: bool, details: dict).
        
        Example:
            >>> can_create, details = engine.can_create_follow_up_order('parent_123')
            >>> if can_create:
            ...     # Place follow-up order
        """
        replacement_state = self.resolve_parent_replacement_state(parent_client_order_id)
        max_order_replacement = replacement_state["max_order_replacement"]
        current_order_replacement = replacement_state["current_order_replacement"]

        details = {
            "current_order_replacement": current_order_replacement,
            "max_order_replacement": max_order_replacement,
        }
        return current_order_replacement < max_order_replacement, details

    def handle_cancelled_order(self, order: dict) -> None:
        """Handle a cancelled order by potentially creating a follow-up.
        
        If the order is pre-marked for automatic move (move_on_cancel=True),
        executes the pending move instead of creating a child order.
        
        NOTE: External orders (created in Coinbase UI, not by our engine) are
        tracked for record-keeping but do NOT trigger follow-up orders.
        
        Args:
            order: Cancelled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        # CRITICAL: Check for stealth order BEFORE marking as external
        # Stealth-revealed slices won't be in orderbook yet, but they're not external orders
        original_stealth_order = None
        if self.stealth_order_bridge:
            original_stealth_order = self.stealth_order_bridge.stealth_manager.find_stealth_order_by_placed_order_id(
                client_order_id
            )
        
        # If this is a stealth-revealed order, register it in the orderbook first
        if original_stealth_order and original_stealth_order.get("parent_order_id"):
            parent_client_order_id_stealth = original_stealth_order["parent_order_id"]
            self.register_child_order(client_order_id, parent_client_order_id_stealth)

        # Check if this is an external order (not created by our engine)
        # External orders are ones we didn't place, so we shouldn't create follow-ups
        is_external_order = self._is_external_order(client_order_id)

        # CRITICAL: Claim follow-up processing FIRST to prevent duplicates
        # This must happen before any other processing to prevent race conditions
        if not self.claim_follow_up_processing("cancelled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=None,
                    details={"reason": "cancelled_order_follow_up_already_claimed"},
                ),
            )
            return

        # For external orders, just track them but don't create follow-ups
        if is_external_order:
            self._handle_external_order_tracking(
                client_order_id,
                order,
                "cancelled",
                processed_flag_name="cancelled",
            )
            return

        with self.orderbook_lock:
            if self.orderbook.should_replace["CANCELLED"] is not True:
                self.release_follow_up_processing("cancelled", client_order_id)
                return
            is_parent, parent_client_order_id = self.resolve_parent_client_order_id(client_order_id)

        # Check for pending move (automation) - executes instead of normal follow-up
        from database.order import has_pending_move
        if has_pending_move(parent_client_order_id):
            try:
                from business.move_manager import MoveManager
                move_manager = MoveManager(self.orderbook)
                move_result = move_manager.execute_pending_move_for_order(parent_client_order_id)
                
                if move_result["success"]:
                    self.log_message(
                        "order",
                        {
                            "event": "pending_move_auto_executed",
                            "original_parent_client_order_id": parent_client_order_id,
                            "new_parent_client_order_id": move_result["new_parent_client_order_id"],
                            "trigger": "cancelled_order"
                        }
                    )
                    # Successfully handled via pending move, don't do normal follow-up
                    self.complete_follow_up_processing("cancelled", client_order_id)
                    return
                else:
                    self.log_message(
                        "warning",
                        {
                            "event": "pending_move_execution_failed",
                            "original_parent_client_order_id": parent_client_order_id,
                            "error": move_result.get("error"),
                            "message": move_result.get("message")
                        }
                    )
                    # IMPORTANT: Don't fall through to normal follow-up
                    # If a pending move failed, don't create a child order as fallback
                    # Complete the processing to mark as handled
                    self.complete_follow_up_processing("cancelled", client_order_id)
                    return
            except Exception as e:
                self.log_message(
                    "error",
                    {
                        "event": "pending_move_execution_exception",
                        "original_parent_client_order_id": parent_client_order_id,
                        "error": str(e)
                    }
                )
                # IMPORTANT: Don't fall through to normal follow-up
                # If a pending move exception occurs, don't create a child order as fallback
                # Complete the processing to mark as handled
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

        try:
            order_template = self.compute_order_template(client_order_id)
            if not order_template:
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_template_compute_failed",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details={"reason": "cancelled_order_follow_up_template_compute_failed"},
                    ),
                )
                self.release_follow_up_processing("cancelled", client_order_id)
                return

            if self.child_order_already_exists(parent_client_order_id, order_template):
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_duplicate_child_skipped",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order={
                            "product_id": order_template["product_id"],
                            "side": order_template["side"],
                            "price": float(order_template["start_price"]),
                        },
                    ),
                )
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

            # All orders are stealth orders - create stealth follow-up on cancel
            try:
                # Update the original stealth order status to CANCELLED
                if original_stealth_order:
                    self.stealth_order_bridge.stealth_manager.update_execution(
                        stealth_order_id=original_stealth_order["stealth_order_id"],
                        executed_size=0.0,
                        order_status=StealthOrderStatus.CANCELLED.value
                    )
                
                follow_up_price = float(order_template["start_price"])
                
                # Build reveal condition for the follow-up (use same as filled orders)
                reveal_condition = {
                    "type": "time_delay",
                    "delay_seconds": 0  # Immediate reveal on cancel follow-up
                }
                
                # Get target_movement from parent order (source of truth)
                from database.order import get_parent_order
                parent_order_data = get_parent_order(parent_client_order_id)
                parent_target_movement = parent_order_data.get("target_movement") if parent_order_data else None
                parent_target_movement_type = parent_order_data.get("target_movement_type", TargetMovementType.PERCENTAGE.value) if parent_order_data else TargetMovementType.PERCENTAGE.value
                
                stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(
                    original_stealth_order_id=client_order_id,
                    side=order_template["side"],
                    total_size=order_template["order_base_size"],
                    limit_price=follow_up_price,
                    reveal_condition=reveal_condition,
                    follow_up_reveal_direction="same",
                    notes=f"Auto follow-up from cancelled order",
                    target_movement=parent_target_movement,
                    target_movement_type=parent_target_movement_type
                )
                
                # Register stealth follow-up as child of original parent
                self.register_child_order(stealth_follow_up_id, parent_client_order_id)
                
                self.log_message(
                    "order",
                    {
                        "event": "stealth_follow_up_created_on_cancel",
                        "stealth_follow_up_id": stealth_follow_up_id,
                        "parent_id": parent_client_order_id,
                        "product_id": order_template["product_id"],
                        "side": order_template["side"],
                    }
                )
                
                self.complete_follow_up_processing("cancelled", client_order_id)
                return
            except Exception as e:
                self.log_message(
                    "error",
                    {
                        "event": "stealth_follow_up_creation_failed_on_cancel",
                        "error": str(e),
                        "parent_id": parent_client_order_id,
                        "client_order_id": client_order_id
                    }
                )
                # All orders are stealth orders - no fallback to regular orders
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

        except Exception:
            self.release_follow_up_processing("cancelled", client_order_id)
            raise

    def move_cancelled_order(
        self,
        original_parent_client_order_id: str,
        new_order_details: dict,
        reason: str = "cancelled_move",
        notes: str = None
    ) -> dict:
        """Move a cancelled parent order to a new parent order.
        
        Instead of creating a child order, this replaces the parent/child relationship
        by creating a completely new parent order. The original parent remains in the
        database for audit purposes, and the move is recorded in order_moves table.
        
        Args:
            original_parent_client_order_id: The client_order_id of the parent to move.
            new_order_details: Dict with new parent configuration (product_id, side, size,
                             price, target_movement, target_movement_type, max_order_replacement).
            reason: Reason for the move (default 'cancelled_move').
            notes: Optional additional context.
        
        Returns:
            Dict with move result:
            {
                "success": bool,
                "message": str,
                "new_parent_client_order_id": str or None,
                "error": str or None
            }
            
        Example:
            >>> result = engine.move_cancelled_order(
            ...     original_parent_client_order_id="old_parent_uuid",
            ...     new_order_details={
            ...         "product_id": "BTC-USDC",
            ...         "side": "BUY",
            ...         "size": 1.0,
            ...         "price": 42500.0,
            ...         "target_movement": 0.005
            ...     },
            ...     reason="user_cancelled_and_moved"
            ... )
        """
        from business.move_manager import MoveManager
        
        try:
            move_manager = MoveManager(self.orderbook)
            result = move_manager.move_order(
                original_parent_client_order_id=original_parent_client_order_id,
                new_order_details=new_order_details,
                reason=reason,
                notes=notes
            )
            
            if result["success"]:
                self.log_message(
                    "order",
                    {
                        "event": "order_moved",
                        "original_parent_client_order_id": original_parent_client_order_id,
                        "new_parent_client_order_id": result["new_parent_client_order_id"],
                        "move_id": result["move_id"],
                        "reason": reason,
                        "product_id": new_order_details.get("product_id"),
                        "side": new_order_details.get("side"),
                        "price": new_order_details.get("price"),
                        "notes": notes
                    }
                )
            else:
                self.log_message(
                    "warning",
                    {
                        "event": "order_move_failed",
                        "original_parent_client_order_id": original_parent_client_order_id,
                        "reason": reason,
                        "error": result.get("error"),
                        "message": result.get("message")
                    }
                )
            
            return result
            
        except Exception as e:
            error_msg = f"Exception during order move: {str(e)}"
            self.log_message(
                "error",
                {
                    "event": "order_move_exception",
                    "original_parent_client_order_id": original_parent_client_order_id,
                    "error": error_msg
                }
            )
            return {
                "success": False,
                "message": error_msg,
                "new_parent_client_order_id": None,
                "error": error_msg
            }

    def handle_filled_order(self, order: dict) -> None:
        """Handle a filled order by creating a follow-up if allowed.
        
        NOTE: External orders (created in Coinbase UI, not by our engine) are
        tracked for record-keeping but do NOT trigger follow-up orders.
        
        Args:
            order: Filled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        # CRITICAL: Claim follow-up processing FIRST to prevent duplicates
        # This must happen before any other processing to prevent race conditions
        if not self.claim_follow_up_processing("filled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=None,
                    details={"reason": "filled_order_follow_up_already_claimed"},
                ),
            )
            return

        # CRITICAL: Check for stealth order BEFORE marking as external
        # Stealth-revealed slices won't be in orderbook yet, but they're not external orders
        original_stealth_order = None
        if self.stealth_order_bridge:
            original_stealth_order = self.stealth_order_bridge.stealth_manager.find_stealth_order_by_placed_order_id(
                client_order_id
            )
        
        # If this is a stealth-revealed order, register it in the orderbook first
        if original_stealth_order and original_stealth_order.get("parent_order_id"):
            parent_client_order_id_stealth = original_stealth_order["parent_order_id"]
            self.register_child_order(client_order_id, parent_client_order_id_stealth)

        # Check if this is an external order (not created by our engine)
        # External orders are ones we didn't place, so we shouldn't create follow-ups
        is_external_order = self._is_external_order(client_order_id)

        with self.orderbook_lock:
            if self.orderbook.should_replace["FILLED"] is not True:
                return

            _, parent_client_order_id = self.resolve_parent_client_order_id(
                client_order_id,
                order=order,
                create_parent=True,
                status="FILLED",
            )

        # For external orders, just track them but don't create follow-ups
        # EXCEPT: Stealth-revealed orders should create follow-ups (Child stealth orders)
        if is_external_order and not original_stealth_order:
            self._handle_external_order_tracking(
                client_order_id,
                order,
                "filled",
                processed_flag_name=None,  # Don't complete processing for filled orders
            )
            return

        # Handle stealth order fills - create a Child stealth order as follow-up
        # NOTE: This is handled in the later stealth order code path (around line 1663)
        # After normal follow-up processing claims the order. Kept here for reference only.

        # Note: We already claimed processing at the start of handle_filled_order
        # No need to claim again here
        
        try:
            can_replace, replacement_details = self.can_create_follow_up_order(parent_client_order_id)
            if not can_replace:
                self.log_message(
                    "order",
                    self.build_follow_up_log_payload(
                        "follow_up_max_replacements_reached",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details=replacement_details,
                    ),
                )
                self.complete_follow_up_processing("filled", client_order_id)
                return

            target_movement = self.resolve_parent_target_movement(parent_client_order_id)
            order_template = self.compute_order_template(
                client_order_id,
                target_movement=target_movement,
            )
            if not order_template:
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_template_compute_failed",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details={"reason": "filled_order_follow_up_template_compute_failed"},
                    ),
                )
                self.release_follow_up_processing("filled", client_order_id)
                return

            if self.child_order_already_exists(parent_client_order_id, order_template):
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_duplicate_child_skipped",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order={
                            "product_id": order_template["product_id"],
                            "side": order_template["side"],
                            "price": float(order_template["start_price"]),
                        },
                        details=replacement_details,
                    ),
                )
                self.complete_follow_up_processing("filled", client_order_id)
                return

            # Use the stealth order already found at the start of this function
            # If this is a stealth order follow-up, create a stealth order instead of a regular order
            if original_stealth_order:
                try:
                    # Update the original stealth order status to EXECUTED
                    filled_size = float(order.get("filled_size", order_template["order_base_size"]))
                    self.stealth_order_bridge.stealth_manager.update_execution(
                        stealth_order_id=original_stealth_order["stealth_order_id"],
                        executed_size=filled_size,
                        order_status=StealthOrderStatus.EXECUTED.value
                    )
                    
                    # This is a stealth order fill - create a stealth follow-up instead of a regular order
                    follow_up_price = float(order_template["start_price"])
                    
                    # Seed the market cache with the fill price
                    product_id = order["product_id"]
                    fill_price = float(order.get("price", follow_up_price))
                    
                    self.stealth_order_bridge.stealth_manager._market_cache[product_id] = {
                        "product_id": product_id,
                        "price": fill_price,
                        "bid": fill_price,
                        "ask": fill_price,
                        "volume_1m": 0,
                        "time": get_local_now()
                    }
                    
                    # Build the reveal condition for the follow-up using configurable direction
                    follow_up_reveal_condition = dict(original_stealth_order.get("reveal_condition_json", {}))
                    direction_choice = original_stealth_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value)
                    
                    if follow_up_reveal_condition.get("type") == "price":
                        # Set threshold to the ACTUAL price where we plan to place the new order
                        # Use float conversion to ensure numeric precision
                        follow_up_reveal_condition["price_threshold"] = float(follow_up_price)
                        
                        if direction_choice == FollowUpRevealDirection.OPPOSITE.value:
                            # Flip direction (below → above, above → below)
                            if "direction" in follow_up_reveal_condition:
                                follow_up_reveal_condition["direction"] = Direction.ABOVE.value if follow_up_reveal_condition.get("direction") == Direction.BELOW.value else Direction.BELOW.value
                        elif direction_choice == FollowUpRevealDirection.SAME.value:
                            # Keep original direction unchanged
                            pass
                        # else: Unknown direction choice, keep original
                    
                    # Use parent order's target_movement (source of truth)
                    from database.order import get_parent_order
                    parent_order_data = get_parent_order(parent_client_order_id)
                    parent_target_movement = parent_order_data.get("target_movement") if parent_order_data else None
                    parent_target_movement_type = parent_order_data.get("target_movement_type", TargetMovementType.PERCENTAGE.value) if parent_order_data else TargetMovementType.PERCENTAGE.value
                    
                    # Debug: Log the exact reveal condition being set
                    self.log_message(
                        "info",
                        {
                            "event": "stealth_follow_up_condition_set",
                            "follow_up_price": follow_up_price,
                            "fill_price": fill_price,
                            "threshold": follow_up_reveal_condition.get("price_threshold"),
                            "direction": follow_up_reveal_condition.get("direction"),
                            "hold_duration_seconds": follow_up_reveal_condition.get("hold_duration_seconds"),
                            "market_cache_price": self.stealth_order_bridge.stealth_manager._market_cache.get(product_id, {}).get("price"),
                        }
                    )
                    
                    stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(
                        original_stealth_order_id=original_stealth_order["stealth_order_id"],
                        side=order_template["side"],
                        total_size=order_template["order_base_size"],
                        limit_price=follow_up_price,
                        reveal_condition=follow_up_reveal_condition,
                        follow_up_reveal_direction=direction_choice,
                        notes=f"Auto follow-up from stealth order reveal",
                        target_movement=parent_target_movement,
                        target_movement_type=parent_target_movement_type
                    )
                    
                    # Register stealth follow-up as child of original parent
                    self.register_child_order(stealth_follow_up_id, parent_client_order_id)
                    
                    self.log_message(
                        "order",
                        {
                            "event": "stealth_follow_up_created",
                            "stealth_follow_up_id": stealth_follow_up_id,
                            "parent_stealth_id": original_stealth_order["stealth_order_id"],
                            "parent_target_movement": {
                                "movement": parent_target_movement,
                                "type": parent_target_movement_type
                            } if parent_target_movement else None,
                            "product_id": product_id,
                            "side": order_template["side"],
                            "reveal_condition": follow_up_reveal_condition,
                            "follow_up_reveal_direction": direction_choice,
                        }
                    )
                    
                    self.complete_follow_up_processing("filled", client_order_id)
                    return
                except Exception as e:
                    self.log_message(
                        "error",
                        {
                            "event": "stealth_follow_up_creation_failed",
                            "error": str(e),
                            "original_stealth_order_id": original_stealth_order.get("stealth_order_id"),
                            "client_order_id": client_order_id
                        }
                    )
                    # All orders are stealth orders - no fallback to regular orders
                    self.complete_follow_up_processing("filled", client_order_id)
                    return

        except Exception:
            self.release_follow_up_processing("filled", client_order_id)
            raise

    def build_parent_child_order_ids_snapshot(self) -> tuple:
        """Query database and build parent/child order mapping snapshot.
        
        Since all orders are stealth orders, all children are stealth children
        stored in the stealth_orders table with parent_order_id set.
        
        Returns:
            Tuple (parent_order_ids_dict, child_order_ids_dict).
        """
        from database.order import get_stealth_children_for_parent
        
        parent_order_ids = {}
        child_order_ids = {}

        parent_orders = self.db_helper.get_parent_orders()

        for parent in parent_orders:
            parent_client_order_id = parent["client_order_id"]

            parent_order_ids[parent_client_order_id] = {
                "parent_id": parent["id"],
                "orders": [],
                "target_movement": {
                    "movement": float(parent["target_movement"]),
                    "type": parent.get("target_movement_type", TargetMovementType.PERCENTAGE.value),
                },
                "max_order_replacement": int(parent["max_order_replacement"]),
                "current_order_replacement": int(parent["current_order_replacement"]),
            }

            # All children are stealth children (stored in stealth_orders table)
            stealth_children = get_stealth_children_for_parent(parent_client_order_id)
            for stealth_child in stealth_children:
                stealth_child_id = stealth_child["client_order_id"]  # This is stealth_order_id
                parent_order_ids[parent_client_order_id]["orders"].append(stealth_child_id)
                child_order_ids[stealth_child_id] = parent_client_order_id

        return parent_order_ids, child_order_ids

    def adopt_child_to_new_parent(
        self,
        child_client_order_id: str,
        new_parent_client_order_id: str,
        keep_adoption_history: bool = True
    ) -> bool:
        """
        Reassign a child order to a new parent order (adoption).
        
        Updates both in-memory orderbook structures and the database to reflect
        the new parent-child relationship. Optionally tracks the original parent
        for audit history.
        
        This is useful for strategies like:
        - Migrating orders to a new parent due to market conditions
        - Consolidating children from multiple parents to a single parent
        - Orphaning a child and making it the parent of other orders
        
        Args:
            child_client_order_id: The UUID of the child order to adopt.
            new_parent_client_order_id: The UUID of the new parent order.
            keep_adoption_history: If True, stores the old parent in the database
                                   for audit trail. If False, old parent link is lost.
        
        Returns:
            True if adoption was successful, False otherwise.
        
        Raises:
            None - errors are logged and False is returned.
        
        Examples:
            >>> # Adopt child to new parent, keeping history
            >>> result = engine.adopt_child_to_new_parent(
            ...     child_client_order_id="child-uuid-123",
            ...     new_parent_client_order_id="parent-uuid-456",
            ...     keep_adoption_history=True
            ... )
            >>> if result:
            ...     print("Adoption successful")
            
            >>> # Adopt without tracking history
            >>> result = engine.adopt_child_to_new_parent(
            ...     child_client_order_id="child-uuid-123",
            ...     new_parent_client_order_id="parent-uuid-456",
            ...     keep_adoption_history=False
            ... )
        
        Notes:
            - Both child and new parent must exist in the system
            - Validates existence before attempting adoption
            - Updates in-memory orderbook atomically with orderbook_lock
            - Persists changes to database immediately
            - Logs adoption event for audit trail
        """
        # First update database
        success = self.db_helper.adopt_child_to_parent(
            child_client_order_id=child_client_order_id,
            new_parent_client_order_id=new_parent_client_order_id,
            keep_adoption_history=keep_adoption_history,
        )
        
        if not success:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "adopt_child_database_failed",
                    child_client_order_id=child_client_order_id,
                    new_parent_client_order_id=new_parent_client_order_id,
                ),
            )
            return False
        
        # Then update in-memory structures atomically
        with self.orderbook_lock:
            old_parent = self.orderbook.child_order_ids.get(child_client_order_id)
            
            # Remove from old parent's children list
            if old_parent and old_parent in self.orderbook.parent_order_ids:
                children_list = self.orderbook.parent_order_ids[old_parent].get("orders", [])
                if child_client_order_id in children_list:
                    children_list.remove(child_client_order_id)
            
            # Update mapping to new parent
            self.orderbook.child_order_ids[child_client_order_id] = new_parent_client_order_id
            
            # Add to new parent's children list
            if new_parent_client_order_id in self.orderbook.parent_order_ids:
                children_list = self.orderbook.parent_order_ids[new_parent_client_order_id].get("orders", [])
                if child_client_order_id not in children_list:
                    children_list.append(child_client_order_id)
        
        # Log the adoption
        self.log_message(
            "order",
            self.build_event_log_payload(
                "child_order_adopted",
                child_client_order_id=child_client_order_id,
                old_parent_client_order_id=old_parent,
                new_parent_client_order_id=new_parent_client_order_id,
                kept_history=keep_adoption_history,
            ),
        )
        
        return True

    def load_parent_child_order_ids(self, force_log: bool = False) -> bool:
        """Load parent/child order mappings from database into orderbook.
        
        Args:
            force_log: Whether to log reconciliation event.
        
        Returns:
            True if state changed, False if already in sync.
        """
        if force_log:
            self.log_message(
                "reconcile",
                self.build_event_log_payload("parent_child_reconcile_started"),
            )

        try:
            new_parent_order_ids, new_child_order_ids = self.build_parent_child_order_ids_snapshot()
        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "build_parent_child_snapshot_failed",
                    error=str(e),
                ),
            )
            return False

        loaded_parent_count = len(new_parent_order_ids)
        loaded_child_count = len(new_child_order_ids)

        with self.orderbook_lock:
            if all((
                self.orderbook.parent_order_ids == new_parent_order_ids,
                self.orderbook.child_order_ids == new_child_order_ids,
            )):
                if force_log:
                    self.log_message(
                        "reconcile",
                        self.build_event_log_payload(
                            "parent_child_reconcile_in_sync",
                            parent_count=loaded_parent_count,
                            child_count=loaded_child_count,
                        ),
                    )
                return False

            self.orderbook.parent_order_ids = new_parent_order_ids
            self.orderbook.child_order_ids = new_child_order_ids

        self.log_message(
            "reconcile",
            self.build_event_log_payload(
                "parent_child_reconciled",
                parent_count=loaded_parent_count,
                child_count=loaded_child_count,
            ),
        )
        return True

    def reconcile_parent_child_order_ids_periodically(self, interval_seconds: int = 30) -> None:
        """Periodically load parent/child orders from database.
        
        Runs in daemon thread, loops forever.
        
        Args:
            interval_seconds: Sleep duration between syncs (default 30).
        
        Returns:
            None (infinite loop)
        """
        while True:
            try:
                self.load_parent_child_order_ids(force_log=False)
            except Exception as e:
                self.log_message(
                    "error",
                    self.build_event_log_payload(
                        "periodic_parent_child_reconcile_error",
                        error=str(e),
                    ),
                )
            sleep(interval_seconds)

    def rotate_seen_events_buckets(self) -> None:
        """Periodically rotate event deduplication hash buckets using EventBridge.
        
        Runs in daemon thread, loops forever. Uses EventBridge to shift old hashes
        out every max_rotate_seen_events_bucket_seconds to avoid memory growth.
        
        Returns:
            None (infinite loop)
        """
        while True:
            # Use EventBridge to rotate dedup buckets
            self.evt_bridge.rotate_dedup_buckets()
            sleep(self.max_rotate_seen_events_bucket_seconds)

    def generate_process_event_worker(self, channel: str) -> callable:
        """Generate an event worker function for a specific channel.
        
        Returns a callable that processes events from the channel's queue
        in an infinite loop.
        
        Args:
            channel: Channel name ('ticker', 'user', 'heartbeats').
        
        Returns:
            Callable worker function.
        
        Example:
            >>> worker = engine.generate_process_event_worker('user')
            >>> thread = threading.Thread(target=worker, daemon=True)
            >>> thread.start()
        """
        def worker() -> None:
            while True:
                event = self.event_queue[channel].get()
                try:
                    if channel == ChannelType.TICKER.value:
                        with self.ticker_lock:
                            self.log_message(
                                "ticker",
                                self.build_event_log_payload(
                                    "ticker_event_received",
                                    **self.include_debug_fields(received_event=event),
                                ),
                            )
                            for tickr in event["tickers"]:
                                self.ticker[tickr["product_id"]] = tickr
                                # Broadcast to price chart
                                price = float(tickr.get("price", 0))
                                product_id = tickr.get("product_id")
                                if price > 0 and product_id:
                                    broadcast_ticker(product_id, price)
                                # Record bid/ask for spread monitor
                                best_bid = float(tickr.get("best_bid", 0))
                                best_ask = float(tickr.get("best_ask", 0))
                                if best_bid > 0 and best_ask > 0 and product_id:
                                    record_spread_tick(product_id, best_bid, best_ask)
                                # Feed market data to stealth order evaluator
                                if self.stealth_order_bridge and product_id:
                                    self.stealth_order_bridge.process_ticker_update(product_id, tickr)

                    elif channel == ChannelType.USER.value:
                        self.log_message(
                            "user",
                            self.build_event_log_payload(
                                "user_event_received",
                                **self.include_debug_fields(received_event=event),
                            ),
                        )
                        self.event_executor.submit(self.process_user_event, event)

                finally:
                    self.event_queue[channel].task_done()

        return worker

    def connect_to_websocket(self) -> None:
        """Establish and maintain websocket connection to Coinbase.
        
        Runs in daemon thread, loops forever. Reconnects on disconnect.
        
        Returns:
            None (infinite loop)
        """
        # Create SDK client and wrap with our abstraction
        sdk_client = WSClient(
            verbose=True,
            api_key=self.api_key,
            api_secret=self.api_secret,
            on_open=self.on_open,
            on_message=self.on_message,
        )
        ws_client = CoinbaseWebSocketClient(sdk_client)

        ws_client.connect()
        ws_client.subscribe(
            products=self.subscription.product_ids,
            channels=self.subscription.channels,
        )

        try:
            while True:
                if ws_client.sleep_with_exception_check(1):
                    break
        except WSClientConnectionClosedException as e:
            self.log_message(
                "connection",
                self.build_event_log_payload(
                    "websocket_connection_closed",
                    error=str(e),
                ),
            )

    def start_background_threads(self) -> None:
        """Start all background worker threads.
        
        Initializes parent/child order mappings, then launches:
        - Reconciliation thread
        - Deduplication rotation thread
        - Channel workers (ticker, user, heartbeats)
        - Websocket threads
        - Status monitoring thread
        
        Returns:
            None
        """
        self.load_parent_child_order_ids(force_log=True)
        
        # Update dashboard with initial engine status
        update_engine_status({
            "running": True,
            "threads_active": 2 + len(self.subscription.channels) + self.websocket_thread_maximum,
            "event_queue_depth": 0,
        })
        add_log_entry("INFO", "Trading engine started")

        threading.Thread(
            name="parent_child_reconcile_thread",
            target=self.reconcile_parent_child_order_ids_periodically,
            kwargs={"interval_seconds": 30},
            daemon=True,
        ).start()
        
        # Start status monitoring thread
        threading.Thread(
            name="dashboard_status_monitor",
            target=self._monitor_engine_status,
            daemon=True,
        ).start()

        threading.Thread(
            name="rotate_seen_events_buckets_thread",
            target=self.rotate_seen_events_buckets,
            daemon=True,
        ).start()

        for channel in self.subscription.channels:
            threading.Thread(
                name=f"{channel}_worker",
                target=self.generate_process_event_worker(channel),
                daemon=True,
            ).start()
        
        # Start fee manager (fetches taker fees from Coinbase API, refreshes hourly)
        self.fee_manager.start()

        for websocket in range(self.websocket_thread_maximum):
            threading.Thread(
                name=f"websocket_thread_{websocket}",
                target=self.connect_to_websocket,
                daemon=True,
            ).start()

    def _monitor_engine_status(self) -> None:
        """Monitor and broadcast engine status periodically to dashboard.
        
        Runs in background thread, updates event queue depth every 5 seconds.
        
        Returns:
            None (infinite loop)
        """
        while True:
            try:
                # Calculate total events in all queues
                total_queue_depth = sum(q.qsize() for q in self.event_queue.values())
                
                update_engine_status({
                    "running": True,
                    "threads_active": 2 + len(self.subscription.channels) + self.websocket_thread_maximum,
                    "event_queue_depth": total_queue_depth,
                })
                
                sleep(5)
            except Exception as e:
                self.log_message("error", self.build_event_log_payload(
                    "dashboard_status_update_failed",
                    error=str(e),
                ))
                sleep(5)

    def run_forever(self) -> None:
        """Start all background threads and loop forever.
        
        Call this to launch the trading engine. Blocks indefinitely.
        
        Returns:
            None (infinite loop)
        
        Example:
            >>> engine = OrderEngine(...)
            >>> engine.run_forever()  # Starts all threads and loops
        """
        self.start_background_threads()
        while True:
            sleep(1)
