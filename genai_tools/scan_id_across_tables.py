import sys
from pprint import pprint

sys.path.insert(0, r"e:/coinbase")
from database.database import PostgresDB

needle = "a70569f5-3b05-4006-9d04-4b3bb943be86"

db = PostgresDB()
db.connect()

cols = db.execute_query(
    """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND (
        column_name ILIKE '%%client_order_id%%'
        OR column_name ILIKE '%%order_id%%'
        OR column_name ILIKE '%%revealed_orders%%'
        OR column_name ILIKE '%%raw_payload_json%%'
        OR column_name ILIKE '%%trigger_payload_json%%'
      )
    ORDER BY table_name, column_name
    """
)

hits = []
for c in cols:
    table_name = c["table_name"]
    column_name = c["column_name"]
    q = "SELECT COUNT(*) AS cnt FROM {table} WHERE CAST({col} AS TEXT) ILIKE %s".format(
        table=table_name,
        col=column_name,
    )
    try:
        r = db.execute_query(q, ("%" + needle + "%",))
        cnt = int(r[0]["cnt"]) if r else 0
        if cnt > 0:
            hits.append((table_name, column_name, cnt))
    except Exception:
        continue

print("=== tables/columns containing needle ===")
if not hits:
    print("(none)")
else:
    for h in hits:
        print(h)

for table_name, column_name, cnt in hits:
    print("\n--- {}.{} (count={}) ---".format(table_name, column_name, cnt))
    q2 = "SELECT * FROM {table} WHERE CAST({col} AS TEXT) ILIKE %s LIMIT 3".format(
        table=table_name,
        col=column_name,
    )
    rows = db.execute_query(q2, ("%" + needle + "%",))
    for row in rows:
        pprint(row)

db.disconnect()
