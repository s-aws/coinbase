"""WebSocket Hook Registry for extensible message handling.

This module provides a hook registry system that allows extensions to
register pre/post processors for different websocket message types and
order statuses. This enables core features to be extended without
modifying the main handler logic.

Example:
    >>> hooks = WebSocketHookRegistry()
    >>> hooks.register_pre_order_status('FILLED', my_pre_processor)
    >>> hooks.register_post_order_status('FILLED', my_post_processor)
    >>> 
    >>> # In order_engine.py:
    >>> hooks.call_pre_order_status('FILLED', order)
    >>> # ... handle order ...
    >>> hooks.call_post_order_status('FILLED', order)

Hook Signature:
    Pre-processor: (order: dict) -> None
    Post-processor: (order: dict) -> None
    
    Hooks should not raise exceptions - they should log errors internally.
    If a hook needs to modify the order, it should do so in-place on the dict.
"""

from typing import Callable, Dict, List
import logging


class WebSocketHookRegistry:
    """Registry for pre/post processors on websocket message types.
    
    Supports hooks for:
    - Order status changes (OPEN, FILLED, CANCELLED, PENDING, etc.)
    - Snapshot messages (positions)
    - Message parsing/validation
    
    Attributes:
        _pre_order_status_hooks: Dict[status -> List[Callable]]
        _post_order_status_hooks: Dict[status -> List[Callable]]
        _pre_snapshot_hooks: List[Callable]
        _post_snapshot_hooks: List[Callable]
    """
    
    def __init__(self):
        """Initialize empty hook registries."""
        self._pre_order_status_hooks: Dict[str, List[Callable]] = {}
        self._post_order_status_hooks: Dict[str, List[Callable]] = {}
        self._pre_snapshot_hooks: List[Callable] = []
        self._post_snapshot_hooks: List[Callable] = []
        self._order_normalizers: List[Callable] = []
        self._snapshot_normalizers: List[Callable] = []
        self._logger = logging.getLogger(__name__)
    
    # --- Order Status Hooks ---
    
    def register_pre_order_status(self, status: str, callback: Callable) -> None:
        """Register a pre-processor for an order status change.
        
        Pre-processors run BEFORE the order status is processed by the engine.
        This is useful for early validation, metrics, or triggering alerts.
        
        Args:
            status: Order status (OPEN, FILLED, CANCELLED, PENDING, etc.)
            callback: Function(order: dict) -> None
        
        Example:
            >>> def validate_filled_order(order):
            ...     if order.get('cumulative_quantity') == 0:
            ...         logging.warning("Zero quantity fill")
            >>> hooks.register_pre_order_status('FILLED', validate_filled_order)
        """
        if status not in self._pre_order_status_hooks:
            self._pre_order_status_hooks[status] = []
        self._pre_order_status_hooks[status].append(callback)
    
    def register_post_order_status(self, status: str, callback: Callable) -> None:
        """Register a post-processor for an order status change.
        
        Post-processors run AFTER the order status is processed by the engine.
        This is useful for triggering secondary workflows or cleanup.
        
        Args:
            status: Order status (OPEN, FILLED, CANCELLED, PENDING, etc.)
            callback: Function(order: dict) -> None
        
        Example:
            >>> def notify_filled_order(order):
            ...     # Send to external system
            ...     external_api.log_fill(order['client_order_id'])
            >>> hooks.register_post_order_status('FILLED', notify_filled_order)
        """
        if status not in self._post_order_status_hooks:
            self._post_order_status_hooks[status] = []
        self._post_order_status_hooks[status].append(callback)
    
    def call_pre_order_status(self, status: str, order: dict) -> None:
        """Call all registered pre-processors for an order status.
        
        Args:
            status: Order status that changed.
            order: Order dict from websocket message.
        
        Returns:
            None. Exceptions from hooks are logged but not raised.
        """
        callbacks = self._pre_order_status_hooks.get(status, [])
        for callback in callbacks:
            try:
                callback(order)
            except Exception as e:
                self._logger.error(
                    f"Pre-processor for status {status} failed: {e}",
                    exc_info=True,
                    extra={'client_order_id': order.get('client_order_id')}
                )
    
    def call_post_order_status(self, status: str, order: dict) -> None:
        """Call all registered post-processors for an order status.
        
        Args:
            status: Order status that changed.
            order: Order dict from websocket message.
        
        Returns:
            None. Exceptions from hooks are logged but not raised.
        """
        callbacks = self._post_order_status_hooks.get(status, [])
        for callback in callbacks:
            try:
                callback(order)
            except Exception as e:
                self._logger.error(
                    f"Post-processor for status {status} failed: {e}",
                    exc_info=True,
                    extra={'client_order_id': order.get('client_order_id')}
                )
    
    # --- Snapshot Hooks ---
    
    def register_pre_snapshot(self, callback: Callable) -> None:
        """Register a pre-processor for position snapshot messages.
        
        Pre-processors run BEFORE the snapshot is processed by the engine.
        
        Args:
            callback: Function(snapshot: dict) -> None
        
        Example:
            >>> def validate_snapshot(snapshot):
            ...     positions = snapshot.get('positions', {})
            ...     if not positions:
            ...         logging.info("Empty position snapshot")
            >>> hooks.register_pre_snapshot(validate_snapshot)
        """
        self._pre_snapshot_hooks.append(callback)
    
    def register_post_snapshot(self, callback: Callable) -> None:
        """Register a post-processor for position snapshot messages.
        
        Post-processors run AFTER the snapshot is processed by the engine.
        
        Args:
            callback: Function(snapshot: dict) -> None
        
        Example:
            >>> def log_snapshot(snapshot):
            ...     # Record snapshot timestamp for audit
            ...     audit_log.record_snapshot(snapshot.get('timestamp'))
            >>> hooks.register_post_snapshot(log_snapshot)
        """
        self._post_snapshot_hooks.append(callback)
    
    def call_pre_snapshot(self, snapshot: dict) -> None:
        """Call all registered pre-processors for a snapshot.
        
        Args:
            snapshot: Position snapshot dict from websocket message.
        
        Returns:
            None. Exceptions from hooks are logged but not raised.
        """
        for callback in self._pre_snapshot_hooks:
            try:
                callback(snapshot)
            except Exception as e:
                self._logger.error(
                    f"Pre-processor for snapshot failed: {e}",
                    exc_info=True
                )
    
    def call_post_snapshot(self, snapshot: dict) -> None:
        """Call all registered post-processors for a snapshot.
        
        Args:
            snapshot: Position snapshot dict from websocket message.
        
        Returns:
            None. Exceptions from hooks are logged but not raised.
        """
        for callback in self._post_snapshot_hooks:
            try:
                callback(snapshot)
            except Exception as e:
                self._logger.error(
                    f"Post-processor for snapshot failed: {e}",
                    exc_info=True
                )
    
    # --- Order and Snapshot Normalizers ---
    
    def register_order_normalizer(self, callback: Callable) -> None:
        """Register a normalizer for order normalization.
        
        Normalizers run AFTER pre-hooks but BEFORE post-hooks and engine processing.
        They transform raw Coinbase fields into engine-friendly format.
        
        Use cases:
        - Handle product-type-specific field variations
        - Coerce string values to proper types
        - Add computed fields
        - Enrich order data
        
        Args:
            callback: Function(order: dict) -> None (modifies in-place)
        
        Example:
            >>> def normalize_futures_order(order):
            ...     # Coinbase sends different fields for futures
            ...     if 'contract_expiry_type' in order:
            ...         order['is_expiring'] = order['contract_expiry_type'] == 'EXPIRING'
            >>> hooks.register_order_normalizer(normalize_futures_order)
        """
        self._order_normalizers.append(callback)
    
    def register_snapshot_normalizer(self, callback: Callable) -> None:
        """Register a normalizer for position snapshot normalization.
        
        Normalizers run AFTER pre-hooks but BEFORE post-hooks and engine processing.
        They transform raw Coinbase snapshot fields into engine-friendly format.
        
        Args:
            callback: Function(snapshot: dict) -> None (modifies in-place)
        
        Example:
            >>> def normalize_snapshot(snapshot):
            ...     # Enrich position data with computed fields
            ...     for pos in snapshot.get('positions', {}).get('perpetual_futures_positions', []):
            ...         pos['notional_value'] = float(pos['net_size']) * float(pos['mark_price'])
            >>> hooks.register_snapshot_normalizer(normalize_snapshot)
        """
        self._snapshot_normalizers.append(callback)
    
    def call_order_normalizers(self, order: dict) -> None:
        """Call all registered order normalizers.
        
        Args:
            order: Order dict to normalize (modified in-place).
        
        Returns:
            None. Exceptions from normalizers are logged but not raised.
        """
        for normalizer in self._order_normalizers:
            try:
                normalizer(order)
            except Exception as e:
                self._logger.error(
                    f"Order normalizer failed: {e}",
                    exc_info=True,
                    extra={'client_order_id': order.get('client_order_id')}
                )
    
    def call_snapshot_normalizers(self, snapshot: dict) -> None:
        """Call all registered snapshot normalizers.
        
        Args:
            snapshot: Snapshot dict to normalize (modified in-place).
        
        Returns:
            None. Exceptions from normalizers are logged but not raised.
        """
        for normalizer in self._snapshot_normalizers:
            try:
                normalizer(snapshot)
            except Exception as e:
                self._logger.error(
                    f"Snapshot normalizer failed: {e}",
                    exc_info=True
                )
    
    def unregister_order_normalizer(self, callback: Callable) -> None:
        """Unregister an order normalizer.
        
        Args:
            callback: Previously registered normalizer callback.
        """
        try:
            self._order_normalizers.remove(callback)
        except ValueError:
            self._logger.warning("Callback not found in order normalizers")
    
    def unregister_snapshot_normalizer(self, callback: Callable) -> None:
        """Unregister a snapshot normalizer.
        
        Args:
            callback: Previously registered normalizer callback.
        """
        try:
            self._snapshot_normalizers.remove(callback)
        except ValueError:
            self._logger.warning("Callback not found in snapshot normalizers")
    
    # --- Hook Management ---
    
    def unregister_pre_order_status(self, status: str, callback: Callable) -> None:
        """Unregister a pre-processor for an order status.
        
        Args:
            status: Order status.
            callback: Previously registered callback.
        """
        if status in self._pre_order_status_hooks:
            try:
                self._pre_order_status_hooks[status].remove(callback)
            except ValueError:
                self._logger.warning(f"Callback not found for pre-order-status {status}")
    
    def unregister_post_order_status(self, status: str, callback: Callable) -> None:
        """Unregister a post-processor for an order status.
        
        Args:
            status: Order status.
            callback: Previously registered callback.
        """
        if status in self._post_order_status_hooks:
            try:
                self._post_order_status_hooks[status].remove(callback)
            except ValueError:
                self._logger.warning(f"Callback not found for post-order-status {status}")
    
    def unregister_pre_snapshot(self, callback: Callable) -> None:
        """Unregister a pre-processor for snapshots.
        
        Args:
            callback: Previously registered callback.
        """
        try:
            self._pre_snapshot_hooks.remove(callback)
        except ValueError:
            self._logger.warning("Callback not found for pre-snapshot")
    
    def unregister_post_snapshot(self, callback: Callable) -> None:
        """Unregister a post-processor for snapshots.
        
        Args:
            callback: Previously registered callback.
        """
        try:
            self._post_snapshot_hooks.remove(callback)
        except ValueError:
            self._logger.warning("Callback not found for post-snapshot")
    
    def clear_all(self) -> None:
        """Clear all registered hooks and normalizers. Useful for testing."""
        self._pre_order_status_hooks.clear()
        self._post_order_status_hooks.clear()
        self._pre_snapshot_hooks.clear()
        self._post_snapshot_hooks.clear()
        self._order_normalizers.clear()
        self._snapshot_normalizers.clear()
    
    def get_hook_count(self, status: str = None) -> int:
        """Get total number of registered hooks and normalizers.
        
        Args:
            status: If provided, count hooks for specific order status.
                   If None, count all hooks and normalizers.
        
        Returns:
            Number of registered hooks and normalizers.
        """
        if status:
            return (
                len(self._pre_order_status_hooks.get(status, [])) +
                len(self._post_order_status_hooks.get(status, []))
            )
        
        total = sum(len(hooks) for hooks in self._pre_order_status_hooks.values())
        total += sum(len(hooks) for hooks in self._post_order_status_hooks.values())
        total += len(self._pre_snapshot_hooks)
        total += len(self._post_snapshot_hooks)
        total += len(self._order_normalizers)
        total += len(self._snapshot_normalizers)
        return total


# Global singleton hook registry
_global_hooks: WebSocketHookRegistry = None


def get_global_hook_registry() -> WebSocketHookRegistry:
    """Get or create the global hook registry.
    
    This is the default registry used by OrderEngine if no custom
    registry is provided.
    
    Returns:
        WebSocketHookRegistry singleton.
    
    Example:
        >>> hooks = get_global_hook_registry()
        >>> hooks.register_post_order_status('FILLED', my_handler)
    """
    global _global_hooks
    if _global_hooks is None:
        _global_hooks = WebSocketHookRegistry()
    return _global_hooks


def set_global_hook_registry(registry: WebSocketHookRegistry) -> None:
    """Set a custom global hook registry.
    
    Useful for testing or using a custom registry implementation.
    
    Args:
        registry: WebSocketHookRegistry to use globally.
    """
    global _global_hooks
    _global_hooks = registry
