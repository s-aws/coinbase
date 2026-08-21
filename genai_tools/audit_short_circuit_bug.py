import sys
from pprint import pprint

sys.path.insert(0, r"e:/coinbase")
from database.database import PostgresDB

IDS = [
    "b2d49023-6f69-45b0-b8a8-805a10a038d3",
    "ab3df345-5954-4547-9cf6-11ca50e995e2",
    "c2c8e13c-e367-49cd-8757-b86e45583b25",
    "4a5cc725-91a9-4e4e-af2d-ca7830cf67d1",
    "a70569f5-3b05-4006-9d04-4b3bb943be86",
]


def run() -> None:
    db = PostgresDB()
    db.connect()

    print("=== ORDER_PARENT rows for cited IDs ===")
    rows = db.execute_query(
        """
        SELECT id, client_order_id, parent_order_id, product_id, side, size, price,
               status, ownership_scope, current_order_replacement, max_order_replacement,
               target_movement, target_movement_type, allow_partial_fills, created_at
        FROM order_parent
        WHERE client_order_id = ANY(%s)
        ORDER BY created_at ASC
        """,
        (IDS,),
    )
    for r in rows:
        pprint(r)
    print("count=", len(rows))

    print("\n=== OPEN rows in order_parent ===")
    open_rows = db.execute_query(
        """
        SELECT id, client_order_id, parent_order_id, product_id, side, size, price,
               status, ownership_scope, created_at
        FROM order_parent
        WHERE status='OPEN'
        ORDER BY created_at DESC
        """
    )
    for r in open_rows:
        pprint(r)
    print("open_count=", len(open_rows))

    print("\n=== Child status breakdown ===")
    child_status = db.execute_query(
        """
        SELECT status, COUNT(*) AS cnt
        FROM order_parent
        WHERE parent_order_id IS NOT NULL
        GROUP BY status
        ORDER BY cnt DESC
        """
    )
    for r in child_status:
        pprint(r)

    print("\n=== order_event_stream columns ===")
    cols = db.execute_query(
        "SELECT column_name FROM information_schema.columns WHERE table_name='order_event_stream' ORDER BY ordinal_position"
    )
    col_names = [c["column_name"] for c in cols]
    print(col_names)

    print("\n=== order_event_stream rows for cited IDs ===")
    stream = db.execute_query(
        """
        SELECT event_type, client_order_id, parent_client_order_id,
               event_status_from, event_status_to,
               trigger_payload_json, source_channel, created_at
        FROM order_event_stream
        WHERE client_order_id = ANY(%s) OR parent_client_order_id = ANY(%s)
        ORDER BY created_at ASC
        """,
        (IDS, IDS),
    )
    for r in stream:
        pprint(r)
    print("stream_row_count=", len(stream))

    print("\n=== fill_ledger rows for cited IDs ===")
    fills = db.execute_query(
        """
        SELECT client_order_id, instrument, side, quantity, price, fees,
               reconciliation_status, created_at
        FROM fill_ledger
        WHERE client_order_id = ANY(%s)
        ORDER BY created_at ASC
        """,
        (IDS,),
    )
    for r in fills:
        pprint(r)
    print("fill_row_count=", len(fills))

    print("\n=== startup drift ID a705... ===")
    in_parent = db.execute_query(
        """
        SELECT client_order_id, parent_order_id, product_id, side, price, status, created_at
        FROM order_parent
        WHERE client_order_id=%s
        """,
        ("a70569f5-3b05-4006-9d04-4b3bb943be86",),
    )
    print("order_parent rows:", len(in_parent))
    for r in in_parent:
        pprint(r)

    in_stream = db.execute_query(
        """
        SELECT event_type, client_order_id, parent_client_order_id,
               event_status_from, event_status_to, source_channel, created_at
        FROM order_event_stream
        WHERE client_order_id=%s OR parent_client_order_id=%s
        ORDER BY created_at ASC
        """,
        (
            "a70569f5-3b05-4006-9d04-4b3bb943be86",
            "a70569f5-3b05-4006-9d04-4b3bb943be86",
        ),
    )
    print("order_event_stream rows:", len(in_stream))
    for r in in_stream:
        pprint(r)

    db.disconnect()


if __name__ == "__main__":
    run()
