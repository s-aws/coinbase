from database.database import PostgresDB

DB_CLIENT = PostgresDB()

print('=== PARENT ORDERS ===')
try:
    query = "SELECT client_order_id, target_movement, target_movement_type FROM order_parent LIMIT 5"
    parents = DB_CLIENT.execute_query(query)
    if parents:
        for p in parents:
            print(f'Order ID: {p.get("client_order_id")}')
            print(f'  Target Movement: {p.get("target_movement")}')
            print(f'  Type: {p.get("target_movement_type")}')
            print()
    else:
        print('No parent orders found')
except Exception as e:
    print(f'Error: {e}')

print('\n=== STEALTH ORDERS (first 5) ===')
try:
    query = "SELECT stealth_order_id, parent_order_id, target_movement, target_movement_type FROM stealth_orders LIMIT 5"
    stealth = DB_CLIENT.execute_query(query)
    if stealth:
        for s in stealth:
            print(f'Order ID: {s.get("stealth_order_id")}')
            print(f'  Parent: {s.get("parent_order_id")}')
            print(f'  Target Movement: {s.get("target_movement")}')
            print(f'  Type: {s.get("target_movement_type")}')
            print()
    else:
        print('No stealth orders found')
except Exception as e:
    print(f'Error: {e}')
