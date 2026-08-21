import json
from database.database import PostgresDB


def main() -> None:
    db = PostgresDB()
    try:
        tables = [
            "conditional_orders",
            "fill_ledger",
            "order_moves",
            "order_parent",
            "stealth_order_reveal_history",
            "stealth_order_snapshots",
            "stealth_orders",
        ]

        print("=== TABLE ROW COUNTS ===")
        for table in tables:
            count = db.execute_query(f"SELECT COUNT(*) AS c FROM {table}")[0]["c"]
            print(f"{table}: {count}")

        print("\n=== TABLE COLUMNS ===")
        columns = db.execute_query(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        current_table = None
        for row in columns:
            if row["table_name"] != current_table:
                current_table = row["table_name"]
                print(f"\n{current_table}:")
            print(f"  - {row['column_name']} ({row['data_type']})")

        print("\n=== LINKAGE METRICS ===")
        total_fills = db.execute_query("SELECT COUNT(*) AS c FROM fill_ledger")[0]["c"]
        fills_linked_parent = db.execute_query(
            """
            SELECT COUNT(*) AS c
            FROM fill_ledger f
            JOIN order_parent p ON p.client_order_id = f.client_order_id
            """
        )[0]["c"]
        fills_linked_stealth = db.execute_query(
            """
            SELECT COUNT(*) AS c
            FROM fill_ledger f
            JOIN stealth_orders s ON s.stealth_order_id::text = f.client_order_id
            """
        )[0]["c"]
        fills_missing_links = db.execute_query(
            """
            SELECT COUNT(*) AS c
            FROM fill_ledger f
            LEFT JOIN order_parent p ON p.client_order_id = f.client_order_id
            LEFT JOIN stealth_orders s ON s.stealth_order_id::text = f.client_order_id
            WHERE p.client_order_id IS NULL AND s.stealth_order_id IS NULL
            """
        )[0]["c"]
        reveal_history_with_market = db.execute_query(
            """
            SELECT COUNT(*) AS c
            FROM stealth_order_reveal_history
            WHERE market_price IS NOT NULL
            """
        )[0]["c"]

        print(f"fill_ledger total rows: {total_fills}")
        print(f"fills linked to order_parent.client_order_id: {fills_linked_parent}")
        print(f"fills linked to stealth_orders.stealth_order_id: {fills_linked_stealth}")
        print(f"fills with no link in parent/stealth tables: {fills_missing_links}")
        print(f"reveal_history rows with market_price populated: {reveal_history_with_market}")

        print("\n=== RECENT EVENTS / ORDERS ===")

        queries = {
            "fill_ledger": "SELECT * FROM fill_ledger LIMIT 10",
            "order_parent": "SELECT * FROM order_parent LIMIT 10",
            "order_moves": "SELECT * FROM order_moves LIMIT 10",
            "stealth_orders": "SELECT * FROM stealth_orders LIMIT 10",
            "stealth_order_reveal_history": "SELECT * FROM stealth_order_reveal_history LIMIT 10",
            "stealth_order_snapshots": "SELECT * FROM stealth_order_snapshots LIMIT 10",
            "conditional_orders": "SELECT * FROM conditional_orders LIMIT 10",
        }

        for table_name, query in queries.items():
            print(f"\n--- {table_name} ---")
            rows = db.execute_query(query)
            print(json.dumps(rows, default=str, indent=2))

    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
