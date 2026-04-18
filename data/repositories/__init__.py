"""Data access layer - Repositories for persistence.

This module provides clean abstractions for data persistence:
- OrderRepository: Protocol interface for order storage
- PostgresOrderRepository: PostgreSQL implementation

Using the repository pattern allows:
- Easy testing with mock repositories
- Swapping database implementations
- Clear separation of concerns
- Business logic independent of storage

Usage:
    >>> from data.repositories import OrderRepository
    >>> from data.repositories.postgres import PostgresOrderRepository
    >>> from database.database import PostgresDB
    >>> 
    >>> # Create database connection
    >>> db = PostgresDB()
    >>> 
    >>> # Create repository
    >>> repo = PostgresOrderRepository(db)
    >>> 
    >>> # Use in business logic
    >>> order = repo.get_order('my_order_id')
    >>> all_orders = repo.get_all_orders()
"""

from .order_repository import OrderRepository
from .postgres_order_repository import PostgresOrderRepository

__all__ = [
    'OrderRepository',
    'PostgresOrderRepository',
]
