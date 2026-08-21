from database.database import PostgresDB

db = PostgresDB()
print('DB_CTX', db.execute_query("SELECT current_database() AS db, current_schema() AS schema"))
print('MATCHED_COLUMNS', db.execute_query("""
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'stealth_orders'
  AND column_name IN (
    'reveal_pricing_policy',
    'follow_up_reveal_direction',
    'anchor_repricing_policy_json',
    'anchor_repricing_state_json'
  )
ORDER BY column_name
"""))
