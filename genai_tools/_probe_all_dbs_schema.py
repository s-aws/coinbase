import psycopg2
from database.database import DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_USER, DEFAULT_DB_PASSWORD, DEFAULT_DB_NAME


def fetch_db_names():
    conn = psycopg2.connect(host=DEFAULT_DB_HOST, port=DEFAULT_DB_PORT, database=DEFAULT_DB_NAME, user=DEFAULT_DB_USER, password=DEFAULT_DB_PASSWORD)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def check_columns(db_name):
    result = {"database": db_name, "ok": False, "error": None, "columns": []}
    try:
        conn = psycopg2.connect(host=DEFAULT_DB_HOST, port=DEFAULT_DB_PORT, database=db_name, user=DEFAULT_DB_USER, password=DEFAULT_DB_PASSWORD)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name
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
                """)
                result["columns"] = [r[0] for r in cur.fetchall()]
                result["ok"] = True
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


db_names = fetch_db_names()
print('DATABASES', db_names)
for name in db_names:
    print('CHECK', check_columns(name))
