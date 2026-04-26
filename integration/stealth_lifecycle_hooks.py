"""Stealth Order Lifecycle Hook Registry — full play-by-play event notifications.

This module provides a pluggable hook system that fires at every state-machine
transition of a stealth order, from initial creation through condition evaluation,
reveal attempts, failures, and final terminal states.

Why a separate registry from OrderStateHookRegistry?
------------------------------------------------------
Exchange-visible orders (tracked by OrderStateHookRegistry) only exist from the
moment they land on the exchange book. Stealth orders have a rich *pre-exchange*
lifecycle (hidden, evaluating conditions, reveal attempts, failures) that is
internal to our system and invisible to the exchange. A dedicated registry allows
consumers to reason about the complete lifecycle without mixing exchange-visible
and internal-only events.

Design constraints (deadlock safety)
-------------------------------------
StealthOrderManager does not hold a single global lock across its lifecycle
methods. Hooks are dispatched at the point where data is already persisted so:

1. Hooks execute after the DB write that captured the transition — they observe
   the committed state, not an intermediate state.
2. Hook callbacks acquire their own lock (OrderInventory._lock, RLock) which is
   entirely disjoint from any StealthOrderManager state.
3. Hooks that do DB I/O (e.g. the event stream publisher) do so on their own
   connection, completely decoupled from the caller's transaction.

Hook signature contract
-----------------------
``on_transition(stealth_order_id: str,
                event: StealthLifecycleEvent,
                context: dict) -> None``

The ``context`` dict provides the data needed to reconstruct the event without
additional DB queries. Standard keys:

    product_id        str    Trading pair, e.g. 'BTC-USDC'
    side              str    'BUY' or 'SELL'
    product_type      str    'SPOT' or 'FUTURE'
    size              float  Slice size for this reveal (0.0 if no placement)
    total_size        float  Total order size
    limit_price       float  Limit price of the order
    reason            str    Creation reason (e.g. 'normal_placement', 'follow_up')
    parent_order_id   str|None  Parent stealth order ID if follow-up
    placed_order_id   str|None  client_order_id of the exchange slice (if placed)
    failure_reason    str|None  Human-readable failure message (PLACEMENT_BLOCKED,
                                REVEAL_FAILED events only)
    timestamp         datetime  UTC time of the event

Subscribers are called in registration order. Exceptions are caught and logged;
they never disrupt the stealth evaluation loop.

Example — wiring OrderInventory and event stream at startup
------------------------------------------------------------
    >>> from integration.stealth_lifecycle_hooks import (
    ...     get_global_stealth_lifecycle_hook_registry
    ... )
    >>> from data.order_inventory import get_global_order_inventory
    >>>
    >>> lc_hooks = get_global_stealth_lifecycle_hook_registry()
    >>> inventory = get_global_order_inventory()
    >>> lc_hooks.register_on_transition(inventory.on_stealth_transition)

Example — custom failure alerting hook
---------------------------------------
    >>> def alert_on_failure(stealth_order_id, event, context):
    ...     if event in (StealthLifecycleEvent.REVEAL_FAILED,
    ...                  StealthLifecycleEvent.PLACEMENT_BLOCKED):
    ...         send_alert(f"Stealth order {stealth_order_id} failed: "
    ...                    f"{context.get('failure_reason')}")
    >>> lc_hooks.register_on_transition(alert_on_failure)

Extending
---------
Add new lifecycle events by:
1. Adding the value to ``core.enums.StealthLifecycleEvent``
2. Adding the dispatch call in ``core.stealth_order_manager`` at the transition point
3. Updating ``data.order_inventory.on_stealth_transition`` to handle the new event
No changes to this registry class are needed.
"""

import threading
from typing import Callable, Dict, Any, List, Optional

from core.enums import StealthLifecycleEvent
from logging_service import get_logger

logger = get_logger("StealthLifecycleHooks")


class StealthLifecycleHookRegistry:
    """Registry for stealth order lifecycle transition hooks.

    All registered callbacks receive the same (stealth_order_id, event, context)
    signature. Subscribers are called in registration order. Exceptions are caught
    and logged; they never propagate to the caller.

    Attributes:
        _on_transition_hooks: Callbacks fired on every lifecycle transition.
        _lock:                 RLock for thread-safe registration.
    """

    def __init__(self) -> None:
        """Initialise with empty hook list."""
        self._on_transition_hooks: List[
            Callable[[str, StealthLifecycleEvent, Dict[str, Any]], None]
        ] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_on_transition(
        self,
        callback: Callable[[str, StealthLifecycleEvent, Dict[str, Any]], None],
    ) -> None:
        """Register a hook that fires on every stealth lifecycle transition.

        Hook signature:
            ``callback(stealth_order_id: str,
                       event: StealthLifecycleEvent,
                       context: dict) -> None``

        See module docstring for the standard ``context`` keys.

        Args:
            callback: Function with the above signature.

        Example:
            >>> def my_handler(oid, event, ctx):
            ...     print(f"{oid} → {event}: {ctx.get('failure_reason')}")
            >>> registry.register_on_transition(my_handler)
        """
        with self._lock:
            self._on_transition_hooks.append(callback)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def call_on_transition(
        self,
        stealth_order_id: str,
        event: StealthLifecycleEvent,
        context: Dict[str, Any],
    ) -> None:
        """Dispatch all registered hooks for the given lifecycle transition.

        Non-blocking: exceptions in subscribers are caught and logged so that a
        misbehaving subscriber never stalls the stealth evaluation loop.

        Args:
            stealth_order_id: UUID string of the stealth order that transitioned.
            event:            The transition event (StealthLifecycleEvent member).
            context:          Dict with event-specific data (see module docstring).
        """
        with self._lock:
            hooks = list(self._on_transition_hooks)

        for hook in hooks:
            try:
                hook(stealth_order_id, event, context)
            except Exception as exc:
                logger.error(
                    f"[StealthLifecycleHooks] hook {hook.__name__!r} raised on "
                    f"{event} for {stealth_order_id}: {exc}",
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_registry: Optional[StealthLifecycleHookRegistry] = None
_registry_lock = threading.RLock()


def get_global_stealth_lifecycle_hook_registry() -> StealthLifecycleHookRegistry:
    """Return the process-wide StealthLifecycleHookRegistry singleton.

    Thread-safe double-checked locking. Safe to call from any thread.

    Returns:
        The global StealthLifecycleHookRegistry instance.

    Example:
        >>> registry = get_global_stealth_lifecycle_hook_registry()
        >>> registry.register_on_transition(my_handler)
    """
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = StealthLifecycleHookRegistry()
    return _global_registry


def reset_global_stealth_lifecycle_hook_registry() -> None:
    """Reset the global registry to a fresh empty instance.

    Intended for use in test teardown. Clears all registered hooks.

    Example:
        >>> reset_global_stealth_lifecycle_hook_registry()
    """
    global _global_registry
    with _registry_lock:
        _global_registry = None
