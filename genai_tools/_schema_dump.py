from database.database import PostgresDB
db = PostgresDB()
for tbl in ("stealth_orders", "order_parent", "market_ticks", "order_event_stream"):
    rows = db.execute_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=%s ORDER BY ordinal_position",
        (tbl,),
    )
    print(f"\n=== {tbl} ===")
    if rows:
        for r in rows:
            print(f"  {r['column_name']}")
    else:
        print("  (table does not exist)")
