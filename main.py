"""Main trading engine module for Coinbase Advanced API order management.

This module implements a multithreaded trading engine that:
- Maintains a live websocket connection to Coinbase for real-time order updates
- Manages parent-child order relationships and their lifecycle
- Automatically creates follow-up orders based on fills and cancellations
- Handles order deduplication and event processing with thread-safe operations
- Synchronizes in-memory orderbook state with PostgreSQL database
- Implements position tracking for futures contracts

Architecture:
    - OrderEngine: Main engine class coordinating all operations
    - Background Threads:
        * websocket_threads: Maintain connections to Coinbase (configurable count)
        * event_workers: Process events from specific channels (ticker, user, heartbeats)
        * reconciliation_thread: Periodically sync parent/child orders from database
        * deduplication_thread: Rotate event deduplication buckets
    - Event Processing:
        * Thread-safe event queuing with deduplication using hash-based bucketing
        * Processing flags prevent duplicate follow-up order creation
        * Position updates applied atomically with order placements

Example:
    >>> from main import OrderEngine
    >>> from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
    >>> import database.order as DB_CLIENT
    >>> 
    >>> engine = OrderEngine(
    ...     orderbook=ORDERBOOK,
    ...     db_client=DB_CLIENT,
    ...     subscription=Subscription,
    ...     api_key=API_KEY,
    ...     api_secret=API_SECRET,
    ...     order_post_only=ORDER_POST_ONLY
    ... )
    >>> engine.run_forever()  # Blocks indefinitely, runs all background threads
"""

import json
import threading
from time import sleep
from hashlib import sha256
from queue import Queue, Full
from copy import deepcopy
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from coinbase.websocket import WSClient, WSClientConnectionClosedException

from configuration import (
    Subscription,
    ORDERBOOK,
    API_KEY,
    API_SECRET,
    ORDER_POST_ONLY,
    DEFAULT_MAX_ORDER_REPLACEMENT,
    calculate_new_order_move_from_snapshot,
    apply_calculated_position_update,
    get_futures_positions,
)

from order import create_limit_order_span
import database.order as DB_CLIENT
from integration.engine_integration import OrderEngineIntegration
from integration.calculator_bridge import CalculatorBridge
from integration.processor_bridge import ProcessorBridge
from integration.event_bridge import EventBridge


