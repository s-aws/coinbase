"""Quick script to verify tables were created."""
from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB

db = PostgresDB()
try:
    tables = db.execute_query("""
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public' 
        ORDER BY tablename
    """)
    
    print("\n✓ Tables in database:")
    for table in tables:
        print(f"  • {table['tablename']}")
    
    print(f"\nTotal: {len(tables)} tables")
    
    # Show fill_ledger schema
    print("\n" + "="*60)
    print("fill_ledger schema:")
    print("="*60)
    fill_ledger_columns = db.execute_query("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'fill_ledger'
        ORDER BY ordinal_position
    """)
    for col in fill_ledger_columns:
        null_str = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
        print(f"  {col['column_name']:30} {col['data_type']:20} {null_str}")
    
    # Show conditional_orders schema
    print("\n" + "="*60)
    print("conditional_orders schema:")
    print("="*60)
    cond_columns = db.execute_query("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'conditional_orders'
        ORDER BY ordinal_position
    """)
    for col in cond_columns:
        null_str = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
        print(f"  {col['column_name']:30} {col['data_type']:20} {null_str}")
    
    print("\n✓ Database verification complete!")
    
finally:
    db.disconnect()
