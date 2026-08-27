"""Order Inventory — aggregate working-order counts and stealth lifecycle ledger.

This module provides two complementary in-memory data structures, both backed by
database state so they survive process restarts:

1. **OrderInventory** — aggregate counts of working orders on the exchange,
   keyed by (product_id, side, product_type). Updated via OrderStateHookRegistry.

2. **StealthInventoryEntry** — per-order lifecycle tracking for stealth orders
   from creation through every state-machine transition. Updated via
   StealthLifecycleHookRegistry.

Both structures are held by the **OrderInventory** class (single entry point).

NOTIONAL CALCULATION (CRITICAL FOR FUTURES)
--------------------------------------------
**SPOT ORDERS:**
  notional = total_size (in base currency, e.g. BTC)
  Example: 1.5 BTC = 1.5 units of exposure

**FUTURES/PERPETUAL ORDERS:**
  notional = total_size × avg_price × contract_size
  - total_size: number of contracts
  - avg_price: representative price (limit price for pending, mark price for current)
  - contract_size: from product metadata (e.g., BTC-PERP has contract_size=0.01)
  Example: 100 contracts × $50,000 × 0.01 = $50,000 notional exposure

OrderInventoryEntry.get_notional() computes this automatically. For SPOT products
(contract_size=1.0), this simplifies to: total_size × avg_price.

Restart resilience
------------------
On startup call ``OrderInventory.rebuild_from_database(db_client)`` once before
wiring the hooks. This loads:
  - Working exchange orders from ``order_parent WHERE status IN ('OPEN','PENDING')``
  - All stealth orders from ``stealth_orders``, including terminal history
  - Last lifecycle failure information from ``stealth_orders.last_lifecycle_event``
    and ``stealth_orders.failure_reason`` columns (added by migration in database/order.py)

After rebuild, subsequent hook calls keep the in-memory state in sync.

Deadlock safety
---------------
``OrderInventory._lock`` is a ``threading.RLock()``.  It is a leaf lock — nothing
called while holding ``_lock`` acquires any other application lock.  The call chain
is always:

  StateManager._lock  (released)
       ↓ hook dispatch (OUTSIDE lock)
  OrderInventory._lock  (brief, data-only mutation)

or:

  StealthOrderManager  (no global lock)
       ↓ hook dispatch
  OrderInventory._lock  (brief, data-only mutation)

No circular acquisition is possible.

Thread safety
-------------
All public methods that read or write inventory state acquire ``_lock``.
``rebuild_from_database`` is expected to be called from the startup thread before
other threads begin dispatching hooks, so it does NOT acquire ``_lock``.

Example — startup wiring
--------------------------
    >>> from data.order_inventory import get_global_order_inventory
    >>> from integration.order_state_hooks import get_global_order_state_hook_registry
    >>> from integration.stealth_lifecycle_hooks import get_global_stealth_lifecycle_hook_registry
    >>>
    >>> inventory = get_global_order_inventory()
    >>> inventory.rebuild_from_database(db_client)
    >>>
    >>> state_hooks = get_global_order_state_hook_registry()
    >>> state_hooks.register_on_opened(inventory.on_order_opened)
    >>> state_hooks.register_on_closed(inventory.on_order_closed)
    >>>
    >>> lc_hooks = get_global_stealth_lifecycle_hook_registry()
    >>> lc_hooks.register_on_transition(inventory.on_stealth_transition)

Example — querying inventory
------------------------------
    >>> inv = get_global_order_inventory()
    >>> inv.get_count('BTC-USDC', OrderSide.BUY, ProductType.SPOT)
    3
    >>> entry = inv.get_entry('BTC-PERP', OrderSide.BUY, ProductType.FUTURE)
    >>> if entry:
    ...     notional = entry.get_notional()  # contracts × avg_price × contract_size
    ...     print(f"Notional exposure: ${notional:,.2f}")
    >>> inv.get_stealth_pending()          # HIDDEN + PENDING
    [StealthInventoryEntry(...), ...]
    >>> inv.get_stealth_failures()         # PLACEMENT_BLOCKED + REVEAL_FAILED
    [StealthInventoryEntry(...), ...]
    >>> inv.get_stealth_on_exchange()      # REVEALED (on exchange books)
    [StealthInventoryEntry(...), ...]
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any

from core.enums import (
    OrderSide,
    OrderStateEvent,
    ProductType,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.models import Order
from core.constants import SPOT_PRODUCT_IDS, DERIVATIVES_PRODUCT_IDS
from logging_service import get_logger

logger = get_logger("OrderInventory")


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# Key for the exchange-visible working-order aggregate buckets
_InventoryKey = Tuple[str, OrderSide, ProductType]  # (product_id, side, type)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class OrderInventoryEntry:
    """Aggregate of working (exchange-visible) orders for one product/side/type bucket.

    Tracks both exchange-visible count and financial exposure (notional). For SPOT products,
    notional is simply total_size. For FUTURES/PERPETUAL products, notional accounts for
    the contract multiplier: contracts × price × contract_size.

    NOTIONAL CALCULATION
    --------------------
    **SPOT Example:**
      Product: BTC-USDC, total_size=1.5, avg_price=50000, contract_size=1.0
      Notional = 1.5 × 50,000 × 1.0 = $75,000

    **FUTURES Example:**
      Product: BTC-PERP, total_size=100, avg_price=50000, contract_size=0.01
      Notional = 100 × 50,000 × 0.01 = $50,000

    Use get_notional() to compute automatically.

    WEIGHTED AVERAGE PRICE
    ----------------------
    When multiple orders are added to the same bucket:
      avg_price = total_cost / total_size
    where total_cost = sum of (order_size × order_price) for all orders in bucket.

    The total_cost field makes this calculation transparent and reversible.

    Attributes:
        product_id:       Trading pair, e.g. 'BTC-USDC' or 'BTC-PERP'.
        side:             OrderSide.BUY or OrderSide.SELL.
        product_type:     ProductType.SPOT or ProductType.FUTURE.
        count:            Number of working orders currently on the exchange.
        total_size:       Sum of size across all working orders in this bucket.
                          For SPOT: base currency units (e.g., BTC).
                          For FUTURES: number of contracts.
        total_cost:       Sum of (size × price) across all orders in bucket.
                          Used for weighted average: avg_price = total_cost / total_size.
        avg_price:        Weighted average price (total_cost / total_size).
                          Used in notional calculation: total_size × avg_price × contract_size.
        contract_size:    Multiplier for notional calculation (from product metadata).
                          SPOT: always 1.0 (notional = total_size × avg_price).
                          FUTURES: contract multiplier (e.g., 0.01 for BTC-PERP = 0.01 BTC/contract).
        first_placed_at:  Timestamp of the oldest still-working order.
        last_placed_at:   Timestamp of the most recently placed working order.
        client_order_ids: Set of client_order_ids for deduplication / idempotency.
    """

    product_id: str
    side: OrderSide
    product_type: ProductType
    count: int = 0
    total_size: float = 0.0
    total_cost: float = 0.0
    avg_price: float = 0.0
    contract_size: float = 1.0
    first_placed_at: Optional[datetime] = None
    last_placed_at: Optional[datetime] = None
    client_order_ids: Set[str] = field(default_factory=set)

    def get_notional(self) -> float:
        """Calculate notional exposure for this bucket.

        Notional = total_size × avg_price × contract_size

        For SPOT products (contract_size=1.0):
          notional = total_size × avg_price
          Example: 1.5 BTC @ $50,000 = $75,000

        For FUTURES products:
          notional = contracts × price × contract_multiplier
          Example: 100 contracts @ $50,000 × 0.01 (BTC-PERP) = $50,000

        Returns:
            The notional exposure as a float, or 0.0 if price/size are not set.

        Examples:
            >>> entry = OrderInventoryEntry(
            ...     product_id='BTC-USDC', side=OrderSide.BUY,
            ...     product_type=ProductType.SPOT,
            ...     total_size=1.5, avg_price=50000.0, contract_size=1.0
            ... )
            >>> entry.get_notional()
            75000.0

            >>> entry = OrderInventoryEntry(
            ...     product_id='BTC-PERP', side=OrderSide.BUY,
            ...     product_type=ProductType.FUTURE,
            ...     total_size=100, avg_price=50000.0, contract_size=0.01
            ... )
            >>> entry.get_notional()
            50000.0
        """
        return self.total_size * self.avg_price * self.contract_size

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for dashboard / API responses."""
        return {
            "product_id": self.product_id,
            "side": self.side.value if isinstance(self.side, OrderSide) else self.side,
            "product_type": (
                self.product_type.value
                if isinstance(self.product_type, ProductType)
                else self.product_type
            ),
            "count": self.count,
            "total_size": self.total_size,
            "total_cost": self.total_cost,
            "avg_price": self.avg_price,
            "contract_size": self.contract_size,
            "notional": self.get_notional(),
            "first_placed_at": (
                self.first_placed_at.isoformat() if self.first_placed_at else None
            ),
            "last_placed_at": (
                self.last_placed_at.isoformat() if self.last_placed_at else None
            ),
        }


