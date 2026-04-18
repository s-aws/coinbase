"""Engine integration bridge for OrderEngine with business logic modules.

Provides a unified interface that wraps OrderEngine while offering access to
specialized business logic bridges. Uses the Bridge pattern to integrate
OrderCalculator, OrderProcessor, and EventProcessor without coupling them
directly to OrderEngine.

This module preserves backward compatibility with OrderEngine while enabling
access to specialized computation, validation, and event handling.

Example:
    >>> from main import OrderEngine
    >>> from bridges.engine_integration import OrderEngineIntegration
    >>> engine = OrderEngine(...)
    >>> integrated = OrderEngineIntegration(engine)
    >>> integrated.run_forever()  # Same interface as OrderEngine
"""

from bridges.calculator_bridge import CalculatorBridge
from bridges.processor_bridge import ProcessorBridge
from bridges.event_bridge import EventBridge


class OrderEngineIntegration:
    """Wraps OrderEngine with bridge access to business logic modules.
    
    This class delegates to the wrapped OrderEngine while providing
    bridge access to specialized business logic components for:
    - Order calculations (follow-up prices, fees, positions)
    - Order processing (validation, enrichment, context)
    - Event handling (deduplication, routing, filtering)
    
    Attributes:
        engine: Wrapped OrderEngine instance.
        calculator_bridge: CalculatorBridge for order calculations.
        processor_bridge: ProcessorBridge for order processing.
        event_bridge: EventBridge for event deduplication and routing.
    
    Example:
        >>> from main import OrderEngine
        >>> engine = OrderEngine(
        ...     orderbook=ORDERBOOK,
        ...     db_client=DB_CLIENT,
        ...     subscription=Subscription,
        ...     api_key=API_KEY,
        ...     api_secret=API_SECRET,
        ...     order_post_only=ORDER_POST_ONLY,
        ... )
        >>> integrated = OrderEngineIntegration(engine)
        >>> integrated.run_forever()
    """

    def __init__(self, engine):
        """Initialize integration with existing OrderEngine.
        
        Args:
            engine: OrderEngine instance to wrap and provide bridge access to.
        """
        self.engine = engine
        self.calculator_bridge = CalculatorBridge()
        self.processor_bridge = ProcessorBridge()
        self.event_bridge = EventBridge(
            max_dedup_buckets=engine.max_seen_event_buckets,
            dedup_bucket_duration_secs=engine.max_rotate_seen_events_bucket_seconds,
        )

    # Delegation to engine (preserve original interface)

    def log_message(self, log_type: str, message) -> None:
        """Delegate to engine.log_message."""
        return self.engine.log_message(log_type, message)

    def build_order_log_context(self, order: dict) -> dict:
        """Use processor bridge to build order context.
        
        Args:
            order: Order dict to extract context from.
        
        Returns:
            Dict with concise order information for logging.
        """
        return self.processor_bridge.build_order_context(order)

    def build_event_log_payload(self, event: str, **kwargs) -> dict:
        """Delegate to engine.build_event_log_payload."""
        return self.engine.build_event_log_payload(event, **kwargs)

    def include_debug_fields(self, **kwargs) -> dict:
        """Delegate to engine.include_debug_fields."""
        return self.engine.include_debug_fields(**kwargs)

    def normalize_product_type(self, order: dict) -> str:
        """Delegate to engine.normalize_product_type."""
        return self.engine.normalize_product_type(order)

    def resolve_order_size(self, order: dict) -> float:
        """Delegate to engine.resolve_order_size."""
        return self.engine.resolve_order_size(order)

    def resolve_profit_target(self, order: dict) -> float:
        """Delegate to engine.resolve_profit_target."""
        return self.engine.resolve_profit_target(order)

    def get_orderbook_snapshot(self) -> dict:
        """Delegate to engine.get_orderbook_snapshot."""
        return self.engine.get_orderbook_snapshot()

    def refresh_positions_if_needed(self, product_id: str) -> None:
        """Delegate to engine.refresh_positions_if_needed."""
        return self.engine.refresh_positions_if_needed(product_id)

    def resolve_parent_client_order_id(
        self,
        client_order_id: str,
        order: dict = None,
        create_parent: bool = False,
        status: str = None,
    ) -> tuple:
        """Delegate to engine.resolve_parent_client_order_id."""
        return self.engine.resolve_parent_client_order_id(
            client_order_id,
            order,
            create_parent,
            status,
        )

    def claim_follow_up_processing(
        self,
        processed_flag_name: str,
        client_order_id: str,
    ) -> bool:
        """Delegate to engine.claim_follow_up_processing."""
        return self.engine.claim_follow_up_processing(
            processed_flag_name,
            client_order_id,
        )

    def release_follow_up_processing(
        self,
        processed_flag_name: str,
        client_order_id: str,
    ) -> None:
        """Delegate to engine.release_follow_up_processing."""
        return self.engine.release_follow_up_processing(
            processed_flag_name,
            client_order_id,
        )

    def complete_follow_up_processing(
        self,
        processed_flag_name: str,
        client_order_id: str,
    ) -> None:
        """Delegate to engine.complete_follow_up_processing."""
        return self.engine.complete_follow_up_processing(
            processed_flag_name,
            client_order_id,
        )

    def build_follow_up_log_payload(
        self,
        event: str,
        source_order: dict = None,
        parent_client_order_id: str = None,
        new_order: dict = None,
        attempted_new_order: dict = None,
        details: dict = None,
    ) -> dict:
        """Delegate to engine.build_follow_up_log_payload."""
        return self.engine.build_follow_up_log_payload(
            event,
            source_order,
            parent_client_order_id,
            new_order,
            attempted_new_order,
            details,
        )

    def on_open(self) -> None:
        """Delegate to engine.on_open."""
        return self.engine.on_open()

    def on_message(self, msg: str) -> None:
        """Delegate to engine.on_message."""
        return self.engine.on_message(msg)

    def process_user_event(self, event: dict) -> None:
        """Delegate to engine.process_user_event."""
        return self.engine.process_user_event(event)

    def process_user_snapshot(self, snapshot: dict) -> None:
        """Delegate to engine.process_user_snapshot."""
        return self.engine.process_user_snapshot(snapshot)

    def process_user_order(self, order: dict) -> None:
        """Delegate to engine.process_user_order."""
        return self.engine.process_user_order(order)

    def apply_position_update(self, order_template: dict) -> None:
        """Delegate to engine.apply_position_update."""
        return self.engine.apply_position_update(order_template)

    def compute_order_template(
        self,
        client_order_id: str,
        target_movement: dict = None,
    ) -> dict:
        """Delegate to engine.compute_order_template."""
        return self.engine.compute_order_template(client_order_id, target_movement)

    def child_order_already_exists(
        self,
        parent_client_order_id: str,
        order_template: dict,
    ) -> bool:
        """Delegate to engine.child_order_already_exists."""
        return self.engine.child_order_already_exists(
            parent_client_order_id,
            order_template,
        )

    def resolve_parent_target_movement(self, parent_client_order_id: str) -> dict:
        """Delegate to engine.resolve_parent_target_movement."""
        return self.engine.resolve_parent_target_movement(parent_client_order_id)

    def resolve_parent_replacement_state(self, parent_client_order_id: str) -> dict:
        """Delegate to engine.resolve_parent_replacement_state."""
        return self.engine.resolve_parent_replacement_state(parent_client_order_id)

    def can_create_follow_up_order(self, parent_client_order_id: str) -> tuple:
        """Delegate to engine.can_create_follow_up_order."""
        return self.engine.can_create_follow_up_order(parent_client_order_id)

    def handle_cancelled_order(self, order: dict) -> None:
        """Delegate to engine.handle_cancelled_order."""
        return self.engine.handle_cancelled_order(order)

    def handle_filled_order(self, order: dict) -> None:
        """Delegate to engine.handle_filled_order."""
        return self.engine.handle_filled_order(order)

    def record_follow_up_order(
        self,
        source_order: dict,
        new_order: list,
        order_template: dict,
        parent_client_order_id: str,
        processed_flag_name: str = None,
    ) -> None:
        """Delegate to engine.record_follow_up_order."""
        return self.engine.record_follow_up_order(
            source_order,
            new_order,
            order_template,
            parent_client_order_id,
            processed_flag_name,
        )

    def build_parent_child_order_ids_snapshot(self) -> tuple:
        """Delegate to engine.build_parent_child_order_ids_snapshot."""
        return self.engine.build_parent_child_order_ids_snapshot()

    def load_parent_child_order_ids(self, force_log: bool = False) -> bool:
        """Delegate to engine.load_parent_child_order_ids."""
        return self.engine.load_parent_child_order_ids(force_log)

    def reconcile_parent_child_order_ids_periodically(
        self,
        interval_seconds: int = 30,
    ) -> None:
        """Delegate to engine.reconcile_parent_child_order_ids_periodically."""
        return self.engine.reconcile_parent_child_order_ids_periodically(
            interval_seconds,
        )

    def rotate_seen_events_buckets(self) -> None:
        """Delegate to engine.rotate_seen_events_buckets."""
        return self.engine.rotate_seen_events_buckets()

    def generate_process_event_worker(self, channel: str) -> callable:
        """Delegate to engine.generate_process_event_worker."""
        return self.engine.generate_process_event_worker(channel)

    def connect_to_websocket(self) -> None:
        """Delegate to engine.connect_to_websocket."""
        return self.engine.connect_to_websocket()

    def start_background_threads(self) -> None:
        """Delegate to engine.start_background_threads."""
        return self.engine.start_background_threads()

    def run_forever(self) -> None:
        """Delegate to engine.run_forever.
        
        Starts all background threads and runs main event loop indefinitely.
        """
        return self.engine.run_forever()

    # Bridge accessor methods

    def get_calculator_bridge(self) -> CalculatorBridge:
        """Get calculator bridge for direct access to calculations.
        
        Returns:
            CalculatorBridge instance.
        """
        return self.calculator_bridge

    def get_processor_bridge(self) -> ProcessorBridge:
        """Get processor bridge for direct access to order processing.
        
        Returns:
            ProcessorBridge instance.
        """
        return self.processor_bridge

    def get_event_bridge(self) -> EventBridge:
        """Get event bridge for direct access to event handling.
        
        Returns:
            EventBridge instance.
        """
        return self.event_bridge
