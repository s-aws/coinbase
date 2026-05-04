"""WebSocket event processor for handling real-time market and order events.

This module provides business logic for:
- Event deduplication using hash-based bucketing
- Event routing and filtering
- Event validation and enrichment
- Channel-specific event handling

Example:
    >>> from business.event_processor import EventProcessor
    >>> processor = EventProcessor(max_dedup_buckets=3)
    >>> 
    >>> # Check if event is duplicate
    >>> event = {'order_id': 'order-123', 'type': 'filled'}
    >>> is_duplicate = processor.is_duplicate_event(event)
    >>> 
    >>> # Filter events by channel
    >>> user_events = processor.filter_events_by_channel(all_events, 'user')
    >>> 
    >>> # Check if event should be processed
    >>> should_process = processor.should_process_event(event, subscribed_products)
"""

from hashlib import sha256
import json
import threading
from typing import List, Dict, Set, Any, Optional
from queue import Queue
from core.exceptions import WebSocketMessageError, DuplicateEventError


class EventProcessor:
    """Processes WebSocket events with deduplication and routing."""

    def __init__(self, max_dedup_buckets: int = 3, dedup_bucket_duration_secs: int = 60):
        """Initialize event processor.
        
        Args:
            max_dedup_buckets: Number of rolling dedup hash buckets (default: 3).
            dedup_bucket_duration_secs: Time window per dedup bucket in seconds (default: 60).
        """
        self.max_dedup_buckets = max_dedup_buckets
        self.dedup_bucket_duration_secs = dedup_bucket_duration_secs

        # Hash buckets for event deduplication. All access (read, write,
        # rotation) MUST go through ``self._dedup_lock`` — multiple WSClient
        # threads call into this processor concurrently and any non-atomic
        # check-then-mark sequence reintroduces the fan-out duplicate-event
        # bug. Use ``claim_event`` for the normal dedup path; the legacy
        # ``is_duplicate_event`` / ``mark_event_seen`` pair is preserved for
        # back-compat callers but is NOT safe to combine across threads.
        self._dedup_lock = threading.Lock()
        self.seen_events = {i: set() for i in range(max_dedup_buckets)}
        self.current_bucket = 0

    @staticmethod
    def hash_event(event: dict) -> str:
        """Create a hash of an event for deduplication.
        
        Serializes the event to JSON and hashes it. Used to detect duplicate
        events across websocket reconnections.
        
        Args:
            event: Event dict to hash.
        
        Returns:
            Hexadecimal SHA256 hash string.
        
        Raises:
            WebSocketMessageError: If event cannot be serialized to JSON.
        
        Examples:
            >>> processor = EventProcessor()
            >>> event1 = {'type': 'filled', 'order_id': '123'}
            >>> event2 = {'type': 'filled', 'order_id': '123'}
            >>> processor.hash_event(event1) == processor.hash_event(event2)
            True
        """
        try:
            event_string = json.dumps(event, sort_keys=True, default=str)
            return sha256(event_string.encode()).hexdigest()
        except (TypeError, ValueError) as e:
            raise WebSocketMessageError(
                error_type="EventSerializationError",
                message=f"Failed to serialize event for hashing: {str(e)}",
                raw_data=str(event),
            )

    def claim_event(self, event: dict) -> bool:
        """Atomically claim an event for processing.

        Returns ``True`` if this caller is the first to see the event
        (caller should proceed to process it). Returns ``False`` if another
        thread already claimed it (caller should drop it).

        This is the correct entry point when multiple WSClient threads can
        deliver the same payload. The check-against-buckets and add-to-current
        bucket happen under a single lock, so concurrent callers cannot all
        observe "new" and then all enqueue.

        Args:
            event: Event dict to claim.

        Returns:
            True if newly claimed; False if already seen.
        """
        event_hash = self.hash_event(event)
        with self._dedup_lock:
            for bucket in self.seen_events.values():
                if event_hash in bucket:
                    return False
            self.seen_events[self.current_bucket].add(event_hash)
            return True

    def is_duplicate_event(self, event: dict) -> bool:
        """Check if an event has been seen before.

        WARNING: This method is NOT atomic with ``mark_event_seen``. Combining
        them in a check-then-mark sequence across threads reintroduces the
        fan-out duplicate bug. For the normal dedup path use ``claim_event``
        instead. This method is retained for read-only callers (audits,
        strict-check helpers, tests).

        Args:
            event: Event dict to check.

        Returns:
            True if event is a duplicate, False if new.
        """
        event_hash = self.hash_event(event)
        with self._dedup_lock:
            for bucket in self.seen_events.values():
                if event_hash in bucket:
                    return True
            return False

    def mark_event_seen(self, event: dict) -> None:
        """Mark an event as seen in the current bucket.

        WARNING: Not atomic with ``is_duplicate_event``. Use ``claim_event``
        for the normal dedup path. Retained for back-compat callers that
        already hold an external lock or only need one half of the operation.

        Args:
            event: Event dict to mark.

        Returns:
            None
        """
        event_hash = self.hash_event(event)
        with self._dedup_lock:
            self.seen_events[self.current_bucket].add(event_hash)

    def rotate_dedup_buckets(self) -> None:
        """Rotate dedup hash buckets, dropping oldest bucket.
        
        Shifts the current bucket index, causing the oldest bucket to be
        discarded. New events are added to the new current bucket.
        Effectively maintains a rolling time window of seen events.
        
        Returns:
            None
        
        Examples:
            >>> processor = EventProcessor(max_dedup_buckets=3)
            >>> # Initial state: buckets 0, 1, 2; current = 0
            >>> processor.current_bucket
            0
            >>> processor.rotate_dedup_buckets()
            >>> # New state: buckets become 1, 2, 0 (3 rotated out); current = 1
            >>> processor.current_bucket
            1
        """
        # Clear the oldest bucket (one past the current position, wrapping).
        # Lock so concurrent ``claim_event`` / ``mark_event_seen`` cannot
        # observe a half-rotated state or mutate the bucket being replaced.
        with self._dedup_lock:
            next_bucket = (self.current_bucket + 1) % self.max_dedup_buckets
            self.seen_events[next_bucket] = set()
            self.current_bucket = next_bucket

    def filter_events_by_channel(
        self,
        events: List[Dict[str, Any]],
        channel: str,
    ) -> List[Dict[str, Any]]:
        """Filter events to those from a specific channel.
        
        Args:
            events: List of event dicts.
            channel: Channel name to filter by (e.g., 'user', 'ticker', 'level2').
        
        Returns:
            Filtered list of events from the specified channel.
        
        Examples:
            >>> processor = EventProcessor()
            >>> events = [
            ...     {'channel': 'user', 'type': 'filled'},
            ...     {'channel': 'ticker', 'type': 'snapshot'},
            ...     {'channel': 'user', 'type': 'cancelled'},
            ... ]
            >>> user_events = processor.filter_events_by_channel(events, 'user')
            >>> len(user_events)
            2
        """
        return [e for e in events if e.get("channel") == channel]

    def filter_events_by_product(
        self,
        events: List[Dict[str, Any]],
        product_id: str,
    ) -> List[Dict[str, Any]]:
        """Filter events to those related to a specific product.
        
        Handles different event structures where product_id may be in:
        - Direct 'product_id' field
        - Nested in 'tickers' array
        - Missing (channel events without product context)
        
        Args:
            events: List of event dicts.
            product_id: Product ID to filter by (e.g., 'BTC-USDC').
        
        Returns:
            Filtered list of events related to the product.
        
        Examples:
            >>> processor = EventProcessor()
            >>> events = [
            ...     {'product_id': 'BTC-USDC', 'type': 'filled'},
            ...     {'product_id': 'ETH-USDC', 'type': 'filled'},
            ...     {'product_id': 'BTC-USDC', 'type': 'cancelled'},
            ... ]
            >>> btc_events = processor.filter_events_by_product(events, 'BTC-USDC')
            >>> len(btc_events)
            2
        """
        filtered = []
        for event in events:
            # Direct product_id match
            if event.get("product_id") == product_id:
                filtered.append(event)
                continue
            
            # Check in tickers (ticker events)
            tickers = event.get("tickers", [])
            if isinstance(tickers, list):
                for ticker in tickers:
                    if ticker.get("product_id") == product_id:
                        filtered.append(event)
                        break
        
        return filtered

    def should_process_event(
        self,
        event: dict,
        subscribed_products: List[str],
        subscribed_channels: List[str] = None,
    ) -> bool:
        """Determine if an event should be processed.
        
        An event should be processed if:
        - It's not a duplicate (checked via is_duplicate_event)
        - Its channel is subscribed to (if subscribed_channels provided)
        - Its product is in subscribed products (if applicable)
        
        Args:
            event: Event dict to check.
            subscribed_products: List of product IDs we care about.
            subscribed_channels: Optional list of channels to filter by.
        
        Returns:
            True if event should be processed, False otherwise.
        
        Examples:
            >>> processor = EventProcessor()
            >>> event = {'channel': 'user', 'product_id': 'BTC-USDC'}
            >>> processor.should_process_event(
            ...     event,
            ...     subscribed_products=['BTC-USDC', 'ETH-USDC'],
            ...     subscribed_channels=['user', 'ticker']
            ... )
            True
        """
        # Check for duplicates
        if self.is_duplicate_event(event):
            return False

        # Check channel filter if provided
        if subscribed_channels:
            if event.get("channel") not in subscribed_channels:
                return False

        # Check product filter (if product_id present in event)
        product_id = event.get("product_id")
        if product_id and product_id not in subscribed_products:
            return False

        return True

    @staticmethod
    def extract_orders_from_event(event: dict) -> List[Dict[str, Any]]:
        """Extract order data from a user channel event.
        
        User channel events contain orders in a nested structure. This method
        extracts all orders from the event payload.
        
        Args:
            event: WebSocket event dict (typically from 'user' channel).
        
        Returns:
            List of order dicts, or empty list if no orders found.
        
        Examples:
            >>> processor = EventProcessor()
            >>> event = {
            ...     'events': [
            ...         {
            ...             'orders': [
            ...                 {'order_id': '1', 'status': 'FILLED'},
            ...                 {'order_id': '2', 'status': 'OPEN'},
            ...             ]
            ...         }
            ...     ]
            ... }
            >>> orders = processor.extract_orders_from_event(event)
            >>> len(orders)
            2
        """
        orders = []
        events = event.get("events", [])
        
        if isinstance(events, list):
            for sub_event in events:
                event_orders = sub_event.get("orders", [])
                if isinstance(event_orders, list):
                    orders.extend(event_orders)
        
        return orders

    @staticmethod
    def extract_product_id_from_event(event: dict) -> Optional[str]:
        """Extract product_id from an event.
        
        Handles multiple event formats:
        - Direct 'product_id' field
        - In 'orders' -> 'product_id'
        - In 'tickers' -> 'product_id'
        
        Args:
            event: Event dict.
        
        Returns:
            Product ID if found, None otherwise.
        
        Examples:
            >>> processor = EventProcessor()
            >>> event = {'product_id': 'BTC-USDC'}
            >>> processor.extract_product_id_from_event(event)
            'BTC-USDC'
        """
        # Direct field
        if event.get("product_id"):
            return event.get("product_id")

        # From orders
        orders = processor.extract_orders_from_event(event)
        if orders and orders[0].get("product_id"):
            return orders[0].get("product_id")

        # From tickers
        tickers = event.get("tickers", [])
        if tickers and isinstance(tickers, list) and tickers[0].get("product_id"):
            return tickers[0].get("product_id")

        return None
