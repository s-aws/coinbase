"""Order Placement Hook Registry for pre/post submission extensibility.

This module provides a pluggable hook system for intercepting orders before they
are submitted to Coinbase's REST API. Extensions can validate, modify, or block
orders at the final submission point.

Example:
    >>> from integration.order_placement_hooks import get_global_placement_hook_registry
    >>> registry = get_global_placement_hook_registry()
    >>>
    >>> def validate_order(order):
    ...     if order['limit_price'] < 0:
    ...         raise ValueError("Price cannot be negative")
    ...     # Can also modify: order['limit_price'] = round(order['limit_price'], 2)
    ...
    >>> registry.register_pre_submission(validate_order)
"""

import threading
from typing import Callable, List, Optional, Dict, Any


class OrderPlacementHookRegistry:
    """Registry for order placement hooks (pre/post submission to Coinbase).
    
    Allows extensions to:
    - Validate orders before REST API submission
    - Modify orders (price, size, etc.) before sending to Coinbase
    - Block orders entirely by raising exceptions
    - Log/track submission events after REST call
    
    Hooks run sequentially. If any pre-submission hook raises an exception,
    submission is blocked and the exception is propagated.
    
    Attributes:
        _pre_submission_hooks: List of callbacks to run before REST submission.
        _post_submission_hooks: List of callbacks to run after REST submission.
        _lock: Thread lock for thread-safe hook registration.
    """
    
    def __init__(self):
        """Initialize empty hook registry."""
        self._pre_submission_hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._post_submission_hooks: List[Callable[[Dict[str, Any], Any], None]] = []
        self._lock = threading.RLock()
    
    # Extension example:
    # >>> def risk_limit_check(order):
    # ...     max_size = 10.0
    # ...     if order['size'] > max_size:
    # ...         raise ValueError(f"Order size {order['size']} exceeds max {max_size}")
    # >>> registry.register_pre_submission(risk_limit_check)
    #
    # >>> def log_submission(order, result):
    # ...     if result.get('success'):
    # ...         logging.info(f"Order {order['client_order_id']} submitted as {result['order_id']}")
    # >>> registry.register_post_submission(log_submission)
    
    def register_pre_submission(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a hook to run BEFORE REST API submission.
        
        Hook signature: callback(order: dict) -> None
        
        The order dict is passed by reference, so hooks CAN modify it before submission.
        If the hook raises an exception, submission is blocked and exception is propagated.
        
        Args:
            callback: Function with signature (order: dict) -> None.
                     Can modify order in-place or raise exception to block submission.
        
        Returns:
            None
        
        Example:
            >>> def validate_price(order):
            ...     if order['limit_price'] <= 0:
            ...         raise ValueError("Price must be > 0")
            ...     # Can also modify:
            ...     order['limit_price'] = round(order['limit_price'], 2)
            >>> registry.register_pre_submission(validate_price)
        """
        with self._lock:
            self._pre_submission_hooks.append(callback)
    
    def register_post_submission(self, callback: Callable[[Dict[str, Any], Any], None]) -> None:
        """Register a hook to run AFTER REST API submission.
        
        Hook signature: callback(order: dict, result: Any) -> None
        
        Post-submission hooks run after the order is placed. Exceptions here do not
        affect order placement (order is already submitted). Use for logging/tracking.
        
        Args:
            callback: Function with signature (order: dict, result: Any) -> None.
                     'result' is the return value from REST_CLIENT.place_limit_order().
        
        Returns:
            None
        
        Example:
            >>> def log_submission(order, result):
            ...     print(f"Placed {order['side']} {order['product_id']} @ {order['limit_price']}")
            >>> registry.register_post_submission(log_submission)
        """
        with self._lock:
            self._post_submission_hooks.append(callback)
    
    def call_pre_submission_hooks(self, order: Dict[str, Any]) -> None:
        """Execute all pre-submission hooks in sequence.
        
        If any hook raises an exception, execution stops and exception is propagated.
        This blocks order submission.
        
        Args:
            order: Order dict to validate/modify. Hooks can modify in-place.
        
        Returns:
            None
        
        Raises:
            Exception: If any hook raises an exception.
        
        Example:
            >>> registry.call_pre_submission_hooks(order_data)  # May raise
        """
        with self._lock:
            hooks_to_call = list(self._pre_submission_hooks)
        
        for hook in hooks_to_call:
            try:
                hook(order)
            except Exception as e:
                # Propagate exception - this blocks submission
                raise
    
    def call_post_submission_hooks(
        self,
        order: Dict[str, Any],
        result: Any,
    ) -> List[Exception]:
        """Execute all post-submission hooks in sequence.
        
        If a hook raises an exception, it is logged but does not affect order placement.
        All hooks are called even if some raise exceptions.
        
        Args:
            order: Order dict that was submitted.
            result: Return value from REST_CLIENT.place_limit_order().
        
        Returns:
            Exceptions raised by hooks. They never change placement truth,
            but the caller must surface them as local-finalization errors.
        """
        with self._lock:
            hooks_to_call = list(self._post_submission_hooks)

        errors: List[Exception] = []
        for hook in hooks_to_call:
            try:
                hook(order, result)
            except Exception as e:
                # Do not propagate: the order is already placed. Returning
                # every error keeps the failure observable without stopping
                # later hooks or inviting a placement retry.
                errors.append(e)
        return errors


# Global singleton registry
_global_placement_hook_registry: Optional[OrderPlacementHookRegistry] = None
_registry_lock = threading.RLock()


def get_global_placement_hook_registry() -> OrderPlacementHookRegistry:
    """Get the global order placement hook registry (singleton).
    
    Returns:
        The global OrderPlacementHookRegistry instance.
    
    Example:
        >>> registry = get_global_placement_hook_registry()
        >>> registry.register_pre_submission(my_validator)
    """
    global _global_placement_hook_registry
    
    if _global_placement_hook_registry is None:
        with _registry_lock:
            if _global_placement_hook_registry is None:
                _global_placement_hook_registry = OrderPlacementHookRegistry()
    
    return _global_placement_hook_registry


def reset_global_placement_hook_registry() -> None:
    """Reset the global registry (for testing).
    
    This clears all registered hooks. Use in test teardown.
    
    Returns:
        None
    """
    global _global_placement_hook_registry
    with _registry_lock:
        _global_placement_hook_registry = None
