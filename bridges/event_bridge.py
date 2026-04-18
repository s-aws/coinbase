"""Event bridge providing event processing utilities.

Wraps EventProcessor to provide a clean interface for event deduplication,
filtering, and validation.

Example:
    >>> bridge = EventBridge()
    >>> event = {'channel': 'user', 'product_id': 'BTC-USDC'}
    >>> if not bridge.is_duplicate_event(event):
    ...     bridge.mark_event_seen(event)
    ...     # Process event
"""

from business.event_processor import EventProcessor


class EventBridge:
    """Adapter bridge wrapping EventProcessor for OrderEngine.
    
    Provides event deduplication and filtering utilities that OrderEngine uses.
    
    Attributes:
        processor: EventProcessor instance for deduplication and routing.
    """

    def __init__(self, max_dedup_buckets: int = 3, dedup_bucket_duration_secs: int = 60):
        """Initialize event bridge.
        
        Args:
            max_dedup_buckets: Number of rolling dedup buckets (default 3).
            dedup_bucket_duration_secs: Duration of each bucket in seconds (default 60).
        """
        self.processor = EventProcessor(
            max_dedup_buckets=max_dedup_buckets,
            dedup_bucket_duration_secs=dedup_bucket_duration_secs,
        )

    def hash_event(self, event: dict) -> str:
        """Generate SHA256 hash of event for deduplication.
        
        Args:
            event: Event dict to hash.
        
        Returns:
            Hex string SHA256 hash.
        
        Example:
            >>> bridge = EventBridge()
            >>> hash1 = bridge.hash_event({'type': 'filled'})
            >>> hash2 = bridge.hash_event({'type': 'filled'})
            >>> hash1 == hash2
            True
        """
        return self.processor.hash_event(event)

    def is_duplicate_event(self, event: dict) -> bool:
        """Check if event has been seen before.
        
        Args:
            event: Event dict to check.
        
        Returns:
            True if event seen in any dedup bucket.
        
        Example:
            >>> bridge = EventBridge()
            >>> is_dup = bridge.is_duplicate_event(
            ...     {'type': 'filled', 'id': '123'}
            ... )
            >>> is_dup
            False
        """
        return self.processor.is_duplicate_event(event)

    def mark_event_seen(self, event: dict) -> None:
        """Mark event as seen in current bucket.
        
        Args:
            event: Event dict to mark.
        
        Returns:
            None
        
        Example:
            >>> bridge = EventBridge()
            >>> bridge.mark_event_seen({'type': 'filled', 'id': '123'})
        """
        self.processor.mark_event_seen(event)

    def rotate_dedup_buckets(self) -> None:
        """Rotate event deduplication buckets (shift old events out).
        
        Called periodically (e.g., every 60 seconds) to prevent
        unbounded memory growth. Discards oldest bucket.
        
        Returns:
            None
        
        Example:
            >>> bridge = EventBridge()
            >>> bridge.rotate_dedup_buckets()
        """
        self.processor.rotate_dedup_buckets()

    def filter_events_by_channel(self, events: list, channel: str) -> list:
        """Filter events to specific channel.
        
        Args:
            events: List of event dicts.
            channel: Channel name to filter by.
        
        Returns:
            List of events matching channel.
        
        Example:
            >>> bridge = EventBridge()
            >>> user_events = bridge.filter_events_by_channel(
            ...     [{'channel': 'user'}, {'channel': 'ticker'}],
            ...     'user'
            ... )
            >>> len(user_events)
            1
        """
        return self.processor.filter_events_by_channel(events, channel)

    def filter_events_by_product(self, events: list, product_id: str) -> list:
        """Filter events to specific product.
        
        Args:
            events: List of event dicts.
            product_id: Product ID to filter by.
        
        Returns:
            List of events matching product.
        
        Example:
            >>> bridge = EventBridge()
            >>> btc_events = bridge.filter_events_by_product(
            ...     [{'product_id': 'BTC-USDC'}, {'product_id': 'ETH-USDC'}],
            ...     'BTC-USDC'
            ... )
            >>> len(btc_events)
            1
        """
        return self.processor.filter_events_by_product(events, product_id)

    def should_process_event(
        self,
        event: dict,
        subscribed_products: list,
        subscribed_channels: list,
    ) -> bool:
        """Check if event should be processed.
        
        Validates: not duplicate, channel subscribed, product subscribed.
        
        Args:
            event: Event dict to check.
            subscribed_products: List of subscribed product IDs.
            subscribed_channels: List of subscribed channel names.
        
        Returns:
            True if event should be processed.
        
        Example:
            >>> bridge = EventBridge()
            >>> should_process = bridge.should_process_event(
            ...     {'channel': 'user', 'product_id': 'BTC-USDC'},
            ...     ['BTC-USDC'],
            ...     ['user', 'ticker']
            ... )
            >>> should_process
            True
        """
        return self.processor.should_process_event(
            event,
            subscribed_products,
            subscribed_channels,
        )

    def extract_orders_from_event(self, event: dict) -> list:
        """Extract orders from user channel event.
        
        Args:
            event: User channel event dict.
        
        Returns:
            List of order dicts (may be empty).
        
        Example:
            >>> bridge = EventBridge()
            >>> orders = bridge.extract_orders_from_event(
            ...     {'orders': [{'order_id': '123'}]}
            ... )
            >>> len(orders)
            1
        """
        return self.processor.extract_orders_from_event(event)

    def extract_product_id_from_event(self, event: dict) -> str:
        """Extract product_id from event (handles nested structures).
        
        Args:
            event: Event dict from websocket.
        
        Returns:
            Product ID string or empty string if not found.
        
        Example:
            >>> bridge = EventBridge()
            >>> product_id = bridge.extract_product_id_from_event(
            ...     {'product_id': 'BTC-USDC'}
            ... )
            >>> product_id
            'BTC-USDC'
        """
        return self.processor.extract_product_id_from_event(event)