@dataclass
class StealthInventoryEntry:
    """Per-stealth-order lifecycle state snapshot held in memory.

    This mirrors the most recent known state of a stealth order and is the
    fast-path for queries like "show all pending stealth orders" without hitting
    the database.

    Attributes:
        stealth_order_id: UUID string — primary identifier.
        product_id:       Trading pair.
        side:             OrderSide enum.
        product_type:     ProductType enum.
        status:           StealthOrderStatus (HIDDEN, PENDING, TRIGGERED, REVEALED,
                          ERROR, EXECUTED, CANCELLED).
        last_event:       Most recent StealthLifecycleEvent.
        failure_reason:   Populated for PLACEMENT_BLOCKED / REVEAL_FAILED events.
        placed_order_id:  client_order_id of the most recently revealed slice.
        total_size:       Total order size.
        revealed_size:    Size placed on exchange so far.
        limit_price:      Limit price.
        created_at:       When the stealth order was first created.
        last_updated_at:  When the entry was last updated by a hook.
    """

    stealth_order_id: str
    product_id: str
    side: OrderSide
    product_type: ProductType
    status: StealthOrderStatus
    last_event: StealthLifecycleEvent
    total_size: float = 0.0
    revealed_size: float = 0.0
    limit_price: float = 0.0
    failure_reason: Optional[str] = None
    placed_order_id: Optional[str] = None
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for dashboard / API responses."""
        return {
            "stealth_order_id": self.stealth_order_id,
            "product_id": self.product_id,
            "side": self.side.value if isinstance(self.side, OrderSide) else self.side,
            "product_type": (
                self.product_type.value
                if isinstance(self.product_type, ProductType)
                else self.product_type
            ),
            "status": (
                self.status.value
                if isinstance(self.status, StealthOrderStatus)
                else self.status
            ),
            "last_event": (
                self.last_event.value
                if isinstance(self.last_event, StealthLifecycleEvent)
                else self.last_event
            ),
            "total_size": self.total_size,
            "revealed_size": self.revealed_size,
            "limit_price": self.limit_price,
            "failure_reason": self.failure_reason,
            "placed_order_id": self.placed_order_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_updated_at": (
                self.last_updated_at.isoformat() if self.last_updated_at else None
            ),
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _infer_product_type(product_id: str) -> ProductType:
    """Infer ProductType from product_id using the same logic as StateManager."""
    if product_id in SPOT_PRODUCT_IDS:
        return ProductType.SPOT
    if product_id in DERIVATIVES_PRODUCT_IDS:
        return ProductType.FUTURE
    if any(s in product_id for s in ("DEC", "JAN", "FEB", "MAR", "APR")):
        return ProductType.FUTURE
    return ProductType.SPOT


def _parse_side(raw: Any) -> OrderSide:
    """Coerce a raw side value (str or OrderSide) to OrderSide."""
    if isinstance(raw, OrderSide):
        return raw
    return OrderSide(str(raw).upper())


def _parse_stealth_status(raw: Any) -> StealthOrderStatus:
    """Coerce a raw status to StealthOrderStatus, defaulting to HIDDEN."""
    try:
        return StealthOrderStatus(str(raw).upper())
    except (ValueError, AttributeError):
        return StealthOrderStatus.HIDDEN


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class OrderInventory:
    """Aggregate working-order counts and stealth order lifecycle ledger.

    Maintains two independent stores under a single lock:
    - ``_exchange_orders``: Dict[_InventoryKey, OrderInventoryEntry]
    - ``_stealth_orders``: Dict[str, StealthInventoryEntry]

    Both are rebuilt from the database on startup via ``rebuild_from_database()``.
    Subsequent updates arrive through hook callbacks registered on the global
    OrderStateHookRegistry and StealthLifecycleHookRegistry singletons.

    See module docstring for startup wiring example.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._exchange_orders: Dict[_InventoryKey, OrderInventoryEntry] = {}
        self._stealth_orders: Dict[str, StealthInventoryEntry] = {}

    # ------------------------------------------------------------------
    # OrderStateHookRegistry callbacks
    # ------------------------------------------------------------------

    def on_order_opened(self, order: Order) -> None:
        """Hook: called when an order becomes working on the exchange.

        Increments the aggregate count for (product_id, side, product_type).
        Also tracks representative price and contract_size for notional calculation.
        Maintains weighted average price: avg_price = total_cost / total_size.
        Idempotent: duplicate client_order_ids are ignored.

        Notional exposure is calculated as: total_size × avg_price × contract_size
        - For SPOT: contract_size=1.0, notional = total_size × avg_price
        - For FUTURES: contract_size from product metadata, notional = contracts × price × multiplier

        Args:
            order: The Order that became working.
        """
        from configuration import ORDERBOOK, safe_float
        
        product_type = order.product_type or _infer_product_type(order.product_id)
        side = order.order_side
        key: _InventoryKey = (order.product_id, side, product_type)
        now = datetime.utcnow()

        # Get product metadata for contract_size
        product_data = ORDERBOOK.product.get(order.product_id, {})
        contract_size = 1.0
        if product_type == ProductType.FUTURE:
            future_details = product_data.get("future_product_details", {})
            contract_size = safe_float(future_details.get("contract_size"), default=1.0)

        # Get representative price for notional calculation
        order_price = safe_float(order.limit_price, default=0.0)
        if order_price == 0.0:
            order_price = safe_float(order.avg_price, default=0.0)

        with self._lock:
            entry = self._exchange_orders.get(key)
            if entry is None:
                entry = OrderInventoryEntry(
                    product_id=order.product_id,
                    side=side,
                    product_type=product_type,
                    contract_size=contract_size,
                    avg_price=order_price,
                    total_cost=0.0,
                )
                self._exchange_orders[key] = entry
            else:
                # Update contract_size if first time seeing it (or if it changed)
                if entry.contract_size == 1.0:
                    entry.contract_size = contract_size

            if order.client_order_id in entry.client_order_ids:
                return  # idempotent

            # Update total_cost and recalculate weighted average price
            order_cost = order.size * order_price
            entry.total_cost += order_cost
            entry.total_size += order.size
            if entry.total_size > 0:
                entry.avg_price = entry.total_cost / entry.total_size

            entry.client_order_ids.add(order.client_order_id)
            entry.count += 1
            if entry.first_placed_at is None:
                entry.first_placed_at = order.created_at or now
            entry.last_placed_at = order.created_at or now

    def on_order_closed(self, order: Order, event: OrderStateEvent) -> None:
        """Hook: called when a working order exits the exchange book.

        Decrements the aggregate count for (product_id, side, product_type).
        Updates weighted average price based on remaining orders: avg_price = total_cost / total_size.
        Idempotent: unknown client_order_ids are silently ignored.

        Args:
            order: The Order that closed.
            event: Why it closed (FILLED, CANCELLED, EXPIRED).
        """
        product_type = order.product_type or _infer_product_type(order.product_id)
        side = order.order_side
        key: _InventoryKey = (order.product_id, side, product_type)

        with self._lock:
            entry = self._exchange_orders.get(key)
            if entry is None:
                return
            if order.client_order_id not in entry.client_order_ids:
                return  # already removed or never tracked

            entry.client_order_ids.discard(order.client_order_id)
            entry.count = max(0, entry.count - 1)
            
            # Update total_cost proportionally as we remove size
            # Note: We don't know the original entry price for this order, so we use current avg_price
            # This is a best-effort estimate when closing orders incrementally
            if entry.total_size > 0:
                cost_to_remove = order.size * entry.avg_price
                entry.total_cost = max(0.0, entry.total_cost - cost_to_remove)
            
            entry.total_size = max(0.0, entry.total_size - order.size)

            # Refresh timestamps and price from remaining set (best effort)
            if entry.count == 0:
                entry.first_placed_at = None
                entry.last_placed_at = None
                entry.total_cost = 0.0
                entry.avg_price = 0.0  # No orders remaining, reset price

    # ------------------------------------------------------------------
    # StealthLifecycleHookRegistry callback
    # ------------------------------------------------------------------

    def on_stealth_transition(
        self,
        stealth_order_id: str,
        event: StealthLifecycleEvent,
        context: Dict[str, Any],
    ) -> None:
        """Hook: called on every stealth order lifecycle transition.

        Creates or updates the StealthInventoryEntry for ``stealth_order_id``.
        Maps ``StealthLifecycleEvent`` values to ``StealthOrderStatus`` values to
        keep the in-memory status aligned with the database.

        Args:
            stealth_order_id: UUID of the stealth order.
            event:            The lifecycle event.
            context:          Dict with product_id, side, size, etc. (see module docs).
        """
        now = datetime.utcnow()
        product_id = context.get("product_id", "")
        raw_side = context.get("side", "BUY")
        product_type = _infer_product_type(product_id)
        side = _parse_side(raw_side)

        # Map lifecycle event → order status
        _STATUS_MAP: Dict[StealthLifecycleEvent, StealthOrderStatus] = {
            StealthLifecycleEvent.CREATED:            StealthOrderStatus.HIDDEN,
            StealthLifecycleEvent.CONDITION_WATCHING: StealthOrderStatus.PENDING,
            StealthLifecycleEvent.CONDITION_RESET:    StealthOrderStatus.HIDDEN,
            StealthLifecycleEvent.CONDITION_MET:      StealthOrderStatus.TRIGGERED,
            StealthLifecycleEvent.REVEAL_ATTEMPTED:   StealthOrderStatus.TRIGGERED,
            StealthLifecycleEvent.PLACEMENT_BLOCKED:  StealthOrderStatus.TRIGGERED,
            StealthLifecycleEvent.REVEAL_FAILED:      StealthOrderStatus.ERROR,
            StealthLifecycleEvent.REVEAL_SUCCEEDED:   StealthOrderStatus.REVEALED,
            StealthLifecycleEvent.FILL_RECEIVED:      StealthOrderStatus.REVEALED,
            StealthLifecycleEvent.EXECUTED:           StealthOrderStatus.EXECUTED,
            StealthLifecycleEvent.CANCELLED:          StealthOrderStatus.CANCELLED,
        }
        new_status = _STATUS_MAP.get(event, StealthOrderStatus.HIDDEN)

        with self._lock:
            entry = self._stealth_orders.get(stealth_order_id)

            if entry is None:
                # First time we see this order — create entry
                entry = StealthInventoryEntry(
                    stealth_order_id=stealth_order_id,
                    product_id=product_id,
                    side=side,
                    product_type=product_type,
                    status=new_status,
                    last_event=event,
                    total_size=float(context.get("total_size", 0.0)),
                    revealed_size=float(context.get("size", 0.0)),
                    limit_price=float(context.get("limit_price", 0.0)),
                    created_at=context.get("timestamp") or now,
                    last_updated_at=now,
                )
                self._stealth_orders[stealth_order_id] = entry
            else:
                # Update existing entry
                entry.status = new_status
                entry.last_event = event
                entry.last_updated_at = now

                if event == StealthLifecycleEvent.REVEAL_SUCCEEDED:
                    entry.revealed_size += float(context.get("size", 0.0))
                    entry.placed_order_id = context.get("placed_order_id")
                    entry.failure_reason = None  # clear any prior failure

                elif event in (
                    StealthLifecycleEvent.PLACEMENT_BLOCKED,
                    StealthLifecycleEvent.REVEAL_FAILED,
                ):
                    entry.failure_reason = context.get("failure_reason")

                elif event == StealthLifecycleEvent.FILL_RECEIVED:
                    entry.revealed_size += float(context.get("size", 0.0))

    # ------------------------------------------------------------------
    # Query — exchange-visible working orders
    # ------------------------------------------------------------------

    def get_count(
        self,
        product_id: str,
        side: OrderSide,
        product_type: ProductType,
    ) -> int:
        """Return the number of working exchange orders for the given bucket.

        Args:
            product_id:   Trading pair.
            side:         OrderSide.BUY or OrderSide.SELL.
            product_type: ProductType.SPOT or ProductType.FUTURE.

        Returns:
            Integer count (0 if no entry exists for this bucket).

        Example:
            >>> inv.get_count('BTC-USDC', OrderSide.BUY, ProductType.SPOT)
            3
        """
        with self._lock:
            entry = self._exchange_orders.get((product_id, side, product_type))
            return entry.count if entry else 0

    def get_entry(
        self,
        product_id: str,
        side: OrderSide,
        product_type: ProductType,
    ) -> Optional[OrderInventoryEntry]:
        """Return the full OrderInventoryEntry for the given bucket, or None.

        Args:
            product_id:   Trading pair.
            side:         OrderSide.BUY or OrderSide.SELL.
            product_type: ProductType.SPOT or ProductType.FUTURE.

        Returns:
            OrderInventoryEntry or None.
        """
        with self._lock:
            return self._exchange_orders.get((product_id, side, product_type))

    def get_for_product(self, product_id: str) -> List[OrderInventoryEntry]:
        """Return all inventory entries for a given product across all sides/types.

        Args:
            product_id: Trading pair.

        Returns:
            List of OrderInventoryEntry (may be empty).

        Example:
            >>> inv.get_for_product('BTC-USDC')
            [OrderInventoryEntry(side=BUY, count=2), OrderInventoryEntry(side=SELL, count=1)]
        """
        with self._lock:
            return [e for k, e in self._exchange_orders.items() if k[0] == product_id]

    def get_all(self) -> List[OrderInventoryEntry]:
        """Return all exchange working-order inventory entries.

        Returns:
            List of all OrderInventoryEntry objects.
        """
        with self._lock:
            return list(self._exchange_orders.values())

    def get_total_open_count(self) -> int:
        """Return the total number of working orders across all products.

        Returns:
            Sum of count across all inventory entries.

        Example:
            >>> inv.get_total_open_count()
            7
        """
        with self._lock:
            return sum(e.count for e in self._exchange_orders.values())

    # ------------------------------------------------------------------
    # Query — stealth orders
    # ------------------------------------------------------------------

    def get_stealth_entry(self, stealth_order_id: str) -> Optional[StealthInventoryEntry]:
        """Return the inventory entry for a specific stealth order.

        Args:
            stealth_order_id: UUID of the stealth order.

        Returns:
            StealthInventoryEntry or None.
        """
        with self._lock:
            return self._stealth_orders.get(stealth_order_id)

    def get_stealth_by_status(
        self, status: StealthOrderStatus
    ) -> List[StealthInventoryEntry]:
        """Return all stealth inventory entries with the given status.

        Args:
            status: StealthOrderStatus to filter by.

        Returns:
            List of matching StealthInventoryEntry objects.

        Example:
            >>> inv.get_stealth_by_status(StealthOrderStatus.REVEALED)
            [StealthInventoryEntry(...), ...]
        """
        with self._lock:
            return [e for e in self._stealth_orders.values() if e.status == status]

    def get_stealth_pending(self) -> List[StealthInventoryEntry]:
        """Return stealth orders not yet revealed (HIDDEN or PENDING status).

        These are orders that exist only internally — not on the exchange books.

        Returns:
            List of StealthInventoryEntry with HIDDEN or PENDING status.
        """
        with self._lock:
            return [
                e
                for e in self._stealth_orders.values()
                if e.status in (StealthOrderStatus.HIDDEN, StealthOrderStatus.PENDING)
            ]

    def get_stealth_triggered(self) -> List[StealthInventoryEntry]:
        """Return stealth orders whose condition is met but not yet placed.

        These are in TRIGGERED status — condition confirmed, awaiting reveal attempt.

        Returns:
            List of StealthInventoryEntry with TRIGGERED status.
        """
        with self._lock:
            return [
                e
                for e in self._stealth_orders.values()
                if e.status == StealthOrderStatus.TRIGGERED
            ]

    def get_stealth_on_exchange(self) -> List[StealthInventoryEntry]:
        """Return stealth orders that have been revealed to the exchange (REVEALED status).

        These are already contributing to the exchange-visible working order count.

        Returns:
            List of StealthInventoryEntry with REVEALED status.
        """
        with self._lock:
            return [
                e
                for e in self._stealth_orders.values()
                if e.status == StealthOrderStatus.REVEALED
            ]

    def get_stealth_failures(self) -> List[StealthInventoryEntry]:
        """Return stealth orders that failed to be placed, with their failure reason.

        Includes entries whose last event was PLACEMENT_BLOCKED or REVEAL_FAILED.
        A pre-REST PLACEMENT_BLOCKED entry remains TRIGGERED/retriable; a REST
        REVEAL_FAILED entry is terminal ERROR and is not automatically retried.

        Returns:
            List of StealthInventoryEntry with a non-None failure_reason.
        """
        with self._lock:
            return [
                e
                for e in self._stealth_orders.values()
                if e.failure_reason is not None
            ]

    def get_all_stealth(self) -> Dict[str, StealthInventoryEntry]:
        """Return the complete stealth order inventory dict (copy).

        Returns:
            Dict mapping stealth_order_id → StealthInventoryEntry.
        """
        with self._lock:
            return dict(self._stealth_orders)

    def get_stealth_count_by_product(
        self, product_id: str, status: Optional[StealthOrderStatus] = None
    ) -> int:
        """Return the number of stealth orders for a product, optionally filtered by status.

        Args:
            product_id: Trading pair to filter by.
            status:     Optional StealthOrderStatus filter. If None, counts all statuses.

        Returns:
            Integer count.

        Example:
            >>> inv.get_stealth_count_by_product('BTC-USDC', StealthOrderStatus.HIDDEN)
            2
        """
        with self._lock:
            return sum(
                1
                for e in self._stealth_orders.values()
                if e.product_id == product_id
                and (status is None or e.status == status)
            )

    # ------------------------------------------------------------------
    # Snapshot for dashboard / API
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Return a complete JSON-safe snapshot of the entire inventory.

        Suitable for dashboard WebSocket broadcast or REST API responses.

        Returns:
            Dict with 'exchange_orders' and 'stealth_orders' sections.

        Example:
            >>> summary = inv.get_summary()
            >>> summary['exchange_orders']
            [{'product_id': 'BTC-USDC', 'side': 'BUY', 'count': 2, ...}]
        """
        with self._lock:
            return {
                "exchange_orders": [e.to_dict() for e in self._exchange_orders.values()],
                "stealth_orders": [e.to_dict() for e in self._stealth_orders.values()],
                "total_open_count": sum(
                    e.count for e in self._exchange_orders.values()
                ),
                "stealth_counts": {
                    s.value: sum(
                        1
                        for e in self._stealth_orders.values()
                        if e.status == s
                    )
                    for s in StealthOrderStatus
                },
            }

    # ------------------------------------------------------------------
    # Database rebuild (called once on startup, before hooks are wired)
    # ------------------------------------------------------------------

    def rebuild_from_database(self, db_client) -> None:
        """Repopulate in-memory inventory from the database after a restart.

        Reads:
        - ``order_parent WHERE status IN ('OPEN','PENDING')`` for exchange working orders.
        - ``stealth_orders`` for stealth lifecycle entries (all non-empty statuses).

        Reconstructs contract_size and avg_price from product metadata and order data.
        Maintains weighted average: avg_price = total_cost / total_size.
        For notional calculation: total_size × avg_price × contract_size

        This method is intentionally NOT protected by ``_lock`` because it is
        expected to run from the startup/main thread before any hook callbacks
        begin firing. If called from a live thread, acquire the lock externally.

        Args:
            db_client: PostgresDB instance.

        Returns:
            None.  Mutates internal state directly.

        Raises:
            Does not raise; logs errors and continues with partial state.

        Example:
            >>> inventory.rebuild_from_database(db_client)
            INFO [OrderInventory] Rebuilt 4 working exchange orders, 7 stealth entries
        """
        from configuration import ORDERBOOK, safe_float
        
        exchange_count = 0
        stealth_count = 0

        # ---- Rebuild exchange-visible working orders ----
        try:
            rows = db_client.execute_query(
                """
                SELECT client_order_id, product_id, side, size, price, status, created_at
                FROM   order_parent
                WHERE  status IN ('OPEN', 'PENDING', 'open', 'pending')
                """
            )
            for row in rows:
                try:
                    product_id = row["product_id"]
                    side = _parse_side(row["side"])
                    product_type = _infer_product_type(product_id)
                    key: _InventoryKey = (product_id, side, product_type)
                    size = float(row.get("size") or 0.0)
                    order_price = safe_float(row.get("price"), default=0.0)
                    client_order_id = str(row["client_order_id"])
                    created_at = row.get("created_at")

                    # Get contract_size from product metadata
                    product_data = ORDERBOOK.product.get(product_id, {})
                    contract_size = 1.0
                    if product_type == ProductType.FUTURE:
                        future_details = product_data.get("future_product_details", {})
                        contract_size = safe_float(future_details.get("contract_size"), default=1.0)

                    entry = self._exchange_orders.get(key)
                    if entry is None:
                        entry = OrderInventoryEntry(
                            product_id=product_id,
                            side=side,
                            product_type=product_type,
                            contract_size=contract_size,
                            total_cost=0.0,
                            avg_price=0.0,
                        )
                        self._exchange_orders[key] = entry
                    else:
                        # Update contract_size if first time seeing it
                        if entry.contract_size == 1.0:
                            entry.contract_size = contract_size

                    if client_order_id not in entry.client_order_ids:
                        # Add to total_cost and recalculate weighted average
                        order_cost = size * order_price
                        entry.total_cost += order_cost
                        entry.total_size += size
                        if entry.total_size > 0:
                            entry.avg_price = entry.total_cost / entry.total_size

                        entry.client_order_ids.add(client_order_id)
                        entry.count += 1
                        if entry.first_placed_at is None:
                            entry.first_placed_at = created_at
                        entry.last_placed_at = created_at
                    exchange_count += 1
                except Exception as row_exc:
                    logger.warning(
                        f"[OrderInventory] Skipping malformed order_parent row: {row_exc}"
                    )
        except Exception as exc:
            logger.error(f"[OrderInventory] Failed to rebuild exchange orders: {exc}")

        # ---- Rebuild stealth lifecycle entries ----
        try:
            rows = db_client.execute_query(
                """
                SELECT stealth_order_id, product_id, side, status,
                       total_size, revealed_size, limit_price,
                       last_lifecycle_event, failure_reason,
                       created_at, updated_at
                FROM   stealth_orders
                """
            )
            for row in rows:
                try:
                    oid = str(row["stealth_order_id"])
                    product_id = row["product_id"]
                    side = _parse_side(row["side"])
                    product_type = _infer_product_type(product_id)
                    status = _parse_stealth_status(row.get("status", "HIDDEN"))

                    # last_lifecycle_event column added by migration; may be NULL
                    raw_event = row.get("last_lifecycle_event")
                    try:
                        last_event = StealthLifecycleEvent(raw_event) if raw_event else StealthLifecycleEvent.CREATED
                    except ValueError:
                        last_event = StealthLifecycleEvent.CREATED

                    entry = StealthInventoryEntry(
                        stealth_order_id=oid,
                        product_id=product_id,
                        side=side,
                        product_type=product_type,
                        status=status,
                        last_event=last_event,
                        total_size=float(row.get("total_size") or 0.0),
                        revealed_size=float(row.get("revealed_size") or 0.0),
                        limit_price=float(row.get("limit_price") or 0.0),
                        failure_reason=row.get("failure_reason"),
                        created_at=row.get("created_at"),
                        last_updated_at=row.get("updated_at"),
                    )
                    self._stealth_orders[oid] = entry
                    stealth_count += 1
                except Exception as row_exc:
                    logger.warning(
                        f"[OrderInventory] Skipping malformed stealth_orders row: {row_exc}"
                    )
        except Exception as exc:
            logger.error(f"[OrderInventory] Failed to rebuild stealth entries: {exc}")

        logger.info(
            f"[OrderInventory] Rebuilt {exchange_count} working exchange orders, "
            f"{stealth_count} stealth entries"
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_inventory: Optional[OrderInventory] = None
_inventory_lock = threading.RLock()


def get_global_order_inventory() -> OrderInventory:
    """Return the process-wide OrderInventory singleton.

    Thread-safe double-checked locking.

    Returns:
        The global OrderInventory instance.

    Example:
        >>> inv = get_global_order_inventory()
        >>> inv.get_count('BTC-USDC', OrderSide.BUY, ProductType.SPOT)
        2
    """
    global _global_inventory
    if _global_inventory is None:
        with _inventory_lock:
            if _global_inventory is None:
                _global_inventory = OrderInventory()
    return _global_inventory


def reset_global_order_inventory() -> None:
    """Reset the global inventory singleton (for test teardown).

    Clears all in-memory state.

    Example:
        >>> reset_global_order_inventory()
    """
    global _global_inventory
    with _inventory_lock:
        _global_inventory = None
