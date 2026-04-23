"""PostgreSQL implementation of OrderRepository.

Wraps the existing database.order module to provide a clean repository interface.
This allows the database implementation details to be hidden from business logic.

Usage:
    >>> from database.database import PostgresDB
    >>> from data.repositories.postgres import PostgresOrderRepository
    >>> 
    >>> db = PostgresDB()
    >>> repo = PostgresOrderRepository(db)
    >>> 
    >>> # Use standard repository interface
    >>> order = repo.get_order('my_order_id')
    >>> all_orders = repo.get_all_orders()
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from database.database import PostgresDB
from database.order import (
    get_parent_order,
    get_parent_orders,
    insert_order_parent,
    update_order_parent_status
)
from core.models import Order
from core.enums import OrderStatus


class PostgresOrderRepository:
    """PostgreSQL implementation of OrderRepository.
    
    Wraps database.order module to provide a clean interface for order
    persistence operations.
    """
    
    def __init__(self, db: PostgresDB):
        """Initialize with database connection.
        
        Args:
            db: PostgresDB instance for database access
        
        Raises:
            ValueError: If db is None
        """
        if db is None:
            raise ValueError("db cannot be None")
        self._db = db
    
    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve a single order by client_order_id.
        
        Note: Current implementation queries parent orders only.
        Future enhancement: Query both parent and child orders.
        
        Args:
            client_order_id: The client-specified order ID
        
        Returns:
            Order instance if found, None if not found
        
        Raises:
            Exception: If database access fails
        """
        # Query parent orders table
        parent = get_parent_order(client_order_id)
        if parent:
            return Order(
                client_order_id=parent.get("client_order_id"),
                product_id=parent.get("product_id"),
                order_side=parent.get("side"),
                status=OrderStatus.PENDING,
                size=float(parent.get("size", 0)),
                price=float(parent.get("price", 0))
            )
        
        # Query child orders table
        children = get_child_orders(client_order_id)
        if children:
            child = children[0]
            return Order(
                client_order_id=child.get("client_order_id"),
                product_id=child.get("product_id"),
                order_side=child.get("side"),
                status=OrderStatus.PENDING,
                size=float(child.get("size", 0)),
                price=float(child.get("price", 0))
            )
        
        return None
    
    def get_all_orders(self) -> List[Order]:
        """Retrieve all orders.
        
        Returns:
            List of all Order instances (combines parent and child orders)
        
        Raises:
            Exception: If database access fails
        """
        # Get all parent orders
        parents = self._get_all_parent_orders()
        
        # Convert to Order instances
        orders = [
            Order(
                client_order_id=p.get("client_order_id"),
                product_id=p.get("product_id"),
                order_side=p.get("side"),
                status=OrderStatus.PENDING,
                size=float(p.get("size", 0)),
                price=float(p.get("price", 0))
            )
            for p in parents
        ]
        
        return orders
    
    def get_orders_by_product(self, product_id: str) -> List[Order]:
        """Retrieve all orders for a specific product.
        
        Args:
            product_id: The product ID (e.g., 'BTC-USDC')
        
        Returns:
            List of Order instances for that product
        
        Raises:
            Exception: If database access fails
        """
        all_orders = self.get_all_orders()
        return [o for o in all_orders if o.product_id == product_id]
    
    def get_orders_by_status(self, status: str) -> List[Order]:
        """Retrieve all orders with a specific status.
        
        Note: Current database schema stores parent order status.
        
        Args:
            status: Order status (e.g., 'OPEN', 'FILLED', 'CANCELLED')
        
        Returns:
            List of Order instances with that status
        
        Raises:
            Exception: If database access fails
        """
        all_orders = self.get_all_orders()
        return [o for o in all_orders if o.status.value == status]
    
    def save_order(self, order: Order) -> None:
        """Save or update an order.
        
        Saves to parent orders table. For follow-up orders, use save_child_order.
        
        Args:
            order: The Order instance to save
        
        Raises:
            ValueError: If order is missing required fields
            Exception: If database access fails
        """
        if not order.client_order_id or not order.product_id:
            raise ValueError("Order must have client_order_id and product_id")
        
        insert_order_parent(
            db=self._db,
            client_order_id=order.client_order_id,
            product_id=order.product_id,
            side=order.order_side.value if order.order_side else "BUY",
            size=str(order.size) if order.size else "0",
            price=str(order.price) if order.price else "0",
            target_movement=None,
            max_order_replacement=None,
            current_order_replacement=0,
            status=OrderStatus.PENDING.value
        )
    
    def save_parent_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        size: float,
        price: float,
        target_movement: Optional[Dict[str, Any]] = None,
        max_order_replacement: Optional[int] = None
    ) -> int:
        """Save a parent order record.
        
        Args:
            client_order_id: Client-specified ID
            product_id: Trading pair
            side: 'BUY' or 'SELL'
            size: Order size
            price: Order price
            target_movement: Target movement configuration (optional)
            max_order_replacement: Max replacement count (optional)
        
        Returns:
            The parent order ID (for linking child orders)
        
        Raises:
            Exception: If database access fails
        """
        parent_id = insert_order_parent(
            db=self._db,
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=str(size),
            price=str(price),
            target_movement=target_movement,
            max_order_replacement=max_order_replacement,
            current_order_replacement=0,
            status=OrderStatus.PENDING.value
        )
        return parent_id
    
    def get_parent_orders(self) -> List[Dict[str, Any]]:
        """Retrieve all parent orders.
        
        Returns:
            List of parent order records as dictionaries
        
        Raises:
            Exception: If database access fails
        """
        return self._get_all_parent_orders()
    
    def update_order_status(self, client_order_id: str, status: str) -> None:
        """Update the status of an order.
        
        Args:
            client_order_id: The order ID
            status: New status value
        
        Raises:
            Exception: If database access fails
        """
        update_order_parent_status(
            db=self._db,
            client_order_id=client_order_id,
            status=status
        )
    
    def delete_order(self, client_order_id: str) -> None:
        """Delete an order record.
        
        Note: Current implementation doesn't support deletion.
        Use update_order_status to mark as cancelled instead.
        
        Args:
            client_order_id: The order ID to delete
        
        Raises:
            NotImplementedError: Deletion not supported
        """
        raise NotImplementedError("Use update_order_status to mark as cancelled instead")
    
    # ========================================================================
    # Private Helper Methods
    # ========================================================================
    
    def _get_all_parent_orders(self) -> List[Dict[str, Any]]:
        """Get all parent orders from database.
        
        Internal helper method.
        
        Returns:
            List of parent order records as dictionaries
        """
        return get_parent_orders()
