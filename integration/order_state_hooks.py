"""Order State Hook Registry — exchange-visible order lifecycle notifications.

This module provides a pluggable hook system that fires when an order transitions
between exchange-visible states (OPENED → FILLED / CANCELLED / EXPIRED).

The hooks are the integration seam between StateManager (which owns the authoritative
in-memory order state) and any consumer that needs to react to order transitions,
such as OrderInventory for aggregate counting, risk managers for exposure limits, or
dashboard WebSocket broadcast.

Design constraints (deadlock safety)
-------------------------------------
StateManager holds ``self._lock`` (threading.Lock, NON-recursive) while mutating
its internal collections. **Hook dispatch is intentionally done AFTER the lock is
released** (see StateManager._dispatch_order_state_opened / _dispatch_order_state_closed).
This guarantees:

1. Hooks can safely acquire their own locks (e.g. OrderInventory._lock) without
   creating a lock-ordering violation.
2. Hooks can perform I/O (DB writes) without holding StateManager._lock, preventing
   long-hold-period stalls.
3. No callback can call back into StateManager while the lock is still held.

Hook signature contract
-----------------------
``on_opened(order: Order) -> None``
    Called once when an order becomes working on the exchange.

``on_closed(order: Order, event: OrderStateEvent) -> None``
    Called once when an order exits the working state for any terminal reason.
    ``event`` identifies why (FILLED, CANCELLED, EXPIRED).

Both hook types are non-blocking: exceptions are caught and logged so a misbehaving
subscriber never disrupts trading execution.

Example — wiring OrderInventory at startup
------------------------------------------
    >>> from integration.order_state_hooks import get_global_order_state_hook_registry
    >>> from data.order_inventory import get_global_order_inventory
    >>>
    >>> registry = get_global_order_state_hook_registry()
    >>> inventory = get_global_order_inventory()
    >>>
    >>> registry.register_on_opened(inventory.on_order_opened)
    >>> registry.register_on_closed(inventory.on_order_closed)

Example — custom risk limit hook
---------------------------------
    >>> def max_position_guard(order):
    ...     count = inventory.get_count(order.product_id, order.order_side, order.product_type)
    ...     if count > 5:
    ...         logger.warning(f"Position limit reached for {order.product_id}")
    >>> registry.register_on_opened(max_position_guard)

Extending
---------
Add new hook types (e.g. on_amended) by following the exact pattern below:
1. Add the new event value to ``core.enums.OrderStateEvent``
2. Add ``_on_amended_hooks`` list and ``register_on_amended`` / ``call_on_amended``
3. Call ``call_on_amended`` from StateManager after lock release
"""

import threading
from typing import Callable, List, Optional, Any

from core.models import Order
from core.enums import OrderStateEvent
from logging_service import get_logger

logger = get_logger("OrderStateHooks")


class OrderStateHookRegistry:
    """Registry for exchange-visible order state transition hooks.

    Subscribers are called in registration order. Exceptions inside any subscriber
    are caught and logged; they never propagate to the caller.

    Attributes:
        _on_opened_hooks:  Callbacks fired when an order becomes working.
        _on_closed_hooks:  Callbacks fired when an order exits working state.
        _lock:             RLock for thread-safe hook registration.
    """

    def __init__(self) -> None:
        """Initialise with empty hook lists."""
        self._on_opened_hooks: List[Callable[[Order], None]] = []
        self._on_closed_hooks: List[Callable[[Order, OrderStateEvent], None]] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_on_opened(self, callback: Callable[[Order], None]) -> None:
        """Register a hook that fires when an order becomes working on the exchange.

        Hook signature: ``callback(order: Order) -> None``

        The ``order`` object reflects the state at the moment the transition was
        detected by StateManager. Do NOT modify the order in-place.

        Args:
            callback: Function with signature (order: Order) -> None.

        Example:
            >>> def track_new_order(order):
            ...     print(f"New working order: {order.client_order_id} {order.product_id}")
            >>> registry.register_on_opened(track_new_order)
        """
        with self._lock:
            self._on_opened_hooks.append(callback)

    def register_on_closed(
        self, callback: Callable[[Order, OrderStateEvent], None]
    ) -> None:
        """Register a hook that fires when an order leaves the working state.

        Hook signature: ``callback(order: Order, event: OrderStateEvent) -> None``

        ``event`` will be one of: FILLED, CANCELLED, EXPIRED.

        Args:
            callback: Function with signature (order: Order, event: OrderStateEvent) -> None.

        Example:
            >>> def track_closed(order, event):
            ...     print(f"Order {order.client_order_id} closed: {event}")
            >>> registry.register_on_closed(track_closed)
        """
        with self._lock:
            self._on_closed_hooks.append(callback)

    # ------------------------------------------------------------------
    # Dispatch (called by StateManager after its lock is released)
    # ------------------------------------------------------------------

    def call_on_opened(self, order: Order) -> None:
        """Dispatch all on_opened hooks for the given order.

        Non-blocking: exceptions in subscribers are caught and logged.
        Must be called OUTSIDE StateManager._lock to avoid deadlock.

        Args:
            order: The Order that became working on the exchange.
        """
        with self._lock:
            hooks = list(self._on_opened_hooks)

        for hook in hooks:
            try:
                hook(order)
            except Exception as exc:
                logger.error(
                    f"[OrderStateHooks] on_opened hook {hook.__name__!r} raised: {exc}",
                    exc_info=True,
                )

    def call_on_closed(self, order: Order, event: OrderStateEvent) -> None:
        """Dispatch all on_closed hooks for the given order and termination event.

        Non-blocking: exceptions in subscribers are caught and logged.
        Must be called OUTSIDE StateManager._lock to avoid deadlock.

        Args:
            order: The Order that exited the working state.
            event: The reason it closed (FILLED, CANCELLED, EXPIRED).
        """
        with self._lock:
            hooks = list(self._on_closed_hooks)

        for hook in hooks:
            try:
                hook(order, event)
            except Exception as exc:
                logger.error(
                    f"[OrderStateHooks] on_closed hook {hook.__name__!r} raised: {exc}",
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_registry: Optional[OrderStateHookRegistry] = None
_registry_lock = threading.RLock()


def get_global_order_state_hook_registry() -> OrderStateHookRegistry:
    """Return the process-wide OrderStateHookRegistry singleton.

    Thread-safe double-checked locking. Safe to call from any thread.

    Returns:
        The global OrderStateHookRegistry instance.

    Example:
        >>> registry = get_global_order_state_hook_registry()
        >>> registry.register_on_opened(my_callback)
    """
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = OrderStateHookRegistry()
    return _global_registry


def reset_global_order_state_hook_registry() -> None:
    """Reset the global registry to a fresh empty instance.

    Intended for use in test teardown. Clears all registered hooks.

    Example:
        >>> reset_global_order_state_hook_registry()
    """
    global _global_registry
    with _registry_lock:
        _global_registry = None
