"""Drop all tables from the PostgreSQL database.

WARNING: This is a destructive operation. All data in the database will be permanently deleted.

Utility script to clear the database by dropping all tables from the public schema.
Useful for resetting the database during development or testing.

Example:
    >>> python cli_delete_all_tables.py
    Found 2 table(s) to delete:
      - order_parent
      - order_child
    Dropped table: order_parent
    Dropped table: order_child
    
    All tables deleted successfully!
"""

from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    create_order_child_table,
    create_stealth_orders_table,
    create_stealth_order_snapshots_table,
    create_stealth_order_reveal_history_table,
    create_order_moves_table,
)

def main() -> None:
    """Delete all tables from the public schema in the PostgreSQL database.
    
    Retrieves all table names from the public schema and drops them with CASCADE
    to handle foreign key dependencies. Logs each table name before deletion.
    
    WARNING: This operation is permanent and irreversible. All data in all tables
    will be deleted. Use with caution, especially in production environments.
    
    Process:
    1. Query information_schema.pg_tables for public schema tables
    2. Display list of tables to be deleted
    3. Drop each table with CASCADE option
    4. Print confirmation for each drop
    
    Returns:
        None
    
    Raises:
        Exception: If database connection fails or SQL execution fails.
    
    Example:
        >>> main()
        Found 2 table(s) to delete:
          - order_parent
          - order_child
        Dropped table: order_parent
        Dropped table: order_child
        
        All tables deleted successfully!
    """
    db = PostgresDB()
    
    try:
        # Get all table names from public schema
        tables = db.execute_query("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        
        if not tables:
            print("No tables found to delete")
            return
        
        print(f"Found {len(tables)} table(s) to delete:")
        for table in tables:
            print(f"  - {table['tablename']}")
        
        # Drop all tables with CASCADE to handle dependencies
        with db.get_cursor() as cursor:
            for table in tables:
                table_name = table['tablename']
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                print(f"Dropped table: {table_name}")
        
        print("\nAll tables deleted successfully!")

        create_order_parent_table()
        create_order_child_table()
        create_stealth_orders_table()
        create_stealth_order_snapshots_table()
        create_stealth_order_reveal_history_table()
        create_order_moves_table()

        print("All tables created successfully!")
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
