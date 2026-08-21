import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import PostgresDB


def main() -> None:
    db = PostgresDB()

    tables = db.execute_query(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    table_names = [r["table_name"] for r in tables]
    print("TABLES=", table_names)

    targets = [
        "order_event_stream",
        "fill_ledger",
        "stealth_orders",
        "stealth_order_reveal_history",
        "order_moves",
    ]

    out = {}
    for table_name in targets:
        cols = db.execute_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        out[table_name] = [c["column_name"] for c in cols]

    print("STORYBOARD_TABLE_COLUMNS=", json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
