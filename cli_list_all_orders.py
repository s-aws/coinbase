"""List all parent orders from the database and display them in a readable format.

Queries the order_parent table and displays order details including product,
side, size, price, target movement, and status. Useful for reviewing order history
and verifying parent order configurations.

Example:
    >>> python cli_list_all_orders.py
    Found 3 order(s):
    Client Order ID: order_123_abc
      Product ID: BTC-USDC
      Side: BUY
      Size: 0.5
      Price: 42000.00
      Target Movement: 0.4%
      Status: FILLED
    ----------------------------------------
    Client Order ID: order_124_def
      Product ID: ETH-USDC
      Side: SELL
      Size: 2.5
      Price: 2000.00
      Target Movement: 0.4%
      Status: OPEN
    ----------------------------------------
"""
from database.database import PostgresDB

def main() -> None:
    """Retrieve and display all parent orders from the database.
    
    Queries the order_parent table from PostgreSQL and prints each order's
    details in a formatted, human-readable output. Shows one order per block
    separated by dashes.
    
    Order details displayed:
    - Client Order ID: Unique identifier for the order
    - Product ID: Trading pair (e.g., BTC-USDC)
    - Side: BUY or SELL
    - Size: Number of units to trade
    - Price: Entry price in quote currency
    - Target Movement: Profit target as percentage
    - Status: Current order status (OPEN, FILLED, CANCELLED, etc.)
    
    Returns:
        None
    
    Raises:
        Exception: If database connection fails or query fails.
    
    Example:
        >>> main()
        Found 3 order(s):
        Client Order ID: parent_order_1
          Product ID: BTC-USDC
          Side: BUY
          Size: 0.5
          Price: 42000.00
          Target Movement: 0.4%
          Status: FILLED
        ----------------------------------------
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
