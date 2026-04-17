"""Create database tables for order tracking and management.

Initializes the PostgreSQL schema with parent and child order tables.
Run this once before starting the trading engine.

Example:
    >>> python cli_create_all_tables.py
    All tables created successfully!
"""

from database.order import create_order_parent_table, create_order_child_table

def main() -> None:
    """Create all required database tables for order tracking.
    
    Initializes parent and child order tables in the database. These tables
    store the parent-child order relationships and order metadata for
    persistence and reconciliation.
    
    The tables created:
    - order_parent: Tracks parent orders with product, side, size, price,
                    profit target, and replacement counters
    - order_child: Tracks child follow-up orders linked to parents
    
    Should only be run once during initial setup. Safe to run multiple times
    (tables already created will be skipped).
    
    Returns:
        None
    
    Raises:
        Exception: If database connection fails or SQL execution fails.
    
    Example:
        >>> main()
        All tables created successfully!
    """
    create_order_parent_table()
    create_order_child_table()
    print("All tables created successfully!")

if __name__ == "__main__":
    main()
