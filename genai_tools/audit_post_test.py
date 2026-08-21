"""Audit DB state after stealth retracement test."""
import sys, json
sys.path.insert(0, '.')
from database.database import PostgresDB

db = PostgresDB()
db.connect()

print("=" * 100)
print("STEALTH ORDERS")
print("=" * 100)
rows = db.execute_query(
    "SELECT stealth_order_id, side, status, limit_price, target_movement, "
    "target_movement_type, anchor_repricing_state_json "
    "FROM stealth_orders ORDER BY created_at"
)
for r in rows or []:
    sid = str(r['stealth_order_id'])[:8]
    state = r.get('anchor_repricing_state_json') or {}
    rh = state.get('reprice_history') or []
    print(f"  {sid} {r['side']:4s} status={r['status']:9s} limit={r['limit_price']} "
          f"tm={r['target_movement']} tmt={r['target_movement_type']}")
    print(f"    current_logical_limit={state.get('current_logical_limit_price')} "
          f"reprice_count={len(rh)} last_reason={state.get('reprice_reason')}")
    print(f"    active_placement={state.get('active_placement_client_order_id')} "
          f"active_xch={state.get('active_exchange_order_id')} "
          f"active_price={state.get('active_exchange_price')}")
    print(f"    last_profitability_block={state.get('last_profitability_block_reason')}")

print("\n" + "=" * 100)
print("ORDER_PARENT")
print("=" * 100)
rows = db.execute_query(
    "SELECT id, client_order_id, side, price, size, status, target_movement, "
    "target_movement_type, parent_order_id, current_order_replacement, "
    "max_order_replacement, created_at "
    "FROM order_parent ORDER BY id"
)
for r in rows or []:
    coid = str(r['client_order_id'])[:8]
    pid = str(r['parent_order_id'])[:8] if r['parent_order_id'] else 'ROOT'
    print(f"  #{r['id']} {coid} {r['side']:4s} {r['size']:>6} @ {r['price']:>10} "
          f"status={r['status']:14s} tm={r['target_movement']} tmt={r['target_movement_type']} "
          f"parent={pid} repl={r['current_order_replacement']}/{r['max_order_replacement']}")

print("\n" + "=" * 100)
print("STEALTH_ORDER_REVEAL_HISTORY")
print("=" * 100)
rows = db.execute_query(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name='stealth_order_reveal_history' ORDER BY ordinal_position"
)
print("reveal_history columns:", [r['column_name'] for r in rows or []])

rows = db.execute_query(
    "SELECT * FROM stealth_order_reveal_history ORDER BY created_at"
)
for r in rows or []:
    print(" ", {k: v for k, v in r.items() if v is not None})

print("\n" + "=" * 100)
print("FILL_LEDGER")
print("=" * 100)
rows = db.execute_query(
    "SELECT derived_trade_key, instrument, side, size, price, fees, ts "
    "FROM fill_ledger ORDER BY ts"
)
for r in rows or []:
    print(f"  {r['side']} {r['size']} {r['instrument']} @ {r['price']} "
          f"fees={r['fees']} ts={r['ts']}")

print("\n" + "=" * 100)
print("PARTIAL_FILL_PROGRESS")
print("=" * 100)
rows = db.execute_query(
    "SELECT client_order_id, status, filled_size, total_size, last_fill_at "
    "FROM partial_fill_progress ORDER BY last_fill_at NULLS FIRST"
)
for r in rows or []:
    coid = str(r['client_order_id'])[:8]
    print(f"  {coid} status={r['status']:12s} filled={r['filled_size']}/{r['total_size']}")

db.disconnect()
