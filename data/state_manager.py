"""State management with dependency injection.

The StateManager replaces the global OrderBook singleton. It manages:
- Order tracking (filled, cancelled, active)
- Position tracking (futures positions)
- Profit configuration per product
- Subscription configuration

Unlike the original OrderBook, StateManager:
- Is not a global singleton (injected via DI)
- Accepts repositories and external clients as dependencies
- Has clear ownership of state mutations
- Is testable with mock repositories

Usage:
    >>> from data.state_manager import StateManager
    >>> from data.repositories import PostgresOrderRepository
    >>> 
    >>> state = StateManager(
    ...     order_repo=order_repo,
    ...     profit_config={'BTC-USDC': {'BUY': 0.004}}
    ... )
    >>> 
    >>> state.update_order_filled(order)
    >>> position = state.get_position('BTC-USDC')
"""

from typing import Dict, Optional, List, Any, Set
from threading import Lock
from core.models import Order, Position
from core.enums import OrderStatus
from core.constants import SPOT_PRODUCT_IDS, DERIVATIVES_PRODUCT_IDS


class StateManager:
    """Manages trading state without global singletons.
    
    Replaces the OrderBook singleton with a properly injected, testable
    state management class. Maintains order and position tracking with
    thread-safe mutations.
    """
    
    def __init__(
        self,
        order_repo=None,
        profit_config: Optional[Dict[str, Any]] = None,
        product_config: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """Initialize StateManager.
        
        Args:
            order_repo: OrderRepository instance (optional for in-memory mode)
            profit_config: Profit targets by product or type
                          Structure: {'BTC-USDC': {'BUY': 0.004, 'SELL': 0.004}, ...}
                          Or: {'SPOT': {'BUY': 0.004, 'SELL': 0.004}, ...}
            product_config: Product metadata (increments, min sizes, etc.)
        
        Examples:
            >>> state = StateManager(
            ...     order_repo=repo,
            ...     profit_config={
            ...         'BTC-USDC': {'BUY': 0.004, 'SELL': 0.004},
            ...         'SPOT': {'BUY': 0.002, 'SELL': 0.002},
            ...     }
            ... )
        """
        self._order_repo = order_repo
        self._lock = Lock()
        
        # In-memory order tracking
        self._filled_orders: Dict[str, Order] = {}
        self._cancelled_orders: Dict[str, Order] = {}
        self._active_orders: Dict[str, Order] = {}
        
        # Position tracking
        self._positions: Dict[str, Position] = {}
        
        # Configuration
        self._profit_config = profit_config or {}
        self._product_config = product_config or {}
        
        # Subscription tracking
        self._subscribed_products: Set[str] = set()
        self._subscribed_channels: Set[str] = set()
    
    # ========================================================================
    # Order Tracking
    # ========================================================================
    
    def add_active_order(self, order: Order) -> None:
        """Track an active (open) order.
        
        Args:
            order: The Order instance to track
        
        Examples:
            >>> state.add_active_order(order)
        """
        with self._lock:
            self._active_orders[order.client_order_id] = order
            if self._order_repo:
                self._order_repo.save_order(order)
    
    def mark_order_filled(self, order: Order) -> None:
        """Mark an order as filled and remove from active.
        
        Args:
            order: The Order instance that was filled
        
        Examples:
            >>> state.mark_order_filled(order)
        """
        with self._lock:
            client_id = order.client_order_id
            
            # Remove from active
            self._active_orders.pop(client_id, None)
            
            # Add to filled
            self._filled_orders[client_id] = order
            
            # Update repository
            if self._order_repo:
                self._order_repo.update_order_status(client_id, 'FILLED')
    
    def mark_order_cancelled(self, order: Order) -> None:
        """Mark an order as cancelled and remove from active.
        
        Args:
            order: The Order instance that was cancelled
        
        Examples:
            >>> state.mark_order_cancelled(order)
        """
        with self._lock:
            client_id = order.client_order_id
            
            # Remove from active
            self._active_orders.pop(client_id, None)
            
            # Add to cancelled
            self._cancelled_orders[client_id] = order
            
            # Update repository
            if self._order_repo:
                self._order_repo.update_order_status(client_id, 'CANCELLED')
    
    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve an order from any state (active, filled, cancelled).
        
        Args:
            client_order_id: The order ID to find
        
        Returns:
            The Order instance, or None if not found
        
        Examples:
            >>> order = state.get_order('order_123')
        """
        with self._lock:
            # Check in order: active, filled, cancelled
            if client_order_id in self._active_orders:
                return self._active_orders[client_order_id]
            if client_order_id in self._filled_orders:
                return self._filled_orders[client_order_id]
            if client_order_id in self._cancelled_orders:
                return self._cancelled_orders[client_order_id]
            
            # Fall back to repository
            if self._order_repo:
                return self._order_repo.get_order(client_order_id)
            
            return None
    
    def get_active_orders(self) -> Dict[str, Order]:
        """Get all currently active orders.
        
        Returns:
            Dictionary of active Order instances
        
        Examples:
            >>> active = state.get_active_orders()
            >>> print(f"{len(active)} orders still open")
        """
        with self._lock:
            return dict(self._active_orders)
    
    def get_filled_orders(self) -> Dict[str, Order]:
        """Get all filled orders.
        
        Returns:
            Dictionary of filled Order instances
        
        Examples:
            >>> filled = state.get_filled_orders()
        """
        with self._lock:
            return dict(self._filled_orders)
    
    def get_cancelled_orders(self) -> Dict[str, Order]:
        """Get all cancelled orders.
        
        Returns:
            Dictionary of cancelled Order instances
        
        Examples:
            >>> cancelled = state.get_cancelled_orders()
        """
        with self._lock:
            return dict(self._cancelled_orders)
    
    # ========================================================================
    # Position Tracking
    # ========================================================================
    
    def update_position(self, product_id: str, position: Position) -> None:
        """Update a position (futures).
        
        Args:
            product_id: The product ID
            position: The Position instance
        
        Examples:
            >>> state.update_position('BIP-20DEC30-CDE', position)
        """
        with self._lock:
            self._positions[product_id] = position
    
    def get_position(self, product_id: str) -> Optional[Position]:
        """Get a position by product ID.
        
        Args:
            product_id: The product ID
        
        Returns:
            Position instance if exists, None otherwise
        
        Examples:
            >>> pos = state.get_position('BIP-20DEC30-CDE')
            >>> if pos:
            ...     print(f"Contracts: {pos.number_of_contracts}")
        """
        with self._lock:
            return self._positions.get(product_id)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions.
        
        Returns:
            Dictionary mapping product_id to Position
        
        Examples:
            >>> all_positions = state.get_all_positions()
        """
        with self._lock:
            return dict(self._positions)
    
    # ========================================================================
    # Configuration Access
    # ========================================================================
    
    def get_profit_config(self, product_id: str) -> Dict[str, float]:
        """Get profit configuration for a product.
        
        Implements fallback: product-specific → product type → default
        
        Args:
            product_id: The product ID (e.g., 'BTC-USDC')
        
        Returns:
            Dictionary with 'BUY' and 'SELL' profit targets
        
        Examples:
            >>> config = state.get_profit_config('BTC-USDC')
            >>> buy_profit = config['BUY']  # e.g., 0.004
        """
        # Try product-specific config
        if product_id in self._profit_config:
            return self._profit_config[product_id]
        
        # Try product type (SPOT or FUTURE)
        product_type = self._infer_product_type(product_id)
        if product_type in self._profit_config:
            return self._profit_config[product_type]
        
        # Default fallback
        return {'BUY': 0.002, 'SELL': 0.002}
    
    def set_profit_config(
        self,
        product_id: str,
        buy_profit: float,
        sell_profit: float
    ) -> None:
        """Set profit configuration for a product.
        
        Args:
            product_id: The product ID
            buy_profit: Profit target for BUY orders (e.g., 0.004 for 0.4%)
            sell_profit: Profit target for SELL orders
        
        Examples:
            >>> state.set_profit_config('BTC-USDC', 0.004, 0.004)
        """
        with self._lock:
            self._profit_config[product_id] = {
                'BUY': buy_profit,
                'SELL': sell_profit
            }
    
    def get_product_config(self, product_id: str) -> Dict[str, Any]:
        """Get product configuration (increments, min sizes, etc.).
        
        Args:
            product_id: The product ID
        
        Returns:
            Dictionary with product metadata
        
        Examples:
            >>> config = state.get_product_config('BTC-USDC')
            >>> price_increment = config.get('price_increment')
        """
        with self._lock:
            return self._product_config.get(product_id, {})
    
    def set_product_config(self, product_id: str, config: Dict[str, Any]) -> None:
        """Set product configuration.
        
        Args:
            product_id: The product ID
            config: Configuration dictionary
        
        Examples:
            >>> state.set_product_config('BTC-USDC', {
            ...     'price_increment': '1',
            ...     'base_increment': '0.001'
            ... })
        """
        with self._lock:
            self._product_config[product_id] = config
    
    # ========================================================================
    # Subscription Tracking
    # ========================================================================
    
    def add_subscription(self, product_id: str, channel: str) -> None:
        """Track a WebSocket subscription.
        
        Args:
            product_id: The product ID
            channel: The channel name (e.g., 'ticker', 'level2')
        
        Examples:
            >>> state.add_subscription('BTC-USDC', 'ticker')
        """
        with self._lock:
            self._subscribed_products.add(product_id)
            self._subscribed_channels.add(channel)
    
    def get_subscribed_products(self) -> Set[str]:
        """Get all subscribed products.
        
        Returns:
            Set of product IDs
        
        Examples:
            >>> products = state.get_subscribed_products()
        """
        with self._lock:
            return set(self._subscribed_products)
    
    def get_subscribed_channels(self) -> Set[str]:
        """Get all subscribed channels.
        
        Returns:
            Set of channel names
        
        Examples:
            >>> channels = state.get_subscribed_channels()
        """
        with self._lock:
            return set(self._subscribed_channels)
    
    # ========================================================================
    # Statistics & Reporting
    # ========================================================================
    
    def get_order_stats(self) -> Dict[str, int]:
        """Get order statistics.
        
        Returns:
            Dictionary with counts of orders in each state
        
        Examples:
            >>> stats = state.get_order_stats()
            >>> print(f"Active: {stats['active']}, Filled: {stats['filled']}")
        """
        with self._lock:
            return {
                'active': len(self._active_orders),
                'filled': len(self._filled_orders),
                'cancelled': len(self._cancelled_orders),
                'total': len(self._active_orders) + len(self._filled_orders) + len(self._cancelled_orders)
            }
    
    # ========================================================================
    # Private Helper Methods
    # ========================================================================
    
    def _infer_product_type(self, product_id: str) -> str:
        """Infer if product is SPOT or FUTURE from ID.
        
        Args:
            product_id: The product ID
        
        Returns:
            'SPOT' or 'FUTURE'
        """
        if product_id in SPOT_PRODUCT_IDS:
            return 'SPOT'
        if product_id in DERIVATIVES_PRODUCT_IDS:
            return 'FUTURE'
        
        # Fallback: check for futures suffix patterns
        if any(suffix in product_id for suffix in ['DEC', 'JAN', 'FEB', 'MAR', 'APR']):
            return 'FUTURE'
        
        return 'SPOT'
