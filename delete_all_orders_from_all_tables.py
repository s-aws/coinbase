"""
Delete all orders from all tables in the database. Use with caution.
"""

from database.database import PostgresDB


def main():
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
        
        # Delete all orders from all tables
        with db.get_cursor() as cursor:
            for table in tables:
                table_name = table['tablename']
                cursor.execute(f"DELETE FROM {table_name}")
                print(f"Deleted all orders from table: {table_name}")
        
        print("\nAll orders from all tables deleted successfully!")
        
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
