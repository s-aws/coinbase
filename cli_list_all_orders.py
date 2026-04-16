""" List all orders from the database and print them in a readable format. """
from database.database import PostgresDB

def main() -> None:
    """
    Retrieve and display all parent orders from the database.
    
    Queries the order_parent table and prints order details in a formatted output.
    Displays client order ID, product, side, size, price, target movement, and status.
    
    Returns:
        None
    """
    db = PostgresDB()
    try:
        orders = db.execute_query("SELECT * FROM order_parent")
        if not orders:
            print("No orders found in the database.")
            return
        
        print(f"Found {len(orders)} order(s):")
        for order in orders:
            print(f"Client Order ID: {order['client_order_id']}")
            print(f"  Product ID: {order['product_id']}")
            print(f"  Side: {order['side']}")
            print(f"  Size: {order['size']}")
            print(f"  Price: {order['price']}")
            print(f"  Target Movement: {order['target_movement']*100}%")
            print(f"  Status: {order['status']}")
            print("-" * 40)
    finally:
        db.disconnect()

if __name__ == "__main__":
    main()
