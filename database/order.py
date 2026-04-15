"""
Order insertion functions for parent and child tables.
"""

from database.database import PostgresDB
from typing import Dict, List, Any, Optional

DB_CLIENT = PostgresDB()

def create_order_parent_table() -> None:
    """Create the order_parent table if it doesn't exist."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_parent (
        id SERIAL PRIMARY KEY,
        target_movement NUMERIC,
        target_movement_type VARCHAR(1),
        client_order_id VARCHAR(40) UNIQUE NOT NULL,
        product_id VARCHAR(255) NOT NULL,
        side VARCHAR(10) NOT NULL,
        size NUMERIC NOT NULL,
        price NUMERIC NOT NULL,
        status VARCHAR(20) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_parent table done.")


def create_order_child_table() -> None:
    """Create the order_child table if it doesn't exist."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_child (
        id SERIAL PRIMARY KEY,
        parent_client_order_id VARCHAR(40) NOT NULL,
        client_order_id VARCHAR(40) UNIQUE NOT NULL,
        product_id VARCHAR(255) NOT NULL,
        side VARCHAR(10) NOT NULL,
        size NUMERIC NOT NULL,
        price NUMERIC NOT NULL,
        status VARCHAR(20) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_client_order_id) REFERENCES order_parent(client_order_id)
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_child table done.")


