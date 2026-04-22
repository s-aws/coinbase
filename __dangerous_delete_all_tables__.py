"""Drop all tables from the PostgreSQL database and recreate them.

WARNING: This is a destructive operation. All data in the database will be permanently deleted.

Utility script to completely reset the database by dropping all tables from the public schema
and then recreating all required tables with proper schema.

Useful for resetting the database during development or testing.

Example:
    >>> python __dangerous_delete_all_tables__.py
    Found 6 table(s) to delete:
      - order_parent
      - order_child
      - stealth_orders
      - stealth_order_snapshots
      - stealth_order_reveal_history
      - order_moves
    Dropped table: order_parent
    Dropped table: order_child
    ...
    All tables deleted successfully!
    
    Creating tables...
    order_parent table done.
    order_child table done.
    ...
    All tables recreated successfully!
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
from psycopg2 import sql

def main() -> None:
    """Delete all tables from the public schema and recreate them.
    
    Retrieves all table names from the public schema and drops them with CASCADE
    to handle foreign key dependencies. Then recreates all required tables.
    
    WARNING: This operation is permanent and irreversible. All data in all tables
    will be deleted. Use with caution, especially in production environments.
    
    Process:
    1. Query information_schema.pg_tables for public schema tables
    2. Display list of tables to be deleted
    3. Drop each table safely with CASCADE option
    4. Recreate all required tables in proper dependency order
    5. Display confirmation for each operation
    
    Returns:
        None
    
    Raises:
        Exception: If database connection fails or critical SQL execution fails.
    
    Example:
        >>> main()
        Found 6 table(s) to delete:
          - order_parent
          - order_child
          - stealth_orders
          - stealth_order_snapshots
          - stealth_order_reveal_history
          - order_moves
        Dropped table: order_parent
        Dropped table: order_child
        ...
        All tables deleted successfully!
        
        Creating tables...
        order_parent table done.
        order_child table done.
        ...
        All tables created successfully!
    """
    db = PostgresDB()
    
    try:
        # Get all table names from public schema
        tables = db.execute_query("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        
        if not tables:
            print("✓ No tables found to delete - database is already clean")
        else:
            print(f"Found {len(tables)} table(s) to delete:")
            for table in tables:
                print(f"  - {table['tablename']}")
            
            # Drop all tables with CASCADE to handle dependencies
            # Using CASCADE ensures foreign key constraints don't prevent drops
            dropped_count = 0
            failed_drops = []
            
            with db.get_cursor() as cursor:
                for table in tables:
                    table_name = table['tablename']
                    try:
                        # Use sql.Identifier for safe table name handling
                        drop_query = sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                            sql.Identifier(table_name)
                        )
                        cursor.execute(drop_query)
                        print(f"✓ Dropped table: {table_name}")
                        dropped_count += 1
                    except Exception as e:
                        error_msg = f"✗ Failed to drop table {table_name}: {type(e).__name__}: {e}"
                        print(error_msg)
                        failed_drops.append((table_name, e))
            
            if failed_drops:
                print(f"\n⚠ Warning: {len(failed_drops)} table(s) failed to drop:")
                for table_name, error in failed_drops:
                    print(f"  - {table_name}: {error}")
            else:
                print(f"\n✓ All {dropped_count} tables deleted successfully!")
        
        # Recreate all required tables
        print("\nCreating tables...")
        try:
            create_order_parent_table()
            create_order_child_table()
            create_stealth_orders_table()
            create_stealth_order_snapshots_table()
            create_stealth_order_reveal_history_table()
            create_order_moves_table()
            
            print("\n✓ All tables recreated successfully!")
        except Exception as e:
            print(f"\n✗ Error creating tables: {type(e).__name__}: {e}")
            raise
            
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
