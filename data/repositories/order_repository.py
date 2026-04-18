"""Order repository interface and implementations.

Defines the abstraction layer for order data access. The OrderRepository
protocol defines what operations must be supported for order persistence.

Implementations can use any backend (PostgreSQL, SQLite, in-memory, etc.)
without affecting business logic.

Usage:
    >>> from data.repositories import OrderRepository
    >>> from data.repositories.postgres import PostgresOrderRepository
    >>> 
    >>> # Inject the repository into business logic
    >>> repo = PostgresOrderRepository(db_connection)
    >>> engine = OrderEngine(order_repo=repo)
    >>> 
    >>> # Or use a mock in tests
    >>> mock_repo = MockOrderRepository()
    >>> engine = OrderEngine(order_repo=mock_repo)
"""

from typing import Protocol, List, Dict, Optional, Any
from datetime import datetime
from core.models import Order


class OrderRepository(Protocol):
    """Interface for order persistence operations.
    
    Defines the contract for any order storage backend. Implementations
    must support these operations but can use any underlying storage.
    """
    
    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve a single order by client_order_id.
        
        Args:
            client_order_id: The client-specified order ID
        
        Returns:
            Order instance if found, None if not found
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> order = repo.get_order('my_order_123')
            >>> if order:
            ...     print(f"Status: {order.status}")
        """
        ...
    
    def get_all_orders(self) -> List[Order]:
        """Retrieve all orders.
        
        Returns:
            List of all Order instances (may be empty)
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> all_orders = repo.get_all_orders()
            >>> open_orders = [o for o in all_orders if o.status == OrderStatus.OPEN]
        """
        ...
    
    def get_orders_by_product(self, product_id: str) -> List[Order]:
        """Retrieve all orders for a specific product.
        
        Args:
            product_id: The product ID (e.g., 'BTC-USDC')
        
        Returns:
            List of Order instances for that product
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> btc_orders = repo.get_orders_by_product('BTC-USDC')
        """
        ...
    
    def get_orders_by_status(self, status: str) -> List[Order]:
        """Retrieve all orders with a specific status.
        
        Args:
            status: Order status (e.g., 'OPEN', 'FILLED', 'CANCELLED')
        
        Returns:
            List of Order instances with that status
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> filled = repo.get_orders_by_status('FILLED')
        """
        ...
    
    def save_order(self, order: Order) -> None:
        """Save or update an order.
        
        If the order already exists (by client_order_id), updates it.
        Otherwise creates a new record.
        
        Args:
            order: The Order instance to save
        
        Raises:
            ValueError: If order is missing required fields
            Exception: If database access fails
        
        Examples:
            >>> order = Order(client_order_id='test', product_id='BTC-USDC', ...)
            >>> repo.save_order(order)
        """
        ...
    
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
        
        Parent orders track the original order specification that may spawn
        multiple follow-up orders. Useful for reconciliation and analysis.
        
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
        
        Examples:
            >>> parent_id = repo.save_parent_order(
            ...     client_order_id='parent_123',
            ...     product_id='BTC-USDC',
            ...     side='BUY',
            ...     size=0.5,
            ...     price=40000.0
            ... )
            >>> print(f"Parent ID: {parent_id}")
        """
        ...
    
    def save_child_order(
        self,
        parent_order_id: int,
        client_order_id: str,
        product_id: str,
        side: str,
        size: float,
        price: float,
        replacement_order_number: int = 0
    ) -> int:
        """Save a child (follow-up) order record.
        
        Links follow-up orders to their parent, tracking the replacement chain.
        
        Args:
            parent_order_id: The parent order ID (from save_parent_order)
            client_order_id: Child order's client ID
            product_id: Trading pair
            side: 'BUY' or 'SELL'
            size: Order size
            price: Order price
            replacement_order_number: Replacement number in the sequence
        
        Returns:
            The child order ID (for further updates)
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> child_id = repo.save_child_order(
            ...     parent_order_id=1,
            ...     client_order_id='child_001',
            ...     product_id='BTC-USDC',
            ...     side='SELL',
            ...     size=0.5,
            ...     price=40160.0,
            ...     replacement_order_number=1
            ... )
        """
        ...
    
    def get_parent_orders(self) -> List[Dict[str, Any]]:
        """Retrieve all parent orders.
        
        Returns:
            List of parent order records
        
        Raises:
            Exception: If database access fails
        """
        ...
    
    def get_children_of_parent(self, parent_order_id: int) -> List[Dict[str, Any]]:
        """Retrieve all child orders for a parent.
        
        Args:
            parent_order_id: The parent order ID
        
        Returns:
            List of child order records
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> children = repo.get_children_of_parent(1)
            >>> print(f"Parent {1} has {len(children)} follow-ups")
        """
        ...
    
    def update_order_status(self, client_order_id: str, status: str) -> None:
        """Update the status of an order.
        
        Args:
            client_order_id: The order ID
            status: New status value
        
        Raises:
            Exception: If database access fails
        
        Examples:
            >>> repo.update_order_status('order_123', 'FILLED')
        """
        ...
    
    def delete_order(self, client_order_id: str) -> None:
        """Delete an order record.
        
        Use with caution - hard delete removes history.
        
        Args:
            client_order_id: The order ID to delete
        
        Raises:
            Exception: If database access fails
        """
        ...