def insert_order_parent(
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    target_movement: float,
    target_movement_type: str = "P",
    status: str = "pending"
) -> Optional[int]:
    """
    Insert a parent order into the order_parent table.
    
    Args:
        client_order_id: Unique client order identifier
        product_id: Trading pair (e.g., 'BTC-USD')
        side: Order side ('BUY' or 'SELL')
        size: Order size
        price: Order price
        target_movement: Target price movement for this and child orders
        target_movement_type: 'P' for percentage, 'A' for absolute (default: 'P')
        status: Order status (default: 'pending')
    
    Returns:
        The inserted row's ID (serial primary key) on success, None on failure
    """
    query = """
    INSERT INTO order_parent (client_order_id, product_id, side, size, price, status, target_movement, target_movement_type)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (client_order_id, product_id, side, size, price, status, target_movement, target_movement_type)
    
    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]['id']
            print(f"Parent order inserted: {client_order_id} (ID: {inserted_id})")
            return inserted_id
        else:
            print(f"Failed to retrieve inserted order ID for: {client_order_id}")
            return None
    except Exception as e:
        print(f"Error inserting parent order: {e}")
        return None


def insert_order_child(
    parent_client_order_id: str,
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    status: str = "pending"
) -> Optional[int]:
    """
    Insert a child order into the order_child table.
    
    Args:
        parent_client_order_id: Parent order's client_order_id
        client_order_id: Unique child order identifier
        product_id: Trading pair (e.g., 'BTC-USD')
        side: Order side ('BUY' or 'SELL')
        size: Order size
        price: Order price
        status: Order status (default: 'pending')
    
    Returns:
        The inserted row's ID (serial primary key) on success, None on failure
    
    Raises:
        Exception: If parent_client_order_id doesn't exist in order_parent table
    """
    query = """
    INSERT INTO order_child (parent_client_order_id, client_order_id, product_id, side, size, price, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """

    params = (parent_client_order_id, client_order_id, product_id, side, size, price, status)

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]['id']
            print(f"Child order inserted: {client_order_id} (ID: {inserted_id}, parent: {parent_client_order_id})")
            return inserted_id
        else:
            print(f"Failed to retrieve inserted child order ID for: {client_order_id}")
            return None
    except Exception as e:
        print(f"Error inserting child order: {e}")
        return None


def insert_order_parent_batch(
    orders: List[Dict[str, Any]],
) -> List[Optional[int]]:
    """
    Insert multiple parent orders at once.
    
    Args:
        orders: List of dictionaries with keys:
                - client_order_id (required)
                - product_id (required)
                - side (required)
                - size (required)
                - price (required)
                - status (optional, default: 'pending')
                - target_movement (required)
                - target_movement_type (optional, default: 'P')
    
    Returns:
        List of inserted row IDs (None for any that failed)
    """
    inserted_ids = []
    
    for order in orders:
        client_order_id = order.get('client_order_id')
        product_id = order.get('product_id')
        side = order.get('side')
        size = order.get('size')
        price = order.get('price')
        status = order.get('status', 'pending')
        target_movement = order.get('target_movement')
        target_movement_type = order.get('target_movement_type', 'P')
        if not all([client_order_id, product_id, side, size, price, target_movement]):
            print(f"Skipping invalid order: {order}")
            inserted_ids.append(None)
            continue
        
        result = insert_order_parent(client_order_id, product_id, side, size, price, target_movement, target_movement_type, status)
        inserted_ids.append(result)
    
    return inserted_ids


def insert_order_child_batch(
    orders: List[Dict[str, Any]]
) -> int:
    """
    Insert multiple child orders at once.
    
    Args:
        orders: List of dictionaries with keys:
                - parent_client_order_id (required)
                - client_order_id (required)
                - product_id (required)
                - side (required)
                - size (required)
                - price (required)
                - status (optional, default: 'pending')
    
    Returns:
        Total number of rows inserted
    """
    total_inserted = 0
    
    for order in orders:
        parent_client_order_id = order.get('parent_client_order_id')
        client_order_id = order.get('client_order_id')
        product_id = order.get('product_id')
        side = order.get('side')
        size = order.get('size')
        price = order.get('price')
        status = order.get('status', 'pending')
        
        if not all([parent_client_order_id, client_order_id, product_id, side, size, price]):
            print(f"Skipping invalid order: {order}")
            continue
        
        result = insert_order_child(parent_client_order_id, client_order_id, product_id, side, size, price, status)
        total_inserted += result
    
    return total_inserted


def get_parent_order(client_order_id: str) -> Dict[str, Any]:
    """
    Retrieve a parent order by client_order_id.
    
    Args:
        client_order_id: Client order identifier
    
    Returns:
        Order record as dictionary, or None if not found
    """
    query = "SELECT * FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return results[0] if results else None


def get_parent_orders() -> List[Dict[str, Any]]:
    """
    Retrieve all parent orders.
    
    Args:
        None
    
    Returns:
        List of parent order records as dictionaries
    """
    query = "SELECT * FROM order_parent"
    return DB_CLIENT.execute_query(query)


def get_child_orders(parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all child orders for a parent order.
    
    Args:
        parent_client_order_id: Parent order's client_order_id
    
    Returns:
        List of child order records
    """
    query = "SELECT * FROM order_child WHERE parent_client_order_id = %s"
    return DB_CLIENT.execute_query(query, (parent_client_order_id,))


def update_order_parent_status(
    client_order_id: str,
    status: str
) -> int:
    """
    Update the status of a parent order.
    
    Args:
        client_order_id: Unique client order identifier
        status: New status value (e.g., 'pending', 'open', 'filled', 'cancelled', 'failed')
    
    Returns:
        Number of rows updated (0 if order not found, 1 on success)
    """
    query = "UPDATE order_parent SET status = %s WHERE client_order_id = %s"
    params = (status, client_order_id)
    
    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(f"Parent order status updated: {client_order_id} -> {status}")
    else:
        print(f"No parent order found with client_order_id: {client_order_id}")
    return result


def update_order_parent_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """
    Update status for multiple parent orders at once.
    
    Args:
        status_updates: List of dictionaries with keys:
                       - client_order_id (required)
                       - status (required)
    
    Returns:
        Total number of rows updated
    """
    total_updated = 0
    
    for update in status_updates:
        client_order_id = update.get('client_order_id')
        status = update.get('status')
        
        if not all([client_order_id, status]):
            print(f"Skipping invalid status update: {update}")
            continue
        
        result = update_order_parent_status(client_order_id, status)
        total_updated += result
    
    return total_updated

def update_order_child_status(
    client_order_id: str,
    status: str
) -> int:
    """
    Update the status of a child order.
    
    Args:
        client_order_id: Unique client order identifier
        status: New status value (e.g., 'pending', 'open', 'filled', 'cancelled', 'failed')
    
    Returns:
        Number of rows updated (0 if order not found, 1 on success)
    """
    query = "UPDATE order_child SET status = %s WHERE client_order_id = %s"
    params = (status, client_order_id)
    
    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(f"Child order status updated: {client_order_id} -> {status}")
    else:
        print(f"No child order found with client_order_id: {client_order_id}")
    return result

def update_order_child_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """
    Update status for multiple child orders at once.
    
    Args:
        status_updates: List of dictionaries with keys:
                       - client_order_id (required)
                       - status (required)
    
    Returns:
        Number of rows updated (0 if order not found, 1 on success)
    """
    total_updated = 0
    
    for update in status_updates:
        client_order_id = update.get('client_order_id')
        status = update.get('status')
        
        if not all([client_order_id, status]):
            print(f"Skipping invalid status update: {update}")
            continue
        
        result = update_order_child_status(client_order_id, status)
        total_updated += result
    
    return total_updated
