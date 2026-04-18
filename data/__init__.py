"""Data access layer - Database connections and repositories.

This module contains all data persistence logic:
- database.py: Database connection management (unchanged from original)
- repositories/: Order and position repository interfaces and implementations

The repository pattern provides clean data access abstractions that enable
easy testing and implementation swapping.

Usage:
    >>> from data.repositories import PostgresOrderRepository
    >>> from database.database import PostgresDB
    >>> 
    >>> db = PostgresDB()
    >>> order_repo = PostgresOrderRepository(db)
"""

# Re-export for convenience
from .repositories import OrderRepository, PostgresOrderRepository
from .state_manager import StateManager

__all__ = [
    'OrderRepository',
    'PostgresOrderRepository',
    'StateManager',
]
