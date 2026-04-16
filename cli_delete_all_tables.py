"""
Drop all tables from the PostgreSQL database.
"""

from database.database import PostgresDB


def main() -> None:
    """
    Delete all tables from the public schema in the PostgreSQL database.
    
    Retrieves all table names and drops them with CASCADE to handle dependencies.
    Logs table names before deletion.
    
    Returns:
        None
    """
    db = PostgresDB()
    
    try:
        # Get all table names
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
        
        # Drop all tables
        with db.get_cursor() as cursor:
            for table in tables:
                table_name = table['tablename']
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                print(f"Dropped table: {table_name}")
        
        print("\nAll tables deleted successfully!")
        
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
