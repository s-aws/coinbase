"""Fill Event Hook Registry for pre/post fill recording extensibility.

This module provides a pluggable hook system for intercepting fills before and after
they are recorded to the fill ledger. Extensions can validate, enrich, or block fills,
and can log/track fills after recording.

Mirrors the OrderPlacementHookRegistry pattern but for fill lifecycle events.

Example:
    >>> from integration.fill_event_hooks import get_global_fill_event_hook_registry
    >>> registry = get_global_fill_event_hook_registry()
    >>>
    >>> def validate_fill(fill_data):
    ...     if fill_data['quantity'] <= 0:
    ...         raise ValueError("Fill quantity must be > 0")
    ...     # Can also modify: fill_data['commission_percentage'] = 0.001
    ...
    >>> registry.register_pre_fill(validate_fill)
"""

import threading
from typing import Callable, List, Optional, Dict, Any


class FillEventHookRegistry:
    """Registry for fill event hooks (pre/post recording to fill ledger).
    
    Allows extensions to:
    - Validate fills before recording to ledger
    - Enrich fills (add commission, adjust price, etc.) before persistence
    - Block fills entirely by raising exceptions
    - Log/track fills after recording to ledger
    
    Hooks run sequentially. If any pre-fill hook raises an exception,
    recording is blocked and the exception is propagated.
    
    Attributes:
        _pre_fill_hooks: List of callbacks to run before fill recording.
        _post_fill_hooks: List of callbacks to run after fill recording.
        _lock: Thread lock for thread-safe hook registration.
    """
    
    def __init__(self):
        """Initialize empty hook registry."""
        self._pre_fill_hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._post_fill_hooks: List[Callable[[Dict[str, Any], str], None]] = []
        self._lock = threading.RLock()
    
    def register_pre_fill(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a hook to run BEFORE fill recording to ledger.
        
        Hook signature: callback(fill_data: dict) -> None
        
        The fill_data dict is passed by reference, so hooks CAN modify it before recording.
        If the hook raises an exception, fill recording is blocked and exception is propagated.
        
        Fill data structure:
            {
                'instrument': str (e.g. 'BTC-USD'),
                'side': str ('BUY' or 'SELL'),
                'quantity': float,
                'price': float,
                'fees': float,
                'client_order_id': str (UUID),
                'timestamp': datetime,
                'commission_percentage': float (optional, default 0.0)
            }
        
        Args:
            callback: Function with signature (fill_data: dict) -> None.
                     Can modify fill_data in-place or raise exception to block recording.
        
        Returns:
            None
        
        Example:
            >>> def validate_fill(fill):
            ...     if fill['quantity'] <= 0:
            ...         raise ValueError("Quantity must be > 0")
            ...     # Can also enrich:
            ...     fill['commission_percentage'] = 0.001
            >>> registry.register_pre_fill(validate_fill)
        """
        with self._lock:
            self._pre_fill_hooks.append(callback)
    
    def register_post_fill(self, callback: Callable[[Dict[str, Any], str], None]) -> None:
        """Register a hook to run AFTER fill recording to ledger.
        
        Hook signature: callback(fill_data: dict, trade_id: str) -> None
        
        Post-fill hooks run after the fill is recorded. Exceptions here do not
        affect fill recording (fill is already in database). Use for logging/tracking.
        
        Args:
            callback: Function with signature (fill_data: dict, trade_id: str) -> None.
                     'trade_id' is the unique identifier for the recorded fill.
        
        Returns:
            None
        
        Example:
            >>> def log_fill(fill, trade_id):
            ...     print(f"Recorded {fill['side']} {fill['quantity']} {fill['instrument']} @ {fill['price']}")
            >>> registry.register_post_fill(log_fill)
        """
        with self._lock:
            self._post_fill_hooks.append(callback)
    
    def call_pre_fill_hooks(self, fill_data: Dict[str, Any]) -> None:
        """Execute all pre-fill hooks in sequence.
        
        If any hook raises an exception, execution stops and exception is propagated.
        This blocks fill recording.
        
        Args:
            fill_data: Fill dict to validate/enrich. Hooks can modify in-place.
        
        Returns:
            None
        
        Raises:
            Exception: If any hook raises an exception.
        
        Example:
            >>> registry.call_pre_fill_hooks(fill_data)  # May raise
        """
        with self._lock:
            hooks_to_call = list(self._pre_fill_hooks)
        
        for hook in hooks_to_call:
            try:
                hook(fill_data)
            except Exception as e:
                # Propagate exception - this blocks fill recording
                raise
    
    def call_post_fill_hooks(self, fill_data: Dict[str, Any], trade_id: str) -> None:
        """Execute all post-fill hooks in sequence.
        
        If a hook raises an exception, it is logged but does not affect fill recording.
        All hooks are called even if some raise exceptions.
        
        Args:
            fill_data: Fill dict that was recorded.
            trade_id: Unique identifier for the recorded fill (from fill_ledger table).
        
        Returns:
            None
        """
        with self._lock:
            hooks_to_call = list(self._post_fill_hooks)
        
        for hook in hooks_to_call:
            try:
                hook(fill_data, trade_id)
            except Exception as e:
                # Log but don't propagate - fill is already recorded
                # Extensions should handle their own logging
                pass


# Global singleton registry
_global_fill_event_hook_registry: Optional[FillEventHookRegistry] = None
_registry_lock = threading.RLock()


def get_global_fill_event_hook_registry() -> FillEventHookRegistry:
    """Get the global fill event hook registry (singleton).
    
    Returns:
        The global FillEventHookRegistry instance.
    
    Example:
        >>> registry = get_global_fill_event_hook_registry()
        >>> registry.register_pre_fill(my_validator)
    """
    global _global_fill_event_hook_registry
    
    if _global_fill_event_hook_registry is None:
        with _registry_lock:
            if _global_fill_event_hook_registry is None:
                _global_fill_event_hook_registry = FillEventHookRegistry()
    
    return _global_fill_event_hook_registry


def reset_global_fill_event_hook_registry() -> None:
    """Reset the global registry (for testing).
    
    This clears all registered hooks. Use in test teardown.
    
    Returns:
        None
    """
    global _global_fill_event_hook_registry
    with _registry_lock:
        _global_fill_event_hook_registry = None
