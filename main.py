"""
Main trading engine module for Coinbase Advanced API order management.

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

Key Features:
    - Thread-safe orderbook operations with fine-grained locking
    - Event deduplication to prevent duplicate order processing
    - Configurable order replacement logic for FILLED and CANCELLED orders
    - Support for both spot and futures trading
    - Automatic position refresh for futures contracts
    - Comprehensive logging with configurable verbosity

Usage:
    >>> from main import OrderEngine
    >>> from configuration import ORDERBOOK, API_KEY, API_SECRET, ORDER_POST_ONLY, Subscription
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
    >>> engine.run_forever()  # Blocks indefinitely
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
    calculate_new_order_move_from_snapshot,
    apply_calculated_position_update,
    get_futures_positions,
)

from order import create_limit_order_span
import database.order as DB_CLIENT


class OrderEngine:
    """
    Multithreaded trading engine for Coinbase Advanced API order management.
    
    Manages the complete lifecycle of parent and child orders, maintains position state,
    and coordinates real-time order updates via websocket with database persistence.
    All operations are thread-safe using locks for shared state.
    
    Attributes:
        orderbook (OrderBook): Shared orderbook state containing orders, positions, products.
        db_client (database.order): Database client for persisting order state.
        subscription (Subscription): Websocket channel and product subscriptions.
        api_key (str): Coinbase API key for authentication.
        api_secret (str): Coinbase API secret for signing requests.
        order_post_only (dict): Post-only flags per order side (BUY/SELL).
        
        websocket_thread_maximum (int): Number of concurrent websocket connections.
        max_workers (int): Thread pool size for async event processing.
        max_rotate_seen_events_bucket_seconds (int): Event dedup bucket rotation interval.
        max_seen_event_buckets (int): Number of dedup buckets for duplicate detection.
        queue_maxsize (int): Maximum size per event queue.
        
        ticker (dict): Current ticker prices keyed by product_id.
        ticker_lock (threading.Lock): Lock protecting ticker dictionary.
        orderbook_lock (threading.Lock): Lock protecting orderbook state.
        seen_events_lock (threading.Lock): Lock protecting event dedup buckets.
        
        event_executor (ThreadPoolExecutor): Executor for async event processing.
        event_queue (dict): Event queues per channel.
        seen_events (dict): Rotating buckets of hashed events for deduplication.
        seen_events_default_bucket (int): Index of current bucket for new events.
        
        logging_flags (dict): Boolean flags controlling log output by category.
        websocket_events (dict): Mapping of websocket event types to structure.
    
    Thread Safety:
        - orderbook_lock: Protects order, positions, parent_order_ids, child_order_ids
        - ticker_lock: Protects ticker dictionary
        - seen_events_lock: Protects event deduplication buckets
        - All shared state access is synchronized through these locks
    
    Event Processing:
        - Events deduplicated using rolling hash-based buckets
        - Processing flags prevent concurrent follow-up order creation for same order
        - States: None (unclaimed), "processing" (claimed), "done" (complete)
    
    Order Relationships:
        - parent_order_ids: Maps parent UUID -> {orders: [child UUIDs], target_movement, ...}
        - child_order_ids: Maps child UUID -> parent UUID
        - Maintained both in memory and database for reliability
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
        """
        Initialize the trading engine with configuration and state.
        
        Sets up all internal data structures, locks, thread pools, and event queues.
        Does not start background threads - call run_forever() to start execution.
        
        Args:
            orderbook: OrderBook instance containing product and position data.
            db_client: Database client for order persistence (database.order module).
            subscription: Subscription object with channels and product_ids.
            api_key: Coinbase API key for websocket authentication.
            api_secret: Coinbase API secret for request signing.
            order_post_only: Dict mapping side ('BUY'/'SELL') to post-only boolean.
            websocket_thread_maximum: Number of concurrent websocket connections (default: 3).
            max_workers: Thread pool size for async event processing (default: 16).
            max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval seconds (default: 60).
            max_seen_event_buckets: Number of rotating dedup buckets (default: 3).
            queue_maxsize: Max events per channel queue (default: 10000).
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
        self.seen_events_default_bucket = 0
        self.queue_maxsize = queue_maxsize

        self.ticker = {}
        self.ticker_lock = threading.Lock()
        self.orderbook_lock = threading.Lock()
        self.seen_events_lock = threading.Lock()

        self.event_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="user_event_thread",
        )

        self.event_queue = {
            channel: Queue(maxsize=self.queue_maxsize)
            for channel in self.subscription.channels
        }

        self.seen_events = {
            i: set() for i in range(self.max_seen_event_buckets)
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
        """
        Log a message with timestamp, thread name, and message type.

        Args:
            log_type: The type/category of the log message.
            message: The message content to log. Dict/list payloads are serialized as JSON.

        Returns:
            None
        """
        if not self.logging_flags.get(log_type, False):
            return

        if isinstance(message, (dict, list)):
            message = json.dumps(message, sort_keys=True, default=str)

        print(f"{datetime.now()} {threading.current_thread().name} [{log_type.upper()}] {message}")

    @staticmethod
    def hash_dict(dictionary: dict) -> str:
        """
        Generate a SHA256 hash of a dictionary.
        
        Args:
            dictionary: The dictionary to hash.
        
        Returns:
            The hexadecimal SHA256 hash of the dictionary.
        """
        dict_string = json.dumps(dictionary, sort_keys=True)
        return sha256(dict_string.encode()).hexdigest()

    @staticmethod
    def order_limit_price_or_avg_price(order: dict) -> float:
        """
        Get the effective price for an order (limit price or average price).
        
        Args:
            order: The order dictionary containing limit_price and/or avg_price.
        
        Returns:
            The limit price if available and positive, otherwise the average price.
        """
        if order.get("limit_price") and float(order["limit_price"]) > 0:
            return float(order["limit_price"])
        return float(order["avg_price"])

    @staticmethod
    def safe_float(value, default: float = 0.0) -> float:
        """
        Safely convert a value to float.

        Args:
            value: The value to convert.
            default: The default value to return on conversion failure.

        Returns:
            Parsed float or default.
        """
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default


    def build_order_log_context(self, order: dict) -> dict:
        """
        Build a normalized structured logging payload for an order.

        Args:
            order: Order payload.

        Returns:
            Normalized order context for logs.
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
        """
        Build a structured event log payload.

        Args:
            event: Event name.
            **kwargs: Additional structured fields.

        Returns:
            Structured log payload.
        """
        payload = {"event": event}
        payload.update(kwargs)
        return payload

    def include_debug_fields(self, **kwargs) -> dict:
        """
        Return debug-only fields when verbose logging is enabled.

        Args:
            **kwargs: Candidate debug fields.

        Returns:
            A dictionary containing only non-empty debug fields when enabled.
        """
        if not self.debug_logging_enabled:
            return {}
        return {
            key: value for key, value in kwargs.items()
            if value is not None
        }

    def normalize_product_type(self, order: dict) -> str:
        """
        Normalize product type from order payload and configured products.

        Args:
            order: Order payload.

        Returns:
            Normalized product type string.
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
        """
        Resolve order size from the best available quantity field.

        Args:
            order: Order payload.

        Returns:
            Resolved order size.
        """
        for field in ("cumulative_quantity", "filled_size", "base_size", "size", "leaves_quantity"):
            value = self.safe_float(order.get(field), default=0.0)
            if value > 0:
                return value
        return 0.0

    def resolve_profit_target(self, order: dict) -> float:
        """
        Resolve profit target for an order using product-specific or product-type defaults.

        Args:
            order: Order payload.

        Returns:
            Profit movement target.
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
        """
        Get a thread-safe snapshot of the current orderbook state.
        
        Returns:
            A dictionary containing deep copies of orders, positions, products, profit settings,
            and parent/child order ID mappings.
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
        """
        Refresh futures positions from API if product_id is not already cached.
        
        Args:
            product_id: The product ID to check and refresh positions for.
        
        Returns:
            None
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
        """
        Resolve the parent client order ID for a given order and optionally create parent entry.
        
        Args:
            client_order_id: The client order ID to resolve.
            order: The order dictionary (required if create_parent is True).
            create_parent: Whether to create a new parent entry if order is not found.
            status: The status to use when creating parent entry (defaults to order status).
        
        Returns:
            A tuple of (is_parent: bool, parent_client_order_id: str or None).
        """
        is_parent = False
        parent_client_order_id = None

        if client_order_id in self.orderbook.parent_order_ids:
            is_parent = True
            parent_client_order_id = client_order_id

        elif client_order_id in self.orderbook.child_order_ids:
            parent_client_order_id = self.orderbook.child_order_ids[client_order_id]

        elif create_parent and order is not None:
            self.orderbook.parent_order_ids[client_order_id] = {
                "orders": [],
                "target_movement": {
                    "movement": self.resolve_profit_target(order),
                    "type": "P",
                },
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
            )

            self.orderbook.parent_order_ids[client_order_id]["parent_id"] = parent_id
            is_parent = True
            parent_client_order_id = client_order_id

        return is_parent, parent_client_order_id

    def claim_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> bool:
        """
        Reserve a source order so only one worker can create a follow-up order for it.
        
        Args:
            processed_flag_name: The name of the processed flag attribute on the orderbook.
            client_order_id: The client order ID to claim.
        
        Returns:
            True if this caller won the claim and should continue, False if another worker
            already claimed or completed it.
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
        """
        Remove a processing reservation after a failed placement so a retry can occur.
        
        Args:
            processed_flag_name: The name of the processed flag attribute on the orderbook.
            client_order_id: The client order ID to release.
        
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
        """
        Mark a source order as fully processed after a successful placement.
        
        Args:
            processed_flag_name: The name of the processed flag attribute on the orderbook.
            client_order_id: The client order ID to mark as complete.
        
        Returns:
            None
        """
        with self.orderbook_lock:
            processed_flags = getattr(self.orderbook, processed_flag_name, None)
            if not isinstance(processed_flags, dict):
                return

            processed_flags[client_order_id] = "done"


    def build_follow_up_order_log_context(self, order: dict) -> dict:
        """
        Build normalized order details for follow-up order logs.

        Args:
            order: Source order payload.

        Returns:
            Structured source order context.
        """
        return self.build_order_log_context(order)

    def build_follow_up_log_payload(
        self,
        event: str,
        source_order: dict = None,
        parent_client_order_id: str = None,
        new_order: dict = None,
        attempted_new_order: dict = None,
        details: dict = None,
    ) -> dict:
        """
        Build a structured JSON payload for follow-up order logs.

        Args:
            event: Event name.
            source_order: Source order payload that triggered the follow-up.
            parent_client_order_id: Parent client order id if known.
            new_order: Newly placed order details if placement succeeded.
            attempted_new_order: Attempted order details if placement failed or was skipped.
            details: Additional metadata.

        Returns:
            Structured log payload.
        """
        payload = {"event": event}

        if parent_client_order_id is not None:
            payload["parent_client_order_id"] = parent_client_order_id

        if source_order is not None:
            payload["source"] = self.build_follow_up_order_log_context(source_order)

        if new_order is not None:
            payload["new"] = new_order

        if attempted_new_order is not None:
            payload["attempted_new"] = attempted_new_order

        if details:
            payload["details"] = details

        return payload

    def on_open(self) -> None:
        """
        Callback when websocket connection is established.
        
        Returns:
            None
        """
        self.log_message("connection", "Connection Opened!")

    def on_message(self, msg: str) -> None:
        """
        Callback when websocket message is received.
        
        Parses the JSON message, deduplicates events using hash-based bucketing,
        and queues events for processing.
        
        Args:
            msg: The raw websocket message string.
        
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
                event_hash = self.hash_dict(event)

                with self.seen_events_lock:
                    if any(event_hash in bucket for bucket in self.seen_events.values()):
                        continue

                try:
                    self.event_queue[channel].put(deepcopy(event), timeout=0.01)

                    with self.seen_events_lock:
                        self.seen_events[self.seen_events_default_bucket].add(event_hash)

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
        """
        Process a user websocket event (orders or positions).
        
        Args:
            event: The event dictionary containing type, orders, and/or positions.
        
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
        """
        Process a position snapshot from a websocket event.
        
        Updates the orderbook's futures positions with normalized position data.
        
        Args:
            snapshot: The snapshot dictionary containing positions by type.
        
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
        """
        Process an order status update from a websocket event.
        
        Updates the orderbook, database, and handles follow-up order creation
        for FILLED and CANCELLED orders.
        
        Args:
            order: The order dictionary containing status and order details.
        
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
        """
        Apply a position update from an order template to the orderbook.
        
        Args:
            order_template: The order template dictionary potentially containing position_update.
        
        Returns:
            None
        """
        position_update = order_template.get("position_update")
        if not position_update:
            return
        with self.orderbook_lock:
            apply_calculated_position_update(self.orderbook.positions, position_update)

    def compute_order_template(self, client_order_id: str, target_movement: dict = None) -> dict:
        """
        Compute the template for a follow-up order based on an existing order.
        
        Args:
            client_order_id: The client order ID to compute template for.
            target_movement: Optional target movement override (type and amount).
        
        Returns:
            A dictionary containing the computed order template with pricing and sizing.
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
        """
        Check if a child order matching the template already exists for the parent.
        
        Args:
            parent_client_order_id: The parent order's client ID.
            order_template: The order template with product_id, side, size, and price.
        
        Returns:
            True if a matching child order exists, False otherwise.
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
        """
        Get the target movement configuration for a parent order.
        
        Args:
            parent_client_order_id: The parent order's client ID.
        
        Returns:
            A dictionary with movement type (P/A) and amount, or None if not found.
        """
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_client_order_id, {})
            return deepcopy(parent.get("target_movement"))

    def handle_cancelled_order(self, order: dict) -> None:
        """
        Handle order replacement for a cancelled order.
        
        Computes a follow-up order template and creates a replacement order
        if configured to do so.
        
        Args:
            order: The cancelled order dictionary.
        
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
        """
        Handle order replacement for a filled order.
        
        Creates a new parent order if needed, computes a follow-up order template,
        and creates a replacement order if configured to do so.
        
        Args:
            order: The filled order dictionary.
        
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
        """
        Record a successfully placed follow-up order in the orderbook and database.
        
        Updates parent/child order relationships, applies position updates,
        and persists the new order to the database.
        
        Args:
            source_order: The source (parent or cancelled) order that triggered this placement.
            new_order: The result list from create_limit_order_span.
            order_template: The computed order template used for placement.
            parent_client_order_id: The parent order's client ID.
            processed_flag_name: Optional flag name to mark processing as complete.
        
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
                }
                self.orderbook.parent_order_ids[parent_client_order_id] = parent_entry

            parent_entry.setdefault("orders", []).append(new_order_client_order_id)
            self.orderbook.child_order_ids[new_order_client_order_id] = parent_client_order_id

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

    def build_parent_child_order_ids_snapshot(self) -> tuple:
        """
        Build a snapshot of parent/child order relationships from the database.
        
        Returns:
            A tuple of (parent_order_ids: dict, child_order_ids: dict) where:
            - parent_order_ids maps parent client order ID to parent metadata and child order list
            - child_order_ids maps child client order ID to parent client order ID
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
            }

            child_orders = self.db_client.get_child_orders(parent_client_order_id)
            for child in child_orders:
                child_client_order_id = child["client_order_id"]
                parent_order_ids[parent_client_order_id]["orders"].append(child_client_order_id)
                child_order_ids[child_client_order_id] = parent_client_order_id

        return parent_order_ids, child_order_ids

    def load_parent_child_order_ids(self, force_log: bool = False) -> bool:
        """
        Load and reconcile parent/child order IDs from the database.
        
        Compares database state with in-memory state and updates if differences are found.
        
        Args:
            force_log: If True, always log reconciliation status even if no changes.
        
        Returns:
            True if changes were made, False if already in sync.
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
        """
        Periodically reconcile parent/child order IDs from the database.
        
        Runs indefinitely, sleeping between reconciliation attempts.
        
        Args:
            interval_seconds: The interval in seconds between reconciliations.
        
        Returns:
            None
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
        """
        Periodically rotate the seen events deduplication buckets.
        
        Shifts older buckets and clears the default bucket on a fixed interval.
        This prevents unbounded memory growth while allowing recent duplicate detection.
        
        Returns:
            None
        """
        while True:
            with self.seen_events_lock:
                for i in range(self.max_seen_event_buckets - 1, 0, -1):
                    self.seen_events[i] = self.seen_events[i - 1]
                self.seen_events[self.seen_events_default_bucket] = set()
            sleep(self.max_rotate_seen_events_bucket_seconds)

    def generate_process_event_worker(self, channel: str) -> callable:
        """
        Generate a worker function for processing events from a specific channel.
        
        Args:
            channel: The channel name to process events from.
        
        Returns:
            A callable worker function that processes events indefinitely.
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
        """
        Establish and maintain a websocket connection to Coinbase.
        
        Opens the websocket, subscribes to configured channels/products,
        and handles the connection lifecycle until closure.
        
        Returns:
            None
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
        """
        Start all background worker threads for the trading engine.
        
        Initializes parent/child order reconciliation, event deduplication,
        event processing workers, and websocket connections.
        
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
        """
        Start the trading engine and run indefinitely.
        
        Initializes all background threads and enters a persistent loop.
        
        Returns:
            None
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
    engine.run_forever()