class OrderEngine:
    """Multithreaded trading engine for Coinbase Advanced API order management.
    
    Orchestrates real-time order processing, parent-child order relationship tracking,
    and automatic follow-up order creation. Handles all threading, state management,
    and event deduplication.
    
    Attributes:
        orderbook: OrderBook instance (source-of-truth for orders/positions).
        db_client: Database client for persisting parent/child orders.
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
        seen_events_lock: Thread lock for event deduplication buckets.
        event_executor: ThreadPoolExecutor for user event processing.
        event_queue: Dict mapping channel name to Queue.
        seen_events: Dict mapping bucket index to set of event hashes.
        logging_flags: Dict controlling which log types are emitted.
        debug_logging_enabled: Whether to include debug fields in logs.
        websocket_events: Event type schemas (internal reference).
    
    Example:
        >>> engine = OrderEngine(
        ...     orderbook=ORDERBOOK,
        ...     db_client=DB_CLIENT,
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
        db_client,
        subscription,
        api_key,
        api_secret,
        order_post_only,
        websocket_thread_maximum=3,
        max_workers=16,
        max_rotate_seen_events_bucket_seconds=60,
        max_seen_event_buckets=3,
        queue_maxsize=10000,
    ) -> None:
        """Initialize the OrderEngine with configuration and state.
        
        Args:
            orderbook: OrderBook instance for state tracking.
            db_client: Database client module.
            subscription: Subscription config object.
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            order_post_only: Dict mapping order side to post_only flag.
            websocket_thread_maximum: Number of parallel websocket threads (default 3).
            max_workers: Thread pool size (default 16).
            max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval (default 60).
            max_seen_event_buckets: Number of dedup buckets (default 3).
            queue_maxsize: Max size for event queues (default 10000).
        """
        self.orderbook = orderbook
        self.db_client = db_client
        self.subscription = subscription
        self.api_key = api_key
        self.api_secret = api_secret
        self.order_post_only = order_post_only

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

        self.orderbook.db_client = self.db_client

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

        print(f"{datetime.now()} {threading.current_thread().name} [{log_type.upper()}] {message}")

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

    @staticmethod
    def safe_float(value, default: float = 0.0) -> float:
        """Safely convert value to float with default fallback.
        
        Args:
            value: Value to convert.
            default: Default if conversion fails.
        
        Returns:
            Float or default.
        
        Example:
            >>> OrderEngine.safe_float('123.45')
            123.45
            >>> OrderEngine.safe_float(None)
            0.0
        """
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

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

    def resolve_order_size(self, order: dict) -> float:
        """Extract order size from multiple possible fields.
        
        Args:
            order: Order dict.
        
        Returns:
            Order size or 0.0 if not found.
        
        Example:
            >>> size = engine.resolve_order_size({'base_size': '1.5'})
            >>> size
            1.5
        """
        for field in ("cumulative_quantity", "filled_size", "base_size", "size", "leaves_quantity"):
            value = self.safe_float(order.get(field), default=0.0)
            if value > 0:
                return value
        return 0.0

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

            parent_id = self.db_client.insert_order_parent(
                client_order_id=client_order_id,
                product_id=order["product_id"],
                side=order["order_side"],
                size=float(self.resolve_order_size(order)),
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

    def build_follow_up_log_payload(
        self,
        event: str,
        source_order: dict = None,
        parent_client_order_id: str = None,
        new_order: dict = None,
        attempted_new_order: dict = None,
        details: dict = None,
    ) -> dict:
        """Build structured log payload for follow-up order events.
        
        Args:
            event: Event name.
            source_order: Original order that triggered follow-up.
            parent_client_order_id: Parent order ID.
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
                channel == "subscriptions",
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
        outstanding_hold_amount = self.safe_float(
            normalized_order.get("outstanding_hold_amount"),
            default=0.0,
        )

        with self.orderbook_lock:
            self.orderbook.order[client_order_id] = normalized_order

        if status == "FILLED" and outstanding_hold_amount > 0:
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
            if client_order_id in self.orderbook.child_order_ids:
                self.db_client.update_order_child_status(
                    client_order_id=client_order_id,
                    status=status,
                )
            elif client_order_id in self.orderbook.parent_order_ids:
                self.db_client.update_order_parent_status(
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
        if status == "CANCEL_QUEUED":
            return
        if status == "PENDING":
            return
        if status == "FAILED":
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "order_failed",
                    source=self.build_order_log_context(order),
                    **self.include_debug_fields(raw_order=order),
                ),
            )
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            return
        if status == "OPEN":
            return
        if status == "CANCELLED":
            self.handle_cancelled_order(order)
            return
        if status == "FILLED":
            self.handle_filled_order(order)
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

        if self.normalize_product_type(order) == "FUTURE":
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

        if hasattr(self.db_client, "child_order_exists"):
            try:
                return bool(self.db_client.child_order_exists(
                    parent_client_order_id=parent_client_order_id,
                    product_id=order_template["product_id"],
                    side=order_template["side"],
                    size=float(order_template["order_base_size"]),
                    price=float(order_template["start_price"]),
                ))
            except TypeError:
                try:
                    return bool(self.db_client.child_order_exists(parent_client_order_id, order_template))
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
            Dict with 'type' and 'movement' keys, or empty dict.
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
        
        Args:
            order: Cancelled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        with self.orderbook_lock:
            if self.orderbook.should_replace["CANCELLED"] is not True:
                return
            _, parent_client_order_id = self.resolve_parent_client_order_id(client_order_id)

        if not self.claim_follow_up_processing("cancelled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=parent_client_order_id,
                    details={"reason": "cancelled_order_follow_up_already_claimed"},
                ),
            )
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

            new_order = create_limit_order_span(
                product_id=order_template["product_id"],
                side=order_template["side"],
                order_base_size=order_template["order_base_size"],
                order_price_difference=order_template["order_price_difference"],
                start_price=order_template["start_price"],
                post_only=self.order_post_only[order_template["side"]],
            )

            self.record_follow_up_order(
                order,
                new_order,
                order_template,
                parent_client_order_id,
                processed_flag_name="cancelled",
            )

        except Exception:
            self.release_follow_up_processing("cancelled", client_order_id)
            raise

    def handle_filled_order(self, order: dict) -> None:
        """Handle a filled order by creating a follow-up if allowed.
        
        Args:
            order: Filled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        with self.orderbook_lock:
            if self.orderbook.should_replace["FILLED"] is not True:
                return

            _, parent_client_order_id = self.resolve_parent_client_order_id(
                client_order_id,
                order=order,
                create_parent=True,
                status="FILLED",
            )

        if not self.claim_follow_up_processing("filled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=parent_client_order_id,
                    details={"reason": "filled_order_follow_up_already_claimed"},
                ),
            )
            return

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

            new_order = create_limit_order_span(
                product_id=order_template["product_id"],
                side=order_template["side"],
                order_base_size=order_template["order_base_size"],
                order_price_difference=order_template["order_price_difference"],
                start_price=order_template["start_price"],
                post_only=self.order_post_only[order_template["side"]],
            )

            self.record_follow_up_order(
                order,
                new_order,
                order_template,
                parent_client_order_id,
                processed_flag_name="filled",
            )

        except Exception:
            self.release_follow_up_processing("filled", client_order_id)
            raise

    def record_follow_up_order(
        self,
        source_order: dict,
        new_order: list,
        order_template: dict,
        parent_client_order_id: str,
        processed_flag_name: str = None,
    ) -> None:
        """Record a successfully placed follow-up order.
        
        Updates orderbook parent/child mappings, increments counters, persists to DB.
        
        Args:
            source_order: Original order that triggered follow-up.
            new_order: API response list from create_limit_order_span.
            order_template: Computed template used.
            parent_client_order_id: Parent order ID.
            processed_flag_name: Flag dict name ('filled' or 'cancelled').
        
        Returns:
            None
        """
        client_order_id = source_order["client_order_id"]

        if new_order[0]["success"] is not True:
            self.log_message(
                "error",
                self.build_follow_up_log_payload(
                    "follow_up_order_placement_failed",
                    source_order=source_order,
                    parent_client_order_id=parent_client_order_id,
                    attempted_new_order={
                        "product_id": order_template["product_id"],
                        "side": order_template["side"],
                        "price": float(order_template["start_price"]),
                    },
                ),
            )
            if processed_flag_name:
                self.release_follow_up_processing(processed_flag_name, client_order_id)
            return

        success_response = new_order[0]["success_response"]
        limit_cfg = new_order[0]["order_configuration"]["limit_limit_gtc"]

        new_order_client_order_id = success_response["client_order_id"]
        new_order_product_id = success_response["product_id"]
        new_order_side = success_response["side"]
        new_order_size = limit_cfg["base_size"]
        new_order_price = self.order_limit_price_or_avg_price(limit_cfg)

        self.log_message(
            "order",
            self.build_follow_up_log_payload(
                "follow_up_order_placed",
                source_order=source_order,
                parent_client_order_id=parent_client_order_id,
                new_order={
                    "client_order_id": new_order_client_order_id,
                    "product_id": new_order_product_id,
                    "side": new_order_side,
                    "price": float(new_order_price),
                },
                details={"size": new_order_size},
            ),
        )

        if not parent_client_order_id:
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_parent_mapping_missing",
                    source_order=source_order,
                    parent_client_order_id=parent_client_order_id,
                    new_order={
                        "client_order_id": new_order_client_order_id,
                        "product_id": new_order_product_id,
                        "side": new_order_side,
                        "price": float(new_order_price),
                    },
                ),
            )
            return

        with self.orderbook_lock:
            parent_entry = self.orderbook.parent_order_ids.get(parent_client_order_id)
            if parent_entry is None:
                parent_entry = {
                    "orders": [],
                    "target_movement": {},
                    "max_order_replacement": getattr(
                        self.orderbook,
                        "default_max_order_replacement",
                        DEFAULT_MAX_ORDER_REPLACEMENT,
                    ),
                    "current_order_replacement": 0,
                }
                self.orderbook.parent_order_ids[parent_client_order_id] = parent_entry

            parent_entry.setdefault("orders", []).append(new_order_client_order_id)
            self.orderbook.child_order_ids[new_order_client_order_id] = parent_client_order_id

            if processed_flag_name == "filled":
                parent_entry["current_order_replacement"] += 1

            if processed_flag_name:
                processed_flags = getattr(self.orderbook, processed_flag_name, None)
                if isinstance(processed_flags, dict):
                    processed_flags[client_order_id] = "done"

        self.apply_position_update(order_template)

        self.log_message(
            "database",
            self.build_follow_up_log_payload(
                "follow_up_child_order_persisting",
                source_order=source_order,
                parent_client_order_id=parent_client_order_id,
                new_order={
                    "client_order_id": new_order_client_order_id,
                    "product_id": new_order_product_id,
                    "side": new_order_side,
                    "price": float(new_order_price),
                },
            ),
        )
        self.db_client.insert_order_child(
            parent_client_order_id=parent_client_order_id,
            client_order_id=new_order_client_order_id,
            product_id=new_order_product_id,
            side=new_order_side,
            size=float(new_order_size),
            price=float(new_order_price),
        )

        if processed_flag_name == "filled":
            self.db_client.increment_order_parent_replacement_count(parent_client_order_id)

    def build_parent_child_order_ids_snapshot(self) -> tuple:
        """Query database and build parent/child order mapping snapshot.
        
        Returns:
            Tuple (parent_order_ids_dict, child_order_ids_dict).
        """
        parent_order_ids = {}
        child_order_ids = {}

        parent_orders = self.db_client.get_parent_orders()

        for parent in parent_orders:
            parent_client_order_id = parent["client_order_id"]

            parent_order_ids[parent_client_order_id] = {
                "parent_id": parent["id"],
                "orders": [],
                "target_movement": {
                    "movement": float(parent["target_movement"]),
                    "type": parent.get("target_movement_type", "P"),
                },
                "max_order_replacement": int(parent["max_order_replacement"]),
                "current_order_replacement": int(parent["current_order_replacement"]),
            }

            child_orders = self.db_client.get_child_orders(parent_client_order_id)
            for child in child_orders:
                child_client_order_id = child["client_order_id"]
                parent_order_ids[parent_client_order_id]["orders"].append(child_client_order_id)
                child_order_ids[child_client_order_id] = parent_client_order_id

        return parent_order_ids, child_order_ids

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
                    if channel == "ticker":
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

                    elif channel == "user":
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
        ws_client = WSClient(
            verbose=True,
            api_key=self.api_key,
            api_secret=self.api_secret,
            on_open=self.on_open,
            on_message=self.on_message,
        )

        ws_client.open()
        ws_client.subscribe(
            product_ids=self.subscription.product_ids,
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
        
        Returns:
            None
        """
        self.load_parent_child_order_ids(force_log=True)

        threading.Thread(
            name="parent_child_reconcile_thread",
            target=self.reconcile_parent_child_order_ids_periodically,
            kwargs={"interval_seconds": 30},
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

        for websocket in range(self.websocket_thread_maximum):
            threading.Thread(
                name=f"websocket_thread_{websocket}",
                target=self.connect_to_websocket,
                daemon=True,
            ).start()

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


if __name__ == "__main__":
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_client=DB_CLIENT,
        subscription=Subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY,
    )

    integrated = OrderEngineIntegration(engine)
    integrated.run_forever()
