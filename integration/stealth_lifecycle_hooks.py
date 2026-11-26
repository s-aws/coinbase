"""Stealth-order lifecycle audit callbacks.

This retained registry connects ``StealthOrderManager`` lifecycle dispatch to
``OrderEventStreamPublisher``. It is an audit adapter, not an authoritative order
store and not a general before/after execution interception framework.

Dispatch and durability contract
--------------------------------
Callbacks run synchronously in registration order on the dispatching thread.
The registry copies its subscriber list while holding its ``RLock`` and releases
the lock before invoking callbacks. Subscriber exceptions are logged and
suppressed so audit failures do not interrupt the stealth evaluation loop.

The current audit path is therefore **best effort**. A transition may continue
when a callback or one of its database writes fails, and the event-stream,
lifecycle-history, snapshot, and latest-marker writes are not one atomic commit.
Individual manager call sites determine whether dispatch occurs before or after
their canonical state write; this registry makes no post-commit guarantee.

Canonical order and stealth state must never depend on successful callback
delivery. Eventual durable delivery requires a separately designed transactional
outbox with idempotent replay and per-``client_order_id`` ordering.

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

The production subscriber is registered by ``OrderEngine`` during event-stream
initialization. Tests may register isolated callbacks directly.

Extending
---------
Add new lifecycle events by:
1. Adding the value to ``core.enums.StealthLifecycleEvent``
2. Adding the dispatch call in ``core.stealth_order_manager`` at the transition point
3. Updating audit persistence or projections when the event needs new handling
No registry-class change is normally needed.
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

        Callbacks execute synchronously. Exceptions in subscribers are caught and
        logged so a failed audit callback does not abort the evaluation loop.

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
